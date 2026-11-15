"""Plugins: extra items written in Python.

Drop a .py file in the plugins folder (Options > Plugins > Open folder). It must define:

    NAME = "My plugin"
    ITEMS = [{"id": "clock", "name": "Clock", "label": "", "sample": "88:88:88"}]

    def get_value(item_id):          # called every refresh, return the text to show
        ...

and may define:

    def update():                    # called once per refresh before get_value
    def get_tooltip():               # extra line(s) for the mouse tooltip
    def on_double_click(item_id):    # called when the item is double-clicked

Plugins run inside NetMeter with your user's rights, so only add files you trust.
"""

import importlib.util
import os

from .config import PLUGINS_DIR, log


class Plugin:
    def __init__(self, path):
        self.path = path
        self.file = os.path.basename(path)
        self.error = ""
        self.module = None
        self.items = []
        self.name = self.file
        try:
            spec = importlib.util.spec_from_file_location(
                "netmeter_plugin_" + os.path.splitext(self.file)[0], path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self.module = mod
            self.name = getattr(mod, "NAME", self.file)
            for it in getattr(mod, "ITEMS", []):
                iid = f"p:{os.path.splitext(self.file)[0]}.{it['id']}"
                self.items.append({"id": iid, "raw": it["id"],
                                   "name": it.get("name", it["id"]),
                                   "label": it.get("label", ""),
                                   "sample": it.get("sample", "")})
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            log(f"plugin {self.file} failed to load: {self.error}")


class PluginManager:
    def __init__(self):
        self.plugins = []
        try:
            files = sorted(f for f in os.listdir(PLUGINS_DIR) if f.endswith(".py"))
        except OSError:
            files = []
        for f in files:
            self.plugins.append(Plugin(os.path.join(PLUGINS_DIR, f)))
        self.values = {}

    def items(self):
        """{item_id: (display name, default label, sample)}"""
        out = {}
        for p in self.plugins:
            for it in p.items:
                out[it["id"]] = (f"{it['name']} ({p.name})", it["label"], it["sample"])
        return out

    def update(self):
        for p in self.plugins:
            if not p.module:
                continue
            try:
                if hasattr(p.module, "update"):
                    p.module.update()
                for it in p.items:
                    self.values[it["id"]] = str(p.module.get_value(it["raw"]))
            except Exception as e:
                p.error = f"{type(e).__name__}: {e}"
        return self.values

    def tooltips(self):
        lines = []
        for p in self.plugins:
            if p.module and hasattr(p.module, "get_tooltip"):
                try:
                    t = p.module.get_tooltip()
                    if t:
                        lines.append(str(t))
                except Exception:
                    pass
        return lines

    def double_click(self, item_id):
        for p in self.plugins:
            for it in p.items:
                if it["id"] == item_id and p.module and hasattr(p.module, "on_double_click"):
                    try:
                        p.module.on_double_click(it["raw"])
                        return True
                    except Exception as e:
                        log(f"plugin double-click failed: {e}")
        return False
