#!/usr/bin/env bash
# Re-render the fastfetch logo from the avatar photo with chafa.
#
#   ./make_logo.sh [COLS] [IMAGE]
#   ./make_logo.sh 40          # default: 40 columns wide
#
# Ratio 0.4261 = measured terminal cell width/height for alacritty's default font
# (cell 9.375 x 22.0 px). If you change the terminal font or its size, re-measure:
# render a 24x12 grid of U+2588 blocks in alacritty, screenshot the window and divide
# the grid's pixel width/height by 24 and 12.
set -euo pipefail

COLS="${1:-40}"
IMG="${2:-$HOME/Изображения/ava.jpg}"
OUT="$HOME/.config/fastfetch/ava.ansi"
FONT_RATIO=0.4261

# The image is square-ish, so rows = cols * aspect / ratio; chafa keeps the aspect itself.
ROWS="$(awk -v c="$COLS" -v ar=1.0054 -v fr="$FONT_RATIO" 'BEGIN{ printf "%d", (c*ar*fr)+0.5 }')"

chafa -f symbols --probe=off \
      -s "${COLS}x${ROWS}" --font-ratio="$FONT_RATIO" \
      -c full --symbols block+space \
      --color-space din99d -w 9 \
      "$IMG" > "$OUT"

printf 'rendered %s (%sx%s cells, %s bytes)\n' "$OUT" "$COLS" "$ROWS" "$(stat -c%s "$OUT")"