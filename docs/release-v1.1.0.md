## TriLama v1.1.0

TriLama repère désormais les mails de phishing, grâce à [PhishingDetect](https://github.com/RIZIWYX/PhishingDetect), avant de trier les réponses de candidature.

### Nouveautés
- **Détection du phishing** (optionnelle) : chaque nouveau mail est vérifié par le service `phishdetect` avant le tri.
- Un mail suspect reçoit l'étiquette **Phishing suspect** (`$phishingsuspect`), **reste dans la boîte de réception**, n'est ni classé ni rangé : un faux recruteur ne finit pas en « Stage - Positif ».
- Les mails suspects apparaissent **en tête du récapitulatif** avec la mention « NE PAS CLIQUER » et la justification du LLM.
- Décision en deux étages : un modèle TF-IDF + régression logistique filtre en ~1 ms, le LLM local confirme avant toute alerte. Le modèle classique seul jugeait suspects les vrais mails de recruteurs en français.

### Fiabilité
- Si le détecteur est arrêté ou en panne, TriLama trie normalement, sans vérification.
- Si le LLM ne répond pas, le mail n'est pas accusé.

### Sécurité
- Service `phishdetect` non root, sans port publié, joignable uniquement par `triage` sur le réseau Docker interne.
- Même conteneur Ollama (`qwen2.5:3b`) pour le tri et la détection, aucun mail envoyé à un service tiers.

### Activer la détection
```bash
git clone https://github.com/RIZIWYX/PhishingDetect.git ../phishdetect
# entraîner le modèle une fois : voir le README de PhishingDetect
# dans .env : COMPOSE_PROFILES=phishing et PHISHDETECT_URL=http://phishdetect:8000
docker compose up -d --build
```
Créer ensuite dans le webmail une étiquette « Phishing suspect » associée au mot-clé `$phishingsuspect`.

Détails dans le [README](https://github.com/RIZIWYX/TriLama#détection-du-phishing-optionnelle) et le [CHANGELOG](https://github.com/RIZIWYX/TriLama/blob/main/CHANGELOG.md).
