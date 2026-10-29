#!/usr/bin/env python3
"""Render an image as a truecolor half-block ANSI logo for fastfetch.

Each terminal cell shows two vertical image pixels using U+2580 (upper half
block): foreground = top pixel, background = bottom pixel.  This keeps full
color fidelity and (with the right row count) the correct aspect ratio.

Aspect note: one cell column covers 1 image pixel, one cell row covers 2.
On screen a cell is about RATIO times taller than wide (measured for this
alacritty setup: 22.0 / 9.375 = 2.347), so the number of rows has to be
cols * image_aspect / RATIO for the picture to look undistorted.

Usage:
    python3 gen_logo.py [--cols 40] [--ratio 2.347] [--in IMG] [--out FILE]
"""
from __future__ import annotations

import argparse
import os
from PIL import Image

DEFAULT_IN = os.path.expanduser("~/Изображения/ava.jpg")
DEFAULT_OUT = os.path.expanduser("~/.config/fastfetch/ava.ansi")
BLOCK = "\u2580"


def build(src: str, cols: int, ratio: float) -> str:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    rows = max(1, round(cols * (h / w) / ratio))
    # "cover" fit: scale so the target box is fully filled, then centre-crop.
    px_w, px_h = cols, rows * 2
    scale = max(px_w / w, px_h / h)
    new = (max(px_w, round(w * scale)), max(px_h, round(h * scale)))
    im = im.resize(new, Image.LANCZOS)
    left, top = (new[0] - px_w) // 2, (new[1] - px_h) // 2
    im = im.crop((left, top, left + px_w, top + px_h))
    pixels = im.load()

    lines: list[str] = []
    for y in range(rows):
        out: list[str] = []
        fg = bg = None
        for x in range(cols):
            t = pixels[x, y * 2]
            b = pixels[x, y * 2 + 1]
            if t != fg:
                out.append("\033[38;2;%d;%d;%dm" % t)
                fg = t
            if b != bg:
                out.append("\033[48;2;%d;%d;%dm" % b)
                bg = b
            out.append(BLOCK)
        out.append("\033[0m")
        lines.append("".join(out))
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default=DEFAULT_IN)
    ap.add_argument("--out", dest="dst", default=DEFAULT_OUT)
    ap.add_argument("--cols", type=int, default=40)
    ap.add_argument("--ratio", type=float, default=2.347,
                    help="cell height/width ratio of your terminal font")
    a = ap.parse_args()
    art = build(a.src, a.cols, a.ratio)
    if os.path.dirname(a.dst):
        os.makedirs(os.path.dirname(a.dst), exist_ok=True)
    with open(a.dst, "w", encoding="utf-8") as fh:
        fh.write(art)
    print("wrote %s (%d lines, %d bytes)" % (a.dst, art.count("\n"), len(art)))


if __name__ == "__main__":
    main()