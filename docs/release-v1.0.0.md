## TriLama v1.0.0

Première version de TriLama : tri automatique des réponses de candidature de stage par une IA locale.

### Fonctionnalités
- Classement des nouveaux mails par **Ollama (qwen2.5:3b)**, exécuté en local : refus, positif, relance, accusé de réception, attente.
- **Étiquette** posée dans le webmail et **rangement** dans le dossier « Candidatures stage ».
- **Récapitulatif quotidien** par mail à 20 h.
- **Mode test** (`DRY_RUN`) pour vérifier les classements sans rien modifier.

### Sécurité
- Aucun mail envoyé à un service tiers.
- Ollama sans port exposé, conteneur applicatif non root, secrets hors du dépôt.

### Installation
```bash
git clone https://github.com/RIZIWYX/TriLama.git && cd TriLama
cp .env.example .env && chmod 600 .env && mkdir -p data
docker compose up -d --build
```

Détails dans le [README](https://github.com/RIZIWYX/TriLama#readme) et le [CHANGELOG](https://github.com/RIZIWYX/TriLama/blob/main/CHANGELOG.md).
