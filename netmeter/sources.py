"""Everything NetMeter measures: network, CPU, memory, GPU, disk, temperatures,
plus the daily traffic history."""

import json
import threading
import time
import urllib.request
from collections import deque
from datetime import date, timedelta

import psutil

from .config import HISTORY_FILE, IS_WIN, log, save_json

if IS_WIN:
    import ctypes
    from ctypes import wintypes


# --------------------------------------------------------------------------- network
VIRTUAL_HINTS = ("loopback", "vethernet", "virtualbox", "vmware", "hyper-v", "pseudo",
                 "teredo", "isatap", "bluetooth", "docker", "veth", "virbr", "npcap",
                 "wan miniport", "tap-", "tailscale", "zerotier", "ifb")


def is_virtual(name):
    low = name.lower()
    return low == "lo" or any(h in low for h in VIRTUAL_HINTS)


def all_adapters(include_virtual=True):
    names = sorted(psutil.net_if_stats().keys())
    return names if include_virtual else [n for n in names if not is_virtual(n)]


def auto_adapters():
    return [n for n, st in psutil.net_if_stats().items() if st.isup and not is_virtual(n)]


# --------------------------------------------------------------------------- Windows performance counters
class Pdh:
    """Minimal wrapper for Windows performance counters (what Task Manager uses)."""

    PDH_FMT_DOUBLE = 0x200
    PDH_FMT_NOCAP100 = 0x8000
    PDH_MORE_DATA = 0x800007D2

    def __init__(self):
        self.ok = False
        self.counters = {}
        if not IS_WIN:
            return
        try:
            self.pdh = ctypes.WinDLL("pdh")

            class VALUE(ctypes.Structure):
                _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]

            class ITEM(ctypes.Structure):
                _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", VALUE)]

            self.VALUE, self.ITEM = VALUE, ITEM
            p = self.pdh
            p.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                                        ctypes.POINTER(ctypes.c_void_p)]
            p.PdhOpenQueryW.restype = wintypes.DWORD
            p.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                                ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
            p.PdhAddEnglishCounterW.restype = wintypes.DWORD
            p.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
            p.PdhCollectQueryData.restype = wintypes.DWORD
            p.PdhGetFormattedCounterValue.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                                      ctypes.c_void_p, ctypes.POINTER(VALUE)]
            p.PdhGetFormattedCounterValue.restype = wintypes.DWORD
            p.PdhGetFormattedCounterArrayW.argtypes = [
                ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
            p.PdhGetFormattedCounterArrayW.restype = wintypes.DWORD
            self.query = ctypes.c_void_p()
            if p.PdhOpenQueryW(None, None, ctypes.byref(self.query)) != 0:
                return
            for key, path in (
                    ("cpu", r"\Processor Information(_Total)\% Processor Utility"),
                    ("cpu_perf", r"\Processor Information(_Total)\% Processor Performance"),
                    ("disk_idle", r"\PhysicalDisk(_Total)\% Idle Time"),
                    ("gpu", r"\GPU Engine(*)\Utilization Percentage")):
                h = ctypes.c_void_p()
                if p.PdhAddEnglishCounterW(self.query, path, None, ctypes.byref(h)) == 0:
                    self.counters[key] = h
                else:
                    log(f"performance counter not available: {path}")
            p.PdhCollectQueryData(self.query)
            self.ok = True
        except Exception as e:
            log(f"PDH unavailable: {e!r}")

    def collect(self):
        if self.ok:
            self.pdh.PdhCollectQueryData(self.query)

    def value(self, key):
        h = self.counters.get(key)
        if not h:
            return None
        v = self.VALUE()
        r = self.pdh.PdhGetFormattedCounterValue(
            h, self.PDH_FMT_DOUBLE | self.PDH_FMT_NOCAP100, None, ctypes.byref(v))
        if r != 0 or v.CStatus not in (0, 1):
            return None
        return v.doubleValue

    def array(self, key):
        h = self.counters.get(key)
        if not h:
            return {}
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        fmt = self.PDH_FMT_DOUBLE | self.PDH_FMT_NOCAP100
        r = self.pdh.PdhGetFormattedCounterArrayW(h, fmt, ctypes.byref(size),
                                                  ctypes.byref(count), None)
        if r != self.PDH_MORE_DATA or not size.value:
            return {}
        buf = ctypes.create_string_buffer(size.value)
        r = self.pdh.PdhGetFormattedCounterArrayW(h, fmt, ctypes.byref(size),
                                                  ctypes.byref(count), buf)
        if r != 0:
            return {}
        items = ctypes.cast(buf, ctypes.POINTER(self.ITEM))
        return {items[i].szName: items[i].FmtValue.doubleValue for i in range(count.value)}

    def gpu_usage(self):
        """Like Task Manager: busiest engine, summing every process using it."""
        per_engine = {}
        for name, val in self.array("gpu").items():
            # name looks like pid_123_luid_0x0_0x1_phys_0_eng_3_engtype_3D
            i = name.find("luid_")
            key = name[i:] if i >= 0 else name
            j = key.find("_engtype_")
            key = key[:j] if j >= 0 else key
            per_engine[key] = per_engine.get(key, 0.0) + val
        if not per_engine:
            return None
        return min(100.0, max(per_engine.values()))


# --------------------------------------------------------------------------- temperatures
TEMP_CATEGORIES = ("cpu", "gpu", "disk", "board")


def _category(text):
    t = (text or "").lower()
    if "cpu" in t:
        return "cpu"
    if any(k in t for k in ("nvidia", "ati", "amd", "gpu", "radeon", "intel")):
        return "gpu"
    if any(k in t for k in ("hdd", "ssd", "nvme", "storage", "disk")):
        return "disk"
    if any(k in t for k in ("mainboard", "chip", "motherboard", "superio")):
        return "board"
    return None


def parse_lhm_json(data):
    """LibreHardwareMonitor web server data.json -> [(category, hardware, sensor, °C)]."""
    out = []

    def walk(node, cat, hw, in_temps):
        img = node.get("ImageURL", "")
        text = node.get("Text", "")
        c = _category(img.rsplit("/", 1)[-1]) if img else None
        if c and not node.get("SensorId") and "transparent" not in img:
            cat, hw = c, text
        if text == "Temperatures":
            in_temps = True
        value = str(node.get("Value", ""))
        is_temp = node.get("Type") == "Temperature" or (in_temps and "°" in value)
        if is_temp and value and not node.get("Children"):
            try:
                v = float(value.replace("°C", "").replace("°F", "").replace(",", ".").strip())
                if cat:
                    out.append((cat, hw, text, v))
            except ValueError:
                pass
        for ch in node.get("Children", []) or []:
            walk(ch, cat, hw, in_temps)

    walk(data, None, "", False)
    return out


class TempReader(threading.Thread):
    """Reads temperatures every 2 s in the background so the UI never stalls."""

    def __init__(self, cfg):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.sensors = []
        self.error = ""
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()
        self._lhm = None

    def run(self):
        while not self.stop_flag.is_set():
            if self.cfg.get("hw_temps"):
                try:
                    s = self._read_dll() if self.cfg.get("temp_source") == "dll" else self._read_web()
                    with self.lock:
                        self.sensors, self.error = s, ""
                except Exception as e:
                    with self.lock:
                        self.sensors, self.error = [], str(e)
            self.stop_flag.wait(2)

    def _read_web(self):
        url = self.cfg.get("lhm_url") or "http://localhost:8085/data.json"
        # local address only: don't send this through any proxy
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=1.5) as r:
            return parse_lhm_json(json.load(r))

    def _read_dll(self):
        if self._lhm is None:
            import os
            from .config import DATA_DIR, PROGRAM_DIR
            import clr  # pythonnet
            for d in (PROGRAM_DIR, DATA_DIR):
                p = os.path.join(d, "LibreHardwareMonitorLib.dll")
                if os.path.exists(p):
                    clr.AddReference(p)
                    break
            else:
                raise RuntimeError("LibreHardwareMonitorLib.dll not found")
            from LibreHardwareMonitor.Hardware import Computer
            c = Computer()
            c.IsCpuEnabled = c.IsGpuEnabled = c.IsMotherboardEnabled = c.IsStorageEnabled = True
            c.Open()
            self._lhm = c
        out = []

        def visit(hw, cat):
            hw.Update()
            for s in hw.Sensors:
                if str(s.SensorType) == "Temperature" and s.Value is not None:
                    out.append((cat, str(hw.Name), str(s.Name), float(s.Value)))
            for sub in hw.SubHardware:
                visit(sub, cat)

        for hw in self._lhm.Hardware:
            t = str(hw.HardwareType).lower()
            cat = ("cpu" if t == "cpu" else "gpu" if t.startswith("gpu") else
                   "disk" if t == "storage" else "board" if t in ("motherboard", "superio")
                   else None)
            if cat:
                visit(hw, cat)
        return out

    def snapshot(self):
        with self.lock:
            return list(self.sensors), self.error


