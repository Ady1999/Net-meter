"""Import traffic history from TrafficMonitor.

TrafficMonitor saves it in a text file called history_traffic.dat:

    lines: "123"
    2026/11/06 10240/204800        <- date  upload_KB/download_KB
    2026/11/05 512                  <- older/"mixed" form: one total, in KB

The file is in %APPDATA%\\TrafficMonitor\\ or, in portable mode, next to
TrafficMonitor.exe.
"""

import glob
import os
import re
import subprocess
from datetime import date

from .config import IS_WIN, log

FILE_NAME = "history_traffic.dat"
LINE = re.compile(r"^\s*(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d+)(?:\s*/\s*(\d+))?")


def parse_file(path):
    """{ 'YYYY-MM-DD': {'up': bytes, 'down': bytes} } from a TrafficMonitor file."""
    days = {}
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = LINE.match(line)
            if not m:
                continue
            y, mo, d = int(m[1]), int(m[2]), int(m[3])
            try:
                key = date(y, mo, d).isoformat()
            except ValueError:
                continue
            if m[5] is not None:
                up, down = int(m[4]) * 1024, int(m[5]) * 1024
            else:                       # single value: upload+download together
                up, down = 0, int(m[4]) * 1024
            if up == 0 and down == 0:
                continue
            cur = days.setdefault(key, {"up": 0, "down": 0})
            # the same day can appear twice (today's line + history); keep the larger
            cur["up"] = max(cur["up"], up)
            cur["down"] = max(cur["down"], down)
    return days


def _exe_dirs():
    """Folders where TrafficMonitor.exe is (running, set to auto-start, or installed)."""
    dirs = []
    try:
        import psutil
        for p in psutil.process_iter(["name", "exe"]):
            if (p.info.get("name") or "").lower() == "trafficmonitor.exe" and p.info.get("exe"):
                dirs.append(os.path.dirname(p.info["exe"]))
    except Exception:
        pass
    if IS_WIN:
        import winreg
        # auto-start entry in the registry (Lite version / older versions)
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                    i = 0
                    while True:
                        name, val, _ = winreg.EnumValue(k, i)
                        i += 1
                        if "trafficmonitor" in f"{name} {val}".lower():
                            exe = re.findall(r'"([^"]+\.exe)"|(\S+\.exe)', val, re.I)
                            for a, b in exe:
                                dirs.append(os.path.dirname(a or b))
            except OSError:
                pass
        # auto-start scheduled task (full version 1.80+)
        try:
            out = subprocess.run(["schtasks", "/query", "/tn", "TrafficMonitor", "/xml"],
                                 capture_output=True, text=True, timeout=10,
                                 creationflags=0x08000000).stdout   # no console window
            for exe in re.findall(r"<Command>\s*\"?([^<\"]+)\"?\s*</Command>", out):
                dirs.append(os.path.dirname(exe))
        except Exception:
            pass
        # common install / unzip locations
        env = os.environ
        for base in (env.get("ProgramFiles"), env.get("ProgramFiles(x86)"),
                     os.path.join(env.get("LOCALAPPDATA", ""), "Programs"),
                     os.path.join(env.get("USERPROFILE", ""), "Downloads"),
                     os.path.join(env.get("USERPROFILE", ""), "Desktop"),
                     os.path.join(env.get("USERPROFILE", ""), "Documents"),
                     "C:\\", "D:\\"):
            if base and os.path.isdir(base):
                dirs += glob.glob(os.path.join(base, "TrafficMonitor*"))
                dirs += glob.glob(os.path.join(base, "TrafficMonitor*", "TrafficMonitor*"))
    return dirs


def find_files():
    """Every TrafficMonitor history file on this PC."""
    cands = []
    if IS_WIN:
        appdata = os.environ.get("APPDATA", "")
        cands.append(os.path.join(appdata, "TrafficMonitor", FILE_NAME))
    cands += [os.path.join(d, FILE_NAME) for d in _exe_dirs()]
    seen, out = set(), []
    for c in cands:
        n = os.path.normcase(os.path.abspath(c))
        if n not in seen and os.path.isfile(c):
            seen.add(n)
            out.append(c)
    return out


def merge(history, imported):
    """Add imported days to NetMeter's history.

    On a day both programs recorded, they were counting the same traffic at the
    same time, so the larger figure is kept rather than adding them up."""
    added = updated = 0
    for k, v in imported.items():
        cur = history.days.get(k)
        if cur is None:
            history.days[k] = {"up": v["up"], "down": v["down"]}
            added += 1
        else:
            new_up, new_down = max(cur["up"], v["up"]), max(cur["down"], v["down"])
            if (new_up, new_down) != (cur["up"], cur["down"]):
                cur["up"], cur["down"] = new_up, new_down
                updated += 1
    if added or updated:
        history.dirty = True
        history.save()
    return added, updated


def collect(paths=None):
    """Find and read the files (safe to run in a background thread)."""
    paths = paths if paths is not None else find_files()
    combined = {}
    for p in paths:
        try:
            for k, v in parse_file(p).items():
                c = combined.setdefault(k, {"up": 0, "down": 0})
                c["up"], c["down"] = max(c["up"], v["up"]), max(c["down"], v["down"])
        except OSError as e:
            log(f"could not read {p}: {e}")
    return paths, combined


def apply(history, paths, combined):
    """Merge what collect() found into the history (run on the UI thread)."""
    added, updated = merge(history, combined)
    total = sum(v["up"] + v["down"] for v in combined.values())
    first = min(combined) if combined else None
    log(f"TrafficMonitor import from {paths}: {len(combined)} days, "
        f"{added} added, {updated} updated")
    return {"files": paths, "days": len(combined), "added": added, "updated": updated,
            "bytes": total, "first": first}


def import_all(history, paths=None):
    return apply(history, *collect(paths))


def describe(r):
    from .render import fmt_size
    if not r["files"]:
        return "No TrafficMonitor history file was found."
    return (f"Read {r['days']} days of TrafficMonitor history "
            f"({fmt_size(r['bytes'])} in total, starting {r['first']}).\n"
            f"{r['added']} new day(s) added, {r['updated']} existing day(s) updated.\n\n"
            f"From: " + "\n      ".join(r["files"]))
