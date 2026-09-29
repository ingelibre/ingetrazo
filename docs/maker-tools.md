# Maker extensions

Open **Extensions** and choose **Thread / Bolt / Nut**, **Spur Gear**, or
**Aerofoil / Wing Section**. Enter dimensions, select **Create and place**, then click
in the model to place the part. Escape cancels placement. Each placed part
is one group and one undo step. Move and Rotate position it like any group.
All dialog dimensions are millimetres, regardless of document display units.

* **Thread / Bolt / Nut:** M3–M12 presets plus custom diameter, pitch and
  length; right- or left-hand thread; hex-head bolts, threaded rods and
  internally threaded hex nuts. Nut clearance increases the internal radius.
  Head height applies only to bolts; length is shank length for a bolt and
  total thickness for a nut. Threads are sampled truncated profiles, with
  flat ends, rather than tolerance-certified fasteners. Quality controls the
  number of samples around the circumference. Complexity is limited to keep
  accidental extreme inputs from exhausting memory.
* **Spur Gear:** external, zero-shift involute gear with tooth count, module,
  pressure angle, thickness and optional bore. Pitch diameter is module ×
  tooth count; matching pairs need the same module and pressure angle. Root
  transitions are radial, not cutter-generated fillets. Tooth counts requiring
  undercut are rejected; no helical gears or backlash adjustment in this version.
* **Aerofoil / Wing Section:** choose a preset or enter a custom four-digit
  NACA code, then set chord, span and quality. Creates a constant-section solid
  with chord along X and span along Y.

| Preset | Profile |
| --- | --- |
| General wing | NACA 2412 |
| High lift | Selig S1223 |
| Flat aft lower surface | Clark Y |
| Slow-flight starting point | NACA 4415 |
| Symmetric wing / tail | NACA 0012 |
| Propeller blade section | Eppler E850 |

Stall speed depends on wing loading and lift; gentle stall also depends on the
complete wing, including taper and washout. Presets supply geometry, not guaranteed
flight performance. The propeller preset creates a straight blade blank without
twist, taper or a hub. Published profiles retain their trailing edge geometry;
analytic NACA profiles use a closed trailing edge.

Sources: [bundled data notes](../resources/airfoils/README.md).

The thread controls and profile were rewritten from the local SketchUp
`Sketchup2017_extensions/thread_maker/main.rb` reference. The aerofoil dialog
was informed by `1_rc_plane_designer/main.rb`; the generated four-digit
sections use analytic equations instead of its coarse coordinate tables.
No gear extension was present in the reference folder, so the involute gear
generator is new.

Geometry references: [NACA thickness](https://www.pdas.com/naca456thick4.html),
[NACA camber](https://www.pdas.com/naca456mean2.html), and
[involute gear geometry](https://drivetrainhub.com/notebooks/gears/geometry/Chapter%202%20-%20Spur%20Gears.html).

Fine parts retain their mesh in millimetres with a scale transform into the
model's metres, avoiding vertex welding that would erase small thread details.
These transforms travel with the group through placement, saving and export.
