# utils/icons.py
# SVG icon rendering — agent avatars and folder icons via Gdk.Texture.
#
# Security Manifest:
#   Reads: nothing
#   Writes: nothing (tempfile deleted after use)
#   External: none
#   GTK: Gdk.Texture (utils/ is allowed GTK access)

import math
import os
import tempfile

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk


def render_folder_icon(color_hex: str, letter: str, size: int = 44) -> Gdk.Texture | None:
    """
    Render a folder icon: colored SVG with tab notch + white letter centered on body.

    Args:
        color_hex:  Hex color string e.g. "#6366f1"
        letter:     Single character to display on folder body
        size:       Pixel size (default 44)

    Returns:
        Gdk.Texture — safe to use with Gtk.Picture.set_paintable()
        Returns None on error (texture load failure, missing display).
    """
    if size < 4:
        size = 44

    body_w = size
    body_h = size * 0.8
    tab_w = size * 0.35
    tab_h = size * 0.25
    corner = max(2, size * 0.06)
    letter_size = max(8, int(size * 0.45))

    # Folder body rect with rounded bottom corners
    body_x = 0
    body_y = tab_h
    body_path = (
        f"M {body_x + corner},{body_y} "
        f"L {body_x + body_w - corner},{body_y} "
        f"Q {body_x + body_w},{body_y} {body_x + body_w},{body_y + corner} "
        f"L {body_x + body_w},{body_y + body_h - corner} "
        f"Q {body_x + body_w},{body_y + body_h} {body_x + body_w - corner},{body_y + body_h} "
        f"L {body_x + corner},{body_y + body_h} "
        f"Q {body_x},{body_y + body_h} {body_x},{body_y + body_h - corner} "
        f"L {body_x},{body_y + corner} "
        f"Q {body_x},{body_y} {body_x + corner},{body_y} Z"
    )

    # Folder tab notch at top-left
    tab_path = (
        f"M 0,{body_y} "
        f"L 0,{tab_h * 0.4} "
        f"L {tab_w},{tab_h * 0.4} "
        f"L {tab_w + corner},{tab_h * 0.4} "
        f"L {tab_w + corner},{tab_h} "
        f"L {body_x + corner},{tab_h} "
        f"Q {body_x},{tab_h} {body_x},{tab_h - corner} "
        f"L 0,{body_y} Z"
    )

    # Letter centered in body
    letter_x = body_w / 2
    letter_y = body_y + body_h * 0.55

    def _darken(hex_color: str) -> str:
        r = int(hex_color[1:3], 16) * 0.6
        g = int(hex_color[3:5], 16) * 0.6
        b = int(hex_color[5:7], 16) * 0.6
        return f"#{int(r):02x}{int(g):02x}{int(b):02x}"

    dark = _darken(color_hex)

    svg = f'''<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}"
     xmlns="http://www.w3.org/2000/svg">
      <path d="{body_path}" fill="{color_hex}"/>
      <path d="{tab_path}" fill="{color_hex}"/>
      <path d="{body_path}" fill="none" stroke="{dark}" stroke-width="{max(1, size/44):.1f}"/>
      <path d="{tab_path}" fill="none" stroke="{dark}" stroke-width="{max(1, size/44):.1f}"/>
      <text x="{letter_x}" y="{letter_y}"
       font-family="Arial,sans-serif" font-size="{letter_size}" font-weight="700"
       fill="white" text-anchor="middle" dominant-baseline="middle"
       letter-spacing="0">{letter}</text>
    </svg>'''

    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".svg", delete=False)
        tmp_name = tmp.name
        tmp.write(svg.encode())
        tmp.close()
        try:
            return Gdk.Texture.new_from_filename(tmp_name)
        finally:
            os.unlink(tmp_name)
    except Exception:
        return None



def render_agent_icon(color_hex: str, initials: str, size: int = 44) -> Gdk.Texture:
    """
    Render an agent avatar: colored circle with inscribed hexagon outline + initials.

    Args:
        color_hex:  Hex color string e.g. "#6366f1"
        initials:   2-character string (e.g. "Qr" from "Qrusher")
        size:       Pixel size (default 44)

    Returns:
        Gdk.Texture — safe to use with Gtk.Picture.set_paintable()
    """
    if size < 1 or size > 512:
        size = 44

    cx = size / 2
    cy = size / 2
    circle_r = size / 2 - 2
    hex_r = circle_r * 0.9
    stroke_w = max(1, size / 22)
    font_size = max(8, int(size * 0.27))
    text_y = cy + font_size * 0.35

    # Point-up hexagon vertices
    pts = []
    for i in range(6):
        angle = (60 * i - 90) * math.pi / 180
        px = cx + hex_r * math.cos(angle)
        py = cy + hex_r * math.sin(angle)
        pts.append((px, py))
    path_d = "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in pts) + " Z"

    def _darken(hex_color: str) -> str:
        r = int(hex_color[1:3], 16) * 0.65
        g = int(hex_color[3:5], 16) * 0.65
        b = int(hex_color[5:7], 16) * 0.65
        return f"#{int(r):02x}{int(g):02x}{int(b):02x}"

    hex_dark = _darken(color_hex)

    svg = f'''<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}"
     xmlns="http://www.w3.org/2000/svg">
      <circle cx="{cx}" cy="{cy}" r="{circle_r}" fill="{color_hex}"/>
      <path d="{path_d}" fill="none" stroke="{hex_dark}" stroke-width="{stroke_w:.1f}"/>
      <text x="{cx}" y="{text_y}"
       font-family="Sans,Arial,sans-serif" font-size="{font_size}" font-weight="700"
       fill="white" text-anchor="middle" dominant-baseline="middle"
       letter-spacing="0.5">{initials}</text>
    </svg>'''

    tmp = tempfile.NamedTemporaryFile(suffix=".svg", delete=False)
    tmp_name = tmp.name
    tmp.write(svg.encode())
    tmp.close()
    try:
        return Gdk.Texture.new_from_filename(tmp_name)
    finally:
        os.unlink(tmp_name)
