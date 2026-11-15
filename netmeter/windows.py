"""The floating window, the taskbar window, tooltips and pop-up notifications."""

import os
import tkinter as tk

import time

from . import dock as dockfind
from . import win
from .config import IS_WIN, ITEMS, SCHEMES, log
from .render import ItemPainter, format_item, make_font, sample_text
from .skins import get_skin


def build_entries(app, wcfg, data, kind, fmt=None):
    """Turn the window's item list into drawable entries."""
    items = list(wcfg["items"])
    if kind == "main" and not wcfg.get("more_info", True):
        items = items[:2]
    f = fmt or wcfg["fmt"]
    if f.get("swap_updown") and "up" in items and "down" in items:
        a, b = items.index("up"), items.index("down")
        items[a], items[b] = items[b], items[a]
    pitems = app.plugins.items()
    psamples = {k: v[2] for k, v in pitems.items()}
    out = []
    for iid in items:
        if iid.startswith("p:") and iid not in pitems:
            continue
        default_label = pitems[iid][1] if iid.startswith("p:") else ITEMS[iid][1]
        label = wcfg["labels"].get(iid, default_label)
        out.append({"id": iid, "label": label,
                    "value": format_item(iid, data, f, app.plugins.values),
                    "sample": sample_text(iid, f, psamples)})
    return out


