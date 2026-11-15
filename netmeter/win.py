"""Thin wrappers around the Windows API (taskbar embedding, theme, autostart ...).

Every function here is safe to call on other systems: it just does nothing useful.
"""

import os
import sys

from .config import APP_NAME, IS_WIN, log

if IS_WIN:
    import ctypes
    import winreg
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32")

    HWND = wintypes.HWND

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                    ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = HWND
    user32.FindWindowExW.argtypes = [HWND, HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowExW.restype = HWND
    user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(RECT)]
    user32.GetClientRect.argtypes = [HWND, ctypes.POINTER(RECT)]
    user32.IsWindow.argtypes = [HWND]
    user32.IsWindowVisible.argtypes = [HWND]
    user32.GetParent.argtypes = [HWND]
    user32.GetParent.restype = HWND
    user32.GetAncestor.argtypes = [HWND, wintypes.UINT]
    user32.GetAncestor.restype = HWND
    user32.SetParent.argtypes = [HWND, HWND]
    user32.SetParent.restype = HWND
    user32.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.MoveWindow.argtypes = [HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, wintypes.BOOL]
    user32.ScreenToClient.argtypes = [HWND, ctypes.POINTER(POINT)]
    user32.GetWindowLongW.argtypes = [HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.GetForegroundWindow.restype = HWND
    user32.SetForegroundWindow.argtypes = [HWND]
    user32.GetClassNameW.argtypes = [HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.MonitorFromWindow.argtypes = [HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    user32.GetDC.argtypes = [HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [HWND, wintypes.HDC]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    if hasattr(user32, "GetDpiForWindow"):
        user32.GetDpiForWindow.argtypes = [HWND]
    gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.GetPixel.restype = wintypes.DWORD
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CHILD, WS_POPUP = 0x40000000, 0x80000000
WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = 0x80, 0x40000
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE = 0x80000, 0x20, 0x08000000
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_SHOWWINDOW = 1, 2, 4, 0x10, 0x40
HWND_TOPMOST = -1


# --------------------------------------------------------------------------- basics
def rect_of(hwnd):
    if not IS_WIN or not hwnd:
        return None
    r = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return r.left, r.top, r.right, r.bottom


def class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def windows_build():
    if not IS_WIN:
        return 0
    try:
        return sys.getwindowsversion().build
    except Exception:
        return 0


def is_win11():
    return windows_build() >= 22000


def set_dpi_aware():
    if not IS_WIN:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def toplevel_hwnd(tk_widget):
    """The real Win32 window of a Tk toplevel (Tk wraps it in a frame window)."""
    if not IS_WIN:
        return 0
    tk_widget.update_idletasks()
    inner = tk_widget.winfo_id()
    parent = user32.GetParent(inner)
    return parent or inner


def set_exstyle(hwnd, add=0, remove=0):
    if not IS_WIN or not hwnd:
        return
    s = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (s | add) & ~remove)


def set_tool_window(hwnd):
    set_exstyle(hwnd, add=WS_EX_TOOLWINDOW, remove=WS_EX_APPWINDOW)


def set_click_through(hwnd, enable):
    if enable:
        set_exstyle(hwnd, add=WS_EX_LAYERED | WS_EX_TRANSPARENT)
    else:
        set_exstyle(hwnd, remove=WS_EX_TRANSPARENT)


def force_topmost(hwnd):
    if IS_WIN and hwnd:
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def foreground(hwnd):
    if IS_WIN and hwnd:
        try:
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass


def cursor_pos():
    if not IS_WIN:
        return None
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def virtual_screen():
    """(left, top, width, height) covering every monitor, or None."""
    if not IS_WIN:
        return None
    g = user32.GetSystemMetrics
    return g(76), g(77), g(78), g(79)


def monitor_rect_at(x, y, work=False):
    if not IS_WIN:
        return None
    mon = user32.MonitorFromPoint(POINT(int(x), int(y)), 2)  # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        return None
    r = mi.rcWork if work else mi.rcMonitor
    return r.left, r.top, r.right, r.bottom


def screen_pixel(x, y):
    """Colour of one pixel on screen as '#rrggbb', or None."""
    if not IS_WIN:
        return None
    hdc = user32.GetDC(None)
    try:
        c = gdi32.GetPixel(hdc, int(x), int(y))
    finally:
        user32.ReleaseDC(None, hdc)
    if c == 0xFFFFFFFF:
        return None
    return "#%02x%02x%02x" % (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF)


# --------------------------------------------------------------------------- theme / fullscreen
def windows_uses_light_taskbar():
    if not IS_WIN:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "SystemUsesLightTheme")[0])
    except OSError:
        return False


def widgets_enabled():
    """Windows 11 weather/widgets button on the left of the taskbar."""
    if not is_win11():
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced") as k:
            return winreg.QueryValueEx(k, "TaskbarDa")[0] != 0
    except OSError:
        return True   # on by default


def taskbar_center_aligned():
    if not is_win11():
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced") as k:
            return winreg.QueryValueEx(k, "TaskbarAl")[0] != 0
    except OSError:
        return True   # default on Windows 11 is centred


def fullscreen_app_running():
    """True when the foreground window covers its whole monitor (game, video ...)."""
    if not IS_WIN:
        return False
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    if class_name(hwnd) in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
        return False
    r = rect_of(hwnd)
    if not r:
        return False
    m = monitor_rect_at((r[0] + r[2]) // 2, (r[1] + r[3]) // 2)
    return bool(m) and r[0] <= m[0] and r[1] <= m[1] and r[2] >= m[2] and r[3] >= m[3]


# --------------------------------------------------------------------------- taskbar
class TaskbarInfo:
    """Where a taskbar is and where there is room for our window."""

    def __init__(self, hwnd, primary):
        self.hwnd = hwnd
        self.primary = primary
        self.rect = rect_of(hwnd)
        l, t, r, b = self.rect
        self.vertical = (b - t) > (r - l)
        self.edge = self._edge()

    def _edge(self):
        l, t, r, b = self.rect
        m = monitor_rect_at((l + r) // 2, (t + b) // 2) or self.rect
        if self.vertical:
            return "left" if abs(l - m[0]) <= abs(m[2] - r) else "right"
        return "top" if abs(t - m[1]) <= abs(m[3] - b) else "bottom"

    def child_rect(self, cls):
        if not self.hwnd:
            return None
        h = user32.FindWindowExW(self.hwnd, None, cls, None)
        r = rect_of(h) if h else None
        if r and r[2] > r[0] and r[3] > r[1]:
            return r
        return None

    def notify_area(self):
        """Screen rectangle of the clock / tray icon area, if Windows tells us."""
        r = self.child_rect("TrayNotifyWnd")
        if r and self.contains(r):
            return r
        # secondary taskbars on Windows 10/11 have a clock window of their own
        h = user32.FindWindowExW(self.hwnd, None, "ClockButton", None) if self.hwnd else None
        r = rect_of(h) if h else None
        if r and r[2] > r[0] and self.contains(r):
            return r
        return None

    def contains(self, r):
        l, t, rr, b = self.rect
        return r[0] >= l - 2 and r[2] <= rr + 2 and r[1] >= t - 2 and r[3] <= b + 2


def find_taskbars():
    """[primary taskbar, secondary taskbars...] as TaskbarInfo objects."""
    if not IS_WIN:
        return []
    out = []
    main = user32.FindWindowW("Shell_TrayWnd", None)
    if main and rect_of(main):
        out.append(TaskbarInfo(main, True))
    found = []

    @WNDENUMPROC
    def cb(hwnd, _):
        if class_name(hwnd) == "Shell_SecondaryTrayWnd" and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True
    try:
        user32.EnumWindows(cb, 0)
    except Exception as e:
        log(f"EnumWindows failed: {e}")
    found.sort(key=lambda h: (rect_of(h) or (0, 0))[:2])
    out.extend(TaskbarInfo(h, False) for h in found if rect_of(h))
    return out


def dpi_scale(hwnd=None):
    if not IS_WIN:
        return 1.0
    try:
        if hwnd and hasattr(user32, "GetDpiForWindow"):
            d = user32.GetDpiForWindow(hwnd)
            if d:
                return d / 96.0
        hdc = user32.GetDC(None)
        d = gdi32.GetDeviceCaps(hdc, 88)   # LOGPIXELSX
        user32.ReleaseDC(None, hdc)
        return d / 96.0 if d else 1.0
    except Exception:
        return 1.0


def compute_taskbar_slot(tb, width, height, position="right", offset=0, reserve=None):
    """Screen rectangle (x, y, w, h) for our window on taskbar `tb`.

    width/height: size of our content. For a horizontal taskbar the height is
    stretched to the taskbar; for a vertical one the width is.
    reserve: on Windows 10 we shrink the task-button area, so the slot is at the
    end of the button strip (passed in as a rect)."""
    l, t, r, b = tb.rect
    scale = dpi_scale(tb.hwnd)
    if not tb.vertical:
        h = b - t
        y = t
        if position == "left":
            if reserve:                       # Windows 10: start of the button strip
                x = reserve[0] + offset
            elif is_win11():
                # centred Windows 11 taskbar: empty space on the left, after widgets
                gap = 8 + (160 if widgets_enabled() else 0)
                x = l + int(gap * scale) + offset
            else:
                x = l + offset
            return x, y, width, h
        if reserve:
            x = reserve[2] - width - offset
        else:
            na = tb.notify_area()
            if na:
                x = na[0] - width - offset
            else:
                # Nothing to measure (some Windows 11 builds, secondary taskbars):
                # assume a typical clock + tray area width.
                guess = int((260 if tb.primary else 110) * scale)
                x = r - guess - width - offset
        return max(l, x), y, width, h
    # vertical taskbar (left/right edge of the screen): "right" means just above the
    # clock at the bottom, "left" means at the top, below the Start button
    w = r - l
    x = l
    gap = int(2 * scale)
    if position == "left":
        if reserve:
            y = reserve[1] + offset
        else:
            start = tb.child_rect("Start")
            if start and not (is_win11() and taskbar_center_aligned()):
                y = start[3] + gap + offset
            elif is_win11():
                y = t + gap + offset          # centred icons: the top is free
            else:
                y = t + int(48 * scale) + offset
    elif reserve:
        y = reserve[3] - height - offset
    else:
        na = tb.notify_area()
        if na:
            y = na[1] - height - gap - offset
        else:
            # no tray rectangle: leave room for the clock (and tray icons on the main bar)
            y = b - int((200 if tb.primary else 88) * scale) - height - offset
    y = max(t, min(y, b - height))
    return x, y, w, height


class Win10ButtonSqueeze:
    """On Windows 10 the taskbar buttons fill all space up to the tray; to make room
    for us we shrink the button strip (MSTaskSwWClass) like other taskbar tools do.
    Explorer resizes it again whenever it re-lays out, so call apply() regularly."""

    def __init__(self, tb):
        self.tb = tb
        self.rebar = user32.FindWindowExW(tb.hwnd, None, "ReBarWindow32", None) if IS_WIN else None
        self.tasks = (user32.FindWindowExW(self.rebar, None, "MSTaskSwWClass", None)
                      if self.rebar else None)
        self.active = False

    @property
    def usable(self):
        return bool(IS_WIN and not is_win11() and self.rebar and self.tasks)

    def apply(self, size, side="right"):
        """Shrink the button strip by `size` px, leaving the gap on `side`.
        Returns the screen rect of the whole strip area (our slot is at its end)."""
        if not self.usable:
            return None
        rb = rect_of(self.rebar)
        ts = rect_of(self.tasks)
        if not rb or not ts:
            return None
        rw, rh = rb[2] - rb[0], rb[3] - rb[1]
        if self.tb.vertical:
            want = rh - size
            top = size if side == "left" else 0
            if want > 0 and ((ts[3] - ts[1]) != want or ts[1] - rb[1] != top):
                user32.MoveWindow(self.tasks, 0, top, rw, want, True)
        else:
            want = rw - size
            left = size if side == "left" else 0
            if want > 0 and ((ts[2] - ts[0]) != want or ts[0] - rb[0] != left):
                user32.MoveWindow(self.tasks, left, 0, want, rh, True)
        self.active = True
        return rb

    def restore(self):
        if not self.active or not self.usable or not user32.IsWindow(self.tasks):
            return
        rb = rect_of(self.rebar)
        if rb:
            user32.MoveWindow(self.tasks, 0, 0, rb[2] - rb[0], rb[3] - rb[1], True)
        self.active = False


def embed_into(hwnd, parent):
    """Make our window a child of the taskbar. Returns True on success."""
    if not IS_WIN:
        return False
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    new = (((style & 0xFFFFFFFF) | WS_CHILD) & ~WS_POPUP) & 0xFFFFFFFF
    user32.SetWindowLongW(hwnd, GWL_STYLE, ctypes.c_long(new).value)
    ctypes.set_last_error(0)
    user32.SetParent(hwnd, parent)
    if user32.GetParent(hwnd) != parent:
        log(f"SetParent failed, error {ctypes.get_last_error()}")
        user32.SetWindowLongW(hwnd, GWL_STYLE, style)
        return False
    return True


def place_child(hwnd, parent, x, y, w, h):
    """Position a child window using screen coordinates."""
    p = POINT(int(x), int(y))
    user32.ScreenToClient(parent, ctypes.byref(p))
    # HWND_TOP (None): above the taskbar's own child windows. On Windows 11 a
    # XAML layer covers the whole taskbar and would otherwise hide us.
    user32.SetWindowPos(hwnd, None, p.x, p.y, int(w), int(h),
                        SWP_NOACTIVATE | SWP_SHOWWINDOW)


def place_top(hwnd, x, y, w, h):
    user32.SetWindowPos(hwnd, HWND_TOPMOST, int(x), int(y), int(w), int(h),
                        SWP_NOACTIVATE | SWP_SHOWWINDOW)


def is_window(hwnd):
    return bool(IS_WIN and hwnd and user32.IsWindow(hwnd))


def parent_of(hwnd):
    return user32.GetParent(hwnd) if IS_WIN and hwnd else None


# --------------------------------------------------------------------------- autostart / single instance
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --startup'
    exe = sys.executable
    if IS_WIN and exe.lower().endswith("python.exe"):
        pyw = exe[:-10] + "pythonw.exe"
        if os.path.exists(pyw):
            exe = pyw
    main = os.path.abspath(sys.argv[0])
    return f'"{exe}" "{main}" --startup'


def _linux_autostart_path():
    return os.path.join(os.path.expanduser("~"), ".config", "autostart", "netmeter.desktop")


def autostart_enabled():
    if not IS_WIN:
        return os.path.exists(_linux_autostart_path())
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return bool(winreg.QueryValueEx(k, APP_NAME)[0])
    except OSError:
        return False


def set_autostart(enable):
    if not IS_WIN:
        p = _linux_autostart_path()
        if enable:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(f"[Desktop Entry]\nType=Application\nName={APP_NAME}\n"
                        f"Exec={launch_command()}\n")
        elif os.path.exists(p):
            os.remove(p)
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enable:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass


def single_instance_lock():
    """Returns an object to keep alive, or None if NetMeter is already running."""
    if IS_WIN:
        h = kernel32.CreateMutexW(None, False, "Local\\NetMeter_SingleInstance")
        if ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS
            return None
        return h or True
    import fcntl
    f = open(os.path.join(os.path.expanduser("~"), ".netmeter.lock"), "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return f


def open_path(path):
    try:
        if IS_WIN:
            os.startfile(path)
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        log(f"open {path} failed: {e}")


def open_task_manager():
    if IS_WIN:
        open_path("taskmgr.exe")
    else:
        import shutil
        import subprocess
        for prog in ("gnome-system-monitor", "ksysguard", "xfce4-taskmanager"):
            if shutil.which(prog):
                subprocess.Popen([prog])
                return
