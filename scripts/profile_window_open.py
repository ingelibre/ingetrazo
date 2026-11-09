"""Opening a document in the real window, phase by phase (issue #760).
Uso: cd <checkout> && <venv python> scripts/profile_window_open.py <igz> <salida>

Writes <salida>.json (seconds per phase, memory) and <salida>-cum.txt /
<salida>-tot.txt (the profile, by cumulative and by own time), the same on
Linux and on Windows so the two can be read side by side: Windows took 262 s
to open the SPR of #158 in the window against 41 s headless, so the time
goes after the file is read — preparing the drawing, the index, the UI.
Never the user's settings: a throwaway QSettings and data folder."""
import cProfile
import io
import json
import os
import pstats
import sys
import time

t0 = time.perf_counter()
sys.path.insert(0, os.getcwd())
try:
    from core import malloc_arenas
    malloc_arenas.limit()
except ImportError:
    pass
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication

app = QApplication([])
_dir = tempfile.mkdtemp(prefix="ingetrazo-profile-")
os.environ["XDG_DATA_HOME"] = _dir
QSettings.setDefaultFormat(QSettings.IniFormat)
for scope in (QSettings.UserScope, QSettings.SystemScope):
    QSettings.setPath(QSettings.IniFormat, scope, _dir)
app.setApplicationName("IngeTrazo")
app.setOrganizationName("IngeTrazo")
from core import _native  # noqa: E402
from views.main_window import MainWindow  # noqa: E402


def memory_mb():
    """(resident now, peak resident) in MB."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        c = PMC()
        c.cb = ctypes.sizeof(c)
        ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c),
            c.cb)
        return c.WorkingSetSize / 2**20, c.PeakWorkingSetSize / 2**20
    import resource
    with open("/proc/self/statm") as f:
        now = int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20
    return now, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def settle():
    for _ in range(30):
        app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


win = MainWindow()
win.resize(1600, 1000)
win.show()
settle()
res = {"platform": sys.platform, "engine": _native.engine(),
       "commit": os.popen("git rev-parse --short HEAD").read().strip(),
       "startup_s": round(time.perf_counter() - t0, 2),
       "rss_empty_mb": round(memory_mb()[0])}
vp = win.viewport
prof = cProfile.Profile()


def phase(name, fn):
    t = time.perf_counter()
    prof.enable()
    try:
        fn()
    finally:
        prof.disable()
    res[name + "_s"] = round(time.perf_counter() - t, 2)
    now, peak = memory_mb()
    res[name + "_rss_mb"] = round(now)
    res[name + "_peak_mb"] = round(peak)
    print(f"{name}: {res[name + '_s']} s  RSS {now:.0f} MB  pico {peak:.0f} MB",
          flush=True)


phase("read", lambda: win.open_path(Path(sys.argv[1])))
phase("events", settle)
phase("first_frame", lambda: (vp.repaint(), settle()))
phase("second_frame", lambda: (vp.repaint(), settle()))
time.sleep(0.5)
phase("panels", settle)
res["total_s"] = round(time.perf_counter() - t0, 2)
out = sys.argv[2]
json.dump(res, open(out + ".json", "w"), indent=1)
prof.dump_stats(out + ".prof")
for key, name in (("cumulative", "cum"), ("tottime", "tot")):
    s = io.StringIO()
    pstats.Stats(prof, stream=s).sort_stats(key).print_stats(60)
    open(f"{out}-{name}.txt", "w").write(s.getvalue())
print(json.dumps(res, indent=1), flush=True)
win._saved_version = vp.scene.version
os._exit(0)
