"""Opens an exported DXF in AutoCAD without the "in use or read-only" alert.

AutoCAD has a long-standing fault: when it is not running and a DXF is
opened through Windows (a double-click), it opens the file and then tries to
open it a second time, which raises "currently in use or is read-only".
Starting AutoCAD's own program with the file avoids that; when AutoCAD is
already running, the normal Windows open works correctly.

Windows only. On other systems this does nothing and returns False.
"""

import os
import subprocess
import sys

_NO_WINDOW = 0x08000000        # CREATE_NO_WINDOW


def _autocad_programs():
    """Paths of installed AutoCAD programs (full AutoCAD first, then LT)."""
    import winreg
    found = []
    for product, exe in (("AutoCAD", "acad.exe"), ("AutoCAD LT", "acadlt.exe")):
        base = r"Software\Autodesk" + "\\" + product
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as key:
                release = winreg.QueryValueEx(key, "CurVer")[0]
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base + "\\" + release) as key:
                version = winreg.QueryValueEx(key, "CurVer")[0]
        except OSError:
            continue
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base + "\\" + release + "\\" + version,
                                    0, winreg.KEY_READ | view) as key:
                    folder = winreg.QueryValueEx(key, "AcadLocation")[0]
            except OSError:
                continue
            path = os.path.join(folder, exe)
            if os.path.isfile(path):
                found.append((exe, path))
                break
    return found


def _is_running(exe):
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + exe, "/NH"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return exe.lower() in out.lower()


def open_dxf(path):
    """Open `path` in AutoCAD. Returns True when AutoCAD was asked to open it."""
    if sys.platform != "win32":
        return False
    try:
        programs = _autocad_programs()
    except Exception:
        programs = []
    if not programs:
        return False
    for exe, program in programs:
        if _is_running(exe):
            # Already running: the normal Windows open gives a single, editable copy.
            try:
                os.startfile(path)
                return True
            except OSError:
                return False
    try:
        subprocess.Popen([programs[0][1], path], close_fds=True)
        return True
    except OSError:
        return False
