"""Formatting of values and drawing of item rows on a Tk canvas."""

import tkinter.font as tkfont

from .config import ITEMS


# --------------------------------------------------------------------------- formatting
def fmt_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024


def fmt_speed(bps, f):
    bits = f.get("bits")
    v = (bps or 0) * (8 if bits else 1)
    b = "b" if bits else "B"
    mode = f.get("unit_mode", "auto")
    if mode == "KB":
        v, prefix, dec = v / 1024, "K", 1
    elif mode == "MB":
        v, prefix, dec = v / 1048576, "M", 2
    else:
        prefix, dec = "", 0
        for p, d in (("K", 1), ("M", 2), ("G", 2)):
            if v >= 1024:
                v /= 1024
                prefix, dec = p, d
    if f.get("short"):
        dec = max(0, dec - 1)
    unit = prefix + ("" if f.get("short") and b == "B" and prefix else b)
    if f.get("per_second", True):
        unit += "/s"
    num = f"{v:.{dec}f}"
    if f.get("hide_unit") and mode != "auto":
        return num
    return num + (" " if f.get("space", True) else "") + unit


def fmt_percent(v, f):
    if v is None:
        return "--"
    return f"{v:.0f}" + ("" if f.get("hide_percent") else "%")


def format_item(item, data, f, plugin_values=None):
    if item.startswith("p:"):
        return (plugin_values or {}).get(item, "")
    kind = ITEMS[item][2]
    v = data.get(item)
    if kind == "speed":
        return fmt_speed(v, f)
    if kind == "percent":
        return fmt_percent(v, f)
    if kind == "memory":
        mode = f.get("memory_mode", "percent")
        if mode == "used":
            return _gb(data.get("ram_used"), f)
        if mode == "available":
            return _gb(data.get("ram_avail"), f)
        return fmt_percent(v, f)
    if kind == "temp":
        return "--" if v is None else f"{v:.0f}°C"
    if kind == "freq":
        return "--" if not v else f"{v / 1000:.2f} GHz"
    if kind == "size":
        return fmt_size(v)
    return str(v)


def _gb(n, f):
    if n is None:
        return "--"
    return f"{n / 1073741824:.1f}" + (" " if f.get("space", True) else "") + "GB"


def sample_text(item, f, plugin_samples=None):
    """Widest text an item is likely to show, so the window doesn't jump around."""
    if item.startswith("p:"):
        return (plugin_samples or {}).get(item, "")
    kind = ITEMS[item][2]
    if kind == "speed":
        digits = max(3, int(f.get("speed_width", 5)))
        num = "8" * (digits - 2) + ".8" if digits > 3 else "888"
        unit = fmt_speed(1024 * 1024 * 5, dict(f, unit_mode=f.get("unit_mode", "auto")))
        unit = unit.lstrip("0123456789. ")
        if f.get("hide_unit") and f.get("unit_mode") != "auto":
            return num
        return num + (" " if f.get("space", True) else "") + unit
    if kind in ("percent",):
        return "100" + ("" if f.get("hide_percent") else "%")
    if kind == "memory":
        if f.get("memory_mode", "percent") != "percent":
            return "88.8 GB"
        return "100" + ("" if f.get("hide_percent") else "%")
    if kind == "temp":
        return "100°C"
    if kind == "freq":
        return "8.88 GHz"
    if kind == "size":
        return "888.88 MB"
    return "8888"


def make_font(spec):
    return tkfont.Font(family=spec.get("family", "Segoe UI"), size=int(spec.get("size", 9)),
                       weight="bold" if spec.get("bold") else "normal",
                       slant="italic" if spec.get("italic") else "roman",
                       underline=bool(spec.get("underline")),
                       overstrike=bool(spec.get("overstrike")))


# --------------------------------------------------------------------------- drawing
def rounded_rect(c, color, x0, y0, x1, y1, r):
    """Solid rounded rectangle (no anti-aliasing, so it works with a see-through
    background colour without leaving a fringe)."""
    r = max(0, min(int(r), int((x1 - x0) / 2), int((y1 - y0) / 2)))
    if r <= 1:
        c.create_rectangle(x0, y0, x1, y1, fill=color, outline=color)
        return
    d = 2 * r
    c.create_rectangle(x0 + r, y0, x1 - r, y1, fill=color, outline=color)
    c.create_rectangle(x0, y0 + r, x1, y1 - r, fill=color, outline=color)
    for (ax, ay, start) in ((x0, y0, 90), (x1 - d, y0, 0), (x0, y1 - d, 180),
                            (x1 - d, y1 - d, 270)):
        c.create_arc(ax, ay, ax + d, ay + d, start=start, extent=90, fill=color,
                     outline=color, style="pieslice")


