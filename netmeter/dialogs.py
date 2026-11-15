"""Options, traffic history, connection details, skin picker and about dialogs."""

import calendar
import copy
import csv
import socket
import threading
import tkinter as tk
import urllib.request
from datetime import date, datetime
from tkinter import colorchooser, filedialog, messagebox, ttk
import tkinter.font as tkfont

import psutil

from . import win
from .config import (APP_NAME, DATA_DIR, DEFAULTS, DOUBLE_CLICK_ACTIONS, GRAPHABLE, IS_WIN,
                     ITEMS, PLUGINS_DIR, SKINS_DIR, VERSION)
from .render import ItemPainter, fmt_size, format_item, make_font, sample_text
from .skins import load_skins
from .sources import all_adapters, auto_adapters, default_gateway

UI_FONT = ("Segoe UI" if IS_WIN else "DejaVu Sans", 9)


def _dialog(app, title, size=None):
    w = tk.Toplevel(app.root)
    w.title(f"{APP_NAME} – {title}")
    if size:
        w.geometry(size)
    w.attributes("-topmost", True)
    w.after(300, lambda: w.attributes("-topmost", False))   # appear in front, then behave
    w.lift()
    w.focus_force()
    return w


# =========================================================================== small widgets
class ScrollFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.inner.bind_all(ev, self._wheel, add="+")

    def _wheel(self, e):
        try:
            w = self.winfo_containing(e.x_root, e.y_root)
        except (tk.TclError, KeyError):
            return
        while w is not None and w is not self:
            w = getattr(w, "master", None)
        if w is None:
            return
        if getattr(e, "num", None) == 4:
            self.canvas.yview_scroll(-2, "units")
        elif getattr(e, "num", None) == 5:
            self.canvas.yview_scroll(2, "units")
        else:
            self.canvas.yview_scroll(int(-e.delta / 120) * 2, "units")


class ColorButton(tk.Button):
    """A swatch button that edits store[key]."""

    def __init__(self, parent, store, key, title="Colour", default="#ffffff"):
        self.store, self.key, self.title = store, key, title
        val = store.get(key) or default
        super().__init__(parent, width=3, relief="groove", bg=val, activebackground=val,
                         command=self.pick)

    def pick(self):
        _, hx = colorchooser.askcolor(self.store.get(self.key), title=self.title,
                                      parent=self.winfo_toplevel())
        if hx:
            self.store[self.key] = hx
            self.config(bg=hx, activebackground=hx)


class FontPicker(ttk.Frame):
    def __init__(self, parent, spec):
        super().__init__(parent)
        self.spec = spec
        fams = sorted(set(f for f in tkfont.families() if not f.startswith("@")))
        self.v_family = tk.StringVar(value=spec.get("family", "Segoe UI"))
        self.v_size = tk.IntVar(value=int(spec.get("size", 9)))
        cb = ttk.Combobox(self, textvariable=self.v_family, values=fams, width=22)
        cb.pack(side="left")
        ttk.Spinbox(self, from_=6, to=48, textvariable=self.v_size, width=4).pack(
            side="left", padx=4)
        self.flags = {}
        for k, lbl in (("bold", "B"), ("italic", "I"), ("underline", "U"), ("overstrike", "S")):
            v = tk.BooleanVar(value=bool(spec.get(k)))
            self.flags[k] = v
            ttk.Checkbutton(self, text=lbl, variable=v).pack(side="left")

    def save(self):
        self.spec["family"] = self.v_family.get()
        try:
            self.spec["size"] = int(self.v_size.get())
        except (tk.TclError, ValueError):
            pass
        for k, v in self.flags.items():
            self.spec[k] = bool(v.get())


class ItemsTable(ttk.Frame):
    """Which items to show, their order, label text and colours."""

    def __init__(self, parent, app, wcfg, taskbar):
        super().__init__(parent)
        self.app, self.wcfg, self.taskbar = app, wcfg, taskbar
        pitems = app.plugins.items()
        self.names = {k: v[0] for k, v in ITEMS.items()}
        self.names.update({k: v[0] for k, v in pitems.items()})
        self.default_labels = {k: v[1] for k, v in ITEMS.items()}
        self.default_labels.update({k: v[1] for k, v in pitems.items()})
        order = [i for i in wcfg["items"] + wcfg["hidden_items"] if i in self.names]
        order += [i for i in self.names if i not in order]
        self.shown = set(wcfg["items"])
        self.labels = dict(wcfg.get("labels", {}))
        self.colors = copy.deepcopy(wcfg.get("item_colors", {}))
        cols = ("show", "name", "label") + (("lcol", "vcol") if taskbar else ("col",))
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=9,
                                 selectmode="browse")
        heads = {"show": "Show", "name": "Item", "label": "Label text",
                 "lcol": "Label colour", "vcol": "Value colour", "col": "Colour"}
        widths = {"show": 48, "name": 170, "label": 90, "lcol": 90, "vcol": 90, "col": 90}
        for c in cols:
            self.tree.heading(c, text=heads[c])
            self.tree.column(c, width=widths[c], anchor="center" if c != "name" else "w")
        for i in order:
            self.tree.insert("", "end", iid=i, values=self._row(i))
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Button-1>", self._click)
        btns = ttk.Frame(self)
        btns.pack(side="left", fill="y", padx=(6, 0))
        ttk.Button(btns, text="▲ Up", command=lambda: self._move(-1)).pack(fill="x")
        ttk.Button(btns, text="▼ Down", command=lambda: self._move(1)).pack(fill="x", pady=2)
        ttk.Button(btns, text="Default labels", command=self._reset_labels).pack(
            fill="x", pady=(10, 2))
        ttk.Button(btns, text="Default colours", command=self._reset_colors).pack(fill="x")
        ttk.Label(btns, text="Click a cell\nto change it.", foreground="#777").pack(pady=8)

    def _label(self, i):
        return self.labels.get(i, self.default_labels.get(i, ""))

    def _row(self, i):
        show = "✔" if i in self.shown else ""
        lbl = repr(self._label(i))[1:-1]
        if self.taskbar:
            cc = self.colors.get(i, {})
            return (show, self.names[i], lbl, cc.get("label", "default"),
                    cc.get("value", "default"))
        return (show, self.names[i], lbl, self.colors.get(i, "default"))

    def _click(self, e):
        row = self.tree.identify_row(e.y)
        col = self.tree.identify_column(e.x)
        if not row or self.tree.identify_region(e.x, e.y) != "cell":
            return
        self.tree.selection_set(row)
        name = self.tree["columns"][int(col[1:]) - 1]
        if name == "show":
            if row in self.shown:
                self.shown.discard(row)
            else:
                self.shown.add(row)
        elif name == "label":
            self._edit_label(row)
            return "break"
        elif name in ("col", "lcol", "vcol"):
            if self.taskbar:
                key = "label" if name == "lcol" else "value"
                cur = self.colors.get(row, {}).get(key)
                _, hx = colorchooser.askcolor(cur, parent=self.winfo_toplevel())
                if hx:
                    self.colors.setdefault(row, {})[key] = hx
            else:
                _, hx = colorchooser.askcolor(self.colors.get(row), parent=self.winfo_toplevel())
                if hx:
                    self.colors[row] = hx
        self.tree.item(row, values=self._row(row))
        return "break"

    def _edit_label(self, row):
        x, y, w, h = self.tree.bbox(row, "label")
        ent = ttk.Entry(self.tree)
        ent.insert(0, self._label(row))
        ent.place(x=x, y=y, width=max(w, 120), height=h)
        ent.focus_set()

        def done(_e=None, save=True):
            if save:
                self.labels[row] = ent.get()
                self.tree.item(row, values=self._row(row))
            ent.destroy()
        ent.bind("<Return>", done)
        ent.bind("<FocusOut>", done)
        ent.bind("<Escape>", lambda e: done(save=False))

    def _move(self, d):
        sel = self.tree.selection()
        if sel:
            i = self.tree.index(sel[0])
            self.tree.move(sel[0], "", max(0, i + d))

    def _reset_labels(self):
        self.labels = {}
        for i in self.tree.get_children():
            self.tree.item(i, values=self._row(i))

    def _reset_colors(self):
        self.colors = {}
        for i in self.tree.get_children():
            self.tree.item(i, values=self._row(i))

    def save(self):
        order = list(self.tree.get_children())
        self.wcfg["items"] = [i for i in order if i in self.shown]
        self.wcfg["hidden_items"] = [i for i in order if i not in self.shown]
        self.wcfg["labels"] = {k: v for k, v in self.labels.items()
                               if v != self.default_labels.get(k)}
        self.wcfg["item_colors"] = self.colors