# =========================================================================== floating window
class MainWindow:
    def __init__(self, app):
        self.app = app
        self.cfg = app.cfg["main"]
        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.title("NetMeter")
        self.canvas = tk.Canvas(self.win, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.painter = ItemPainter(self.canvas)
        self._drag = None
        self._bg_image = None
        self.hwnd = 0
        self.hidden_for_fullscreen = False
        self.load_style()
        c = self.canvas
        c.bind("<ButtonPress-1>", self._drag_start)
        c.bind("<B1-Motion>", self._drag_move)
        c.bind("<ButtonRelease-1>", self._drag_end)
        c.bind("<Button-3>", lambda e: app.popup_menu("main", e))
        c.bind("<Double-Button-1>", lambda e: app.double_click(self.cfg, self._item_at(e)))
        self.tooltip = Tooltip(app, c, lambda: self.cfg.get("tooltip", True))

    def load_style(self):
        self.skin = get_skin(self.cfg.get("skin", "Classic Dark"))
        use_skin = self.cfg.get("skin_font", True)
        font_spec = dict(self.cfg["font"])
        if use_skin and self.skin.get("font"):
            font_spec.update(self.skin["font"])
        self.font = make_font(font_spec)
        self.bg = self.skin.get("bg", "#1e1e1e")
        if use_skin:
            self.text_color = self.skin.get("text_color", "#e8e8e8")
            self.item_colors = dict(self.skin.get("item_colors", {}))
        else:
            self.text_color = self.cfg.get("text_color", "#e8e8e8")
            self.item_colors = {}
        self.item_colors.update({} if use_skin else self.cfg.get("item_colors", {}))
        self._bg_image = None
        if self.skin.get("bg_image"):
            try:
                self._bg_image = tk.PhotoImage(file=self.skin["bg_image"])
            except tk.TclError as e:
                log(f"skin background failed: {e}")
        self.painter.width_memory.clear()

    def apply_window_flags(self):
        self.win.attributes("-alpha", float(self.cfg.get("opacity", 0.92)))
        self.win.attributes("-topmost", bool(self.cfg.get("topmost", True)))
        if IS_WIN:
            self.hwnd = win.toplevel_hwnd(self.win)
            win.set_tool_window(self.hwnd)
            win.set_click_through(self.hwnd, bool(self.cfg.get("click_through")))

    def show(self):
        self.refresh(self.app.monitor.data or {})
        self.place()
        self.win.deiconify()
        self.apply_window_flags()
        self.win.lift()

    def refresh(self, data):
        entries = build_entries(self.app, self.cfg, data, "main")
        for e in entries:
            col = self.item_colors.get(e["id"], self.text_color)
            e["label_color"] = e["value_color"] = col
        pad = tuple(self.skin.get("padding", (8, 4)))
        spacing = int(self.skin.get("spacing", 12))
        layout = self.skin.get("layout", "grid2")
        w, h, boxes = self.painter.measure(entries, self.font, layout, spacing, pad)
        if self._bg_image is not None:
            w, h = max(w, self._bg_image.width()), max(h, self._bg_image.height())
        if int(self.canvas["width"]) != w or int(self.canvas["height"]) != h:
            self.canvas.config(width=w, height=h)
        self.entries, self.boxes = entries, boxes
        self.painter.draw(entries, boxes, self.font, self.bg, right_align=False,
                          bg_image=self._bg_image)

    def place(self):
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        x, y = self.cfg.get("x"), self.cfg.get("y")
        if x is None or y is None:
            sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
            x, y = sw - w - 24, sh - h - 90
        if not self.cfg.get("allow_offscreen"):
            x, y = self._clamp(x, y, w, h)
        self.win.geometry(f"+{int(x)}+{int(y)}")
        self.cfg["x"], self.cfg["y"] = int(x), int(y)

    def _clamp(self, x, y, w, h):
        vs = win.virtual_screen() or (0, 0, self.win.winfo_screenwidth(),
                                      self.win.winfo_screenheight())
        left, top, vw, vh = vs
        return (min(max(int(x), left), left + vw - w), min(max(int(y), top), top + vh - h))

    def _item_at(self, e):
        for ent, (x0, y0, x1, y1, *_) in zip(getattr(self, "entries", []),
                                            getattr(self, "boxes", [])):
            if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                return ent["id"]
        return None

    def _drag_start(self, e):
        self._drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _drag_move(self, e):
        if self.cfg.get("locked") or not self._drag:
            return
        x, y = e.x_root - self._drag[0], e.y_root - self._drag[1]
        if not self.cfg.get("allow_offscreen"):
            x, y = self._clamp(x, y, self.win.winfo_width(), self.win.winfo_height())
        self.win.geometry(f"+{x}+{y}")

    def _drag_end(self, _e):
        if self._drag and not self.cfg.get("locked"):
            self.cfg["x"], self.cfg["y"] = self.win.winfo_x(), self.win.winfo_y()
            self.app.save()
        self._drag = None

    def reassert(self):
        """Keep it visible: back on top, back on screen."""
        if self.hidden_for_fullscreen:
            return
        if self.cfg.get("topmost", True):
            if IS_WIN:
                win.force_topmost(self.hwnd)
            else:
                self.win.attributes("-topmost", True)
                self.win.lift()

    def set_fullscreen_hidden(self, hidden):
        if hidden == self.hidden_for_fullscreen:
            return
        self.hidden_for_fullscreen = hidden
        if hidden:
            self.win.withdraw()
        else:
            self.win.deiconify()
            self.apply_window_flags()

    def destroy(self):
        self.tooltip.hide()
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# =========================================================================== taskbar window
class FakeTaskbar:
    """Used when not on Windows: pretend there's a taskbar so the window can still be
    shown and tested. NETMETER_FAKE_TASKBAR="edge:size" picks where, e.g. "left:48"
    or "top:32" (default "bottom:40")."""

    def __init__(self, root):
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        edge, _, size = os.environ.get("NETMETER_FAKE_TASKBAR", "bottom:40").partition(":")
        size = int(size or 40)
        self.hwnd = None
        self.primary = True
        self.edge = edge
        self.vertical = edge in ("left", "right")
        self.rect = {"bottom": (0, sh - size, sw, sh), "top": (0, 0, sw, size),
                     "left": (0, 0, size, sh), "right": (sw - size, 0, sw, sh)}[edge]
        l, t, r, b = self.rect
        # where the clock / tray icons and the Start button would be
        self._notify = (l, b - 150, r, b) if self.vertical else (r - 200, t, r, b)
        self._start = (l, t, r, t + 48) if self.vertical else (l, t, l + 48, b)

    def notify_area(self):
        return self._notify

    def child_rect(self, cls):
        return self._start if cls == "Start" else None


class TaskbarWindow:
    def __init__(self, app):
        self.app = app
        self.cfg = app.cfg["taskbar"]
        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.title("NetMeter taskbar")
        self.canvas = tk.Canvas(self.win, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.painter = ItemPainter(self.canvas)
        self.font = make_font(self.cfg["font"])
        self.draw_font = self.font
        self._fonts = {}
        self.fit_note = ""
        self.dock = None              # custom dock found on the taskbar (Hitodama etc.)
        self._dock_checked = 0.0
        self._dock_misses = 0
        self._drag = None
        self.tb = None
        self.hwnd = 0
        self.embedded = False
        self.squeeze = None
        self.attached = False
        self.size = (0, 0)
        self.last_slot = None
        self.sampled_bg = None
        self.light = None
        c = self.canvas
        c.bind("<Button-3>", lambda e: app.popup_menu("taskbar", e))
        c.bind("<Double-Button-1>", lambda e: app.double_click(self.cfg, self._item_at(e)))
        c.bind("<ButtonPress-1>", self._drag_start)
        c.bind("<B1-Motion>", self._drag_move)
        c.bind("<ButtonRelease-1>", self._drag_end)
        self.tooltip = Tooltip(app, c, lambda: self.cfg.get("tooltip", True))
        self.boxes, self.entries = [], []

    # ----------------------------------------------------------------- attach
    def attach(self):
        """Find the taskbar and dock into it. Returns False if the taskbar isn't ready."""
        if IS_WIN:
            bars = win.find_taskbars()
            if not bars:
                log("taskbar not found yet")
                return False
            idx = max(0, min(int(self.cfg.get("monitor", 0)), len(bars) - 1))
            self.tb = bars[idx]
        else:
            self.tb = FakeTaskbar(self.app.root)
        self.win.deiconify()
        self.win.update_idletasks()
        self.hwnd = win.toplevel_hwnd(self.win) if IS_WIN else 0
        self._apply_colors()
        if IS_WIN:
            win.set_tool_window(self.hwnd)
            if self.cfg.get("embed", "embed") == "embed":
                self.embedded = win.embed_into(self.hwnd, self.tb.hwnd)
                if not self.embedded:
                    log("could not embed in taskbar; floating on top of it instead")
            if self.tb.primary:
                sq = win.Win10ButtonSqueeze(self.tb)
                self.squeeze = sq if sq.usable else None
        self.attached = True
        self.update_dock(force=True)
        log(f"taskbar window attached (embedded={self.embedded}, edge={self.tb.edge}, "
            f"win11={win.is_win11()})")
        self.refresh(self.app.monitor.data or {})
        return True

    def _scheme_colors(self):
        scheme = self.cfg.get("scheme", "auto")
        if scheme == "custom":
            return self.cfg["bg"], self.cfg["label_color"], self.cfg["value_color"]
        if scheme == "auto":
            self.light = win.windows_uses_light_taskbar()
            scheme = "light" if self.light else "dark"
        s = SCHEMES[scheme]
        return s["bg"], s["label_color"], s["value_color"]

    def _apply_colors(self):
        bg, self.label_color, self.value_color = self._scheme_colors()
        if self.cfg.get("auto_bg", True) and IS_WIN and self.tb:
            sampled = self._sample_taskbar_color()
            if sampled:
                bg = sampled
        # pure black can't be used as the see-through colour on Windows 11
        if bg.lower() == "#000000":
            bg = "#010101"
        for c in (self.label_color, self.value_color):
            if c.lower() == bg.lower():
                bg = "#%06x" % ((int(bg[1:], 16) + 1) & 0xFFFFFF)
        self.bg = bg
        try:
            if self.cfg.get("transparent", True):
                self.win.attributes("-transparentcolor", bg)
            else:
                self.win.attributes("-transparentcolor", "")
        except tk.TclError:
            pass     # not supported on this system

    def _sample_taskbar_color(self):
        l, t, r, b = self.tb.rect
        # sample a spot of bare taskbar just beside where we sit
        if self.tb.vertical:
            x, y = l + 3, (self.last_slot[1] - 6) if self.last_slot else (t + b) // 2
        else:
            y = t + 3
            if self.last_slot:
                x = self.last_slot[0] - 6 if self.cfg.get("position") != "left" \
                    else self.last_slot[0] + self.last_slot[2] + 6
            else:
                na = self.tb.notify_area()
                x = (na[0] - 6) if na else (l + r) // 2
        x = max(l + 1, min(r - 2, x))
        return win.screen_pixel(x, y)

    # ----------------------------------------------------------------- drawing
    def _font_at(self, size):
        """The taskbar font at another size (for squeezing into small taskbars)."""
        if size == int(self.cfg["font"].get("size", 9)):
            return self.font
        if size not in self._fonts:
            self._fonts[size] = make_font(dict(self.cfg["font"], size=size))
        return self._fonts[size]

    def _entries(self, data, fmt=None):
        entries = build_entries(self.app, self.cfg, data, "taskbar", fmt)
        ic = self.cfg.get("item_colors", {})
        lc, vc = self._text_colors()
        for e in entries:
            cc = ic.get(e["id"], {})
            e["label_color"] = cc.get("label", lc)
            e["value_color"] = cc.get("value", vc)
            e["graph"] = self._graph_for(e["id"], data)
        return entries

    def _layout(self, data):
        """Pick a layout that fits the taskbar as it is right now (it can be moved to
        any edge and resized on current Windows 11). Returns (entries, w, h, boxes)."""
        l, t, r, b = self.tb.rect
        spacing = int(self.cfg.get("spacing", 8))
        base = int(self.cfg["font"].get("size", 9))
        scale = win.dpi_scale(self.tb.hwnd) if IS_WIN else 1.0
        if self.tb.vertical:
            width = r - l
            fmt = dict(self.cfg["fmt"])
            if width <= 64 * scale:          # narrow side taskbar (48 px by default)
                fmt.update(short=True, space=False,
                           speed_width=min(4, int(fmt.get("speed_width", 5))))
            entries = self._entries(data, fmt)
            self.painter.width_memory.clear()
            # wide side taskbar + "one line" setting: keep everything on one line if it fits
            if not self.cfg.get("two_rows", True):
                w, h, boxes = self.painter.measure(entries, self.font, "row", spacing, (2, 2))
                if w <= width - 2:
                    self.draw_font, self.fit_note = self.font, "one line"
                    return entries, width, h, boxes
            for size in range(base, 5, -1):
                font = self._font_at(size)
                w, h, boxes, fits = self.painter.measure_side(entries, font, width, spacing)
                if fits:
                    break
                if size == base and fmt.get("per_second", True):
                    # before shrinking the text, drop "/s" from speeds
                    fmt["per_second"] = False
                    entries = self._entries(data, fmt)
                    w, h, boxes, fits = self.painter.measure_side(entries, font, width, spacing)
                    if fits:
                        break
            self.draw_font = font
            self.fit_note = f"side {width}px, font {size}"
            return entries, w, h, boxes
        # horizontal taskbar (bottom or top)
        height = b - t
        style = self._backdrop_style()
        if style == "pill":
            if self.dock is not None:
                inner = self.dock["bottom"] - self.dock["top"] + 1
            else:
                inner = height - 2 * max(2, height // 12)
            height = max(12, inner - 2)
        entries = self._entries(data)
        two = self.cfg.get("two_rows", True)
        font = self.font
        for size in range(base, 5, -1):
            font = self._font_at(size)
            line = font.metrics("linespace")
            if two and 2 * line + 2 <= height:
                layout = "grid2"
                break
            if line + 2 <= height:
                layout = "row"           # too short for two rows: put them on one line
                break
        else:
            layout = "row"
        padx = 12 if style == "pill" else 4
        w, h, boxes = self.painter.measure(entries, font, layout, spacing, (padx, 0), None,
                                           height)
        if h != b - t:           # centre the rows within the full taskbar height
            dy = ((b - t) - h) / 2
            boxes = [(x0, y0 + dy, x1, y1 + dy, *rest) for (x0, y0, x1, y1, *rest) in boxes]
            h = b - t
        self.draw_font = font
        self.fit_note = f"{layout} {height}px, font {size}"
        return entries, w, h, boxes

    def refresh(self, data):
        if not self.attached:
            return
        entries, w, h, boxes = self._layout(data)
        self.entries, self.boxes = entries, boxes
        if (w, h) != self.size:
            self.size = (w, h)
            self.canvas.config(width=w, height=h)
            self.win.update_idletasks()
            self.last_slot = None
        backdrop = self._backdrop(w, h)
        self.painter.draw(entries, boxes, self.draw_font, self.bg,
                          right_align=self.cfg.get("right_align", False),
                          graph_color=self.cfg.get("graph_color", "#3a8fd8"),
                          graph_outline=self.cfg.get("graph_outline", False),
                          backdrop=backdrop)
        self.position()

    def _panel_color(self):
        c = self.cfg.get("pill_color", "auto")
        if c and c != "auto":
            return c
        if self.dock is not None:
            return self.dock["color"]
        return self._scheme_colors()[0]

    def _backdrop(self, w, h):
        """Rounded panel behind the stats (pill) or a plain rectangle (solid)."""
        style = self._backdrop_style()
        if style not in ("pill", "solid"):
            return None
        color = self._panel_color()
        if color.lower() == self.bg.lower():          # must differ from see-through key
            self.bg = "#%06x" % ((int(self.bg[1:], 16) ^ 0x000001) & 0xFFFFFF)
            try:
                if self.cfg.get("transparent", True):
                    self.win.attributes("-transparentcolor", self.bg)
            except tk.TclError:
                pass
        if style == "solid":
            return (color, 0, 0, w, h, 0)
        if self.dock is not None and not self.tb.vertical:
            top, bottom = self.dock["top"], self.dock["bottom"]
        else:
            inset = max(2, h // 12)
            top, bottom = inset, h - inset - 1
        return (color, 0, top, w - 1, bottom, int(self.cfg.get("pill_radius", 12)))

    def _text_colors(self):
        """Readable text on our panel: white on dark, black on light."""
        style = self._backdrop_style()
        if style in ("pill", "solid") and self.cfg.get("scheme", "auto") == "auto":
            c = self._panel_color().lstrip("#")
            r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
            light = 0.299 * r + 0.587 * g + 0.114 * b > 140
            return ("#000000", "#000000") if light else ("#ffffff", "#ffffff")
        return self.label_color, self.value_color

    def _graph_for(self, iid, data):
        mode = self.cfg.get("graph", "none")
        if mode == "none" or iid not in self.cfg.get("graph_items", []):
            return None
        series = self.app.monitor.series.get(iid)
        if series is None:
            return None
        kind = ITEMS[iid][2] if iid in ITEMS else ""
        if kind == "speed":
            fixed = float(self.cfg.get("graph_net_max_kb", 0)) * 1024
            scale = fixed or max(max(series, default=0), 1024.0)
            pct = (data.get(iid) or 0) / scale * 100
        else:
            scale, pct = 100.0, data.get(iid)
        return (mode, pct, series, scale)

    def position(self):
        if not self.attached:
            return
        w, h = self.size
        reserve = None
        pos = self.cfg.get("position", "auto")
        docked = self._docked()
        if self.squeeze and not docked and pos != "free":
            try:
                reserve = self.squeeze.apply(h if self.tb.vertical else w,
                                             "left" if pos == "left" else "right")
            except Exception as e:
                log(f"button squeeze failed: {e}")
                self.squeeze = None
        if IS_WIN:
            try:
                self.tb.rect = win.rect_of(self.tb.hwnd) or self.tb.rect
            except Exception:
                pass
        l, t, r, b = self.tb.rect
        offset = int(self.cfg.get("offset", 0))
        if docked:
            gap = int(self.cfg.get("dock_gap", 8)) + offset
            x = l + self.dock["right"] + 1 + gap
            if x + w > r:                         # no room after it: go before it
                x = l + self.dock["left"] - gap - w
            slot = (max(l, x), t, w, b - t)
        elif pos == "free" and self.cfg.get("free_x") is not None and not self.tb.vertical:
            x = l + int(self.cfg["free_x"])
            slot = (max(l, min(x, r - w)), t, w, b - t)
        else:
            slot = win.compute_taskbar_slot(self.tb, w, h, "left" if pos == "left" else "right",
                                            offset, reserve)
        if slot == self.last_slot and self._actual_rect() == slot:
            return
        self.last_slot = slot
        x, y, sw, sh = slot
        if IS_WIN:
            if self.embedded:
                win.place_child(self.hwnd, self.tb.hwnd, x, y, sw, sh)
            else:
                win.place_top(self.hwnd, x, y, sw, sh)
        else:
            self.win.geometry(f"{sw}x{sh}+{x}+{y}")
            self.win.attributes("-topmost", True)
            self.win.lift()

    def _actual_rect(self):
        """Where the window really is on screen right now, as (x, y, w, h)."""
        if IS_WIN:
            r = win.rect_of(self.hwnd)
            return (r[0], r[1], r[2] - r[0], r[3] - r[1]) if r else None
        try:
            g = self.win.geometry()            # "WxH+X+Y"
            size, x, y = g.split("+")[0], g.split("+")[1], g.split("+")[2]
            w, h = size.split("x")
            return int(x), int(y), int(w), int(h)
        except (tk.TclError, ValueError, IndexError):
            return None

    def _item_at(self, e):
        for ent, (x0, y0, x1, y1, *_) in zip(self.entries, self.boxes):
            if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                return ent["id"]
        return None

    # ----------------------------------------------------------------- upkeep
    # ----------------------------------------------------------------- custom docks
    def _docked(self):
        return (self.dock is not None and not self.tb.vertical
                and self.cfg.get("position", "auto") in ("auto", "dock"))

    def update_dock(self, force=False):
        """Look at the taskbar for a custom dock (a floating bar drawn by Hitodama or
        similar). Returns True if what we found changed."""
        # (looked for in every position: even when placed by hand, the panel should
        #  match the dock so the stats stay readable over a busy background)
        if not self.attached or self.tb.vertical:
            changed, self.dock = self.dock is not None, None
            return changed
        # look often while a dock is there (it grows as apps open); when there's none,
        # back off to every 10 s so a normal taskbar costs nothing
        wait = 1.5 if self.dock else min(10.0, 2.0 * (self._dock_misses + 1))
        if not force and time.monotonic() - self._dock_checked < wait:
            return False
        self._dock_checked = time.monotonic()
        l, t, r, b = self.tb.rect
        img = dockfind.grab_strip((l, t, r, b))
        if img is None:
            return False
        excl = None
        if self.last_slot:      # don't mistake our own panel for part of the dock
            x, _, w, _ = self.last_slot
            excl = (x - l - 2, x - l + w + 2)
        found = dockfind.find_dock(img, excl)
        self._dock_misses = 0 if found else self._dock_misses + 1
        old = self.dock
        if found and old and abs(found["right"] - old["right"]) <= 2 and \
                abs(found["left"] - old["left"]) <= 2 and found["top"] == old["top"]:
            return False                        # ignore 1-2 px jitter
        self.dock = found
        if (found is None) != (old is None) or found:
            log(f"custom dock {'found: ' + str(found) if found else 'gone'}")
            return True
        return False

    def _backdrop_style(self):
        style = self.cfg.get("bg_style", "auto")
        if style == "auto":
            return "pill" if self.dock is not None and not self.tb.vertical else "clear"
        return style

    # ----------------------------------------------------------------- dragging
    def _drag_start(self, e):
        self._drag = (e.x_root, self.last_slot[0] if self.last_slot else 0, False)

    def _drag_move(self, e):
        if not self._drag or self.tb is None or self.tb.vertical:
            return
        x0, slot_x, moving = self._drag
        if not moving and abs(e.x_root - x0) < 6:      # ignore tiny moves (clicks)
            return
        self._drag = (x0, slot_x, True)
        self.cfg["position"] = "free"
        self.cfg["free_x"] = slot_x + (e.x_root - x0) - self.tb.rect[0]
        self.last_slot = None
        self.position()

    def _drag_end(self, _e):
        if self._drag and self._drag[2]:
            self.app.save()
            log(f"taskbar window dragged to x={self.cfg['free_x']}")
        self._drag = None

    def check(self):
        """Called every couple of seconds. Returns False if we must be rebuilt
        (Explorer restarted, taskbar moved to another monitor ...)."""
        if self.attached and self.update_dock():
            self.last_slot = None
            self.refresh(self.app.monitor.data or {})
        if not IS_WIN or not self.attached:
            return True
        if not win.is_window(self.tb.hwnd) or not win.is_window(self.hwnd):
            return False
        if self.embedded and win.parent_of(self.hwnd) != self.tb.hwnd:
            return False
        bars = win.find_taskbars()
        idx = max(0, min(int(self.cfg.get("monitor", 0)), len(bars) - 1)) if bars else 0
        if bars and bars[idx].hwnd != self.tb.hwnd:
            return False
        if self.cfg.get("scheme") == "auto" and win.windows_uses_light_taskbar() != self.light:
            self._apply_colors()
        if self.tb.vertical != ((self.tb.rect[3] - self.tb.rect[1]) >
                                (self.tb.rect[2] - self.tb.rect[0])):
            return False
        self.last_slot = None          # re-place: tray icons may have been added
        self.position()
        if not self.embedded:
            if win.fullscreen_app_running():
                self.win.withdraw()
            else:
                self.win.deiconify()
                win.force_topmost(self.hwnd)
        return True

    def destroy(self):
        self.tooltip.hide()
        if self.squeeze:
            try:
                self.squeeze.restore()
            except Exception:
                pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# =========================================================================== tooltip & toast
class Tooltip:
    def __init__(self, app, widget, enabled):
        self.app, self.widget, self.enabled = app, widget, enabled
        self.tip = None
        self.after_id = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", lambda e: self.hide(), add="+")
        widget.bind("<Motion>", self._motion, add="+")
        widget.bind("<ButtonPress>", lambda e: self.hide(), add="+")
        self.pos = (0, 0)

    def _enter(self, e):
        self.pos = (e.x_root, e.y_root)
        self._schedule()

    def _motion(self, e):
        self.pos = (e.x_root, e.y_root)
        if self.tip:
            self._update()
        else:
            self._schedule()

    def _schedule(self):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
        self.after_id = self.widget.after(600, self.show)

    def show(self):
        self.after_id = None
        if not self.enabled():
            return
        if not self.tip:
            self.tip = tk.Toplevel(self.widget)
            self.tip.overrideredirect(True)
            self.tip.attributes("-topmost", True)
            self.label = tk.Label(self.tip, justify="left", bg="#ffffe1", fg="#000000",
                                  relief="solid", bd=1, padx=6, pady=4,
                                  font=("Segoe UI" if IS_WIN else "DejaVu Sans", 9))
            self.label.pack()
        self._update()

    def _update(self):
        if not self.tip:
            return
        self.label.config(text=self.app.tooltip_text())
        self.tip.update_idletasks()
        w, h = self.tip.winfo_reqwidth(), self.tip.winfo_reqheight()
        x, y = self.pos
        sw, sh = self.tip.winfo_screenwidth(), self.tip.winfo_screenheight()
        mon = win.monitor_rect_at(x, y) if IS_WIN else (0, 0, sw, sh)
        tx = min(x + 12, mon[2] - w - 4)
        ty = y + 18 if y + 18 + h < mon[3] - 50 else y - h - 12
        self.tip.geometry(f"+{int(max(mon[0], tx))}+{int(max(mon[1], ty))}")

    def refresh(self):
        if self.tip:
            self.label.config(text=self.app.tooltip_text())

    def hide(self):
        if self.after_id:
            try:
                self.widget.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None
        if self.tip:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None


class Toast:
    """Small notification in the bottom-right corner (used when the tray can't)."""

    def __init__(self, root, title, message, seconds=8):
        t = self.t = tk.Toplevel(root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        frame = tk.Frame(t, bg="#2b2b2b", padx=12, pady=10, highlightthickness=1,
                         highlightbackground="#555555")
        frame.pack()
        tk.Label(frame, text=title, bg="#2b2b2b", fg="#ffffff",
                 font=("Segoe UI" if IS_WIN else "DejaVu Sans", 10, "bold")).pack(anchor="w")
        tk.Label(frame, text=message, bg="#2b2b2b", fg="#dddddd", justify="left",
                 wraplength=300).pack(anchor="w")
        t.update_idletasks()
        sw, sh = t.winfo_screenwidth(), t.winfo_screenheight()
        t.geometry(f"+{sw - t.winfo_reqwidth() - 16}+{sh - t.winfo_reqheight() - 70}")
        for w in (t, frame) + tuple(frame.winfo_children()):
            w.bind("<Button-1>", lambda e: self.close())
        t.after(seconds * 1000, self.close)

    def close(self):
        try:
            self.t.destroy()
        except tk.TclError:
            pass
