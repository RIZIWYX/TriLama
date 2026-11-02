#!/usr/bin/env bash
# Enregistre la démo de la détection de phishing et produit, dans le dépôt PhishingDetect :
#   docs/demo.mp4 et docs/demo.gif
# Rien n'est ajouté aux docs de TriLama.
#
# Usage, depuis la racine de TriLama :   bash demo/lancer-demo-phishing.sh
# Prérequis : TriLama et phishdetect lancés (docker compose up -d) avec DRY_RUN=false,
# et une étiquette « Phishing suspect » (mot-clé $phishingsuspect) créée dans le webmail.
# Attention : le script envoie un vrai mail (faux phishing) à NOTIFY_TO, c'est-à-dire à toi.

set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RACINE="$(cd "$ICI/.." && pwd)"
TMP="$ICI/tmp-phishing"

command -v node >/dev/null || { echo "Il manque node : sudo apt install nodejs npm"; exit 1; }
command -v ffmpeg >/dev/null || { echo "Il manque ffmpeg : sudo apt install ffmpeg"; exit 1; }
[ -f "$RACINE/.env" ] || { echo "Fichier .env introuvable"; exit 1; }

# Dossier du projet PhishingDetect, où la vidéo sera déposée
PHISH="$(grep '^PHISHDETECT_DIR=' "$RACINE/.env" | cut -d= -f2- || true)"
PHISH="${PHISH:-../phishdetect}"
case "$PHISH" in /*) ;; *) PHISH="$RACINE/$PHISH" ;; esac
[ -d "$PHISH" ] || { echo "Projet PhishingDetect introuvable : $PHISH (variable PHISHDETECT_DIR du .env)"; exit 1; }
DOCS="$PHISH/docs"

# Vérifications : mode réel, détecteur activé et en marche
grep -q '^DRY_RUN=false' "$RACINE/.env" || { echo "Mets DRY_RUN=false dans .env (sinon l'étiquette ne sera pas posée)"; exit 1; }
grep -q '^PHISHDETECT_URL=..*' "$RACINE/.env" || { echo "Mets PHISHDETECT_URL=http://phishdetect:8000 dans .env"; exit 1; }
SERVICES="$(cd "$RACINE" && docker compose ps --status running --services 2>/dev/null)"
echo "$SERVICES" | grep -qx triage || { echo "TriLama ne tourne pas : lance d'abord  docker compose up -d"; exit 1; }
echo "$SERVICES" | grep -qx phishdetect || { echo "phishdetect ne tourne pas : vérifie COMPOSE_PROFILES=phishing puis  docker compose up -d"; exit 1; }
echo "TriLama et phishdetect tournent, enregistrement de la démo (5 à 10 minutes)..."

cd "$ICI"
[ -d node_modules/playwright ] || npm install
npx playwright install chromium

rm -rf "$TMP" && mkdir -p "$TMP" "$DOCS"
SORTIE="$TMP" node enregistrer-demo-phishing.mjs

# Carton de transition entre les deux parties
POLICE=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
if [ -f "$POLICE" ]; then
  TEXTE="drawtext=fontfile=$POLICE:text='Quelques minutes plus tard, TriLama a repéré le piège':fontcolor=white:fontsize=34:x=(w-text_w)/2:y=(h-text_h)/2"
else
  TEXTE="null"
fi

# Assemblage : partie 1 + carton + partie 2 (-ss 0.5 retire les premières images blanches)
ffmpeg -y -loglevel error \
  -ss 0.5 -i "$TMP/partie1.webm" \
  -f lavfi -i "color=c=0x7a2f2f:s=1280x720:r=30:d=2.5" \
  -ss 0.5 -i "$TMP/partie2.webm" \
  -filter_complex "[0:v]scale=1280:720,fps=30,setsar=1,format=yuv420p[a];[1:v]$TEXTE,setsar=1,format=yuv420p[b];[2:v]scale=1280:720,fps=30,setsar=1,format=yuv420p[c];[a][b][c]concat=n=3:v=1:a=0[v]" \
  -map "[v]" -c:v libx264 -preset veryfast -crf 23 -an -movflags +faststart "$DOCS/demo.mp4"

# GIF pour le README (palette dédiée : couleurs propres, fichier plus léger)
ffmpeg -y -loglevel error -i "$DOCS/demo.mp4" \
  -vf "fps=10,scale=960:-1:flags=lanczos,split[x][y];[x]palettegen=max_colors=128[p];[y][p]paletteuse=dither=bayer" \
  "$DOCS/demo.gif"

echo "Vidéo : $DOCS/demo.mp4 ($(du -h "$DOCS/demo.mp4" | cut -f1), $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$DOCS/demo.mp4" | cut -d. -f1) s)"
echo "GIF   : $DOCS/demo.gif ($(du -h "$DOCS/demo.gif" | cut -f1))"

echo "Avant de publier : regarde la vidéo en entier pour vérifier qu'aucun autre mail n'apparaît."