class FormatFrame(ttk.LabelFrame):
    def __init__(self, parent, fmt, main):
        super().__init__(parent, text="Units and number format", padding=6)
        self.fmt = fmt
        self.v = {}
        r = 0
        ttk.Label(self, text="Speed in").grid(row=r, column=0, sticky="w")
        self.v["bits"] = tk.StringVar(value="bits" if fmt.get("bits") else "bytes")
        ttk.Radiobutton(self, text="bytes (KB/s)", value="bytes",
                        variable=self.v["bits"]).grid(row=r, column=1, sticky="w")
        ttk.Radiobutton(self, text="bits (Kb/s)", value="bits",
                        variable=self.v["bits"]).grid(row=r, column=2, sticky="w")
        r += 1
        ttk.Label(self, text="Unit").grid(row=r, column=0, sticky="w")
        self.v["unit_mode"] = tk.StringVar(value=fmt.get("unit_mode", "auto"))
        ttk.Combobox(self, textvariable=self.v["unit_mode"], values=("auto", "KB", "MB"),
                     state="readonly", width=8).grid(row=r, column=1, sticky="w")
        ttk.Label(self, text="Memory shows").grid(row=r, column=2, sticky="e")
        self.v["memory_mode"] = tk.StringVar(value=fmt.get("memory_mode", "percent"))
        ttk.Combobox(self, textvariable=self.v["memory_mode"],
                     values=("percent", "used", "available"), state="readonly",
                     width=10).grid(row=r, column=3, sticky="w")
        r += 1
        ttk.Label(self, text="Speed digits").grid(row=r, column=0, sticky="w")
        self.v["speed_width"] = tk.IntVar(value=int(fmt.get("speed_width", 5)))
        ttk.Spinbox(self, from_=3, to=8, textvariable=self.v["speed_width"],
                    width=5).grid(row=r, column=1, sticky="w")
        r += 1
        checks = [("short", "Short mode (fewer decimals, K/s instead of KB/s)"),
                  ("space", "Space between number and unit"),
                  ("per_second", "Show “/s”"),
                  ("hide_unit", "Hide unit (when unit isn't auto)"),
                  ("hide_percent", "Hide % sign"),
                  ("swap_updown", "Swap upload and download")]
        for i, (k, t) in enumerate(checks):
            self.v[k] = tk.BooleanVar(value=bool(fmt.get(k, k in ("space", "per_second"))))
            ttk.Checkbutton(self, text=t, variable=self.v[k]).grid(
                row=r + i // 2, column=(i % 2) * 2, columnspan=2, sticky="w")

    def save(self):
        for k, v in self.v.items():
            val = v.get()
            if k == "bits":
                val = val == "bits"
            self.fmt[k] = val


def _row(parent, r, text, widget, col=0):
    ttk.Label(parent, text=text).grid(row=r, column=col, sticky="w", pady=2, padx=(0, 6))
    widget.grid(row=r, column=col + 1, sticky="w", pady=2)
    return widget


# =========================================================================== options
class OptionsDialog:
    def __init__(self, app, tab=0):
        self.app = app
        self.c = copy.deepcopy(app.cfg)
        self.w = _dialog(app, "Options", "860x660")
        self.savers = []
        nb = self.nb = ttk.Notebook(self.w)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        for title, build in (("General", self._general), ("Taskbar window", self._taskbar),
                             ("Floating window", self._main), ("Hardware", self._hardware),
                             ("Notifications", self._alerts), ("Plugins", self._plugins)):
            sf = ScrollFrame(nb)
            nb.add(sf, text=title)
            build(sf.inner)
        nb.select(tab)
        b = ttk.Frame(self.w)
        b.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(b, text="OK", command=self.ok).pack(side="right")
        ttk.Button(b, text="Cancel", command=self.w.destroy).pack(side="right", padx=4)
        ttk.Button(b, text="Apply", command=self.apply).pack(side="right")

    def _var(self, store, key, kind=tk.BooleanVar, conv=None):
        v = kind(value=store.get(key))

        def save():
            try:
                val = v.get()
            except (tk.TclError, ValueError):
                return
            store[key] = conv(val) if conv else val
        self.savers.append(save)
        return v

    # ----------------------------------------------------------------- general
    def _general(self, p):
        c = self.c
        f = ttk.LabelFrame(p, text="Startup", padding=6)
        f.pack(fill="x", pady=4)
        self.v_auto = tk.BooleanVar(value=win.autostart_enabled())
        ttk.Checkbutton(f, text="Start NetMeter when I sign in to Windows",
                        variable=self.v_auto).grid(row=0, column=0, columnspan=2, sticky="w")
        _row(f, 1, "Wait before showing (seconds)",
             ttk.Spinbox(f, from_=0, to=120, width=5,
                         textvariable=self._var(c, "startup_delay_s", tk.IntVar)))
        ttk.Label(f, text="A short wait lets Windows finish loading the taskbar first.",
                  foreground="#777").grid(row=2, column=0, columnspan=2, sticky="w")

        f = ttk.LabelFrame(p, text="General", padding=6)
        f.pack(fill="x", pady=4)
        ttk.Checkbutton(f, text="Show icon in the notification area (next to the clock)",
                        variable=self._var(c, "tray_icon")).grid(row=0, column=0,
                                                                 columnspan=2, sticky="w")
        _row(f, 1, "Refresh every (ms)",
             ttk.Spinbox(f, from_=250, to=5000, increment=250, width=6,
                         textvariable=self._var(c, "interval_ms", tk.IntVar)))
        v = self._var(c, "cpu_source", tk.StringVar)
        _row(f, 2, "CPU usage measured by",
             ttk.Combobox(f, textvariable=v, state="readonly", width=34, values=(
                 "auto", "pdh", "psutil")))
        ttk.Label(f, text="auto/pdh = same as Task Manager (Windows), psutil = CPU time",
                  foreground="#777").grid(row=3, column=1, sticky="w")
        _row(f, 4, "Monthly totals start on day",
             ttk.Spinbox(f, from_=1, to=28, width=5,
                         textvariable=self._var(c, "month_start_day", tk.IntVar)))

        f = ttk.LabelFrame(p, text="Network connections to count", padding=6)
        f.pack(fill="x", pady=4)
        self.v_amode = tk.StringVar(value=c.get("adapter_mode", "auto"))
        ttk.Radiobutton(f, text="Automatic (all active Wi-Fi / Ethernet adapters)",
                        value="auto", variable=self.v_amode).pack(anchor="w")
        ttk.Radiobutton(f, text="Only the ones selected below:", value="selected",
                        variable=self.v_amode).pack(anchor="w")
        self.v_allad = self._var(c, "show_all_adapters")
        self.lb = tk.Listbox(f, selectmode="multiple", height=6, exportselection=False)
        self.lb.pack(fill="x", pady=2)
        ttk.Checkbutton(f, text="Also list virtual adapters (VPN, Hyper-V, …)",
                        variable=self.v_allad, command=self._fill_adapters).pack(anchor="w")
        self._fill_adapters()

        f = ttk.LabelFrame(p, text="Data", padding=6)
        f.pack(fill="x", pady=4)
        ttk.Label(f, text=f"Settings and history are kept in:\n{DATA_DIR}").pack(anchor="w")
        bf = ttk.Frame(f)
        bf.pack(anchor="w", pady=4)
        ttk.Button(bf, text="Open folder", command=lambda: win.open_path(DATA_DIR)).pack(
            side="left")
        ttk.Button(bf, text="Reset all settings", command=self._reset).pack(side="left", padx=6)
        ttk.Button(bf, text="Import TrafficMonitor history…",
                   command=lambda: self.app.import_trafficmonitor(parent=self.w)).pack(side="left")

    def _fill_adapters(self):
        sel = set(self.c.get("adapters", []))
        try:
            sel |= {self.lb.get(i) for i in self.lb.curselection()}
        except tk.TclError:
            pass
        self.lb.delete(0, "end")
        active = set(auto_adapters())
        for n in all_adapters(self.v_allad.get()):
            self.lb.insert("end", n)
            if n in sel:
                self.lb.selection_set("end")
            if n in active:
                self.lb.itemconfig("end", fg="#0a7d28")

    def _reset(self):
        if messagebox.askyesno(APP_NAME, "Reset every setting to its default?\n"
                               "(Traffic history is kept.)", parent=self.w):
            self.app.apply_config(copy.deepcopy(DEFAULTS))
            self.w.destroy()

    # ----------------------------------------------------------------- taskbar
    def _taskbar(self, p):
        t = self.c["taskbar"]
        f = ttk.LabelFrame(p, text="Placement", padding=6)
        f.pack(fill="x", pady=4)
        ttk.Checkbutton(f, text="Show the taskbar window", variable=self._var(t, "show")).grid(
            row=0, column=0, columnspan=4, sticky="w")
        v = self._var(t, "position", tk.StringVar)
        _row(f, 1, "Position", ttk.Combobox(f, textvariable=v, state="readonly", width=12,
                                            values=("auto", "dock", "right", "left", "free")))
        ttk.Label(f, text="auto = after a custom taskbar's dock (Hitodama etc.) if there is "
                  "one, else next to the clock\n"
                  "dock = always after the custom dock    right = next to the clock\n"
                  "left = left end    free = where you drag it",
                  justify="left").grid(row=1, column=2, sticky="w")
        v = self._var(t, "embed", tk.StringVar)
        _row(f, 2, "Docking", ttk.Combobox(f, textvariable=v, state="readonly", width=12,
                                           values=("embed", "overlay")))
        ttk.Label(f, text="embed = inside the taskbar (best); overlay = float on top of it",
                  ).grid(row=2, column=2, sticky="w")
        bars = len(win.find_taskbars()) or 1
        mons = ["Main taskbar"] + [f"Taskbar on monitor {i + 1}" for i in range(1, max(bars, 2))]
        self.v_mon = tk.StringVar(value=mons[min(int(t.get("monitor", 0)), len(mons) - 1)])
        self.mons = mons
        _row(f, 3, "Which taskbar", ttk.Combobox(f, textvariable=self.v_mon, values=mons,
                                                 state="readonly", width=22))
        _row(f, 4, "Shift (pixels)", ttk.Spinbox(f, from_=-2000, to=2000, width=6,
                                                 textvariable=self._var(t, "offset", tk.IntVar)))
        ttk.Label(f, text="Moves it further from the clock (or the left edge) "
                  "if it overlaps something.").grid(row=4, column=2, sticky="w")

        f = ttk.LabelFrame(p, text="Layout", padding=6)
        f.pack(fill="x", pady=4)
        ttk.Label(f, text="NetMeter fits itself to the taskbar: on a left/right taskbar items "
                  "go one per line, labels move above values when it's narrow, and the "
                  "font only shrinks if nothing else fits.", wraplength=620, justify="left",
                  foreground="#777").grid(row=7, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(f, text="Two rows (unchecked: everything on one line)",
                        variable=self._var(t, "two_rows")).grid(row=0, column=0,
                                                                columnspan=3, sticky="w")
        ttk.Checkbutton(f, text="Right-align values", variable=self._var(t, "right_align")).grid(
            row=1, column=0, columnspan=3, sticky="w")
        _row(f, 2, "Space between items (px)",
             ttk.Spinbox(f, from_=0, to=60, width=5, textvariable=self._var(t, "spacing",
                                                                           tk.IntVar)))
        ttk.Checkbutton(f, text="Show tooltip on mouse hover",
                        variable=self._var(t, "tooltip")).grid(row=3, column=0, columnspan=3,
                                                               sticky="w")
        self._double_click(f, t, 4)

        f = ttk.LabelFrame(p, text="Colours and font", padding=6)
        f.pack(fill="x", pady=4)
        v = self._var(t, "scheme", tk.StringVar)
        _row(f, 0, "Colour scheme", ttk.Combobox(f, textvariable=v, state="readonly",
                                                 width=12, values=("auto", "dark", "light",
                                                                   "custom")))
        ttk.Label(f, text="auto = follow Windows light/dark mode").grid(row=0, column=2,
                                                                        sticky="w")
        cf = ttk.Frame(f)
        cf.grid(row=1, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Label(cf, text="Custom: background").pack(side="left")
        ColorButton(cf, t, "bg").pack(side="left", padx=4)
        ttk.Label(cf, text="labels").pack(side="left")
        ColorButton(cf, t, "label_color").pack(side="left", padx=4)
        ttk.Label(cf, text="values").pack(side="left")
        ColorButton(cf, t, "value_color").pack(side="left", padx=4)
        bs = self._var(t, "bg_style", tk.StringVar)
        bsf = ttk.Frame(f)
        bsf.grid(row=5, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(bsf, text="Background").pack(side="left")
        ttk.Combobox(bsf, textvariable=bs, state="readonly", width=8,
                     values=("auto", "clear", "solid", "pill")).pack(side="left", padx=4)
        ttk.Label(bsf, text="pill colour").pack(side="left")
        pill = {"c": t.get("pill_color") if t.get("pill_color") not in (None, "auto")
                else "#1e1e1e"}
        ColorButton(bsf, pill, "c").pack(side="left", padx=4)
        pauto = tk.BooleanVar(value=t.get("pill_color", "auto") == "auto")
        ttk.Checkbutton(bsf, text="same as the dock", variable=pauto).pack(side="left")
        ttk.Label(bsf, text="  corners").pack(side="left")
        ttk.Spinbox(bsf, from_=0, to=30, width=4,
                    textvariable=self._var(t, "pill_radius", tk.IntVar)).pack(side="left")
        ttk.Label(bsf, text="  gap after dock").pack(side="left")
        ttk.Spinbox(bsf, from_=0, to=100, width=4,
                    textvariable=self._var(t, "dock_gap", tk.IntVar)).pack(side="left")
        ttk.Label(f, text="auto = rounded panel matching the dock when next to a custom "
                  "dock, otherwise see-through", foreground="#777").grid(
            row=6, column=0, columnspan=3, sticky="w")
        self.savers.append(lambda: t.__setitem__(
            "pill_color", "auto" if pauto.get() else pill["c"]))
        ttk.Checkbutton(f, text="Match the taskbar's colour automatically",
                        variable=self._var(t, "auto_bg")).grid(row=2, column=0, columnspan=3,
                                                               sticky="w")
        ttk.Checkbutton(f, text="See-through background",
                        variable=self._var(t, "transparent")).grid(row=3, column=0,
                                                                   columnspan=3, sticky="w")
        ttk.Label(f, text="Font").grid(row=4, column=0, sticky="w")
        fp = FontPicker(f, t["font"])
        fp.grid(row=4, column=1, columnspan=2, sticky="w")
        self.savers.append(fp.save)

        f = ttk.LabelFrame(p, text="Usage graph behind items", padding=6)
        f.pack(fill="x", pady=4)
        v = self._var(t, "graph", tk.StringVar)
        _row(f, 0, "Graph", ttk.Combobox(f, textvariable=v, state="readonly", width=8,
                                         values=("none", "bar", "plot")))
        ttk.Label(f, text="bar = current level, plot = recent history").grid(row=0, column=2,
                                                                             sticky="w")
        gi = ttk.Frame(f)
        gi.grid(row=1, column=0, columnspan=3, sticky="w")
        self.graph_vars = {}
        for i in GRAPHABLE:
            vv = tk.BooleanVar(value=i in t.get("graph_items", []))
            self.graph_vars[i] = vv
            ttk.Checkbutton(gi, text=ITEMS[i][0], variable=vv).pack(side="left")
        cf = ttk.Frame(f)
        cf.grid(row=2, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(cf, text="Graph colour").pack(side="left")
        ColorButton(cf, t, "graph_color").pack(side="left", padx=4)
        ttk.Checkbutton(cf, text="Dashed outline", variable=self._var(t, "graph_outline")).pack(
            side="left", padx=8)
        _row(f, 3, "Speed graph full scale (KB/s, 0 = automatic)",
             ttk.Spinbox(f, from_=0, to=10_000_000, width=9,
                         textvariable=self._var(t, "graph_net_max_kb", tk.IntVar)))

        ff = FormatFrame(p, t["fmt"], False)
        ff.pack(fill="x", pady=4)
        self.savers.append(ff.save)
        f = ttk.LabelFrame(p, text="Items to show", padding=6)
        f.pack(fill="x", pady=4)
        it = ItemsTable(f, self.app, t, True)
        it.pack(fill="x")
        self.savers.append(it.save)

    def _double_click(self, f, wcfg, r):
        names = list(DOUBLE_CLICK_ACTIONS.values())
        keys = list(DOUBLE_CLICK_ACTIONS.keys())
        v = tk.StringVar(value=DOUBLE_CLICK_ACTIONS.get(wcfg.get("double_click", "details")))
        _row(f, r, "Double-click does", ttk.Combobox(f, textvariable=v, values=names,
                                                     state="readonly", width=22))
        pv = tk.StringVar(value=wcfg.get("double_click_app", ""))
        pf = ttk.Frame(f)
        pf.grid(row=r + 1, column=1, columnspan=2, sticky="w")
        ttk.Entry(pf, textvariable=pv, width=40).pack(side="left")

        def browse():
            path = filedialog.askopenfilename(parent=self.w, title="Program to open")
            if path:
                pv.set(path)
        ttk.Button(pf, text="Browse…", command=browse).pack(side="left", padx=4)

        def save():
            wcfg["double_click"] = keys[names.index(v.get())] if v.get() in names else "details"
            wcfg["double_click_app"] = pv.get()
        self.savers.append(save)

    # ----------------------------------------------------------------- floating window
    def _main(self, p):
        m = self.c["main"]
        f = ttk.LabelFrame(p, text="Window", padding=6)
        f.pack(fill="x", pady=4)
        checks = [("show", "Show the floating window"), ("topmost", "Always on top"),
                  ("locked", "Lock position"),
                  ("click_through", "Clicks pass through (turn off from the tray icon)"),
                  ("allow_offscreen", "Allow moving partly off screen"),
                  ("hide_fullscreen", "Hide while a full-screen program is running"),
                  ("more_info", "Show more info (all items, not just speeds)"),
                  ("tooltip", "Show tooltip on mouse hover")]
        for i, (k, txt) in enumerate(checks):
            ttk.Checkbutton(f, text=txt, variable=self._var(m, k)).grid(
                row=i // 2, column=(i % 2) * 2, columnspan=2, sticky="w")
        r = len(checks) // 2 + 1
        ttk.Label(f, text="Opacity").grid(row=r, column=0, sticky="w")
        ttk.Scale(f, from_=0.2, to=1.0, variable=self._var(m, "opacity", tk.DoubleVar),
                  length=200).grid(row=r, column=1, columnspan=2, sticky="w")
        self._double_click(f, m, r + 1)

        f = ttk.LabelFrame(p, text="Look", padding=6)
        f.pack(fill="x", pady=4)
        names = [s["name"] for s in load_skins()]
        v = self._var(m, "skin", tk.StringVar)
        _row(f, 0, "Skin", ttk.Combobox(f, textvariable=v, values=names, state="readonly",
                                        width=22))
        ttk.Button(f, text="Preview skins…",
                   command=lambda: SkinDialog(self.app, on_pick=v.set)).grid(row=0, column=2,
                                                                            padx=6)
        ttk.Checkbutton(f, text="Use the skin's font and colours",
                        variable=self._var(m, "skin_font")).grid(row=1, column=0,
                                                                 columnspan=3, sticky="w")
        ttk.Label(f, text="Font").grid(row=2, column=0, sticky="w")
        fp = FontPicker(f, m["font"])
        fp.grid(row=2, column=1, columnspan=2, sticky="w")
        self.savers.append(fp.save)
        cf = ttk.Frame(f)
        cf.grid(row=3, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(cf, text="Text colour (when not using the skin's)").pack(side="left")
        ColorButton(cf, m, "text_color").pack(side="left", padx=4)

        ff = FormatFrame(p, m["fmt"], True)
        ff.pack(fill="x", pady=4)
        self.savers.append(ff.save)
        f = ttk.LabelFrame(p, text="Items to show", padding=6)
        f.pack(fill="x", pady=4)
        it = ItemsTable(f, self.app, m, False)
        it.pack(fill="x")
        self.savers.append(it.save)

    # ----------------------------------------------------------------- hardware
    def _hardware(self, p):
        c = self.c
        f = ttk.LabelFrame(p, text="Usage", padding=6)
        f.pack(fill="x", pady=4)
        ttk.Label(f, text="CPU, memory, GPU and disk usage and CPU frequency work out of the "
                  "box.\nAdd them under “Items to show” on the taskbar or floating window tab.",
                  justify="left").pack(anchor="w")
        f = ttk.LabelFrame(p, text="Temperatures", padding=6)
        f.pack(fill="x", pady=4)
        ttk.Checkbutton(f, text="Read temperatures (CPU, GPU, disk, mainboard)",
                        variable=self._var(c, "hw_temps")).grid(row=0, column=0,
                                                                columnspan=3, sticky="w")
        msg = ("Windows has no built-in way to read temperatures, so NetMeter gets them from\n"
               "the free LibreHardwareMonitor program:\n"
               "  1. Download LibreHardwareMonitor and run it (it needs admin rights).\n"
               "  2. In it, tick Options › Remote Web Server › Run, and Options › Run on "
               "Windows Startup.\n"
               "  3. Leave the address below as it is (unless you changed the port).")
        ttk.Label(f, text=msg, justify="left").grid(row=1, column=0, columnspan=3, sticky="w",
                                                    pady=4)
        v = self._var(c, "temp_source", tk.StringVar)
        _row(f, 2, "Source", ttk.Combobox(f, textvariable=v, state="readonly", width=8,
                                          values=("web", "dll")))
        ttk.Label(f, text="dll = LibreHardwareMonitorLib.dll in the NetMeter folder "
                  "(needs pythonnet + admin)").grid(row=2, column=2, sticky="w")
        _row(f, 3, "Web server address",
             ttk.Entry(f, width=40, textvariable=self._var(c, "lhm_url", tk.StringVar)))
        v = self._var(c, "cpu_temp_mode", tk.StringVar)
        _row(f, 4, "CPU temperature", ttk.Combobox(f, textvariable=v, state="readonly",
                                                   width=10,
                                                   values=("auto", "average", "max")))
        sensors, err = self.app.monitor.temps.snapshot()
        disks = sorted({s[1] for s in sensors if s[0] == "disk"})
        v = self._var(c, "disk_name", tk.StringVar)
        _row(f, 5, "Disk", ttk.Combobox(f, textvariable=v, values=["auto"] + disks, width=30))
        out = tk.Text(f, height=8, width=80, font=UI_FONT)
        out.grid(row=6, column=0, columnspan=3, sticky="we", pady=4)

        def show():
            s, e = self.app.monitor.temps.snapshot()
            out.delete("1.0", "end")
            if e:
                out.insert("end", f"Couldn't read sensors: {e}\n")
            elif not s:
                out.insert("end", "No sensors yet. Tick the box above and press Apply, "
                           "then wait a few seconds.\n")
            for cat, hw, name, val in s:
                out.insert("end", f"{cat:6} {hw} › {name}: {val:.1f} °C\n")
        ttk.Button(f, text="Show sensors found", command=show).grid(row=7, column=0,
                                                                     sticky="w")
        show()

    # ----------------------------------------------------------------- alerts
    def _alerts(self, p):
        a = self.c["alerts"]
        f = ttk.LabelFrame(p, text="Tell me when…", padding=6)
        f.pack(fill="x", pady=4)
        rows = [("today_traffic", "Today's traffic is over", "MB"),
                ("month_traffic", "This month's traffic is over", "GB"),
                ("memory", "Memory usage is over", "%"),
                ("cpu", "CPU usage is over", "%"),
                ("cpu_temp", "CPU temperature is over", "°C"),
                ("gpu_temp", "GPU temperature is over", "°C"),
                ("disk_temp", "Disk temperature is over", "°C"),
                ("board_temp", "Mainboard temperature is over", "°C")]
        for r, (k, text, unit) in enumerate(rows):
            ttk.Checkbutton(f, text=text, variable=self._var(a[k], "on")).grid(
                row=r, column=0, sticky="w", pady=2)
            ttk.Spinbox(f, from_=1, to=10_000_000, width=8,
                        textvariable=self._var(a[k], "value", tk.IntVar)).grid(
                row=r, column=1, sticky="w")
            ttk.Label(f, text=unit).grid(row=r, column=2, sticky="w")
        ttk.Label(p, text="Each alert shows once, then again only after the value has "
                  "dropped back below the limit\n(traffic alerts: once per day / month). "
                  "Temperature alerts need temperatures turned on (Hardware tab).",
                  justify="left", foreground="#777").pack(anchor="w", pady=4)

    # ----------------------------------------------------------------- plugins
    def _plugins(self, p):
        ttk.Label(p, text="Plugins are small Python files that add items to show. Put them "
                  "in the plugins folder\nand restart NetMeter. An example is included in "
                  "the “plugin-examples” folder.", justify="left").pack(anchor="w", pady=4)
        tree = ttk.Treeview(p, columns=("file", "items", "status"), show="tree headings",
                            height=8)
        tree.heading("#0", text="Plugin")
        tree.heading("file", text="File")
        tree.heading("items", text="Items")
        tree.heading("status", text="Status")
        for pl in self.app.plugins.plugins:
            tree.insert("", "end", text=pl.name, values=(
                pl.file, ", ".join(i["name"] for i in pl.items),
                pl.error or "OK"))
        tree.pack(fill="x", pady=4)
        ttk.Button(p, text="Open plugins folder",
                   command=lambda: win.open_path(PLUGINS_DIR)).pack(anchor="w")

    # ----------------------------------------------------------------- apply
    def apply(self):
        for s in self.savers:
            s()
        c = self.c
        c["adapter_mode"] = self.v_amode.get()
        c["adapters"] = [self.lb.get(i) for i in self.lb.curselection()]
        if c["adapter_mode"] == "selected" and not c["adapters"]:
            c["adapter_mode"] = "auto"
        c["taskbar"]["monitor"] = self.mons.index(self.v_mon.get()) \
            if self.v_mon.get() in self.mons else 0
        c["taskbar"]["graph_items"] = [k for k, v in self.graph_vars.items() if v.get()]
        try:
            if self.v_auto.get() != win.autostart_enabled():
                win.set_autostart(self.v_auto.get())
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Couldn't change the startup setting:\n{e}",
                                 parent=self.w)
        self.app.apply_config(copy.deepcopy(c))

    def ok(self):
        self.apply()
        self.w.destroy()


# =========================================================================== history
class HistoryDialog:
    def __init__(self, app):
        self.app = app
        h = self.h = app.monitor.history
        h.save()
        w = self.w = _dialog(app, "Traffic history", "640x520")
        t = h.today()
        ms = h.period_start(app.cfg.get("month_start_day", 1))
        m = h.total_since(ms)
        y = h.total_since(date.today().replace(month=1, day=1))
        allt = h.total_since(date(1970, 1, 1))
        txt = (f"Today:       ↑ {fmt_size(t['up'])}   ↓ {fmt_size(t['down'])}   "
               f"= {fmt_size(t['up'] + t['down'])}\n"
               f"This month:  ↑ {fmt_size(m['up'])}   ↓ {fmt_size(m['down'])}   "
               f"= {fmt_size(m['up'] + m['down'])}   (since {ms:%d %b})\n"
               f"This year:   ↑ {fmt_size(y['up'])}   ↓ {fmt_size(y['down'])}   "
               f"= {fmt_size(y['up'] + y['down'])}\n"
               f"Everything:  ↑ {fmt_size(allt['up'])}   ↓ {fmt_size(allt['down'])}   "
               f"= {fmt_size(allt['up'] + allt['down'])}")
        ttk.Label(w, text=txt, padding=8, justify="left",
                  font=("Consolas" if IS_WIN else "DejaVu Sans Mono", 9)).pack(anchor="w")
        nb = ttk.Notebook(w)
        nb.pack(fill="both", expand=True, padx=8)

        lf = ttk.Frame(nb)
        nb.add(lf, text="List")
        top = ttk.Frame(lf)
        top.pack(fill="x", pady=4)
        ttk.Label(top, text="Group by").pack(side="left")
        self.v_group = tk.StringVar(value="day")
        cb = ttk.Combobox(top, textvariable=self.v_group, state="readonly", width=10,
                          values=("day", "week", "month", "quarter", "year"))
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self._fill())
        tf = ttk.Frame(lf)
        tf.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tf, columns=("up", "down", "total", "bar"),
                                 show="tree headings")
        for col, txt_, wd in (("#0", "Period", 110), ("up", "Upload", 95),
                              ("down", "Download", 95), ("total", "Total", 95),
                              ("bar", "", 180)):
            self.tree.heading(col, text=txt_)
            self.tree.column(col, width=wd, anchor="w" if col in ("#0", "bar") else "e")
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._fill()

        cf = ttk.Frame(nb)
        nb.add(cf, text="Calendar")
        nav = ttk.Frame(cf)
        nav.pack(fill="x", pady=4)
        self.month = date.today().replace(day=1)
        ttk.Button(nav, text="◀", width=3, command=lambda: self._shift(-1)).pack(side="left")
        self.lbl_month = ttk.Label(nav, text="", width=26, anchor="center")
        self.lbl_month.pack(side="left")
        ttk.Button(nav, text="▶", width=3, command=lambda: self._shift(1)).pack(side="left")
        self.cal = tk.Canvas(cf, bg="#ffffff", highlightthickness=0)
        self.cal.pack(fill="both", expand=True)
        self.cal.bind("<Configure>", lambda e: self._draw_cal())

        b = ttk.Frame(w)
        b.pack(fill="x", padx=8, pady=8)
        ttk.Button(b, text="Close", command=w.destroy).pack(side="right")
        ttk.Button(b, text="Export CSV…", command=self._export).pack(side="left")
        ttk.Button(b, text="Clear history…", command=self._clear).pack(side="left", padx=6)
        ttk.Button(b, text="Import from TrafficMonitor…", command=self._import).pack(side="left")

    def _fill(self):
        self.tree.delete(*self.tree.get_children())
        rows = self.h.grouped(self.v_group.get())
        mx = max((u + d for _, u, d in rows), default=0) or 1
        for label, u, d in rows:
            bar = "█" * max(1 if u + d else 0, int((u + d) / mx * 20))
            self.tree.insert("", "end", text=label, values=(fmt_size(u), fmt_size(d),
                                                           fmt_size(u + d), bar))

    def _shift(self, n):
        y, m = self.month.year, self.month.month + n
        y += (m - 1) // 12
        m = (m - 1) % 12 + 1
        self.month = date(y, m, 1)
        self._draw_cal()

    def _draw_cal(self):
        c = self.cal
        c.delete("all")
        self.lbl_month.config(text=self.month.strftime("%B %Y"))
        W, H = c.winfo_width(), c.winfo_height()
        if W < 50:
            return
        cw, top = W / 7, 22
        weeks = calendar.Calendar(0).monthdatescalendar(self.month.year, self.month.month)
        ch = (H - top) / len(weeks)
        for i, dname in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            c.create_text(i * cw + cw / 2, 11, text=dname, fill="#555", font=UI_FONT)
        vals = {}
        for wk in weeks:
            for d in wk:
                v = self.h.day(d)
                vals[d] = v["up"] + v["down"]
        mx = max([v for d, v in vals.items() if d.month == self.month.month] + [1])
        for r, wk in enumerate(weeks):
            for i, d in enumerate(wk):
                x0, y0 = i * cw, top + r * ch
                v = vals[d]
                inmonth = d.month == self.month.month
                frac = v / mx if inmonth else 0
                fill = "#%02x%02x%02x" % (int(255 - 175 * frac), int(255 - 120 * frac), 255) \
                    if v and inmonth else ("#ffffff" if inmonth else "#f2f2f2")
                outline = "#d33" if d == date.today() else "#dddddd"
                c.create_rectangle(x0 + 1, y0 + 1, x0 + cw - 1, y0 + ch - 1, fill=fill,
                                   outline=outline, width=2 if d == date.today() else 1)
                c.create_text(x0 + 5, y0 + 4, text=str(d.day), anchor="nw",
                              fill="#222" if inmonth else "#aaa", font=UI_FONT)
                if v and inmonth:
                    c.create_text(x0 + cw / 2, y0 + ch / 2 + 6, text=fmt_size(v),
                                  fill="#000", font=(UI_FONT[0], 8))
        m = self.h.total_since(self.month)
        end = date(self.month.year + (self.month.month == 12), self.month.month % 12 + 1, 1)
        e = self.h.total_since(end)
        tot = (m["up"] - e["up"]) + (m["down"] - e["down"])
        self.lbl_month.config(text=f"{self.month:%B %Y}  –  {fmt_size(tot)}")

    def _import(self):
        r = self.app.import_trafficmonitor(parent=self.w)
        if r and (r["added"] or r["updated"]):
            self.w.destroy()
            HistoryDialog(self.app)          # reopen with the new data

    def _export(self):
        path = filedialog.asksaveasfilename(parent=self.w, defaultextension=".csv",
                                            initialfile="netmeter-history.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f)
            wr.writerow(["date", "upload_bytes", "download_bytes", "total_bytes"])
            for k, v in sorted(self.h.days.items()):
                wr.writerow([k, v["up"], v["down"], v["up"] + v["down"]])

    def _clear(self):
        if messagebox.askyesno(APP_NAME, "Delete all traffic history?", parent=self.w):
            self.h.days = {}
            self.h.dirty = True
            self.h.save()
            self.w.destroy()


# =========================================================================== connection details
class DetailsDialog:
    def __init__(self, app):
        self.app = app
        w = self.w = _dialog(app, "Connection details", "600x520")
        self.txt = tk.Text(w, wrap="none", font=("Consolas" if IS_WIN else "DejaVu Sans Mono", 9))
        self.txt.pack(fill="both", expand=True, padx=8, pady=8)
        b = ttk.Frame(w)
        b.pack(fill="x", padx=8, pady=(0, 8))
        self.v_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(b, text="Show all connections", variable=self.v_all,
                        command=self.fill).pack(side="left")
        ttk.Button(b, text="Look up my internet IP", command=self.lookup).pack(side="left",
                                                                              padx=8)
        ttk.Button(b, text="Close", command=w.destroy).pack(side="right")
        ttk.Button(b, text="Refresh", command=self.fill).pack(side="right", padx=4)
        self.public_ip = None
        self.fill()

    def lookup(self):
        self.public_ip = "looking up…"
        self.fill()

        def work():
            try:
                with urllib.request.urlopen("https://api.ipify.org", timeout=6) as r:
                    ip = r.read().decode().strip()
            except Exception as e:
                ip = f"couldn't look it up ({e.__class__.__name__})"
            self.public_ip = ip
            try:
                self.w.after(0, self.fill)
            except (tk.TclError, RuntimeError):
                pass
        threading.Thread(target=work, daemon=True).start()

    def fill(self):
        m = self.app.monitor
        d = m.data or {}
        stats, addrs = psutil.net_if_stats(), psutil.net_if_addrs()
        io = psutil.net_io_counters(pernic=True)
        used = set(m.adapters())
        lines = [f"Computer name:     {socket.gethostname()}",
                 f"Default gateway:   {default_gateway() or 'unknown'}",
                 f"Internet IP:       {self.public_ip or '(press “Look up my internet IP”)'}",
                 f"NetMeter running since {datetime.fromtimestamp(m.start_time):%Y-%m-%d %H:%M}"
                 f":  ↑ {fmt_size(d.get('since_start_up', 0))}  "
                 f"↓ {fmt_size(d.get('since_start_down', 0))}",
                 f"Today:  ↑ {fmt_size(d.get('today_up', 0))}  ↓ {fmt_size(d.get('today_down', 0))}",
                 f"Windows started:   {datetime.fromtimestamp(psutil.boot_time()):%Y-%m-%d %H:%M}",
                 ""]
        names = sorted(stats) if self.v_all.get() else sorted(
            n for n in stats if n in used or (stats[n].isup and n in auto_adapters()))
        for n in names:
            st = stats[n]
            lines.append(f"{n}{'   [counted]' if n in used else ''}")
            lines.append(f"  Status: {'connected' if st.isup else 'disconnected'}   "
                         f"Link speed: {st.speed or '?'} Mb/s   MTU: {st.mtu}")
            for a in addrs.get(n, []):
                fam = getattr(a.family, "name", str(a.family))
                if fam == "AF_INET":
                    lines.append(f"  IPv4: {a.address}   Mask: {a.netmask}")
                elif fam == "AF_INET6":
                    lines.append(f"  IPv6: {a.address}")
                elif a.address and len(a.address) == 17:
                    lines.append(f"  MAC:  {a.address}")
            if n in io:
                lines.append(f"  Since Windows started:  sent {fmt_size(io[n].bytes_sent)}"
                             f",  received {fmt_size(io[n].bytes_recv)}")
            lines.append("")
        self.txt.config(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", "\n".join(lines))
        self.txt.config(state="disabled")


# =========================================================================== skins
class SkinDialog:
    SAMPLE = {"up": 123456, "down": 2345678, "total": 2469134, "cpu": 23, "ram": 61,
              "gpu": 8, "disk": 3, "cpu_freq": 3400, "cpu_temp": 52, "gpu_temp": 44,
              "disk_temp": 35, "board_temp": 38, "today": 1.5e9,
              "ram_used": 9.8e9, "ram_avail": 6.2e9}

    def __init__(self, app, on_pick=None):
        self.app, self.on_pick = app, on_pick
        w = self.w = _dialog(app, "Skins", "560x320")
        self.skins = load_skins()
        left = ttk.Frame(w)
        left.pack(side="left", fill="y", padx=8, pady=8)
        self.lb = tk.Listbox(left, height=14, exportselection=False)
        for s in self.skins:
            self.lb.insert("end", s["name"])
        self.lb.pack(fill="y", expand=True)
        self.lb.bind("<<ListboxSelect>>", lambda e: self.preview())
        right = ttk.Frame(w)
        right.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        self.cv = tk.Canvas(right, width=320, height=180, bg="#808080", highlightthickness=0)
        self.cv.pack(pady=10)
        self.painter = None
        b = ttk.Frame(right)
        b.pack(fill="x", side="bottom")
        ttk.Button(b, text="Use this skin", command=self.use).pack(side="right")
        ttk.Button(b, text="Open skins folder",
                   command=lambda: win.open_path(SKINS_DIR)).pack(side="left")
        cur = app.cfg["main"].get("skin")
        names = [s["name"] for s in self.skins]
        self.lb.selection_set(names.index(cur) if cur in names else 0)
        self.preview()

    def preview(self):
        sel = self.lb.curselection()
        if not sel:
            return
        s = self.skins[sel[0]]
        m = self.app.cfg["main"]
        spec = dict(m["font"])
        spec.update(s.get("font", {}))
        font = make_font(spec)
        self.cv.delete("all")
        sub = tk.Canvas(self.cv, highlightthickness=0, bd=0)
        painter = ItemPainter(sub)
        entries = []
        for iid in ["up", "down", "cpu", "ram"]:
            col = s.get("item_colors", {}).get(iid, s.get("text_color", "#fff"))
            entries.append({"id": iid, "label": m["labels"].get(iid, ITEMS[iid][1]),
                            "value": format_item(iid, self.SAMPLE, m["fmt"]),
                            "sample": sample_text(iid, m["fmt"]),
                            "label_color": col, "value_color": col})
        wdt, hgt, boxes = painter.measure(entries, font, s.get("layout", "grid2"),
                                          int(s.get("spacing", 12)),
                                          tuple(s.get("padding", (8, 4))))
        sub.config(width=wdt, height=hgt)
        img = None
        if s.get("bg_image"):
            try:
                img = tk.PhotoImage(file=s["bg_image"])
            except tk.TclError:
                img = None
        self._img = img
        painter.draw(entries, boxes, font, s.get("bg", "#000"), bg_image=img)
        self.cv.create_window(160, 90, window=sub)
        self._keep = (sub, font)

    def use(self):
        sel = self.lb.curselection()
        if not sel:
            return
        name = self.skins[sel[0]]["name"]
        if self.on_pick:
            self.on_pick(name)
        else:
            self.app.cfg["main"]["skin"] = name
            self.app.apply_config(self.app.cfg)
        self.w.destroy()


def about(app):
    messagebox.showinfo(
        f"About {APP_NAME}",
        f"{APP_NAME} {VERSION}\n\nShows network speed, CPU, memory, GPU, disk and "
        f"temperatures in your taskbar or a floating window.\n\n"
        f"Settings & history: {DATA_DIR}\n\nRuns entirely on your own PC.")
