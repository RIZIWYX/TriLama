# TriLama

**Tri automatique des réponses de candidature de stage par une IA qui tourne en local.**

TriLama surveille ma boîte mail universitaire. Chaque nouveau mail est lu par un modèle de langage
hébergé sur ma machine (Ollama), qui reconnaît les refus, les propositions d'entretien, les relances
et les accusés de réception. Le mail reçoit l'étiquette correspondante dans le webmail, il est rangé
dans le dossier « Candidatures stage », et je reçois chaque soir un récapitulatif.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker_Compose-2496ED?logo=docker&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-qwen2.5:3b-000000)
![Dépendances](https://img.shields.io/badge/d%C3%A9pendances-biblioth%C3%A8que_standard-success)

> **Aucun mail ne quitte la machine.** Pas d'API externe : le modèle est exécuté en local.

## Démonstration

https://github.com/RIZIWYX/TriLama/raw/main/docs/demo.mp4

[▶ Voir la vidéo de démonstration](docs/demo.mp4)

Un mail de refus arrive, TriLama le classe en quelques secondes, lui pose l'étiquette
**Stage - Refus** et le range dans **Candidatures stage**.

```
triage-1  | Tri des candidatures démarré
triage-1  | UID 2633 -> refus (1.00) : Votre candidature au poste de stagiaire développeur
```

## Fonctionnement

```
          IMAP (lecture)                     HTTP (réseau Docker interne)
Webmail  ───────────────►  triage (Python)  ──────────────────────────►  Ollama
(Dovecot)                        │           ◄──────────────────────────  qwen2.5:3b
   ▲                             │             {"categorie": "refus", ...}
   │   étiquette + rangement     │
   └─────────────────────────────┤
                                 │  SMTP, chaque soir à 20 h
                                 └───────────────────────────►  RECAP CANDIDATURE DU JOUR
```

1. Toutes les 5 minutes, `triage` relève les nouveaux mails en IMAP (sans les marquer comme lus).
2. L'expéditeur, l'objet et le corps sont envoyés à Ollama avec une consigne de classement.
   Le modèle répond en JSON imposé, à température 0 pour des résultats stables.
3. Selon la catégorie, `triage` pose l'étiquette (mot-clé IMAP) et déplace le mail.
4. Les réponses de la journée sont gardées en mémoire et envoyées dans un récapitulatif quotidien.

Ollama n'a jamais accès à la boîte mail : il ne voit que le texte que `triage` lui transmet.

| Catégorie | Exemple | Étiquette (mot-clé IMAP) |
|---|---|---|
| Refus | « votre candidature n'a pas été retenue » | Stage - Refus (`$stagerefus`) |
| Positif | proposition d'entretien, de test, d'appel | Stage - Positif (`$stagepositif`) |
| Relance | l'entreprise demande un document ou une action | Stage - Relance (`$stagerelance`) |
| Auto | « nous avons bien reçu votre candidature » | Stage - Auto (`$stageauto`) |
| Attente | réponse humaine sans décision | Stage - Attente (`$stageattente`) |
| Autre | cours, scolarité, newsletters… | aucune, le mail n'est pas touché |

## Installation

Prérequis : Docker et Docker Compose, environ 4 Go de mémoire disponible (RAM + swap) et 3 Go de disque.

```bash
git clone https://github.com/RIZIWYX/TriLama.git
cd TriLama
cp .env.example .env   # renseigner les accès IMAP/SMTP
chmod 600 .env
mkdir -p data
docker compose up -d --build
docker compose logs -f triage
```

Au premier démarrage, le modèle (environ 2 Go) est téléchargé. Seuls les mails reçus
**après** le premier lancement sont traités : l'historique de la boîte n'est pas modifié.

Laisser `DRY_RUN=true` quelques jours permet de vérifier les classements dans les logs
sans rien modifier, avant de passer à `false`.

## Configuration

| Variable | Rôle | Défaut |
|---|---|---|
| `IMAP_HOST`, `IMAP_PORT` | Serveur de réception | port `993` |
| `IMAP_USER`, `IMAP_PASSWORD` | Identifiants de la messagerie | |
| `SMTP_HOST`, `SMTP_PORT` | Serveur d'envoi (`465` SSL ou `587` STARTTLS) | `587` |
| `SMTP_USER`, `SMTP_PASSWORD` | Identifiants d'envoi | |
| `NOTIFY_TO` | Destinataire et expéditeur du récapitulatif | |
| `FOLDER_PARENT` | Dossier de rangement | `Candidatures stage` |
| `MOVE_TO_FOLDER` | Ranger le mail en plus de l'étiqueter | `false` |
| `OLLAMA_MODEL` | Modèle utilisé | `qwen2.5:3b` |
| `POLL_SECONDS` | Intervalle entre deux relèves | `300` |
| `RECAP_HOUR` | Heure du récapitulatif (heure locale) | `20` |
| `DRY_RUN` | Classer sans rien modifier | `true` |

## Sécurité et vie privée

- **Traitement local** : aucun contenu de mail n'est envoyé à un service tiers.
- **Surface réduite** : Ollama n'expose aucun port sur l'hôte, il n'est joignable que depuis le réseau Docker interne.
- **Moindre privilège** : le service `triage` tourne avec un utilisateur non root.
- **Secrets hors du dépôt** : identifiants dans `.env`, exclu par `.gitignore`.
- **Modifications ciblées** : seul le mail traité est déplacé (`MOVE` IMAP, ou `UID EXPUNGE`) ; aucune suppression globale.
- **Boucle évitée** : les récapitulatifs envoyés par TriLama sont reconnus et ignorés.

## Vidéo de démonstration

`bash demo/lancer-demo.sh` enregistre la démo dans le webmail avec Playwright
(envoi d'un faux refus, attente du tri, affichage du mail étiqueté) et produit `docs/demo.mp4`.

## Choix techniques

- **Bibliothèque standard Python uniquement** (`imaplib`, `smtplib`, `urllib`, `zoneinfo`) : pas de dépendance à maintenir.
- **État persistant** (`data/state.json`) : dernier mail traité et réponses du jour, donc ni doublon ni perte après un redémarrage.
- **Reprise sur erreur** : si le modèle échoue, le mail est retenté au cycle suivant.
- **Redémarrage automatique** des conteneurs (`restart: unless-stopped`).

## Limites et pistes

- Un petit modèle peut se tromper sur des cas ambigus ; le mode `DRY_RUN` sert à le vérifier.
- Le tri ne fonctionne que lorsque la machine est allumée.
- Pistes : tests unitaires sur un jeu de mails annotés, intégration continue (GitHub Actions),
  seuil de confiance minimal, accélération GPU optionnelle.

## Auteur

Rayane Graïne, étudiant en L3 informatique à l'Université de Rouen Normandie -
[GitHub](https://github.com/RIZIWYX) · [LinkedIn](https://www.linkedin.com/in/rayane-graine)
