# Tri automatique des réponses de candidature

Un service auto-hébergé qui surveille ma boîte mail universitaire, classe les réponses
à mes candidatures de stage avec un modèle d'IA **local** (Ollama), les range dans le bon
dossier et m'envoie un mail récapitulatif.

**Aucun mail ne quitte la machine** : le modèle tourne en local, sans API externe.

## Fonctionnement

```
IMAP (boîte univ) -> triage (Python) -> Ollama (qwen2.5:3b, local)
                         |
                         +-> déplacement dans "Candidatures stage/Stage - ..."
                         +-> mail récapitulatif (SMTP)
```

| Catégorie | Dossier |
|---|---|
| Refus | Stage - Refus |
| Entretien / proposition | Stage - Positif |
| Demande d'action | Stage - Relance |
| Accusé de réception | Stage - Auto |
| Réponse sans décision | Stage - Attente |
| Hors sujet | laissé dans la boîte de réception |

## Lancer

```bash
cp .env.example .env      # remplir identifiants IMAP/SMTP
mkdir -p data
docker compose up -d --build
docker compose logs -f triage
```

Le premier démarrage télécharge le modèle (~2 Go). Au premier lancement, seuls les mails
**reçus ensuite** sont triés. Laisser `DRY_RUN=true` pour vérifier les classements dans les
logs, puis passer à `false`.

## Choix techniques

- Bibliothèque standard Python uniquement (imaplib, smtplib, urllib) : pas de dépendance.
- `BODY.PEEK` : les mails restent non lus.
- Modèle à température 0 et sortie JSON forcée pour un classement stable.
- Ollama n'expose aucun port sur l'hôte ; conteneur applicatif non root ; secrets dans `.env` (ignoré par git).
- État (dernier UID traité) persistant dans `data/`, donc pas de double traitement après redémarrage.
