"""Write netmeter.ico (used for the .exe and the installer) from the tray icon artwork."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from netmeter.tray import make_image  # noqa: E402

out = os.path.join(ROOT, "netmeter.ico")
make_image().save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])
print("wrote", out)
