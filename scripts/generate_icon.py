#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["Pillow>=10.0"]
# ///
"""
Generate TeterAI CA icon files for the desktop app build.

Usage:
    uv run scripts/generate_icon.py

Source image (optional):
    Drop your logo as build-resources/icon-source.png (or .jpg).
    The script will center-crop it to a square and use it as the icon.
    If no source image is found, a programmatic branded "T" is generated.

Outputs to build-resources/:
    icon.png   (512x512 — Linux + source)
    icon.ico   (multi-resolution 16/32/48/64/128/256 — Windows)
    icon.icns  (macOS placeholder — copy of icon.png)
"""

import shutil
import struct
import zlib
from io import BytesIO
from pathlib import Path

# Brand colours (fallback programmatic icon)
DARK   = (0x31, 0x31, 0x31, 255)   # #313131
ORANGE = (0xF3, 0x70, 0x21, 255)   # #F37021
TRANSP = (0x00, 0x00, 0x00,   0)

OUT_DIR = Path(__file__).parent.parent / "build-resources"

# Candidate source image filenames (checked in order)
SOURCE_CANDIDATES = ["icon-source.png", "icon-source.jpg", "icon-source.jpeg"]


# ---------------------------------------------------------------------------
# Source-image loader — center-crops portrait/landscape to square
# ---------------------------------------------------------------------------

def load_source_image(size: int):
    """
    If a source image exists in build-resources/, load it, center-crop to
    square, and resize to `size`×`size`. Returns a PIL Image or None.
    """
    from PIL import Image

    for name in SOURCE_CANDIDATES:
        path = OUT_DIR / name
        if path.exists():
            print(f"  Found source image: {path.name}")
            img = Image.open(path).convert("RGBA")
            w, h = img.size

            # Center-crop to square
            side = min(w, h)
            left = (w - side) // 2
            top  = (h - side) // 2
            img  = img.crop((left, top, left + side, top + side))

            # Resize to target
            img = img.resize((size, size), Image.LANCZOS)
            print(f"  Cropped {w}×{h} → {side}×{side}, resized to {size}×{size}")
            return img

    return None


# ---------------------------------------------------------------------------
# Programmatic fallback — dark background + orange "T" lettermark
# ---------------------------------------------------------------------------

