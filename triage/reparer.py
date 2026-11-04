"""Remet dans la boîte de réception les mails de la fac rangés par erreur dans le dossier des candidatures.

Sont concernés les mails du dossier FOLDER_PARENT dont l'expéditeur correspond à IGNORE_SENDERS
(par défaut univ-rouen.fr), sauf ceux envoyés depuis ma propre adresse. Ils perdent leurs
étiquettes "Stage - ..." et retournent dans IMAP_INBOX. Aucun appel à l'IA.

Par défaut, le script se contente d'afficher ce qu'il ferait. Pour appliquer :
    docker compose run --rm triage python reparer.py --appliquer
"""
import email
import imaplib
import sys

from app import E, KEYWORDS, clean_subject, dec, is_ignored


def main():
    appliquer = "--appliquer" in sys.argv
    boite = E.get("IMAP_INBOX", "INBOX")
    imap = imaplib.IMAP4_SSL(E["IMAP_HOST"], int(E.get("IMAP_PORT", 993)), timeout=60)
    imap.login(E["IMAP_USER"], E["IMAP_PASSWORD"])
    if imap.select(f'"{E["FOLDER_PARENT"]}"')[0] != "OK":
        raise SystemExit(f"Dossier introuvable : {E['FOLDER_PARENT']}")
    _, data = imap.uid("search", None, "ALL")
    uids = data[0].split()
    print(f"Connecté, {len(uids)} mail(s) dans « {E['FOLDER_PARENT']} »"
          + ("" if appliquer else " (simulation : ajouter --appliquer pour agir)"))
    a_remettre = []
    for uid in uids:
        _, head = imap.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
        entete = email.message_from_bytes(head[0][1])
        sender, subject = dec(entete["From"]), clean_subject(dec(entete["Subject"]))
        if is_ignored(sender):
            a_remettre.append(uid)
            print(f"  -> Réception : {subject} - {sender}")
    reussis = 0
    if appliquer:
        etiquettes = "(" + " ".join(KEYWORDS.values()) + ")"
        print(f"Déplacement vers « {boite} » (MOVE {'disponible' if 'MOVE' in imap.capabilities else 'absent, copie + suppression'})")
        for uid in a_remettre:
            u = uid.decode()
            res = imap.uid("store", u, "-FLAGS", etiquettes)
            if res[0] != "OK":
                print(f"  UID {u} : retrait des étiquettes refusé {res}")
            if "MOVE" in imap.capabilities:
                res = imap.uid("move", u, boite)
            else:
                res = imap.uid("copy", u, boite)
                if res[0] == "OK":
                    imap.uid("store", u, "+FLAGS", r"(\Deleted)")
                    imap.uid("expunge", u)
            if res[0] == "OK":
                reussis += 1
            else:
                print(f"  UID {u} : déplacement refusé {res}")
        print(f"{reussis}/{len(a_remettre)} mail(s) remis dans la boîte de réception")
    else:
        print(f"{len(a_remettre)} mail(s) à remettre dans la boîte de réception")
    imap.logout()


if __name__ == "__main__":
    main()
