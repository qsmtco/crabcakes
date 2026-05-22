# utils/image_utils.py
# PNG icon generation from JPG source — pure Python, no GTK, no network.

from PIL import Image, ImageDraw
import os


def convert_logo_to_icons(jpg_path: str, output_dir: str) -> list[str]:
    """
    Convert crabcakes-logo.jpg to a set of PNG icons at standard sizes.

    Args:
        jpg_path:   Path to the source JPG logo
        output_dir: Directory to write PNG files into

    Returns:
        List of absolute paths to the generated PNG files
    """
    if not os.path.exists(jpg_path):
        raise FileNotFoundError(f"JPG not found: {jpg_path}")

    os.makedirs(output_dir, exist_ok=True)

    sizes = [16, 32, 48, 64, 128, 256]
    outputs = []

    def _add_white_background(img: Image.Image) -> Image.Image:
        """Composite logo onto a solid white background."""
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))  # white canvas
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        if img.mode in ("RGB", "RGBA") and img.size == bg.size:
            bg.paste(img, (0, 0))  # paste uses alpha if RGBA
        return bg

    def _add_rounded_corners(img: Image.Image, radius: int) -> Image.Image:
        """Add rounded corners to an image using an alpha mask.

        Mask: 0 = transparent (corners), 255 = opaque (body).
        Uses direct pixel loop with circle equation.
        """
        w, h = img.size
        r = min(radius, min(w, h) // 2)

        mask = Image.new("L", (w, h), 255)
        for x in range(r):
            for y in range(r):
                if x * x + y * y <= r * r:
                    mask.putpixel((x, y), 0)
                    mask.putpixel((w - 1 - x, y), 0)
                    mask.putpixel((x, h - 1 - y), 0)
                    mask.putpixel((w - 1 - x, h - 1 - y), 0)

        img.putalpha(mask)
        return img

    with Image.open(jpg_path) as img:
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")

        for size in sizes:
            out_path = os.path.join(output_dir, f"{size}.png")
            # Resize, add white background, then round corners
            resized = img.resize((size, size), Image.LANCZOS)
            with_bg = _add_white_background(resized)
            rounded = _add_rounded_corners(with_bg, radius=max(2, size // 8))
            rounded.save(out_path, format="PNG")
            outputs.append(out_path)
            print(f"  Saved: {out_path}")

    return outputs


if __name__ == "__main__":
    import sys
    base = "/home/q/projects/crabcakes"
    jpg = f"{base}/crabcakes-logo.jpg"
    out = f"{base}/icons"
    print(f"Converting {jpg} → {out}/")
    result = convert_logo_to_icons(jpg, out)
    print(f"Done. {len(result)} icons generated.")