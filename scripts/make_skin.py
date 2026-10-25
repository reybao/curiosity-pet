"""Turn a 2x2 character sheet into a private skin folder (see docs/SKIN.md).

Quadrants are read as: top-left idle, top-right listening, bottom-left thinking, bottom-right speaking.
The white (or light grey) background connected to the tile edges is removed, each pose is trimmed,
centered horizontally and aligned at the feet on the same square canvas, and written as 1024x1024 PNGs.

Usage:
    uv run --with pillow python scripts/make_skin.py SHEET.png OUT_DIR --name-zh 悟空 --name-en Goku --sound-zh 嘿 --sound-en hey
"""

import argparse
import json
from collections import deque
from pathlib import Path

from PIL import Image

STATES = {"idle": (0, 0), "listening": (1, 0), "thinking": (0, 1), "speaking": (1, 1)}


def knock_out_background(tile: Image.Image, light: int) -> Image.Image:
    """Make the background transparent: flood-fill light pixels connected to the corners.

    Light pixels inside the character (eye highlights, teeth) are not connected to the edge and stay.
    Edge pixels next to the background get partial alpha by darkness, which softens the outline.
    """
    px = tile.load()
    w, h = tile.size
    bg = [[False] * w for _ in range(h)]

    def is_light(x, y):
        r, g, b, _ = px[x, y]
        return min(r, g, b) > light

    queue = deque()
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if is_light(x, y):
            bg[y][x] = True
            queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not bg[ny][nx] and is_light(nx, ny):
                bg[ny][nx] = True
                queue.append((nx, ny))
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if bg[y][x]:
                px[x, y] = (r, g, b, 0)
            elif any(
                0 <= nx < w and 0 <= ny < h and bg[ny][nx]
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
            ):
                lum = (r + g + b) / 3
                px[x, y] = (r, g, b, int(max(0, min(255, (255 - lum) * 2.2))))
    return tile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("out")
    ap.add_argument("--name-zh", required=True)
    ap.add_argument("--name-en", required=True)
    ap.add_argument("--sound-zh", default="喵")
    ap.add_argument("--sound-en", default="meow")
    ap.add_argument("--light", type=int, default=190, help="min channel value counted as background (default 190)")
    ap.add_argument("--trim", type=float, default=0.02, help="fraction cut from each tile edge to drop grid lines")
    ap.add_argument("--size", type=int, default=1024)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sheet = Image.open(args.sheet).convert("RGBA")
    W, H = sheet.size
    tw, th = W // 2, H // 2
    mx, my = int(tw * args.trim), int(th * args.trim)

    cut = {}
    for state, (cx, cy) in STATES.items():
        tile = sheet.crop((cx * tw + mx, cy * th + my, (cx + 1) * tw - mx, (cy + 1) * th - my))
        tile = knock_out_background(tile, args.light)
        bbox = tile.getbbox()
        if not bbox:
            raise SystemExit(f"{state}: nothing left after removing the background")
        cut[state] = tile.crop(bbox)

    pad = 40
    side = max(max(t.size[0] for t in cut.values()), max(t.size[1] for t in cut.values())) + 2 * pad
    for state, tile in cut.items():
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(tile, ((side - tile.size[0]) // 2, side - pad - tile.size[1]), tile)
        canvas.resize((args.size, args.size), Image.LANCZOS).save(out / f"{state}.png")

    manifest = {
        "name": {"zh": args.name_zh, "en": args.name_en},
        "sound": {"zh": args.sound_zh, "en": args.sound_en},
        "images": {state: f"{state}.png" for state in STATES},
    }
    (out / "skin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"skin written to {out}: {sorted(p.name for p in out.iterdir())}")


if __name__ == "__main__":
    main()