class ItemPainter:
    """Lays out and draws items on a canvas.

    entries: list of dicts {id, label, value, sample, label_color, value_color,
                            graph: None | (kind, pct, series)}
    layout:  "grid2" (two rows, columns of pairs), "row" (one line), "column" (one per line)
             measure_side() is used for taskbars on the left/right edge of the screen.
    boxes:   (x0, y0, x1, y1, label_width[, mode]) where mode is "line" (default),
             "center" (label+value centred on one line) or "stack" (label above value)
    """

    def __init__(self, canvas):
        self.canvas = canvas
        self.width_memory = {}       # id -> widest value seen (keeps layout steady)

    def measure(self, entries, font, layout, spacing, pad=(6, 2), fixed_w=None,
                fixed_h=None):
        line_h = font.metrics("linespace")
        cells = []
        for e in entries:
            lw = font.measure(e["label"]) if e["label"] else 0
            vw = max(font.measure(e["sample"]), font.measure(e["value"]),
                     self.width_memory.get(e["id"], 0))
            self.width_memory[e["id"]] = vw
            cells.append((lw, vw))
        px, py = pad
        if not entries:
            return 1, max(1, line_h), []
        boxes = []
        if layout == "row":
            h = fixed_h or line_h + 2 * py
            x = px
            for lw, vw in cells:
                boxes.append((x, 0, x + lw + vw, h, lw))
                x += lw + vw + spacing
            return (fixed_w or x - spacing + px), h, boxes
        if layout == "column":
            w = max(lw + vw for lw, vw in cells) + 2 * px
            if fixed_w:
                w = fixed_w
            y = py
            row_h = line_h + 2
            for lw, vw in cells:
                boxes.append((px, y, w - px, y + row_h, lw))
                y += row_h + max(0, spacing // 3)
            return w, (fixed_h or y + py), boxes
        # grid2: pairs stacked in columns, an odd last item gets a column by itself
        h = fixed_h or 2 * line_h + 2 * py + 2
        half = h / 2
        x = px
        i = 0
        while i < len(cells):
            if i + 1 < len(cells):
                colw = max(cells[i][0] + cells[i][1], cells[i + 1][0] + cells[i + 1][1])
                lw_max = max(cells[i][0], cells[i + 1][0])
                boxes.append((x, 0, x + colw, half, lw_max))
                boxes.append((x, half, x + colw, h, lw_max))
                i += 2
            else:
                colw = cells[i][0] + cells[i][1]
                boxes.append((x, 0, x + colw, h, cells[i][0]))
                i += 1
            x += colw + spacing
        return (fixed_w or x - spacing + px), h, boxes

    def measure_side(self, entries, font, width, spacing):
        """Layout for a vertical taskbar `width` px wide: one item per line, centred;
        an item that doesn't fit on one line gets its label above its value.
        Returns (w, h, boxes, fits) - fits is False if something is still too wide
        (the caller then tries a smaller font)."""
        line_h = font.metrics("linespace")
        avail = max(1, width - 4)
        gap = max(1, spacing // 3)
        boxes, y, fits = [], 2, True
        for e in entries:
            lw = font.measure(e["label"]) if e["label"] else 0
            vs, va = font.measure(e["sample"]), font.measure(e["value"])
            if lw + max(vs, va) <= avail:            # decided on the sample: no jumping
                h, mode = line_h + 2, "center"
            else:
                h, mode = (2 * line_h + 2 if lw else line_h + 2), "stack"
                if max(lw, va) > avail:
                    fits = False
            boxes.append((2, y, width - 2, y + h, lw, mode))
            y += h + gap
        return width, max(1, y - gap + 2), boxes, fits

    def draw(self, entries, boxes, font, bg, right_align=False, graph_color="#3a8fd8",
             graph_outline=False, bg_image=None, backdrop=None):
        """backdrop: (colour, x0, y0, x1, y1, radius) - a rounded panel behind the text."""
        c = self.canvas
        c.delete("all")
        c.configure(bg=bg)
        if bg_image is not None:
            c.create_image(0, 0, image=bg_image, anchor="nw")
        if backdrop:
            rounded_rect(c, *backdrop)
        for e, box in zip(entries, boxes):
            x0, y0, x1, y1, lw = box[:5]
            mode = box[5] if len(box) > 5 else "line"
            g = e.get("graph")
            if g:
                kind, pct, series = g[0], g[1], g[2]
                if kind == "bar" and pct is not None:
                    top = y1 - (y1 - y0) * max(0.0, min(100.0, pct)) / 100.0
                    c.create_rectangle(x0, top, x1, y1, fill=graph_color, width=0)
                elif kind == "plot" and series:
                    n = max(2, int(x1 - x0))
                    pts = list(series)[-n:]
                    scale = g[3] if len(g) > 3 and g[3] else 100.0
                    coords = []
                    step = (x1 - x0) / max(1, len(pts) - 1)
                    for k, v in enumerate(pts):
                        frac = max(0.0, min(1.0, (v or 0) / scale))
                        coords += [x0 + k * step, y1 - 1 - (y1 - y0 - 2) * frac]
                    if len(coords) >= 4:
                        c.create_line(*coords, fill=graph_color, width=1)
                if graph_outline:
                    c.create_rectangle(x0, y0 + 1, x1 - 1, y1 - 1, outline=graph_color,
                                       dash=(2, 2))
            ymid = (y0 + y1) / 2
            if mode == "stack":
                cx = (x0 + x1) / 2
                if e["label"]:
                    c.create_text(cx, y0 + (y1 - y0) / 4, text=e["label"].strip(),
                                  anchor="center", font=font, fill=e["label_color"])
                    ymid = y0 + (y1 - y0) * 3 / 4
                c.create_text(cx, ymid, text=e["value"], anchor="center", font=font,
                              fill=e["value_color"])
                continue
            if mode == "center":
                total = lw + font.measure(e["value"])
                x = (x0 + x1 - total) / 2
                if e["label"]:
                    c.create_text(x, ymid, text=e["label"], anchor="w", font=font,
                                  fill=e["label_color"])
                c.create_text(x + lw, ymid, text=e["value"], anchor="w", font=font,
                              fill=e["value_color"])
                continue
            if e["label"]:
                c.create_text(x0, ymid, text=e["label"], anchor="w", font=font,
                              fill=e["label_color"])
            if right_align:
                c.create_text(x1, ymid, text=e["value"], anchor="e", font=font,
                              fill=e["value_color"])
            else:
                c.create_text(x0 + lw, ymid, text=e["value"], anchor="w", font=font,
                              fill=e["value_color"])
