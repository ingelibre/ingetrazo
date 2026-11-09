#!/usr/bin/env bash
# The check to run BEFORE every release (Marco, 25-09-2026: «recuerda esto
# siempre antes de cada release pasar por pruebas rigurosas, además deberías
# guardar en un archivo tus resultados, para más adelante compararlos y si
# hubiera alguna fuga de memoria o fallas en el rendimiento cazarlos»).
#
#   scripts/release_check.sh <previous tag> <real .igz>
#   e.g. scripts/release_check.sh v0.5.2 ~/Descargas/plaza.igz
#
# Runs, for HEAD and for the previous tag on the SAME document: the viewport
# benchmark (scripts/bench_session.py) twice, and startup / opening / memory
# with the leak check (scripts/bench_startup.py); then the fast and the slow
# test suites. Everything lands in benchmarks/results/<version>.json, next to
# the earlier releases' files — the history to compare against.
# Opens real GL windows (xcb) for a few seconds each.
set -euo pipefail
PREV="${1:?previous tag, e.g. v0.5.2}"
DOC="${2:?a real .igz, e.g. ~/Descargas/plaza.igz}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PY="$HERE/venv/bin/python"
VER="$("$PY" -c 'import sys; sys.path.insert(0, "'"$HERE"'"); from core.version import __version__; print(__version__)')"
WORK="$(mktemp -d)"
trap 'git -C "$HERE" worktree remove --force "$WORK/prev" 2>/dev/null || true; rm -rf "$WORK"' EXIT
git -C "$HERE" worktree add -q "$WORK/prev" "$PREV"
cp "$HERE/scripts/bench_session.py" "$HERE/scripts/bench_startup.py" "$WORK/"

for run in 1 2; do
  (cd "$WORK/prev" && QT_QPA_PLATFORM=xcb "$PY" "$WORK/bench_session.py" "$DOC" "$PREV" "$WORK/prev-view-$run.json" >/dev/null 2>&1)
  (cd "$HERE" && QT_QPA_PLATFORM=xcb "$PY" "$WORK/bench_session.py" "$DOC" "$VER" "$WORK/head-view-$run.json" >/dev/null 2>&1)
done
(cd "$WORK/prev" && "$PY" "$WORK/bench_startup.py" "$DOC" "$WORK/prev-start.json" >/dev/null 2>&1)
(cd "$HERE" && "$PY" "$WORK/bench_startup.py" "$DOC" "$WORK/head-start.json" >/dev/null 2>&1)

cd "$HERE"
# In batches, one process each: the fast suite no longer fits in memory as
# a single run (07-10, >15 GB) — see scripts/pytest_batches.py.
# A failing test is recorded in the report (and named below), not a reason
# to throw the measurements away: the run used to stop here with nothing.
FAST="$(QT_QPA_PLATFORM=offscreen "$PY" scripts/pytest_batches.py -m 'not slow' tests 2>"$WORK/fast.err" | tail -1 || true)"
SLOW="$(QT_QPA_PLATFORM=offscreen "$PY" scripts/pytest_batches.py -m slow tests 2>"$WORK/slow.err" | tail -1 || true)"
grep -hE "^(FAILED|ERROR)|CRASHED" "$WORK/fast.err" "$WORK/slow.err" || true

"$PY" - "$WORK" "$VER" "$PREV" "$DOC" "$FAST" "$SLOW" <<'PYEOF'
import json, sys, datetime, os
work, ver, prev, doc, fast, slow = sys.argv[1:]
def load(p): return json.load(open(os.path.join(work, p)))
out = {"version": ver, "compared_with": prev, "date": datetime.date.today().isoformat(),
       "document": os.path.basename(doc),
       "tests": {"fast": fast, "slow": slow},
       "viewport": {"head": [load("head-view-1.json"), load("head-view-2.json")],
                    "prev": [load("prev-view-1.json"), load("prev-view-2.json")]},
       "startup_memory": {"head": load("head-start.json"), "prev": load("prev-start.json")}}
path = f"benchmarks/results/{ver}.json"
json.dump(out, open(path, "w"), indent=1)
print(f"→ {path}\n  tests: {fast} | slow: {slow}")
for sec in ("root", "container"):
    for k, v in out["viewport"]["head"][0].get(sec, {}).items():
        if isinstance(v, dict):
            a = min(r[sec][k]["median_ms"] for r in out["viewport"]["prev"])
            b = min(r[sec][k]["median_ms"] for r in out["viewport"]["head"])
            flag = "  ⚠" if b > a * 1.25 else ""
            print(f"  {sec:9s} {k:24s} {prev}={a:9.2f} ms  {ver}={b:9.2f} ms  {100*(b-a)/a:+6.1f}%{flag}")
h, p = out["startup_memory"]["head"], out["startup_memory"]["prev"]
print(f"  startup  {p['startup_s']} s → {h['startup_s']} s | open {min(p['open_s'])} s → {min(h['open_s'])} s")
print(f"  memory   {max(p['rss_after_open_mb'])} MB → {max(h['rss_after_open_mb'])} MB"
      f" (growth over the last reopenings {p.get('rss_growth_last3_mb')} → {h['rss_growth_last3_mb']} MB each)")
print(f"  leaked objects over {len(h['live_after_open'])} reopenings: "
      f"{p.get('leaked_objects', 'n/a')} → {h['leaked_objects'] or 'none'}"
      + ("  ⚠ LEAK" if h["leaked_objects"] else ""))
PYEOF
