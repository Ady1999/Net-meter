"""Notification-area (tray) icon. Runs in its own thread and posts commands to Tk."""

from .config import APP_NAME, log


def make_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, 62, 62), radius=12, fill="#1e1e1e")
    d.polygon([(16, 30), (28, 8), (40, 30)], fill="#ff9f43")
    d.polygon([(24, 34), (48, 34), (36, 56)], fill="#2ecc71")
    return img


class Tray:
    def __init__(self, app):
        self.app = app
        self.icon = None
        try:
            import pystray
            from pystray import Menu, MenuItem as Item
        except Exception as e:
            log(f"tray icon unavailable: {e}")
            return
        post = app.post
        cfg = app.cfg
        menu = Menu(
            Item("Show floating window", lambda: post("toggle_main"), default=True,
                 checked=lambda _: cfg["main"]["show"]),
            Item("Show taskbar window", lambda: post("toggle_taskbar"),
                 checked=lambda _: cfg["taskbar"]["show"]),
            Item("Clicks pass through floating window", lambda: post("toggle_click_through"),
                 checked=lambda _: cfg["main"]["click_through"]),
            Item("Move floating window back to the corner", lambda: post("recenter")),
            Menu.SEPARATOR,
            Item("Traffic history", lambda: post("history")),
            Item("Connection details", lambda: post("details")),
            Item("Options…", lambda: post("options")),
            Menu.SEPARATOR,
            Item("Exit", lambda: post("quit")),
        )
        try:
            self.icon = pystray.Icon(APP_NAME, make_image(), APP_NAME, menu)
            self.icon.run_detached()
        except Exception as e:
            log(f"tray icon failed: {e}")
            self.icon = None

    @property
    def available(self):
        return self.icon is not None

    def set_tooltip(self, text):
        if self.icon:
            try:
                self.icon.title = text[:127]
            except Exception:
                pass

    def notify(self, title, msg):
        if not self.icon:
            return False
        try:
            self.icon.notify(msg, title)
            return True
        except Exception:
            return False

    def refresh_menu(self):
        if self.icon:
            try:
                self.icon.update_menu()
            except Exception:
                pass

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None
