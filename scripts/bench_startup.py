"""Startup, opening and memory of a real document — and a LEAK check.
Uso: cd <checkout> && <venv python> scripts/bench_startup.py <igz> <salida.json>
Abre una ventana GL real (xcb) unos segundos.

The leak check opens the same document REOPENS times in a row: each open
replaces the previous document, so nothing may keep growing. The exact
signal is the count of LIVE objects after each reopening — faces, GL vertex
arrays, dialogs: a document that is gone must take its own with it (the
0.5.2 → 0.5.3 check found the viewport keeping every old document's chunks,
and with them its faces). Resident memory is reported too, but it is only a
hint: the allocator keeps its high-water mark (two documents coexist while
one replaces the other), so it levels off rather than falling back."""
import json
import os
import sys
import time

REOPENS = 6
t0 = time.perf_counter()
os.environ["QT_QPA_PLATFORM"] = "xcb"
sys.path.insert(0, os.getcwd())
# What main.py does first, so the memory measured is the app's.
try:
    from core import malloc_arenas  # noqa: E402
    malloc_arenas.limit()
except ImportError:                     # an older tree (the previous tag)
    pass
from pathlib import Path  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
# Never the user's own settings (window layout, recent files) nor their
# extensions: closing the window saves its state, and release_check runs
# these six times (09-10: Marco's window and recent files were the bench's).
import tempfile as _tempfile
from PySide6.QtCore import QSettings as _QSettings
_bench_dir = _tempfile.mkdtemp(prefix="ingetrazo-bench-")
os.environ["XDG_DATA_HOME"] = _bench_dir
_QSettings.setDefaultFormat(_QSettings.IniFormat)
for _scope in (_QSettings.UserScope, _QSettings.SystemScope):
    _QSettings.setPath(_QSettings.IniFormat, _scope, _bench_dir)
app.setApplicationName("IngeTrazo")
app.setOrganizationName("IngeTrazo")
from views.main_window import MainWindow  # noqa: E402
import gc  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402


def rss_mb() -> float:
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20


def settle():
    for _ in range(30):
        app.processEvents()
    # What deleteLater() queued: the real event loop runs it, a script must.
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def live(names=("Face", "Mesh", "QOpenGLVertexArrayObject", "QProgressDialog")):
    gc.collect()
    counts = dict.fromkeys(names, 0)
    for o in gc.get_objects():
        n = type(o).__name__
        if n in counts:
            counts[n] += 1
    return counts


win = MainWindow()
win.show()
settle()
res = {"commit": os.popen("git rev-parse --short HEAD").read().strip(),
       "startup_s": round(time.perf_counter() - t0, 2),
       "rss_empty_mb": round(rss_mb(), 1), "open_s": [], "rss_after_open_mb": [],
       "live_after_open": []}
doc = Path(sys.argv[1])
for i in range(REOPENS):
    # Projects in tabs (0.6.0, #1066): opening a file that is already open
    # only brings its tab forward, so it was never read again and every
    # reopening after the first timed nothing. Close its tab first, as a
    # user reopening it would; earlier versions have no tabs to close.
    if i and hasattr(win, "close_document"):
        win.close_document(ask=False)
        settle()
    t = time.perf_counter()
    win.open_path(doc)
    settle()
    win.viewport.repaint()
    settle()
    res["open_s"].append(round(time.perf_counter() - t, 2))
    # The side panels refresh 300 ms after the last change (0.5.8): until
    # then the «In model» list still points at the previous document, and
    # counting at once found two documents alive (release_check 10-10).
    time.sleep(0.5)
    settle()
    res["rss_after_open_mb"].append(round(rss_mb(), 1))
    res["live_after_open"].append(live())
first, last = res["live_after_open"][1], res["live_after_open"][-1]
# Objects gained from the 2nd reopening to the last: 0 when nothing leaks.
res["leaked_objects"] = {k: last[k] - first[k] for k in last if last[k] > first[k]}
r = res["rss_after_open_mb"]
res["rss_growth_last3_mb"] = round((r[-1] - r[-3]) / 2, 1)
json.dump(res, open(sys.argv[2], "w"), indent=1)
print(json.dumps(res, indent=1))
win._saved_version = win.viewport.scene.version
win.close()
