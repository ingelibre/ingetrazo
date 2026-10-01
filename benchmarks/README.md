# Benchmarks — the release history

Before every release, `scripts/release_check.sh <previous tag> <real .igz>`
measures the release candidate against the previous release **on the same
document**, and writes `results/<version>.json`. The files stay here, one per
release, so a slow drift or a memory leak shows up as a trend and not only
against the last version.

What each file holds:

- `viewport` — `scripts/bench_session.py`, two runs per version: paint,
  orbit frame, VBO resync, cold chunk rebuild, cold pick index, 60 hovers
  with Select and with Line (and edits inside a container group when the
  document has one). Milliseconds, median of each run.
- `startup_memory` — `scripts/bench_startup.py`: startup time, opening time,
  resident memory and the count of LIVE objects (faces, meshes, GL vertex
  arrays, progress dialogs) after each of six reopenings of the document.
  `leaked_objects` must be empty: a document that is replaced takes its
  objects with it. Resident memory only levels off (the allocator keeps its
  high-water mark), so it is a hint, not the verdict.
- `tests` — the last line of the fast and the slow suites.

Reading them: the same measure varies up to ~20 % between two runs of the
same build (compare the two runs before blaming a change). The script
flags ⚠ a measure more than 25 % slower than the previous release, and
⚠ LEAK when any object count grows across reopenings.

History: the first check (0.5.3, 25-09-2026) caught a leak present since
long before — every New/Open kept the previous document's render chunks
(and through them its faces), and every edited component its GPU buffers:
0.5.2 grew 610 → 1440 MB over five reopenings of the Plaza Yanque.

The reference document so far is the Plaza Yanque model
(`plaza.igz`, 23 MB: 1035 groups, 48 000 faces drawn), kept outside the
repository.

## Interaction benchmark — what the hand on the mouse feels

`scripts/bench_interaction.py` drives the app the way a user does: real Qt
mouse, wheel and key events go through the viewport's own handlers, and
each event is timed until the frame it caused is on screen (the paint runs
in the event loop, so the loop is run; the GPU is waited on with
`glFinish`; a pointer move the viewport parked to coalesce is waited for
too — the screen catching up with the pointer is what the user waits for).
Each event is split into **handler / paint / other / gpu**, and the hover
pass's own compute (pick + snap) is reported apart from the coalescing wait.

Gestures: orbit, pan, zoom (wheel at a point on the model), hover with
Select, hover with Line (the inference engine — snapping to vertices,
edges, midpoints), clicks with Select, Move of an object (click, live drag,
click — the run fails if no undo step landed) and the Ctrl+Z of that move.
Per gesture: median, p95, max and the share of events over one 60 Hz frame
(16.7 ms) and over two — the share is what "it stutters" means.

The documents are public and regenerable: `scripts/bench_models.py` builds
the same synthetic city at four sizes (buildings with recessed windows —
faces with holes —, a round column each, trees as component copies):

| | objects | faces drawn | .igz |
|---|---|---|---|
| city-S | 39 | 8 k | 5 MB |
| city-M | 314 | 73 k | 45 MB |
| city-L | 1 456 | 331 k | 187 MB |
| city-XL | 4 784 | 1 075 k | 579 MB |

```bash
python scripts/bench_models.py S M L XL          # → benchmarks/models/ (git-ignored)
python scripts/bench_interaction.py out.json benchmarks/models/city-S.igz \
    benchmarks/models/city-M.igz examples/pileta-fuente-yanque.igz
python scripts/bench_interaction.py --compare before.json after.json
```

It opens a real window (the machine should be otherwise idle), uses its
own settings (`IngeTrazo-bench`, autosave off) and the GL format `main.py`
asks for. Vsync is off by default: with it every frame waits for the
monitor's refresh (13.3 ms at 75 Hz), a floor that hides the cost under it;
`--vsync` puts it back.
