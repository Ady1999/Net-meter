# NetMeter

Shows your upload/download speed, CPU, memory, GPU, disk and temperatures **in the Windows taskbar**, in a floating window, or both. You can customise every part of it. Everything runs on your own PC.

[![Build](https://github.com/Ady1999/Net-meter/actions/workflows/build.yml/badge.svg)](https://github.com/Ady1999/Net-meter/actions/workflows/build.yml)

## Download

Get the latest version from the **[Releases page](https://github.com/Ady1999/Net-meter/releases/latest)**:

* **`NetMeter-Setup-x.y.z.exe`**: the installer. Run it and you're done. No admin rights or Python needed.
* **`NetMeter-portable-x.y.z.zip`**: the same app without installing. Unzip it and run `NetMeter.exe`.

Windows 10 or 11, 64-bit.

Windows SmartScreen may warn that the app isn't recognised, because it isn't signed with a paid certificate. Click **More info › Run anyway**.

If you used TrafficMonitor, turn off its "Auto run when Windows starts" so the two don't fight over the same spot on the taskbar. NetMeter imports TrafficMonitor's traffic history by itself (see below).

## Where things are

| | |
|---|---|
| **Taskbar window** | Next to the clock (or on the left side of the taskbar). **Right-click** for the menu, **double-click** for connection details (you can change this), **hover** for a tooltip with details. |
| **Floating window** | Off by default. Turn it on from the right-click menu or the tray icon. Drag it anywhere. |
| **Tray icon** | Show or hide either window, open history or options, turn off click-through, exit. |
| **Settings & history** | `%APPDATA%\NetMeter`. For portable mode, put an empty `portable.txt` next to the program. |

## Features

**Taskbar window**
- Sits inside the taskbar (or floats on top of it, if you prefer) to the left of the clock, or on the left side of the taskbar.
- On Windows 10 it narrows the taskbar-button area so the two don't overlap.
- Works with taskbars on any edge, including vertical ones, and on the taskbars of other monitors.
- Two rows or one line. You choose the items, their order and their label text, and the spacing. Values can be right-aligned.
- Colours: follows Windows light/dark mode automatically, or pick dark, light or your own colours. You can also set colours per item, a see-through background, and automatic matching of the taskbar's colour.
- Font: any font, size, bold, italic, underline or strikeout.
- A usage graph behind items (bar or line), for CPU, memory, GPU, disk or network speed, with a colour of your choice and an optional dashed outline.
- If Explorer restarts or the taskbar moves to another monitor, it finds the taskbar again and re-attaches.

**Floating window**
- 8 built-in skins plus your own (see `skin-examples/`), with a preview.
- Opacity, always on top, lock position, click-through, allow off-screen, hide while a full-screen program runs, and a "show more info" toggle.
- Remembers its position, and pulls itself back on screen if a monitor is unplugged.

**What it can show**
- Upload, download and total speed, CPU, memory, GPU and disk usage, CPU frequency, today's traffic.
- CPU, GPU, disk and mainboard temperatures (these need LibreHardwareMonitor, see below).
- Plugin items.

**Number format**
- Bytes or bits, automatic or fixed KB/MB units, short mode, optional space before the unit.
- Optionally hide "/s", the unit or the % sign.
- Memory as a percentage, used, or available.
- Fixed width for speed values, so the window doesn't jump around.
- Swap upload and download.

**Traffic history**
- A list grouped by day, week, month, quarter or year, and a calendar view.
- Totals for today, this month, this year and all time. You choose which day the month starts on.
- Export to CSV, or clear it.

**Notifications**
- Today's or this month's traffic over a limit.
- Memory, CPU or a temperature over a limit.

**Connection details**
- Each adapter's status, link speed, IPv4/IPv6, mask and MAC.
- Default gateway, and your internet IP (only when you click the button).
- Traffic since NetMeter started, today, and since Windows started.

**Other**
- Choose which network adapters to count, or let it pick automatically.
- Two ways to measure CPU: Task Manager-style or CPU time.
- Refresh rate, double-click actions (including opening a program or Task Manager), and Python plugins (see `plugin-examples/`).

**Starting reliably**
- Starts from your user's registry `Run` key, so it needs no admin rights or scheduled task.
- Waits 8 seconds after you sign in (you can change this), then keeps trying for up to a minute until the taskbar exists.
- Brings itself back to the front at 2, 6 and 15 seconds.
- Only one copy runs. Starting it again just brings the running one forward.

## The new Windows 11 taskbar (top, left or right)

Current Windows 11 lets you move the taskbar to the top, left or right edge and make it narrower. NetMeter adjusts itself to the taskbar's current shape and checks again every couple of seconds, so it keeps up if you move or resize it:

* **Bottom or top:** two rows next to the clock. If the taskbar is too short for two rows, everything goes on one line.
* **Left or right, narrow (48 px):** one item per line just above the clock. Labels go above values, and speeds are shortened (`1.6M/s`). If that still doesn't fit, `/s` is dropped, and only then does the font get smaller.
* **Left or right, wide:** one item per line. If you untick **Two rows** and they all fit, everything goes on a single line.
* **Position › left** on a side taskbar puts the stats at the top, just below the Start button.

## Custom taskbars (Hitodama and similar)

Some programs, like Hitodama, restyle the taskbar: an animated background across the whole strip, with a floating rounded bar ("dock") in the middle that holds Start, your apps and the clock. Windows still reports the clock at its old position, so NetMeter **looks at the screen** to find the dock instead:

* With **Position › Automatic** (the default), the stats sit right after the end of the dock, in a rounded panel of the same colour and height, so they look like part of it and stay readable over the animation. If there's no room after it, they go just before it.
* The dock is re-checked every couple of seconds. When it grows or shrinks (apps opened or closed), the stats move with it.
* **Drag the stats** along the taskbar to put them anywhere else. That switches Position to "Where I drag it", and the matching panel is kept. Right-click › Position › Automatic snaps them back to the dock.
* Tweak it in Options › Taskbar window:
  * **Background:** auto, clear, solid or pill.
  * **Pill colour:** the same as the dock, or your own.
  * **Corners**, and the **gap after the dock**.

On a normal taskbar nothing changes: no dock is found, and NetMeter sits next to the clock as before.

## Your TrafficMonitor history

The first time NetMeter starts, it looks for TrafficMonitor's history file (`history_traffic.dat`) and copies every day into NetMeter's traffic history. It checks `%APPDATA%\TrafficMonitor`, the folder TrafficMonitor runs from, its startup entry, and the usual install and download folders. A notification tells you how many days it brought over.

To run it again, for example after TrafficMonitor has counted a few more days, use **Traffic history › Import from TrafficMonitor…** or **Options › General › Import TrafficMonitor history…**. If the file can't be found, it asks you to pick it.

Importing more than once is safe. On days both programs recorded, NetMeter keeps the larger figure instead of adding them together, because both were counting the same traffic. TrafficMonitor's file is only read, never changed.

## Temperatures

Windows has no built-in way for normal programs to read temperatures. Like TrafficMonitor, NetMeter uses **LibreHardwareMonitor** for them:

1. Download LibreHardwareMonitor from its GitHub releases page and run it (it needs admin rights).
2. In LibreHardwareMonitor, turn on **Options › Remote Web Server › Run** and **Options › Run on Windows Startup**.
3. In NetMeter, go to **Options › Hardware**, tick **Read temperatures**, press **Apply**, and use **Show sensors found** to check.
4. Add the temperature items in **Options › Taskbar window › Items to show**.

## If something looks wrong

* **The taskbar window overlaps the tray icons or the clock:** in Options › Taskbar window, raise **Shift (pixels)**. On some Windows 11 versions the tray area can't be measured, so NetMeter guesses its width.
* **It doesn't show in the taskbar at all:** set **Docking** to `overlay`.
* **Anything else:** look at `%APPDATA%\NetMeter\netmeter.log`.

## Not included

* Translations into other languages.
* Online update checks (nothing updates itself).
* TrafficMonitor's own skin files and C++ plugin DLLs. NetMeter uses its own JSON skins and Python plugins instead.

## Building it yourself

You need Python 3.10 or newer on Windows.

* **Install from source:** double-click `install.bat`. It builds `NetMeter.exe`, installs it to `%LOCALAPPDATA%\Programs\NetMeter`, turns on start with Windows and launches it. `uninstall.bat` removes it.
* **Run without building:**
  ```bash
  pip install -r requirements.txt
  ```
  ```bash
  pythonw run.py
  ```
* **Tests:**
  ```bash
  pip install psutil pillow pytest
  ```
  ```bash
  pytest -q tests
  ```

| Folder | What's in it |
|---|---|
| `netmeter/` | The app |
| `packaging/` | Icon, installer script (Inno Setup) and release notes |
| `tests/` | Tests |
| `plugin-examples/`, `skin-examples/` | Examples to copy into `%APPDATA%\NetMeter\plugins` or `skins` |

### How the downloads are made

Every push runs [`.github/workflows/build.yml`](.github/workflows/build.yml) on GitHub's machines:

1. The tests run on Linux.
2. `NetMeter.exe` is built on Windows.
3. **The app is started on that Windows machine** (`NetMeter.exe --self-test report.json`). It attaches to the real taskbar, runs for a few seconds, and records what it found. The build fails if anything went wrong.
4. The installer and portable zip are built, and kept as downloads on the run's page.

To publish a new version:
1. Raise `VERSION` in `netmeter/config.py`.
2. Commit, then push a matching tag:
   ```bash
   git tag v2.1.0
   ```
   ```bash
   git push origin v2.1.0
   ```
   The same workflow then creates the GitHub Release with both downloads attached.
