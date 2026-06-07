#!/usr/bin/env python3
"""
Generate PWA icons for BowersHub AI.

Produces three PNGs in frontend/public/icons/:
  - icon-192.png         (any-purpose, 192x192)
  - icon-512.png         (any-purpose, 512x512)
  - icon-maskable-512.png (maskable, 512x512 — content fits inside the inner 80% safe zone)

Branding: dark navy background (#16213e theme color), indigo accent ring,
white "B" monogram. Simple, recognizable, no external font dependencies —
falls back to PIL's default when DejaVu isn't available.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


THEME = "#16213e"
ACCENT = "#6366f1"  # indigo-500 (matches Tailwind palette used in app)
TEXT_COLOR = "#ffffff"

OUT_DIR = Path(__file__).parent.parent / "frontend" / "public" / "icons"


def load_font(size: int) -> ImageFont.ImageFont:
    """Try a bold sans-serif; fall back gracefully."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def draw_icon(size: int, maskable: bool = False) -> Image.Image:
    """Draw the icon at the requested size."""
    img = Image.new("RGBA", (size, size), THEME)
    draw = ImageDraw.Draw(img)

    # Maskable icons need a safe zone (content lives inside ~80% center).
    # For non-maskable, content can go closer to the edges.
    inner_pad = int(size * 0.12) if maskable else int(size * 0.06)
    inner_box = (inner_pad, inner_pad, size - inner_pad, size - inner_pad)
    inner_size = size - 2 * inner_pad

    # Accent ring (a thick rounded square)
    ring_thickness = max(int(size * 0.04), 2)
    ring_pad = int(inner_size * 0.04)
    rx0 = inner_box[0] + ring_pad
    ry0 = inner_box[1] + ring_pad
    rx1 = inner_box[2] - ring_pad
    ry1 = inner_box[3] - ring_pad
    radius = int((rx1 - rx0) * 0.18)
    for offset in range(ring_thickness):
        draw.rounded_rectangle(
            (rx0 + offset, ry0 + offset, rx1 - offset, ry1 - offset),
            radius=max(radius - offset, 1),
            outline=ACCENT,
            width=1,
        )

    # "B" monogram, centered.
    font_size = int(inner_size * 0.62)
    font = load_font(font_size)
    text = "B"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = (size - text_w) // 2 - bbox[0]
    text_y = (size - text_h) // 2 - bbox[1]
    draw.text((text_x, text_y), text, font=font, fill=TEXT_COLOR)

    return img


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    icons = [
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("icon-maskable-512.png", 512, True),
    ]

    for filename, size, maskable in icons:
        img = draw_icon(size, maskable=maskable)
        out_path = OUT_DIR / filename
        img.save(out_path, "PNG")
        print(f"wrote {out_path} ({size}x{size}{' maskable' if maskable else ''})")


if __name__ == "__main__":
    main()
