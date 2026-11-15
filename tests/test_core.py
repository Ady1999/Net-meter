"""Tests for the parts of NetMeter that don't need a screen or Windows."""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw  # noqa: E402

from netmeter import dock, importer, win  # noqa: E402
from netmeter.render import fmt_size, fmt_speed, format_item, sample_text  # noqa: E402
from netmeter.sources import History, parse_lhm_json, pick_temps  # noqa: E402

F = {"bits": False, "unit_mode": "auto", "short": False, "space": True, "per_second": True}


# ------------------------------------------------------------------ formatting
@pytest.mark.parametrize("bps, fmt, expected", [
    (512, {}, "512 B/s"),
    (1536, {}, "1.5 KB/s"),
    (5 * 1024 ** 2, {}, "5.00 MB/s"),
    (1536, {"short": True}, "2 K/s"),
    (5 * 1024 ** 2, {"short": True, "space": False}, "5.0M/s"),
    (1024, {"bits": True}, "8.0 Kb/s"),
    (5 * 1024 ** 2, {"unit_mode": "MB", "hide_unit": True}, "5.00"),
    (1536, {"per_second": False}, "1.5 KB"),
])
def test_fmt_speed(bps, fmt, expected):
    assert fmt_speed(bps, dict(F, **fmt)) == expected


def test_fmt_size_and_items():
    assert fmt_size(0) == "0 B"
    assert fmt_size(1024 ** 3) == "1.00 GB"
    d = {"cpu": 37.4, "ram": 62.0, "ram_used": 8 * 1024 ** 3, "cpu_temp": 55.2,
         "cpu_freq": 3400}
    assert format_item("cpu", d, F) == "37%"
    assert format_item("cpu", d, dict(F, hide_percent=True)) == "37"
    assert format_item("ram", d, dict(F, memory_mode="used")) == "8.0 GB"
    assert format_item("cpu_temp", d, F) == "55°C"
    assert format_item("cpu_freq", d, F) == "3.40 GHz"
    assert format_item("gpu", {}, F) == "--"
    assert sample_text("up", dict(F, speed_width=5)).startswith("888.8")


# ------------------------------------------------------------------ history
def test_history_period_and_grouping():
    h = History.__new__(History)
    h.days = {"2026-11-01": {"up": 1, "down": 2}, "2026-11-20": {"up": 3, "down": 4},
              "2026-10-31": {"up": 10, "down": 20}}
    h.dirty = False
    assert h.period_start(1, date(2026, 11, 15)) == date(2026, 11, 1)
    assert h.period_start(20, date(2026, 11, 15)) == date(2026, 10, 20)
    months = dict((k, (u, d)) for k, u, d in h.grouped("month"))
    assert months == {"2026-11": (4, 6), "2026-10": (10, 20)}
    assert h.total_since(date(2026, 11, 1)) == {"up": 4, "down": 6}


# ------------------------------------------------------------------ TrafficMonitor import
def test_trafficmonitor_import(tmp_path):
    f = tmp_path / "history_traffic.dat"
    f.write_bytes(b'lines: "6"\r\n2026/11/06 20480/512000\r\n2026/11/06 20480/512000\r\n'
                  b'2026/11/05 10240/2097152\r\n2024/02/30 5/5\r\n2023/07/14 3145728\r\n'
                  b'garbage\r\n2026/10/01 0/0\r\n')
    days = importer.parse_file(str(f))
    assert days == {"2026-11-06": {"up": 20 * 1024 ** 2, "down": 500 * 1024 ** 2},
                    "2026-11-05": {"up": 10 * 1024 ** 2, "down": 2 * 1024 ** 3},
                    "2023-07-14": {"up": 0, "down": 3 * 1024 ** 3}}
    h = History.__new__(History)
    h.days = {"2026-11-06": {"up": 30 * 1024 ** 2, "down": 100}}
    h.dirty = False
    h.save = lambda: None
    added, updated = importer.merge(h, days)
    assert (added, updated) == (2, 1)
    # the larger figure wins on a day both programs counted
    assert h.days["2026-11-06"] == {"up": 30 * 1024 ** 2, "down": 500 * 1024 ** 2}
    assert importer.merge(h, days) == (0, 0)          # importing again changes nothing