def pick_temps(sensors, cfg):
    """Choose one value per category from all the sensors."""
    res = {}
    by = {c: [s for s in sensors if s[0] == c] for c in TEMP_CATEGORIES}
    cpu = by["cpu"]
    if cpu:
        mode = cfg.get("cpu_temp_mode", "auto")
        cores = [s[3] for s in cpu if "core #" in s[2].lower() and "distance" not in s[2].lower()]
        if mode == "average" and cores:
            res["cpu"] = sum(cores) / len(cores)
        elif mode == "max":
            res["cpu"] = max(s[3] for s in cpu if "distance" not in s[2].lower())
        else:
            pref = ("cpu package", "core (tctl/tdie)", "tctl/tdie", "core (tctl)", "tctl",
                    "package", "cpu")
            best = None
            for p in pref:
                best = next((s for s in cpu if s[2].lower() == p), None) or best
                if best:
                    break
            res["cpu"] = (best or cpu[0])[3]
    gpu = by["gpu"]
    if gpu:
        best = next((s for s in gpu if s[2].lower() in ("gpu core", "gpu temperature")), gpu[0])
        res["gpu"] = best[3]
    disk = by["disk"]
    if disk:
        name = cfg.get("disk_name", "auto")
        pool = [s for s in disk if s[1] == name] if name != "auto" else disk
        pool = pool or disk
        best = next((s for s in pool if "composite" in s[2].lower() or s[2] == "Temperature"),
                    pool[0])
        res["disk"] = best[3]
    if by["board"]:
        res["board"] = by["board"][0][3]
    return res