def render_fallback_pil(size: int):
    from PIL import Image, ImageDraw

    img  = Image.new("RGBA", (size, size), TRANSP)
    draw = ImageDraw.Draw(img)

    pad    = size // 10
    radius = size // 5

    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=radius,
        fill=DARK,
    )

    bar_h  = max(4, size // 8)
    bar_w  = int(size * 0.52)
    stem_w = max(3, size // 7)
    bar_x  = (size - bar_w)  // 2
    bar_y  = int(size * 0.25)
    stem_x = (size - stem_w) // 2
    stem_b = int(size * 0.78)

    draw.rectangle([bar_x, bar_y,       bar_x + bar_w, bar_y + bar_h], fill=ORANGE)
    draw.rectangle([stem_x, bar_y, stem_x + stem_w, stem_b],           fill=ORANGE)

    return img


def render_fallback_stdlib(size: int) -> bytes:
    """Pure-stdlib PNG renderer — no Pillow required."""
    def _chunk(tag, data):
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    pad    = size // 10
    radius = size // 5
    bar_h  = max(4, size // 8)
    bar_w  = int(size * 0.52)
    stem_w = max(3, size // 7)
    bar_x  = (size - bar_w)  // 2
    bar_y  = int(size * 0.25)
    stem_x = (size - stem_w) // 2
    stem_b = int(size * 0.78)

    def in_bg(x, y):
        x1, y1, x2, y2 = pad, pad, size - pad, size - pad
        if not (x1 <= x <= x2 and y1 <= y <= y2):
            return False
        in_corner = (x < x1 + radius or x > x2 - radius) and (y < y1 + radius or y > y2 - radius)
        if not in_corner:
            return True
        for cx, cy in [(x1+radius, y1+radius),(x2-radius, y1+radius),
                       (x1+radius, y2-radius),(x2-radius, y2-radius)]:
            if abs(x-cx) <= radius and abs(y-cy) <= radius:
                return (x-cx)**2 + (y-cy)**2 <= radius**2
        return False

    def in_t(x, y):
        return (bar_x  <= x <= bar_x  + bar_w and bar_y <= y <= bar_y + bar_h) or \
               (stem_x <= x <= stem_x + stem_w and bar_y <= y <= stem_b)

    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            row += bytearray(ORANGE if in_t(x, y) else (DARK if in_bg(x, y) else TRANSP))
        rows.append(bytes(row))

    compressed = zlib.compress(b"".join(rows), 9)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", compressed)
            + _chunk(b"IEND", b""))


# ---------------------------------------------------------------------------
# ICO writer — multi-resolution PNG-in-ICO
# ---------------------------------------------------------------------------

def build_ico(get_image, sizes=(256, 128, 64, 48, 32, 16)):
    """Build a Windows ICO containing PNG data at each resolution."""
    images = []
    for s in sizes:
        img = get_image(s)
        buf = BytesIO()
        img.save(buf, format="PNG")
        images.append((s, buf.getvalue()))

    header  = struct.pack("<HHH", 0, 1, len(images))
    offset  = 6 + 16 * len(images)
    entries = b""
    for s, data in images:
        w = h = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(data), offset)
        offset  += len(data)

    return header + entries + b"".join(d for _, d in images)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import Image as _PIL  # noqa: F401
        use_pil = True
        print("  Pillow available — high-quality rendering enabled.")
    except ImportError:
        use_pil = False
        print("  Pillow not found — using stdlib fallback (run via 'uv run' for better quality).")

    # --- Determine rendering function ---
    if use_pil:
        source = load_source_image(512)
        if source:
            # Build icon.png from source
            def get_pil_image(size):
                s = load_source_image(size)
                return s if s is not None else render_fallback_pil(size)
            master = source
            print("  Using source image for all icon sizes.")
        else:
            print("  No icon-source.png found — using programmatic 'T' lettermark.")
            print("  Tip: drop your logo as build-resources/icon-source.png to use it instead.")
            get_pil_image = render_fallback_pil
            master = render_fallback_pil(512)

        # icon.png (512x512)
        print("  Writing icon.png …")
        master.save(OUT_DIR / "icon.png", "PNG")

        # icon.ico (multi-res)
        print("  Writing icon.ico …")
        ico_data = build_ico(get_pil_image)
        (OUT_DIR / "icon.ico").write_bytes(ico_data)

    else:
        # Stdlib fallback — source images require PIL
        for path in (OUT_DIR / n for n in SOURCE_CANDIDATES):
            if path.exists():
                print(f"  [WARN] Found {path.name} but Pillow is required to use it.")
                print("  Run: uv run --with Pillow scripts/generate_icon.py")
                break

        print("  Writing icon.png (stdlib) …")
        (OUT_DIR / "icon.png").write_bytes(render_fallback_stdlib(512))

        print("  Writing icon.ico (stdlib) …")
        sizes = (256, 128, 64, 48, 32, 16)
        images = [(s, render_fallback_stdlib(s)) for s in sizes]
        header  = struct.pack("<HHH", 0, 1, len(images))
        offset  = 6 + 16 * len(images)
        entries = b""
        for s, data in images:
            w = h = 0 if s >= 256 else s
            entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(data), offset)
            offset  += len(data)
        (OUT_DIR / "icon.ico").write_bytes(header + entries + b"".join(d for _, d in images))

    # icon.icns — copy of icon.png (macOS placeholder)
    print("  Writing icon.icns (macOS placeholder) …")
    shutil.copy(OUT_DIR / "icon.png", OUT_DIR / "icon.icns")

    print(f"\n  Done. Icons written to {OUT_DIR}/")
    print("  ✓ icon.png  (512×512)")
    print("  ✓ icon.ico  (multi-res: 16/32/48/64/128/256)")
    print("  ✓ icon.icns (placeholder for macOS)")


if __name__ == "__main__":
    main()
