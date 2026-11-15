"""Settings, data paths and the list of things NetMeter can display."""

import copy
import json
import os
import sys
from datetime import datetime

APP_NAME = "NetMeter"
VERSION = "2.1.0"
IS_WIN = sys.platform == "win32"


# --------------------------------------------------------------------------- paths
def _program_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


PROGRAM_DIR = _program_dir()

# Portable mode: put an empty file called "portable.txt" next to the program and
# settings/history are kept in the program folder instead of %APPDATA%.
if os.path.exists(os.path.join(PROGRAM_DIR, "portable.txt")):
    DATA_DIR = PROGRAM_DIR
elif IS_WIN:
    DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
else:
    DATA_DIR = os.path.join(os.path.expanduser("~"), ".config", "netmeter")

os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(DATA_DIR, "settings.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
LOG_FILE = os.path.join(DATA_DIR, "netmeter.log")
SKINS_DIR = os.path.join(DATA_DIR, "skins")
PLUGINS_DIR = os.path.join(DATA_DIR, "plugins")
for _d in (SKINS_DIR, PLUGINS_DIR):
    os.makedirs(_d, exist_ok=True)


def log(msg):
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1_000_000:
            os.replace(LOG_FILE, LOG_FILE + ".old")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
    except OSError:
        pass


# --------------------------------------------------------------------------- display items
# id -> (name shown in settings, default label, kind)
# kind decides formatting: speed / percent / temp / freq / size / memory / text
ITEMS = {
    "up":         ("Upload speed",        "↑ ",    "speed"),
    "down":       ("Download speed",      "↓ ",    "speed"),
    "total":      ("Total speed",         "⇅ ",    "speed"),
    "cpu":        ("CPU usage",           "CPU ",  "percent"),
    "ram":        ("Memory usage",        "RAM ",  "memory"),
    "gpu":        ("GPU usage",           "GPU ",  "percent"),
    "disk":       ("Disk usage",          "Disk ", "percent"),
    "cpu_freq":   ("CPU frequency",       "Freq ", "freq"),
    "cpu_temp":   ("CPU temperature",     "CPU ",  "temp"),
    "gpu_temp":   ("GPU temperature",     "GPU ",  "temp"),
    "disk_temp":  ("Disk temperature",    "HDD ",  "temp"),
    "board_temp": ("Mainboard temperature", "MB ", "temp"),
    "today":      ("Today's traffic",     "Today ", "size"),
}
TEMP_ITEMS = ("cpu_temp", "gpu_temp", "disk_temp", "board_temp")
GRAPHABLE = ("up", "down", "total", "cpu", "ram", "gpu", "disk")

DOUBLE_CLICK_ACTIONS = {
    "details": "Connection details",
    "history": "Traffic history",
    "options": "Options",
    "taskmgr": "Task Manager",
    "skin": "Change skin",
    "toggle_more": "Show more / less info",
    "app": "Open a program…",
    "none": "Do nothing",
}


def _fmt(**over):
    d = {
        "bits": False,            # show b/s instead of B/s
        "unit_mode": "auto",      # auto | KB | MB
        "short": False,           # one fewer decimal, "K/s" instead of "KB/s"
        "space": True,            # space between number and unit
        "hide_unit": False,       # only when unit_mode isn't auto
        "per_second": True,       # show "/s"
        "hide_percent": False,
        "memory_mode": "percent", # percent | used | available
        "speed_width": 5,         # characters reserved for the number in speeds
        "swap_updown": False,
    }
    d.update(over)
    return d


DEFAULTS = {
    "version": 3,
    # ---------------- general
    "startup_delay_s": 8,
    "tray_icon": True,
    "interval_ms": 1000,
    "adapter_mode": "auto",       # auto | selected
    "adapters": [],               # used when adapter_mode == selected
    "show_all_adapters": False,   # list virtual adapters in menus too
    "cpu_source": "auto",         # auto | psutil | pdh   (pdh = same as Task Manager)
    "month_start_day": 1,
    "hw_temps": False,            # temperatures need LibreHardwareMonitor
    "temp_source": "web",         # web | dll
    "lhm_url": "http://localhost:8085/data.json",
    "cpu_temp_mode": "auto",      # auto | average | max
    "disk_name": "auto",
    "alerts": {
        "today_traffic": {"on": False, "value": 5000},    # MB
        "month_traffic": {"on": False, "value": 100},     # GB
        "memory":        {"on": False, "value": 90},      # %
        "cpu":           {"on": False, "value": 95},      # %
        "cpu_temp":      {"on": False, "value": 85},      # °C
        "gpu_temp":      {"on": False, "value": 85},
        "disk_temp":     {"on": False, "value": 55},
        "board_temp":    {"on": False, "value": 70},
    },
    "alert_state": {},            # remembers which alerts already fired
    "tm_import_done": False,      # TrafficMonitor history imported on first run

    # ---------------- floating (main) window
    "main": {
        "show": False,
        "x": None, "y": None,
        "items": ["up", "down", "cpu", "ram"],
        "hidden_items": ["total", "gpu", "disk", "cpu_freq", "cpu_temp", "gpu_temp",
                         "disk_temp", "board_temp", "today"],
        "more_info": True,        # show the 3rd+ items (TrafficMonitor's "Show more info")
        "skin": "Classic Dark",
        "skin_font": True,        # let the skin decide font & colours
        "font": {"family": "Segoe UI" if IS_WIN else "DejaVu Sans", "size": 10,
                 "bold": False, "italic": False, "underline": False, "overstrike": False},
        "text_color": "#e8e8e8",
        "item_colors": {},        # id -> colour (overrides text_color)
        "labels": {},             # id -> custom label
        "opacity": 0.92,
        "topmost": True,
        "locked": False,
        "click_through": False,
        "allow_offscreen": False,
        "hide_fullscreen": True,
        "tooltip": True,
        "double_click": "details",
        "double_click_app": "",
        "fmt": _fmt(),
    },

    # ---------------- taskbar window
    "taskbar": {
        "show": True,
        "items": ["up", "down", "cpu", "ram"],
        "hidden_items": ["total", "gpu", "disk", "cpu_freq", "cpu_temp", "gpu_temp",
                         "disk_temp", "board_temp", "today"],
        "embed": "embed",         # embed (child of taskbar) | overlay (floating on top)
        "position": "auto",       # auto | right (next to the clock) | left | dock | free
                                  # auto = after a custom dock (e.g. Hitodama) if there is
                                  # one, otherwise next to the clock
        "free_x": None,           # "free": where you dragged it (px from taskbar's left)
        "dock_gap": 8,            # space between a custom dock and our stats
        "bg_style": "auto",       # auto (pill when next to a dock) | clear | solid | pill
        "pill_color": "auto",     # auto = same colour as the dock
        "pill_radius": 12,
        "monitor": 0,             # 0 = main taskbar, 1.. = taskbars on other monitors
        "offset": 0,              # extra pixels away from the clock / left edge
        "two_rows": True,         # False = everything on one line
        "spacing": 8,
        "right_align": False,
        "scheme": "auto",         # auto (follow Windows light/dark) | dark | light | custom
        "auto_bg": True,          # sample the taskbar colour for the background
        "transparent": True,
        "bg": "#202020",
        "label_color": "#ffffff",
        "value_color": "#ffffff",
        "item_colors": {},        # id -> {"label": c, "value": c}
        "labels": {"up": "↑ ", "down": "↓ ", "cpu": "CPU ", "ram": "RAM "},
        "font": {"family": "Segoe UI" if IS_WIN else "DejaVu Sans", "size": 9,
                 "bold": False, "italic": False, "underline": False, "overstrike": False},
        "graph": "none",          # none | bar | plot
        "graph_items": ["cpu", "ram"],
        "graph_color": "#3a8fd8",
        "graph_outline": False,
        "graph_net_max_kb": 0,    # 0 = automatic scale for speed graphs
        "tooltip": True,
        "double_click": "details",
        "double_click_app": "",
        "fmt": _fmt(),
    },
}

SCHEMES = {
    "dark":  {"bg": "#202020", "label_color": "#ffffff", "value_color": "#ffffff"},
    "light": {"bg": "#f3f3f3", "label_color": "#000000", "value_color": "#000000"},
}


def _merge(base, saved):
    for k, v in saved.items():
        if k not in base:
            continue
        if isinstance(base[k], dict) and isinstance(v, dict) and k not in (
                "item_colors", "labels", "alert_state"):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config():
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            _merge(cfg, json.load(f))
    except (OSError, ValueError):
        pass
    # version 2 -> 3: "next to the clock" becomes "automatic", which also handles
    # custom taskbars (Hitodama etc.) that draw their own dock
    if cfg.get("version", 2) < 3:
        if cfg["taskbar"].get("position") == "right":
            cfg["taskbar"]["position"] = "auto"
        cfg["version"] = 3
    # make sure every known item appears exactly once in items/hidden_items
    for win in ("main", "taskbar"):
        w = cfg[win]
        shown = [i for i in w["items"] if i in ITEMS or i.startswith("p:")]
        hidden = [i for i in w["hidden_items"] if (i in ITEMS or i.startswith("p:"))
                  and i not in shown]
        for i in ITEMS:
            if i not in shown and i not in hidden:
                hidden.append(i)
        w["items"], w["hidden_items"] = shown, hidden
    return cfg


def save_json(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        log(f"save failed {path}: {e}")


def save_config(cfg):
    save_json(CONFIG_FILE, cfg)
