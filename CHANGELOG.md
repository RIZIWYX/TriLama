# Changelog

## v1.1.0 - 2026-11-02

- Vérification optionnelle de chaque mail par le détecteur de phishing phishdetect (service Docker `phishdetect`, profil `phishing`).
- Un mail suspect reçoit l'étiquette « Phishing suspect » (`$phishingsuspect`), n'est ni classé ni rangé, et apparaît en tête du récapitulatif.
- Une alerte exige la confirmation du LLM : le modèle classique seul jugeait suspects les mails de recruteurs en français.
- Si le détecteur est indisponible, le tri continue sans vérification.

## v1.0.0 - 2026-11-01

Première version.

- Relève IMAP des nouveaux mails toutes les 5 minutes, sans les marquer comme lus.
- Classement par IA locale (Ollama, qwen2.5:3b) en six catégories : refus, positif, relance, auto, attente, autre.
- Étiquettes du webmail posées sous forme de mots-clés IMAP (`$stagerefus`, `$stagepositif`…).
- Rangement optionnel dans le dossier « Candidatures stage ».
- Récapitulatif quotidien par mail (« RECAP CANDIDATURE DU JOUR »), ignoré par le tri.
- SMTP sur le port 465 (SSL) ou 587 (STARTTLS).
- Mode test `DRY_RUN`, état persistant, reprise sur erreur.
- Déploiement Docker Compose, conteneur non root, Ollama sans port exposé.
