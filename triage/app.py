"""Tri automatique des réponses de candidature de stage.

Lit les nouveaux mails en IMAP, les classe avec un modèle local (Ollama),
leur pose l'étiquette "Stage - ..." (mot-clé IMAP), les range dans un dossier
et envoie un récapitulatif quotidien. Si le service phishdetect est actif, chaque
mail est d'abord vérifié : un mail suspect est signalé et n'est pas trié.
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
# Mots-clés IMAP des étiquettes du webmail (Dovecot)
KEYWORDS = {
    "refus": "$stagerefus",
    "positif": "$stagepositif",
    "relance": "$stagerelance",
    "auto": "$stageauto",
    "attente": "$stageattente",
}
PHISH_LABEL = "Phishing suspect"
PHISH_KEYWORD = "$phishingsuspect"

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


def check_phishing(sender, subject, body):
    """Interroge phishdetect. Renvoie le verdict (dict) ou None s'il est désactivé ou en panne.

    Une panne du détecteur ne doit jamais bloquer le tri : on continue sans lui.
    """
    url = E.get("PHISHDETECT_URL", "").rstrip("/")
    if not url:
        return None
    req = urllib.request.Request(
        f"{url}/predict",
        data=json.dumps({"sender": sender, "subject": subject, "body": body[:8000]}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        # jusqu'à ~30 s quand le LLM est consulté en second avis
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    except (OSError, ValueError) as exc:
        print(f"phishdetect indisponible ({exc}), tri sans vérification")
        return None


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


def move(imap, uid):
    """Déplace le mail dans FOLDER_PARENT (créé s'il n'existe pas)."""
    target = f'"{E["FOLDER_PARENT"]}"'
    imap.create(target)  # sans effet s'il existe déjà
    if "MOVE" in imap.capabilities:
        return imap.uid("move", str(uid), target)[0] == "OK"
    # Repli : copie puis suppression de ce seul mail (UID EXPUNGE)
    if imap.uid("copy", str(uid), target)[0] != "OK":
        return False
    imap.uid("store", str(uid), "+FLAGS", r"(\Deleted)")
    imap.uid("expunge", str(uid))
    return True


def send_recap(results, day):
    # les mails suspects en premier
    results = sorted(results, key=lambda r: r[0] != PHISH_LABEL)
    if results:
        lines = [f"[{label}] {subject} - {sender}\n   {resume} (confiance {conf:.0%})"
                 for label, subject, sender, resume, conf in results]
        body = f"{len(results)} réponse(s) de candidature le {day} :\n\n" + "\n\n".join(lines)
    else:
        body = f"Aucune nouvelle réponse de candidature le {day}."
    msg = EmailMessage()
    msg["Subject"] = RECAP_SUBJECT
    msg["From"] = E.get("SMTP_FROM") or E["NOTIFY_TO"]
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
        body = text_body(msg)
        verdict = check_phishing(sender, subject, body)
        if verdict and verdict.get("phishing"):
            score = float(verdict.get("llm_score", verdict.get("score", 0)))
            why = verdict.get("reason") or f"modèle {verdict.get('source', '?')}"
            print(f"UID {uid} -> PHISHING SUSPECT ({score:.2f}) : {subject}")
            if not dry:  # étiqueté mais laissé dans la boîte de réception, jamais rangé
                imap.uid("store", str(uid), "+FLAGS", f"({PHISH_KEYWORD})")
            results.append([PHISH_LABEL, subject, sender, f"NE PAS CLIQUER - {why}", score])
            state["last_uid"] = uid
            save_state(state)
            continue
        try:
            cat, conf, resume = classify(sender, subject, body)
        except Exception as exc:
            print(f"UID {uid} : échec de classification ({exc}), réessai plus tard")
            break
        print(f"UID {uid} -> {cat} ({conf:.2f}) : {subject}")
        if cat != "autre":
            label = CATEGORIES[cat]
            if not dry:
                imap.uid("store", str(uid), "+FLAGS", f"({KEYWORDS[cat]})")
                if E.get("MOVE_TO_FOLDER", "false").lower() == "true" and not move(imap, uid):
                    print(f"UID {uid} : déplacement impossible")
            results.append([label, subject, sender, resume, conf])
        state["last_uid"] = uid
        save_state(state)
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
