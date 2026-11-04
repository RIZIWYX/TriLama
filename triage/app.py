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
from email.utils import getaddresses, parseaddr

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
CHECK_LABEL = "À vérifier"
# Messageries grand public : on retient l'adresse complète, pas le domaine
WEBMAILS = {"gmail.com", "googlemail.com", "outlook.com", "outlook.fr", "hotmail.com", "hotmail.fr",
            "live.com", "live.fr", "yahoo.com", "yahoo.fr", "icloud.com", "orange.fr", "wanadoo.fr",
            "free.fr", "sfr.fr", "laposte.net", "gmx.fr", "gmx.com", "proton.me", "protonmail.com"}
# Indices qu'un mail inconnu parle peut-être d'une candidature
HINTS = re.compile(r"candidat|stage|stagiaire|internship|application|postul|entretien|interview|recrut", re.I)

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


def clean_subject(subject):
    """Objet lisible pour le récap : sans "Objet :" en tête ni espaces en double."""
    subject = re.sub(r"^\s*(objet|subject)\s*:\s*", "", subject, flags=re.I)
    return re.sub(r"\s+", " ", subject).strip()


def is_ignored(sender):
    """Mail de la fac (cours, UniversiTICE...) : jamais une réponse de candidature.

    IGNORE_SENDERS liste des morceaux d'adresse séparés par des virgules. Les mails envoyés
    depuis ma propre adresse ne sont pas concernés (tests et démos).
    """
    addr = parseaddr(sender)[1].lower()
    moi = my_addresses()
    motifs = [m.strip().lower() for m in E.get("IGNORE_SENDERS", "univ-rouen.fr").split(",") if m.strip()]
    return addr not in moi and any(m in addr for m in motifs)


def my_addresses():
    return {a.lower() for a in (E.get("IMAP_USER", ""), E.get("NOTIFY_TO", ""), E.get("SMTP_FROM", "")) if "@" in a}


def contact_key(addr):
    """Domaine de l'adresse, ou l'adresse complète pour une messagerie grand public."""
    addr = addr.lower()
    domain = addr.rpartition("@")[2]
    return addr if domain in WEBMAILS else domain


def load_whitelist(imap):
    """Liste blanche tirée de mes envois rangés dans FOLDER_PARENT.

    Renvoie (contacts, ids) : domaines ou adresses auxquels j'ai écrit, et Message-ID de mes envois
    (pour reconnaître une réponse directe, quel que soit le domaine de l'expéditeur).
    """
    contacts, ids = set(), set()
    if imap.select(f'"{E["FOLDER_PARENT"]}"', readonly=True)[0] != "OK":
        return contacts, ids
    _, data = imap.fetch("1:*", "(BODY.PEEK[HEADER.FIELDS (FROM TO CC MESSAGE-ID)])")
    moi = my_addresses()
    for item in data:
        if not isinstance(item, tuple):
            continue
        h = email.message_from_bytes(item[1])
        if parseaddr(h.get("From", ""))[1].lower() not in moi:
            continue
        for _, addr in getaddresses(h.get_all("To", []) + h.get_all("Cc", [])):
            if "@" in addr and addr.lower() not in moi:
                contacts.add(contact_key(addr))
        if h.get("Message-ID"):
            ids.add(h["Message-ID"].strip())
    return contacts, ids


def is_known(msg, sender, contacts, ids):
    """Vrai si le mail vient d'un contact de candidature ou répond à l'un de mes envois."""
    if contact_key(parseaddr(sender)[1]) in contacts:
        return True
    refs = (msg.get("In-Reply-To", "") + " " + msg.get("References", "")).split()
    return any(r.strip() in ids for r in refs)


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
    def ligne(label, subject, sender, resume, conf):
        fin = "" if label == CHECK_LABEL else f" (confiance {conf:.0%})"
        return f"- {subject} - {sender}\n  {resume}{fin}"

    phishing = [r for r in results if r[0] == PHISH_LABEL]
    a_verifier = [r for r in results if r[0] == CHECK_LABEL]
    reponses = [r for r in results if r[0] not in (PHISH_LABEL, CHECK_LABEL)]
    parts = []
    if phishing:
        parts.append(f"!!! {len(phishing)} MAIL(S) DE PHISHING SUSPECT(S) - NE PAS CLIQUER !!!\n"
                     "(laissés dans la boîte de réception, étiquette « Phishing suspect »)\n\n"
                     + "\n\n".join(ligne(*r) for r in phishing))
    if reponses:
        parts.append(f"{len(reponses)} réponse(s) de candidature le {day}")
        for label in CATEGORIES.values():  # ordre : refus, positif, relance, auto, attente
            groupe = [r for r in reponses if r[0] == label]
            if groupe:
                parts.append(f"== {label} ({len(groupe)}) ==\n\n"
                             + "\n\n".join(ligne(*r) for r in groupe))
    else:
        parts.append(f"Aucune nouvelle réponse de candidature le {day}.")
    if a_verifier:
        parts.append(f"== À vérifier ({len(a_verifier)}) ==\n"
                     "(expéditeur inconnu qui parle peut-être d'une candidature, non trié)\n\n"
                     + "\n\n".join(ligne(*r) for r in a_verifier))
    body = "\n\n\n".join(parts)
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
    contacts, ids = load_whitelist(imap)
    if state.get("whitelist_size") != len(contacts):
        print(f"Liste blanche : {len(contacts)} contact(s) de candidature, {len(ids)} envoi(s)")
        state["whitelist_size"] = len(contacts)
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
        sender, subject = dec(msg["From"]), clean_subject(dec(msg["Subject"]))
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
        if is_ignored(sender):
            print(f"UID {uid} -> ignoré (expéditeur de la fac) : {subject}")
            state["last_uid"] = uid
            save_state(state)
            continue
        own = parseaddr(sender)[1].lower() in my_addresses()  # mes tests et démos
        if not own and not is_known(msg, sender, contacts, ids):
            if HINTS.search(subject) or HINTS.search(body[:2000]):
                # inconnu mais qui parle peut-être d'une candidature : signalé, pas touché
                print(f"UID {uid} -> à vérifier (expéditeur inconnu) : {subject}")
                results.append([CHECK_LABEL, subject, sender,
                                "Expéditeur absent de mes candidatures, laissé dans la boîte de réception", 1.0])
            else:
                print(f"UID {uid} -> ignoré (sans rapport avec mes candidatures) : {subject}")
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
