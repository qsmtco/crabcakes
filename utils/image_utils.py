# utils/image_utils.py
# PNG icon generation from JPG source — pure Python, no GTK, no network.

from PIL import Image
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

    with Image.open(jpg_path) as img:
        # Convert to RGBA (handles transparency + palette modes)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")

        for size in sizes:
            out_path = os.path.join(output_dir, f"{size}.png")
            # High-quality resize using LANCZOS
            resized = img.resize((size, size), Image.LANCZOS)
            resized.save(out_path, format="PNG")
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