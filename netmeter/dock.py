"""Find a custom "dock" drawn on top of the taskbar (e.g. Hitodama's floating bar).

Programs like Hitodama restyle the taskbar: an animated background across the whole
strip with a floating, rounded, single-colour bar in the middle that holds the Start
button, the apps and the clock. Windows still reports the clock at its old place, so
the only reliable way to know where the bar really is, is to look at the screen.

find_dock() takes a picture of the taskbar strip and returns where that bar is.
"""

from collections import Counter

TOL = 22          # how far (colour distance) a pixel may be from the dock colour.
                  # Docks are often slightly see-through, so their colour drifts a bit.
EDGE_TOL = 14     # stricter, for finding its top/bottom edge against a dark background
MAX_GAP = 40      # gaps (icons, search box...) shorter than this don't split the dock


def _close(p, c, tol=TOL):
    d0, d1, d2 = p[0] - c[0], p[1] - c[1], p[2] - c[2]
    return d0 * d0 + d1 * d1 + d2 * d2 <= tol * tol


def _rows(img, fracs):
    w, h = img.size
    px = img.load()
    return [[px[x, min(h - 1, int(h * f))][:3] for x in range(w)] for f in fracs]


def find_dock(img, exclude=None):
    """img: RGB picture of the taskbar strip. exclude: (x0, x1) to ignore (our own window).

    Returns {"left", "right", "top", "bottom", "color"} in image coordinates, or None
    if there's no separate dock (e.g. a normal, plain taskbar)."""
    w, h = img.size
    if w < 200 or h < 16:
        return None
    # rows just inside the top and bottom edge of where a dock would be: icons and the
    # search box sit in the middle, so these rows are mostly the dock's own colour
    rows = _rows(img, (0.08, 0.1, 0.12, 0.14, 0.86, 0.88, 0.9, 0.92))

    def excluded(x):
        return exclude is not None and exclude[0] <= x < exclude[1]

    # the dock is the most common colour along those rows (the background is either
    # a picture/animation, which varies, or plain - which we detect below)
    counts = Counter()
    for row in rows:
        for x, p in enumerate(row):
            if not excluded(x):
                counts[(p[0] // 16, p[1] // 16, p[2] // 16)] += 1
    if not counts:
        return None
    q, n = counts.most_common(1)[0]
    # average the real pixels in that bucket for an exact colour
    sel = [p for row in rows for x, p in enumerate(row)
           if not excluded(x) and (p[0] // 16, p[1] // 16, p[2] // 16) == q]
    color = tuple(sum(c[i] for c in sel) // len(sel) for i in range(3))

    mask = [False] * w
    for row in rows:
        for x, p in enumerate(row):
            if not excluded(x) and _close(p, color):
                mask[x] = True

    # group into runs, joining across small gaps. Our own window (excluded) is
    # neither dock nor gap: it must not split a bar into two pieces.
    runs, start, last = [], None, None
    for x, m in enumerate(mask):
        if not m:
            continue
        if start is None:
            start = last = x
            continue
        gap = (x - last) - sum(1 for i in range(last, x) if excluded(i))
        if gap <= MAX_GAP:
            last = x
        else:
            runs.append((start, last))
            start = last = x
    if start is not None:
        runs.append((start, last))
    if not runs:
        return None
    left, right = max(runs, key=lambda r: r[1] - r[0])
    length = right - left + 1
    # a dock is a part of the taskbar, not all of it (plain taskbar = no dock)
    if length < 0.15 * w or length > 0.92 * w:
        return None

    # how tall is it? try a few columns inside it (some may hit an icon) and keep the
    # tallest stretch of dock colour
    px = img.load()
    mid = h // 2
    best = None
    for col_x in (right - 6, right - 14, left + 6, left + 14, (left + right) // 2):
        col_x = max(left, min(right, col_x))
        if excluded(col_x):
            continue
        if not _close(px[col_x, mid][:3], color, TOL + 4):
            continue                      # this column hits an icon in the middle
        ext = []
        for step in (-1, 1):              # walk out from the middle, up then down
            y, edge, misses = mid, mid, 0
            while 0 <= y + step < h and misses <= 1:
                y += step
                if _close(px[col_x, y][:3], color, EDGE_TOL):
                    edge, misses = y, 0
                else:
                    misses += 1
            ext.append(edge)
        top, bottom = ext
        if best is None or bottom - top > best[1] - best[0]:
            best = (top, bottom)
    if best is None or best[1] - best[0] < h * 0.5:
        return None
    top, bottom = best
    # a floating dock has a margin above and/or below it; a plain taskbar's own colour
    # runs from edge to edge, so that's not a dock
    if top < 2 and bottom > h - 3:
        return None
    return {"left": left, "right": right, "top": top, "bottom": bottom,
            "color": "#%02x%02x%02x" % color}


def grab_strip(rect):
    """Picture of the screen inside rect (screen coordinates), or None."""
    try:
        from PIL import ImageGrab
        try:
            img = ImageGrab.grab(bbox=rect, all_screens=True, include_layered_windows=True)
        except TypeError:
            img = ImageGrab.grab(bbox=rect)
        return img.convert("RGB")
    except Exception:
        return None