# ------------------------------------------------------------------ temperatures
def test_lhm_parsing():
    def s(t, v):
        return {"Text": t, "Value": v, "SensorId": "/x", "Type": "Temperature",
                "ImageURL": "images/transparent.png", "Children": []}

    def g(t, img, ch):
        return {"Text": t, "ImageURL": img, "Children": ch}
    data = g("Sensor", "", [g("PC", "images_icon/computer.png", [
        g("CPU", "images_icon/cpu.png", [g("Temperatures", "", [
            s("Core #1", "50,0 °C"), s("Core #2", "58.0 °C"), s("CPU Package", "61.0 °C")])]),
        g("RTX", "images_icon/nvidia.png", [g("Temperatures", "", [s("GPU Core", "47.0 °C")])]),
    ])])
    sensors = parse_lhm_json(data)
    assert pick_temps(sensors, {"cpu_temp_mode": "auto"}) == {"cpu": 61.0, "gpu": 47.0}
    assert pick_temps(sensors, {"cpu_temp_mode": "average"})["cpu"] == 54.0


# ------------------------------------------------------------------ custom docks
def _hitodama_like(w=2000, h=52):
    """Busy dark-red background with a floating, slightly see-through dark dock."""
    img = Image.new("RGB", (w, h))
    px = img.load()
    for x in range(w):
        for y in range(h):
            # saturated reds of every brightness, like Hitodama's animated backdrop
            px[x, y] = (45 + (x * 13 + y * 7) % 160, (x * 3) % 10, (y + x) % 8)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((257, 3, 1335, 48), 12, fill=(22, 19, 20))
    for i in range(10):                                   # app icons on the dock
        d.rounded_rectangle((560 + i * 60, 10, 600 + i * 60, 42), 6,
                            fill=(80 + i * 15, 140, 220))
    d.rounded_rectangle((300, 9, 540, 43), 16, fill=(52, 52, 54))   # search box
    return img


def test_dock_found_on_custom_taskbar():
    found = dock.find_dock(_hitodama_like(), exclude=(1680, 1915))
    assert found is not None
    assert abs(found["left"] - 257) <= 3 and abs(found["right"] - 1335) <= 3
    assert found["top"] == 3 and found["bottom"] == 48


def test_own_window_does_not_split_or_fake_a_dock():
    found = dock.find_dock(_hitodama_like(), exclude=(700, 890))
    assert abs(found["right"] - 1335) <= 3
    plain = Image.new("RGB", (1280, 48), (32, 32, 32))
    d = ImageDraw.Draw(plain)
    d.rectangle((0, 0, 47, 47), fill=(42, 74, 122))
    d.rectangle((1080, 0, 1279, 47), fill=(58, 58, 58))
    assert dock.find_dock(plain, exclude=(890, 1078)) is None


@pytest.mark.parametrize("color", [(32, 32, 32), (243, 243, 243)])
def test_plain_taskbar_is_not_a_dock(color):
    img = Image.new("RGB", (1920, 48), color)
    d = ImageDraw.Draw(img)
    for i in range(10):
        d.rounded_rectangle((700 + i * 52, 6, 740 + i * 52, 42), 6, fill=(60 + i * 10, 120, 200))
    assert dock.find_dock(img) is None


# ------------------------------------------------------------------ taskbar placement
class _TB:
    def __init__(self, rect, vertical=False, na=None, primary=True):
        self.rect, self.vertical, self._na, self.primary, self.hwnd = rect, vertical, na, primary, None

    def notify_area(self):
        return self._na

    def child_rect(self, _):
        return None


def test_taskbar_slots():
    tb = _TB((0, 1040, 1920, 1080), na=(1700, 1040, 1920, 1080))
    assert win.compute_taskbar_slot(tb, 150, 40) == (1550, 1040, 150, 40)
    assert win.compute_taskbar_slot(tb, 150, 40, offset=10) == (1540, 1040, 150, 40)
    assert win.compute_taskbar_slot(tb, 150, 40, reserve=(200, 1040, 1700, 1080)) == \
        (1550, 1040, 150, 40)
    assert win.compute_taskbar_slot(tb, 150, 40, "left", reserve=(200, 1040, 1700, 1080)) == \
        (200, 1040, 150, 40)
    side = _TB((0, 0, 48, 1080), vertical=True, na=(0, 900, 48, 1080))
    x, y, w, h = win.compute_taskbar_slot(side, 48, 138)
    assert (x, w, h) == (0, 48, 138) and y + h <= 900