# --------------------------------------------------------------------------- history
class History:
    def __init__(self):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                self.days = json.load(f)
        except (OSError, ValueError):
            self.days = {}
        self.dirty = False

    def add(self, up, down):
        if up <= 0 and down <= 0:
            return
        d = self.days.setdefault(date.today().isoformat(), {"up": 0, "down": 0})
        d["up"] += up
        d["down"] += down
        self.dirty = True

    def day(self, d):
        return self.days.get(d.isoformat(), {"up": 0, "down": 0})

    def today(self):
        return self.day(date.today())

    def period_start(self, start_day, today=None):
        """First day of the current 'month' when the month starts on start_day."""
        today = today or date.today()
        sd = max(1, min(28, int(start_day)))
        if today.day >= sd:
            return today.replace(day=sd)
        prev = today.replace(day=1) - timedelta(days=1)
        return prev.replace(day=sd)

    def total_since(self, start):
        up = down = 0
        for k, v in self.days.items():
            if k >= start.isoformat():
                up += v["up"]
                down += v["down"]
        return {"up": up, "down": down}

    def grouped(self, how):
        """how: day | week | month | quarter | year -> [(label, up, down)] newest first."""
        groups = {}
        for k, v in self.days.items():
            d = date.fromisoformat(k)
            if how == "day":
                key = k
            elif how == "week":
                y, w, _ = d.isocalendar()
                key = f"{y}-W{w:02d}"
            elif how == "month":
                key = k[:7]
            elif how == "quarter":
                key = f"{d.year}-Q{(d.month - 1) // 3 + 1}"
            else:
                key = str(d.year)
            g = groups.setdefault(key, [0, 0])
            g[0] += v["up"]
            g[1] += v["down"]
        return [(k, g[0], g[1]) for k, g in sorted(groups.items(), reverse=True)]

    def save(self):
        if self.dirty:
            save_json(HISTORY_FILE, self.days)
            self.dirty = False


