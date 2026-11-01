#!/usr/bin/env bash
# Enregistre la démo de TriLama et produit :
#   docs/demo.mp4  (vidéo H.264, 1280x720)
#
# Usage, depuis la racine du projet :   bash demo/lancer-demo.sh
# Prérequis : TriLama lancé (docker compose up -d) avec DRY_RUN=false et MOVE_TO_FOLDER=true.
# Attention : le script envoie un vrai mail de test à NOTIFY_TO.

set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RACINE="$(cd "$ICI/.." && pwd)"
TMP="$ICI/tmp"
DOCS="$RACINE/docs"

command -v node >/dev/null || { echo "Il manque node : sudo apt install nodejs npm"; exit 1; }
command -v ffmpeg >/dev/null || { echo "Il manque ffmpeg : sudo apt install ffmpeg"; exit 1; }
[ -f "$RACINE/.env" ] || { echo "Fichier .env introuvable"; exit 1; }

# Vérifications avant de lancer : TriLama doit tourner et être en mode réel avec rangement
grep -q '^DRY_RUN=false' "$RACINE/.env" || { echo "Mets DRY_RUN=false dans .env (sinon le mail ne sera pas trié)"; exit 1; }
grep -q '^MOVE_TO_FOLDER=true' "$RACINE/.env" || { echo "Mets MOVE_TO_FOLDER=true dans .env"; exit 1; }
(cd "$RACINE" && docker compose ps --status running --services 2>/dev/null | grep -qx triage) \
  || { echo "TriLama ne tourne pas : lance d'abord  docker compose up -d"; exit 1; }
echo "TriLama tourne, enregistrement de la démo (5 à 8 minutes)..."

cd "$ICI"
[ -d node_modules/playwright ] || npm install
npx playwright install chromium

rm -rf "$TMP" && mkdir -p "$TMP" "$DOCS"
SORTIE="$TMP" node enregistrer-demo.mjs

# Carton de transition entre les deux parties
POLICE=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
if [ -f "$POLICE" ]; then
  TEXTE="drawtext=fontfile=$POLICE:text='Quelques minutes plus tard, TriLama a trié le mail':fontcolor=white:fontsize=34:x=(w-text_w)/2:y=(h-text_h)/2"
else
  TEXTE="null"
fi

# Assemblage : partie 1 + carton + partie 2 (filtre concat, qui harmonise les formats)
# -ss 0.5 : retire les premières images blanches de chaque partie
ffmpeg -y -loglevel error \
  -ss 0.5 -i "$TMP/partie1.webm" \
  -f lavfi -i "color=c=0x2f6f73:s=1280x720:r=30:d=2.5" \
  -ss 0.5 -i "$TMP/partie2.webm" \
  -filter_complex "[0:v]scale=1280:720,fps=30,setsar=1,format=yuv420p[a];[1:v]$TEXTE,setsar=1,format=yuv420p[b];[2:v]scale=1280:720,fps=30,setsar=1,format=yuv420p[c];[a][b][c]concat=n=3:v=1:a=0[v]" \
  -map "[v]" -c:v libx264 -preset veryfast -crf 23 -an -movflags +faststart "$DOCS/demo.mp4"

echo "Vidéo : docs/demo.mp4 ($(du -h "$DOCS/demo.mp4" | cut -f1), $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$DOCS/demo.mp4" | cut -d. -f1) s)"
