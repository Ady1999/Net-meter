"""The controller: owns the settings, the monitor, the windows and the menus."""

import copy
import os
import queue
import time
import tkinter as tk
import traceback
from datetime import date

from . import dialogs, win
from .config import APP_NAME, DATA_DIR, IS_WIN, ITEMS, load_config, log, save_config
from .plugins import PluginManager
from .render import fmt_size, fmt_speed
from .sources import Monitor, all_adapters
from .tray import Tray
from .windows import MainWindow, TaskbarWindow, Toast

SHOW_FLAG = os.path.join(DATA_DIR, "show.flag")


class App:
    def __init__(self, startup=False, self_test=None):
        self.self_test = self_test
        win.set_dpi_aware()
        self.cfg = load_config()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.root.report_callback_exception = self._tk_error
        self.root.protocol("WM_SAVE_YOURSELF", self.save_all)   # Windows sign-out
        self.commands = queue.Queue()
        self.monitor = Monitor(self.cfg)
        self.plugins = PluginManager()
        self.tray = None
        self.main = None
        self.taskbar = None
        self.started = False
        self.last_history_save = time.monotonic()
        self._options = None

        if win.autostart_enabled():          # keep the startup entry pointing at us
            try:
                win.set_autostart(True)
            except OSError as e:
                log(f"could not refresh startup entry: {e}")

        delay = int(self.cfg.get("startup_delay_s", 8)) if startup else 0
        log(f"starting {APP_NAME} (startup={startup}, delay={delay}s)")
        self.root.after(delay * 1000, self.start)
        self.root.after(150, self._process_commands)

    # =================================================================== lifecycle
    def start(self):
        self.monitor.sample()
        self._sync_tray()
        self._ensure_something_visible()
        if self.cfg["main"]["show"]:
            self._create_main()
        if self.cfg["taskbar"]["show"]:
            self._attach_taskbar()
        self.started = True
        if self.self_test:
            self.root.after(12000, self._write_self_test)
        elif not self.cfg.get("tm_import_done"):
            self.root.after(3000, self.auto_import)
        self.root.after(300, self.tick)
        self.root.after(2000, self.housekeeping)
        # right after sign-in other programs may still be grabbing the screen
        for ms in (2000, 6000, 15000):
            self.root.after(ms, self._reassert)

    def _create_main(self):
        if self.main is None:
            self.main = MainWindow(self)
            self.main.show()

    def _attach_taskbar(self, tries=0):
        if not self.cfg["taskbar"]["show"]:
            return
        if self.taskbar is not None and self.taskbar.attached:
            return
        if self.taskbar is None:
            self.taskbar = TaskbarWindow(self)
        try:
            ok = self.taskbar.attach()
        except Exception:
            log("taskbar attach error: " + traceback.format_exc())
            ok = False
        if ok:
            return
        self.taskbar.destroy()
        self.taskbar = None
        if tries < 30:            # the taskbar can take a while to appear after sign-in
            self.root.after(2000, lambda: self._attach_taskbar(tries + 1))
        else:
            log("gave up waiting for the taskbar; showing the floating window instead")
            self.notify("Taskbar not found",
                        "NetMeter couldn't attach to the taskbar, so it's showing the "
                        "floating window instead.")
            self.cfg["main"]["show"] = True
            self._create_main()

    def _rebuild_taskbar(self):
        log("rebuilding taskbar window (Explorer restarted or taskbar changed)")
        if self.taskbar:
            self.taskbar.destroy()
            self.taskbar = None
        self.root.after(1500, self._attach_taskbar)

    def _sync_tray(self):
        want = self.cfg.get("tray_icon", True) or not (self.cfg["main"]["show"] or
                                                       self.cfg["taskbar"]["show"])
        if want and not self.tray:
            self.tray = Tray(self)
            if not self.tray.available:
                self.tray = None
        elif not want and self.tray:
            self.tray.stop()
            self.tray = None

    def _ensure_something_visible(self):
        if not self.tray and not self.cfg["main"]["show"] and not self.cfg["taskbar"]["show"]:
            self.cfg["main"]["show"] = True

    # =================================================================== loops
    def tick(self):
        try:
            data = self.monitor.sample()
            self.plugins.update()
            for w in (self.main, self.taskbar):
                if w:
                    try:
                        w.refresh(data)
                        w.tooltip.refresh()
                    except tk.TclError as e:
                        log(f"refresh failed: {e}")
                        if w is self.taskbar:
                            self.root.after(0, self._rebuild_taskbar)
            if self.tray:
                self.tray.set_tooltip(
                    f"{APP_NAME}\n↑ {fmt_speed(data['up'], {})}   ↓ {fmt_speed(data['down'], {})}"
                    f"\nCPU {data['cpu']:.0f}%   RAM {data['ram']:.0f}%")
            self._check_alerts(data)
            if time.monotonic() - self.last_history_save > 60:
                self.monitor.history.save()
                self.last_history_save = time.monotonic()
        except Exception:
            log("tick error: " + traceback.format_exc())
        self.root.after(max(250, int(self.cfg.get("interval_ms", 1000))), self.tick)

    def housekeeping(self):
        try:
            if self.taskbar and not self.taskbar.check():
                self._rebuild_taskbar()
            if self.main:
                if self.cfg["main"].get("hide_fullscreen", True):
                    self.main.set_fullscreen_hidden(win.fullscreen_app_running())
                self.main.reassert()
            if os.path.exists(SHOW_FLAG):        # someone started NetMeter a second time
                try:
                    os.remove(SHOW_FLAG)
                except OSError:
                    pass
                self._show_something()
        except Exception:
            log("housekeeping error: " + traceback.format_exc())
        self.root.after(2000, self.housekeeping)

    def _reassert(self):
        if self.main:
            self.main.place()
            self.main.win.deiconify()
            self.main.reassert()
        if self.taskbar:
            self.taskbar.last_slot = None
            self.taskbar.position()

    def _show_something(self):
        if self.cfg["taskbar"]["show"] and self.taskbar:
            self.taskbar.last_slot = None
            self.taskbar.position()
        if not self.cfg["main"]["show"] and not self.cfg["taskbar"]["show"]:
            self.toggle_main()
        elif self.main:
            self.main.win.deiconify()
            self.main.win.lift()

    # =================================================================== TrafficMonitor import
    def auto_import(self):
        """First run: quietly bring over TrafficMonitor's history if it's on this PC."""
        import threading
        from . import importer

        def work():
            try:
                found = importer.collect()
            except Exception:
                log("import search failed: " + traceback.format_exc())
                found = ([], {})
            self.root.after(0, lambda: finish(*found))

        def finish(paths, combined):
            self.cfg["tm_import_done"] = True
            self.save()
            if paths:
                r = importer.apply(self.monitor.history, paths, combined)
                self.notify("TrafficMonitor history imported",
                            f"{r['days']} days ({fmt_size(r['bytes'])}) since {r['first']}. "
                            f"See Traffic history.")
        threading.Thread(target=work, daemon=True).start()

    def import_trafficmonitor(self, parent=None):
        """Manual import (button in Traffic history / Options)."""
        from tkinter import filedialog, messagebox
        from . import importer
        r = importer.import_all(self.monitor.history)
        if not r["files"]:
            if not messagebox.askyesno(
                    APP_NAME, "TrafficMonitor's history file wasn't found automatically.\n\n"
                    "It's called history_traffic.dat and is usually in the TrafficMonitor "
                    "folder or in %APPDATA%\\TrafficMonitor.\n\nFind it yourself?",
                    parent=parent):
                return None
            path = filedialog.askopenfilename(
                parent=parent, title="Find TrafficMonitor's history_traffic.dat",
                filetypes=[("TrafficMonitor history", "history_traffic*.dat"),
                           ("All files", "*.*")])
            if not path:
                return None
            r = importer.import_all(self.monitor.history, [path])
            if not r["days"]:
                messagebox.showwarning(APP_NAME, "That file doesn't contain any "
                                       "TrafficMonitor history.", parent=parent)
                return r
        self.cfg["tm_import_done"] = True
        self.save()
        messagebox.showinfo(APP_NAME, importer.describe(r), parent=parent)
        return r

    # =================================================================== settings
    def save(self):
        save_config(self.cfg)

    def save_all(self):
        self.monitor.history.save()
        self.save()

    def apply_config(self, new):
        """Replace the settings (from the options dialog) and rebuild what's needed."""
        new = copy.deepcopy(new)      # may be self.cfg itself
        new["alert_state"] = self.cfg.get("alert_state", {})
        old_adapters = (self.cfg.get("adapter_mode"), list(self.cfg.get("adapters", [])))
        self.cfg.clear()
        self.cfg.update(new)          # same dict object: tray & monitor see the change
        if (self.cfg.get("adapter_mode"), self.cfg.get("adapters")) != old_adapters:
            self.monitor.reset_network()
        self._sync_tray()
        self._ensure_something_visible()
        if self.main:
            self.main.destroy()
            self.main = None
        if self.taskbar:
            self.taskbar.destroy()
            self.taskbar = None
        if self.cfg["main"]["show"]:
            self._create_main()
        if self.cfg["taskbar"]["show"]:
            self._attach_taskbar()
        if self.tray:
            self.tray.refresh_menu()
        self.save()

    # =================================================================== commands from tray
    def post(self, cmd):
        self.commands.put(cmd)

    def _process_commands(self):
        try:
            while True:
                cmd = self.commands.get_nowait()
                handler = {
                    "toggle_main": self.toggle_main, "toggle_taskbar": self.toggle_taskbar,
                    "toggle_click_through": self.toggle_click_through,
                    "recenter": self.recenter, "history": self.open_history,
                    "details": self.open_details, "options": self.open_options,
                    "quit": self.quit,
                }.get(cmd)
                if handler:
                    handler()
                if cmd == "quit":
                    return
        except queue.Empty:
            pass
        except Exception:
            log("command error: " + traceback.format_exc())
        self.root.after(150, self._process_commands)

    # =================================================================== actions
    def toggle_main(self):
        m = self.cfg["main"]
        m["show"] = not m["show"]
        if not m["show"] and not self.cfg["taskbar"]["show"] and not self.tray:
            m["show"] = True        # never hide the last way back in
        if m["show"]:
            self._create_main()
        elif self.main:
            self.main.destroy()
            self.main = None
        self._after_toggle()

    def toggle_taskbar(self):
        t = self.cfg["taskbar"]
        t["show"] = not t["show"]
        if not t["show"] and not self.cfg["main"]["show"] and not self.tray:
            t["show"] = True
        if t["show"]:
            self._attach_taskbar()
        elif self.taskbar:
            self.taskbar.destroy()
            self.taskbar = None
        self._after_toggle()

    def _after_toggle(self):
        self._sync_tray()
        if self.tray:
            self.tray.refresh_menu()
        self.save()

    def toggle_click_through(self):
        m = self.cfg["main"]
        if not m["click_through"] and not self.tray:
            self.notify(APP_NAME, "Click-through needs the tray icon to turn it back off. "
                        "Turn on the tray icon in Options first.")
            return
        m["click_through"] = not m["click_through"]
        if self.main:
            self.main.apply_window_flags()
        self._after_toggle()

    def set_main_flag(self, key, value):
        self.cfg["main"][key] = value
        if self.main:
            if key in ("more_info",):
                self.main.painter.width_memory.clear()
            self.main.apply_window_flags()
            self.main.refresh(self.monitor.data)
        self.save()

    def set_taskbar_position(self, value):
        t = self.cfg["taskbar"]
        t["position"] = value
        if value == "free" and t.get("free_x") is None and self.taskbar and \
                self.taskbar.last_slot:
            t["free_x"] = self.taskbar.last_slot[0] - self.taskbar.tb.rect[0]
        if self.taskbar:
            self.taskbar.update_dock(force=True)
            self.taskbar.last_slot = None
            self.taskbar.refresh(self.monitor.data or {})
        self.save()

    def recenter(self):
        self.cfg["main"]["x"] = self.cfg["main"]["y"] = None
        if not self.cfg["main"]["show"]:
            self.toggle_main()
        elif self.main:
            self.main.place()
            self.main.win.deiconify()
        self.save()

    def select_adapter(self, name):
        if name == "auto":
            self.cfg["adapter_mode"] = "auto"
        else:
            self.cfg["adapter_mode"] = "selected"
            self.cfg["adapters"] = [name]
        self.monitor.reset_network()
        self.save()

    def open_history(self):
        dialogs.HistoryDialog(self)

    def open_details(self):
        dialogs.DetailsDialog(self)

    def open_options(self, tab=0):
        if self._options:
            try:
                self._options.w.lift()
                self._options.nb.select(tab)
                return
            except tk.TclError:
                pass
        self._options = dialogs.OptionsDialog(self, tab)

    def open_skins(self):
        dialogs.SkinDialog(self)

    def double_click(self, wcfg, item_id=None):
        if item_id and item_id.startswith("p:") and self.plugins.double_click(item_id):
            return
        action = wcfg.get("double_click", "details")
        if action == "details":
            self.open_details()
        elif action == "history":
            self.open_history()
        elif action == "options":
            self.open_options()
        elif action == "taskmgr":
            win.open_task_manager()
        elif action == "skin":
            self.open_skins()
        elif action == "toggle_more":
            self.set_main_flag("more_info", not self.cfg["main"].get("more_info", True))
        elif action == "app" and wcfg.get("double_click_app"):
            win.open_path(wcfg["double_click_app"])

    def quit(self):
        log("exiting")
        self.save_all()
        for w in (self.main, self.taskbar):
            if w:
                w.destroy()
        if self.tray:
            self.tray.stop()
        self.monitor.stop()
        self.root.destroy()

    # =================================================================== menus
    def popup_menu(self, kind, event):
        m = tk.Menu(self.root, tearoff=0)
        self._menu_vars = []

        def check(menu, label, value, cmd):
            v = tk.BooleanVar(value=value)
            self._menu_vars.append(v)
            menu.add_checkbutton(label=label, variable=v, command=cmd)

        net = tk.Menu(m, tearoff=0)
        cur = "auto" if self.cfg.get("adapter_mode") == "auto" else \
            (self.cfg.get("adapters") or ["auto"])[0]
        sel = tk.StringVar(value=cur)
        self._menu_vars.append(sel)
        net.add_radiobutton(label="Automatic", value="auto", variable=sel,
                            command=lambda: self.select_adapter("auto"))
        net.add_separator()
        for n in all_adapters(self.cfg.get("show_all_adapters", False)):
            net.add_radiobutton(label=n, value=n, variable=sel,
                                command=lambda n=n: self.select_adapter(n))
        m.add_cascade(label="Network connection", menu=net)
        m.add_separator()

        mc = self.cfg["main"]
        if kind == "main":
            check(m, "Always on top", mc["topmost"],
                  lambda: self.set_main_flag("topmost", not mc["topmost"]))
            check(m, "Clicks pass through", mc["click_through"], self.toggle_click_through)
            check(m, "Lock position", mc["locked"],
                  lambda: self.set_main_flag("locked", not mc["locked"]))
            check(m, "Show more info", mc.get("more_info", True),
                  lambda: self.set_main_flag("more_info", not mc.get("more_info", True)))
            op = tk.Menu(m, tearoff=0)
            ov = tk.DoubleVar(value=round(mc.get("opacity", 0.92), 1))
            self._menu_vars.append(ov)
            for pct in (100, 90, 80, 70, 60, 50, 40):
                op.add_radiobutton(label=f"{pct}%", value=pct / 100, variable=ov,
                                   command=lambda p=pct: self.set_main_flag("opacity", p / 100))
            m.add_cascade(label="Opacity", menu=op)
            m.add_command(label="Change skin…", command=self.open_skins)
            m.add_separator()
        check(m, "Show floating window", mc["show"], self.toggle_main)
        check(m, "Show taskbar window", self.cfg["taskbar"]["show"], self.toggle_taskbar)
        if kind == "taskbar":
            pos = tk.Menu(m, tearoff=0)
            pv = tk.StringVar(value=self.cfg["taskbar"].get("position", "auto"))
            self._menu_vars.append(pv)
            for value, label in (("auto", "Automatic (after a custom taskbar's dock, "
                                          "otherwise next to the clock)"),
                                 ("dock", "After the custom dock (e.g. Hitodama)"),
                                 ("right", "Next to the clock"),
                                 ("left", "Left end of the taskbar"),
                                 ("free", "Where I drag it")):
                pos.add_radiobutton(label=label, value=value, variable=pv,
                                    command=lambda v=value: self.set_taskbar_position(v))
            pos.add_separator()
            pos.add_command(label="Tip: drag the stats along the taskbar to place them",
                            state="disabled")
            m.add_cascade(label="Position", menu=pos)
            m.add_command(label="Items to show / look…", command=lambda: self.open_options(1))
        m.add_separator()
        m.add_command(label="Traffic history…", command=self.open_history)
        m.add_command(label="Connection details…", command=self.open_details)
        m.add_command(label="Task Manager", command=win.open_task_manager)
        m.add_separator()
        m.add_command(label="Options…",
                      command=lambda: self.open_options(1 if kind == "taskbar" else 2))
        m.add_command(label="About", command=lambda: dialogs.about(self))
        m.add_command(label="Exit", command=self.quit)
        # the menu only closes on an outside click if one of our windows is in front
        if kind == "main" and self.main:
            win.foreground(self.main.hwnd)
        elif IS_WIN:
            win.foreground(win.toplevel_hwnd(self.root))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    # =================================================================== tooltip
    def tooltip_text(self):
        d = self.monitor.data or {}
        f = self.cfg["taskbar"]["fmt"]
        lines = [f"Upload: {fmt_speed(d.get('up'), f)}    Download: {fmt_speed(d.get('down'), f)}",
                 f"Today: ↑ {fmt_size(d.get('today_up'))}  ↓ {fmt_size(d.get('today_down'))}"
                 f"  (total {fmt_size(d.get('today'))})",
                 f"This month: {fmt_size((d.get('month_up') or 0) + (d.get('month_down') or 0))}"]
        if d.get("cpu") is not None:
            lines.append(f"CPU: {d['cpu']:.0f}%" + (f"   {d['cpu_freq'] / 1000:.2f} GHz"
                                                    if d.get("cpu_freq") else ""))
        if d.get("ram_total"):
            lines.append(f"Memory: {fmt_size(d['ram_used'])} / {fmt_size(d['ram_total'])}"
                         f"  ({d['ram']:.0f}%)")
        if d.get("gpu") is not None:
            lines.append(f"GPU: {d['gpu']:.0f}%")
        if d.get("disk") is not None:
            lines.append(f"Disk: {d['disk']:.0f}%")
        temps = [f"{ITEMS[k][0].replace(' temperature', '')} {d[k]:.0f}°C"
                 for k in ("cpu_temp", "gpu_temp", "disk_temp", "board_temp")
                 if d.get(k) is not None]
        if temps:
            lines.append("Temperatures: " + ", ".join(temps))
        lines += self.plugins.tooltips()
        return "\n".join(lines)

    # =================================================================== alerts
    def notify(self, title, msg):
        log(f"notify: {title}: {msg}")
        if not (self.tray and self.tray.notify(title, msg)):
            Toast(self.root, title, msg)

    def _check_alerts(self, d):
        a, st = self.cfg["alerts"], self.cfg.setdefault("alert_state", {})
        today = date.today().isoformat()
        period = self.monitor.history.period_start(self.cfg.get("month_start_day", 1)).isoformat()
        MB, GB = 1024 ** 2, 1024 ** 3
        changed = False
        if a["today_traffic"]["on"] and d["today"] > a["today_traffic"]["value"] * MB \
                and st.get("today_traffic") != today:
            st["today_traffic"] = today
            changed = True
            self.notify("Daily traffic limit",
                        f"You've used {fmt_size(d['today'])} today "
                        f"(limit {a['today_traffic']['value']} MB).")
        month_total = d["month_up"] + d["month_down"]
        if a["month_traffic"]["on"] and month_total > a["month_traffic"]["value"] * GB \
                and st.get("month_traffic") != period:
            st["month_traffic"] = period
            changed = True
            self.notify("Monthly traffic limit",
                        f"You've used {fmt_size(month_total)} this month "
                        f"(limit {a['month_traffic']['value']} GB).")
        for key, val, unit, name in (("memory", d.get("ram"), "%", "Memory usage"),
                                     ("cpu", d.get("cpu"), "%", "CPU usage"),
                                     ("cpu_temp", d.get("cpu_temp"), "°C", "CPU temperature"),
                                     ("gpu_temp", d.get("gpu_temp"), "°C", "GPU temperature"),
                                     ("disk_temp", d.get("disk_temp"), "°C", "Disk temperature"),
                                     ("board_temp", d.get("board_temp"), "°C",
                                      "Mainboard temperature")):
            rule = a[key]
            if not rule["on"] or val is None:
                continue
            fired = st.get(key, False)
            if val > rule["value"] and not fired:
                st[key] = True
                changed = True
                self.notify(f"{name} high", f"{name} is {val:.0f}{unit} "
                            f"(limit {rule['value']}{unit}).")
            elif val < rule["value"] - 5 and fired:
                st[key] = False
                changed = True
        if changed:
            self.save()

    # =================================================================== self-test
    def _write_self_test(self):
        """--self-test REPORT.json: run normally for a few seconds, write down what
        happened (used by the automatic Windows build to check the real thing), quit."""
        import json
        import sys
        from .config import LOG_FILE, VERSION
        rep = {"version": VERSION, "windows_build": win.windows_build(),
               "win11": win.is_win11(), "frozen": bool(getattr(sys, "frozen", False))}
        try:
            rep["taskbars"] = [{"class": win.class_name(t.hwnd) if IS_WIN else "fake",
                                "rect": t.rect, "primary": t.primary, "vertical": t.vertical,
                                "edge": t.edge, "notify_area": t.notify_area()}
                               for t in win.find_taskbars()]
        except Exception as e:
            rep["taskbars"] = f"error: {e!r}"
        tw = self.taskbar
        if tw:
            rep["taskbar_window"] = {
                "attached": tw.attached, "embedded": tw.embedded, "slot": tw.last_slot,
                "actual_rect": tw._actual_rect(), "size": tw.size, "fit": tw.fit_note,
                "dock": tw.dock, "squeeze": bool(tw.squeeze),
                "parent_class": (win.class_name(win.parent_of(tw.hwnd))
                                 if IS_WIN and tw.hwnd and win.parent_of(tw.hwnd) else None)}
        else:
            rep["taskbar_window"] = None
        d = self.monitor.data or {}
        rep["data"] = {k: d.get(k) for k in ("up", "down", "cpu", "ram", "gpu", "disk",
                                            "cpu_freq", "today")}
        rep["pdh_counters"] = sorted(self.monitor.pdh.counters) if self.monitor.pdh.ok else []
        rep["tray_icon"] = bool(self.tray)
        markers = ("tick error", "UI error", "housekeeping error", "fatal", "refresh failed",
                   "command error", "attach error", "Traceback")
        try:
            with open(LOG_FILE, encoding="utf-8") as f:
                rep["errors"] = [ln.rstrip() for ln in f if any(m in ln for m in markers)]
        except OSError:
            rep["errors"] = []
        # a picture of the taskbar area, saved next to the report
        try:
            from PIL import ImageGrab
            bars = win.find_taskbars()
            if bars:
                img = ImageGrab.grab(bbox=bars[0].rect, all_screens=True,
                                     include_layered_windows=True)
                img.save(os.path.splitext(self.self_test)[0] + ".png")
        except Exception as e:
            rep["screenshot_error"] = repr(e)
        with open(self.self_test, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2, default=str)
        self.quit()

    # =================================================================== errors
    def _tk_error(self, exc, val, tb):
        log("UI error: " + "".join(traceback.format_exception(exc, val, tb)))

    def run(self):
        self.root.mainloop()


def main(argv):
    startup = "--startup" in argv
    self_test = None
    if "--self-test" in argv:
        i = argv.index("--self-test")
        self_test = os.path.abspath(argv[i + 1] if i + 1 < len(argv) else "self-test.json")
    lock = win.single_instance_lock()
    if lock is None:
        # already running: ask that copy to show itself, then leave
        try:
            open(SHOW_FLAG, "w").close()
        except OSError:
            pass
        log("already running; asked the running copy to show itself")
        return
    try:
        App(startup=startup, self_test=self_test).run()
    except Exception:
        log("fatal: " + traceback.format_exc())
        raise