# --------------------------------------------------------------------------- the monitor
class Monitor:
    """Collects one snapshot of everything per tick."""

    HIST = 120   # samples kept for graphs

    def __init__(self, cfg):
        self.cfg = cfg
        self.pdh = Pdh()
        self.temps = TempReader(cfg)
        self.temps.start()
        self.history = History()
        self.prev_net = None
        self.prev_t = None
        self.prev_disk = None
        self.start_counters = self._net_totals()
        self.start_time = time.time()
        self.series = {k: deque(maxlen=self.HIST) for k in
                       ("up", "down", "total", "cpu", "ram", "gpu", "disk")}
        psutil.cpu_percent(None)
        try:
            f = psutil.cpu_freq()
            self.base_mhz = f.max or f.current if f else None
        except Exception:
            self.base_mhz = None
        self.data = {}

    def adapters(self):
        if self.cfg.get("adapter_mode") == "selected" and self.cfg.get("adapters"):
            return list(self.cfg["adapters"])
        return auto_adapters()

    def _net_totals(self):
        c = psutil.net_io_counters(pernic=True)
        names = self.adapters()
        return (sum(c[n].bytes_sent for n in names if n in c),
                sum(c[n].bytes_recv for n in names if n in c))

    def reset_network(self):
        self.prev_net = None
        self.start_counters = self._net_totals()

    def sample(self):
        now = time.monotonic()
        sent, recv = self._net_totals()
        up = down = 0.0
        d_up = d_down = 0
        if self.prev_net is not None:
            dt = max(now - self.prev_t, 1e-3)
            d_up, d_down = sent - self.prev_net[0], recv - self.prev_net[1]
            if d_up < 0 or d_down < 0:     # adapter changed / counters reset
                d_up = d_down = 0
            up, down = d_up / dt, d_down / dt
        self.prev_net, self.prev_t = (sent, recv), now
        self.history.add(d_up, d_down)

        self.pdh.collect()
        src = self.cfg.get("cpu_source", "auto")
        cpu = None
        if src in ("auto", "pdh") and self.pdh.ok:
            cpu = self.pdh.value("cpu")
        cpu_ps = psutil.cpu_percent(None)
        cpu = min(100.0, cpu) if cpu is not None else cpu_ps

        vm = psutil.virtual_memory()
        gpu = self.pdh.gpu_usage() if self.pdh.ok else None

        disk = None
        if self.pdh.ok and self.pdh.value("disk_idle") is not None:
            disk = max(0.0, min(100.0, 100.0 - self.pdh.value("disk_idle")))
        else:
            try:
                io = psutil.disk_io_counters()
                bt = getattr(io, "busy_time", None)
                if bt is not None:
                    if self.prev_disk is not None:
                        disk = max(0.0, min(100.0, (bt - self.prev_disk[0]) /
                                            max((now - self.prev_disk[1]) * 1000, 1) * 100))
                    self.prev_disk = (bt, now)
            except Exception:
                pass

        freq = None
        perf = self.pdh.value("cpu_perf") if self.pdh.ok else None
        if perf is not None and self.base_mhz:
            freq = self.base_mhz * perf / 100.0
        else:
            try:
                f = psutil.cpu_freq()
                freq = f.current if f else None
            except Exception:
                pass

        temps = {}
        sensors, temp_err = [], ""
        if self.cfg.get("hw_temps"):
            sensors, temp_err = self.temps.snapshot()
            temps = pick_temps(sensors, self.cfg)
        elif not IS_WIN and hasattr(psutil, "sensors_temperatures"):
            try:
                st = psutil.sensors_temperatures()
                for k, lst in st.items():
                    if lst and "cpu" not in temps and k in ("coretemp", "k10temp", "cpu_thermal"):
                        temps["cpu"] = lst[0].current
            except Exception:
                pass

        today = self.history.today()
        month = self.history.total_since(self.history.period_start(
            self.cfg.get("month_start_day", 1)))
        self.data = {
            "up": up, "down": down, "total": up + down,
            "cpu": cpu, "ram": vm.percent, "ram_used": vm.used, "ram_total": vm.total,
            "ram_avail": vm.available, "gpu": gpu, "disk": disk, "cpu_freq": freq,
            "cpu_temp": temps.get("cpu"), "gpu_temp": temps.get("gpu"),
            "disk_temp": temps.get("disk"), "board_temp": temps.get("board"),
            "today": today["up"] + today["down"], "today_up": today["up"],
            "today_down": today["down"], "month_up": month["up"], "month_down": month["down"],
            "since_start_up": sent - self.start_counters[0],
            "since_start_down": recv - self.start_counters[1],
            "sensors": sensors, "temp_error": temp_err,
        }
        for k in self.series:
            v = self.data.get(k)
            self.series[k].append(v if v is not None else 0)
        return self.data

    def stop(self):
        self.temps.stop_flag.set()
        self.history.save()


def default_gateway():
    """IPv4 default gateway, or None."""
    try:
        if IS_WIN:
            class ROW(ctypes.Structure):
                _fields_ = [(n, wintypes.DWORD) for n in (
                    "dest", "mask", "policy", "next_hop", "if_index", "type", "proto",
                    "age", "next_hop_as", "m1", "m2", "m3", "m4", "m5")]
            row = ROW()
            dest = int.from_bytes(bytes([8, 8, 8, 8]), "little")
            if ctypes.windll.iphlpapi.GetBestRoute(wintypes.DWORD(dest), 0,
                                                   ctypes.byref(row)) == 0:
                b = row.next_hop.to_bytes(4, "little")
                if any(b):
                    return ".".join(str(x) for x in b)
            return None
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                p = line.split()
                if p[1] == "00000000" and p[2] != "00000000":
                    b = bytes.fromhex(p[2])[::-1]
                    return ".".join(str(x) for x in b)
    except Exception:
        return None
    return None
