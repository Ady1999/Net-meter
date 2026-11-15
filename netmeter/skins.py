"""Skins for the floating window.

A skin is a JSON file in the skins folder, for example:

{
  "name": "My Skin",
  "layout": "grid2",            // grid2 | row | column
  "bg": "#1e1e1e",
  "text_color": "#e8e8e8",
  "item_colors": {"up": "#ff9f43", "down": "#2ecc71"},
  "font": {"family": "Segoe UI", "size": 10, "bold": false},
  "padding": [8, 4],
  "spacing": 12,
  "bg_image": "my_background.png"   // optional, file next to the JSON
}
"""

import json
import os

from .config import SKINS_DIR, log

BUILTIN = [
    {"name": "Classic Dark", "layout": "grid2", "bg": "#1e1e1e", "text_color": "#e8e8e8",
     "item_colors": {"up": "#ff9f43", "down": "#2ecc71"}},
    {"name": "Classic Light", "layout": "grid2", "bg": "#f4f4f4", "text_color": "#202020",
     "item_colors": {"up": "#d35400", "down": "#16a085"}},
    {"name": "Midnight", "layout": "grid2", "bg": "#0b1a33", "text_color": "#cfe3ff",
     "item_colors": {"up": "#ffcc66", "down": "#66ffcc"}},
    {"name": "Terminal", "layout": "grid2", "bg": "#000000", "text_color": "#00ff66",
     "font": {"family": "Consolas", "size": 10}},
    {"name": "Rose", "layout": "grid2", "bg": "#2b1b24", "text_color": "#ffe4ef",
     "item_colors": {"up": "#ff7aa8", "down": "#9be7ff"}},
    {"name": "Slim Row", "layout": "row", "bg": "#262626", "text_color": "#f0f0f0",
     "item_colors": {"up": "#ffb86c", "down": "#50fa7b"}, "padding": [8, 3], "spacing": 14},
    {"name": "Tower", "layout": "column", "bg": "#1b2430", "text_color": "#e6edf3",
     "item_colors": {"up": "#f78166", "down": "#56d364"}, "padding": [10, 6]},
    {"name": "Paper", "layout": "column", "bg": "#fffdf5", "text_color": "#333333",
     "item_colors": {"up": "#b5651d", "down": "#2e7d32"}, "padding": [10, 6]},
]


def load_skins():
    skins = [dict(s, builtin=True) for s in BUILTIN]
    try:
        for fn in sorted(os.listdir(SKINS_DIR)):
            if not fn.lower().endswith(".json"):
                continue
            path = os.path.join(SKINS_DIR, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    s = json.load(f)
                s.setdefault("name", os.path.splitext(fn)[0])
                if s.get("bg_image"):
                    s["bg_image"] = os.path.join(SKINS_DIR, s["bg_image"])
                skins.append(s)
            except (OSError, ValueError) as e:
                log(f"skin {fn} could not be loaded: {e}")
    except OSError:
        pass
    return skins


def get_skin(name):
    for s in load_skins():
        if s["name"] == name:
            return s
    return dict(BUILTIN[0], builtin=True)
