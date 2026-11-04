# Changelog

## v1.2.0 - 2026-11-03

- Les mails de la fac (expéditeurs listés dans `IGNORE_SENDERS`, par défaut `univ-rouen.fr`) ne passent plus par l'IA : ils restent dans la boîte de réception, sans étiquette, et ne figurent plus dans le récapitulatif. Les mails envoyés depuis sa propre adresse (tests, démos) restent triés.
- Liste blanche automatique : seuls sont triés les mails venant d'un domaine (ou d'une adresse, pour Gmail, Outlook…) auquel j'ai envoyé une candidature rangée dans « Candidatures stage », ou répondant directement à l'un de ces envois. Un expéditeur inconnu dont le mail parle de candidature ou de stage n'est pas trié mais apparaît dans la section « À vérifier » du récapitulatif ; les autres sont ignorés.
- Récapitulatif en sections : alertes phishing en tête, puis réponses regroupées par catégorie, puis mails à vérifier ; le total ne compte que les réponses de candidature.
- Objets nettoyés dans le récapitulatif (« Objet : » en tête, espaces en double).

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
