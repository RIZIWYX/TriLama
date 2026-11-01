"""Tri automatique des réponses de candidature de stage.

Lit les nouveaux mails en IMAP, les classe avec un modèle local (Ollama),
les déplace dans le dossier "Stage - ..." correspondant et envoie un récapitulatif.
Bibliothèque standard uniquement.
"""
import email
import imaplib
import json
import os
import re
import smtplib
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from email.header import decode_header, make_header
from email.message import EmailMessage

E = os.environ
STATE_FILE = "/data/state.json"
RECAP_SUBJECT = "RECAP CANDIDATURE DU JOUR"
TZ = ZoneInfo(E.get("TZ", "Europe/Paris"))

CATEGORIES = {
    "refus": "Stage - Refus",
    "positif": "Stage - Positif",
    "relance": "Stage - Relance",
    "auto": "Stage - Auto",
    "attente": "Stage - Attente",
}

PROMPT = """Tu tries les mails reçus par un étudiant qui cherche un stage.
Réponds UNIQUEMENT en JSON : {{"categorie": "...", "confiance": 0.0-1.0, "resume": "une phrase"}}
Catégories possibles :
- "refus" : la candidature est refusée
- "positif" : proposition d'entretien, de test, d'appel, ou acceptation
- "relance" : l'entreprise demande une info, un document, ou une action de l'étudiant
- "auto" : accusé de réception automatique ("nous avons bien reçu votre candidature")
- "attente" : réponse humaine sans décision ("nous reviendrons vers vous")
- "autre" : sans rapport avec une candidature de stage

Expéditeur : {sender}
Objet : {subject}
Corps :
{body}
"""


def dec(value):
    return str(make_header(decode_header(value or "")))


def text_body(msg):
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_type() == "text/plain" and not part.get_filename():
            payload = part.get_payload(decode=True) or b""
            return payload.decode(part.get_content_charset() or "utf-8", "replace")
    for part in parts if msg.is_multipart() else [msg]:
        if part.get_content_type() == "text/html":
            html = (part.get_payload(decode=True) or b"").decode(
                part.get_content_charset() or "utf-8", "replace")
            return re.sub(r"<[^>]+>", " ", html)
    return ""


def classify(sender, subject, body):
    prompt = PROMPT.format(sender=sender, subject=subject, body=body[:3000])
    req = urllib.request.Request(
        f"{E['OLLAMA_URL']}/api/generate",
        data=json.dumps({"model": E["OLLAMA_MODEL"], "prompt": prompt,
                         "format": "json", "stream": False,
                         "options": {"temperature": 0}}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        out = json.loads(json.loads(r.read())["response"])
    cat = str(out.get("categorie", "autre")).lower()
    return (cat if cat in CATEGORIES else "autre",
            float(out.get("confiance", 0)), out.get("resume", ""))


def ensure_model():
    req = urllib.request.Request(
        f"{E['OLLAMA_URL']}/api/pull",
        data=json.dumps({"model": E["OLLAMA_MODEL"], "stream": False}).encode())
    for _ in range(30):
        try:
            urllib.request.urlopen(req, timeout=1800).read()
            return
        except OSError:
            time.sleep(5)  # Ollama pas encore démarré
    raise SystemExit("Ollama injoignable")


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def folder(imap, label):
    sep = "/"
    typ, data = imap.list()
    if typ == "OK" and data and data[0]:
        m = re.search(rb'\(.*?\) "(.)"', data[0])
        if m:
            sep = m.group(1).decode()
    name = f"{E['FOLDER_PARENT']}{sep}{label}"
    imap.create(f'"{name}"')  # sans effet s'il existe déjà
    return f'"{name}"'


def send_recap(results, day):
    if results:
        lines = [f"[{label}] {subject} - {sender}\n   {resume} (confiance {conf:.0%})"
                 for label, subject, sender, resume, conf in results]
        body = f"{len(results)} réponse(s) de candidature le {day} :\n\n" + "\n\n".join(lines)
    else:
        body = f"Aucune nouvelle réponse de candidature le {day}."
    msg = EmailMessage()
    msg["Subject"] = RECAP_SUBJECT
    msg["From"] = E["SMTP_USER"]
    msg["To"] = E["NOTIFY_TO"]
    msg.set_content(body)
    port = int(E.get("SMTP_PORT", 587))
    if port == 465:  # SSL direct
        conn = smtplib.SMTP_SSL(E["SMTP_HOST"], port)
    else:  # 587 : STARTTLS
        conn = smtplib.SMTP(E["SMTP_HOST"], port)
        conn.starttls()
    with conn as s:
        s.login(E["SMTP_USER"], E["SMTP_PASSWORD"])
        s.send_message(msg)


def run_once(state):
    dry = E.get("DRY_RUN", "true").lower() == "true"
    imap = imaplib.IMAP4_SSL(E["IMAP_HOST"], int(E.get("IMAP_PORT", 993)))
    imap.login(E["IMAP_USER"], E["IMAP_PASSWORD"])
    imap.select(E.get("IMAP_INBOX", "INBOX"))
    _, data = imap.uid("search", None, "ALL")
    uids = [int(u) for u in data[0].split()]
    if "last_uid" not in state:  # premier lancement : on ne trie que le futur
        state["last_uid"] = max(uids, default=0)
        print(f"Initialisation, dernier UID = {state['last_uid']}")
    results = state.setdefault("pending", [])
    for uid in (u for u in uids if u > state["last_uid"]):
        _, raw = imap.uid("fetch", str(uid), "(BODY.PEEK[])")  # PEEK : reste non lu
        msg = email.message_from_bytes(raw[0][1])
        sender, subject = dec(msg["From"]), dec(msg["Subject"])
        if RECAP_SUBJECT in subject.upper():  # nos propres récaps : ignorés
            state["last_uid"] = uid
            save_state(state)
            continue
        try:
            cat, conf, resume = classify(sender, subject, text_body(msg))
        except Exception as exc:
            print(f"UID {uid} : échec de classification ({exc}), réessai plus tard")
            break
        print(f"UID {uid} -> {cat} ({conf:.2f}) : {subject}")
        if cat != "autre":
            label = CATEGORIES[cat]
            if not dry:
                target = folder(imap, label)
                if imap.uid("copy", str(uid), target)[0] == "OK":
                    imap.uid("store", str(uid), "+FLAGS", r"(\Deleted)")
            results.append([label, subject, sender, resume, conf])
        state["last_uid"] = uid
        save_state(state)
    if not dry:
        imap.expunge()
    imap.logout()
    now = datetime.now(TZ)
    today = now.date().isoformat()
    if now.hour >= int(E.get("RECAP_HOUR", 20)) and state.get("last_recap") != today:
        send_recap(results, now.strftime("%d/%m/%Y"))
        state["pending"] = []
        state["last_recap"] = today
    save_state(state)


def main():
    ensure_model()
    state = load_state()
    print("Tri des candidatures démarré")
    while True:
        try:
            run_once(state)
        except Exception as exc:
            print(f"Erreur : {exc}")
        time.sleep(int(E.get("POLL_SECONDS", 300)))


if __name__ == "__main__":
    main()
