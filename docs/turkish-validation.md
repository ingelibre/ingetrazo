# Turkish contribution: validation evidence

## Refresh — 2026-11-15, upstream 0.6.2.1

Upstream commit: `8dbed761dca99dcae76efd9cd3025bfa5b8014d8` (tree
`5cd1eeec80b0fcd11151748ebc58dec1119c64ca`). The original contribution was
431 upstream commits behind. Resolved 21 conflicted files, keeping the new
Bulgarian/Traditional Chinese language support, Qt colour-dialog regression,
update-check scheduling, folded BIM tree state and all upstream contributor credits.
Other catalogues retain every upstream translation; only the 36 existing
contribution-local messages are appended.

All **491 new canonical upstream messages** are translated into Turkish.
The updated source and Turkish catalogues both contain **3,803 keys**;
`scripts/verify_turkish.py` reports **zero integrity findings**. Its checks
now also run as a pytest regression. This is automated coverage and a contextual
translation pass, not independent human terminology approval.

Windows / Python 3.13.5 / PySide6 6.11.3 results on the refreshed tree:

- Turkish workspace/catalogue suite: **14 passed, process exit 0**. The fixture
  explicitly destroys its window while QApplication is alive, fixing its native
  Windows/offscreen interpreter-shutdown crash.
- Qt translation suite: **10 passed, process exit 0**, including the upstream
  colour-picker regression and Turkish standard buttons/unchanged shortcut names.
- Related upstream UI regressions (About, BIM folded tree, command search,
  initial units and project tab appearance): **78 passed, 7 skipped**, followed
  by native shutdown exit `0xC0000005`. The exact same selection on the clean
  upstream snapshot produced **78 passed, 7 skipped and the same native exit**.
  This control separates the remaining shutdown issue from the Turkish change.
- Layers panel in isolation: **133 passed**, followed by the same native
  shutdown exit. The broad runner also reported 133 passing Layers tests.
- The upstream fast-suite runner was started with 24 interleaved batches and
  its separate theme-process groups (33 groups total). The first **10 groups
  reported 503 passed and 55 skipped**; the remaining run was stopped. This
  is **partial broad coverage**, not a passing complete fast-suite execution.
  Counts above overlap and must not be added together.
- Native Windows renders at 100% and 200%: valid OpenGL context; Turkish
  getting-started dialog and BIM selector visually checked. A modeled wall
  remained `IfcWall` in the selector and exported IFC.
- Conflict-marker scan and `git diff --check` passed.

The refresh was reconstructed through the GitHub API because direct Git HTTPS
was unavailable on this machine. All 409 changed upstream blobs were checked
against their Git object IDs; the reconstructed upstream tree exactly matched
`5cd1eeec80b0fcd11151748ebc58dec1119c64ca`. A synthetic local snapshot was used
only to perform/test the three-way merge; it is not published. The published
merge uses the original PR head and the real upstream commit as parents, so
the project's actual history is preserved. No force-push or upstream-main
write is part of the refresh.

Linux/macOS, installer binaries and independent Turkish terminology review
remain pending. Maintainer CI/review is still required before release inclusion.
The original November 5 validation record follows for historical context.

Date: 2026-11-05. Base: `e61132a7f8a098ca77fb6b0e7cac488c1bd410cb`.

## Implemented and tested

- 3,312/3,312 canonical messages have nonempty Turkish values. Both the
  supplied handoff validator (with the updated count) and
  `scripts/verify_turkish.py` pass. Nine whitespace-damaged handoff keys
  were restored; three keyboard hints retain the actual `Space` key name.
- Language selection/system locale, English fallback and Qt Turkish
  standard buttons; shortcut key names remain unchanged.
- Code-plus-label IFC selection, canonical-code item data, tag-as-you-draw,
  `.igz` save/reload, IFC export and document-specific decimal-comma display.
- Four opt-in workspace profiles; switching, saved customization, restoring
  Original, folded-sidebar recovery and unchanged keyboard assignments.
- Skipped introduction changes neither layout nor units; the opt-in metric
  setting changes future documents only. English/Turkish command discovery
  and dotted/dotless-i search normalization.
- Supported Windows environment: Python 3.13.5, PySide6/Qt **6.11.3**.
  The final focused localization/BIM/workspace/units/dock/credits suites:
  **171 passed**. This includes the regression that an unused workspace
  feature must not write profile settings or replace upstream persistence.
- Native Windows UI captures at 100% and 200% scaling have a valid OpenGL
  context. The new guide and BIM panel were visually checked for clipping.
- A modeled 4 × 0.25 × 2.6 m wall exported as IFC4/IfcWall, with its Turkish
  name preserved. IfcOpenShell parsed it; schema validation: **0 findings**.

## Broad regression status

The `not slow` suite was exercised in the upstream runner's interleaved
24 groups, with independent processes to bound Qt widget memory use. Affected
groups were rerun after the credit and opt-in persistence fixes. Combining
the latest report for each group gives **6,650 passed, 1 failed, 281 skipped
and 2 expected failures**. This is a combined run/rerun result, not one
pristine passing full-suite execution. Slow fuzz tests were deselected.

Two remaining Windows/offscreen issues were reproduced on a clean upstream
worktree at the base commit, using the same Qt version and test order:

| Issue | Contribution | Clean upstream control |
| --- | --- | --- |
| `test_style_editor.py::test_a_swatch_tooltip_keeps_the_tooltip_colours` | Fails because the offscreen tooltip label is not visible in the grouped run | Same assertion in the corresponding group; the isolated case passes |
| Group containing 256 passing tests | Native process exit `0xC0000005` after reporting 256 passed / 3 skipped | Same native exit after the same 256 passed / 3 skipped |

Consequently, **the complete Windows test process is not green**. These
baseline issues remain recorded; the contribution stays a draft for upstream
review. The interrupted composer group was rerun successfully after keeping
workspace persistence inactive until explicit selection (216 passed).

The initial broad run caught a missing About credit and state persistence
running without opting in. AUTHORS/About were synchronized, the profile
controller now retains its menu wrapper, and unused profiles do not change
upstream settings. The affected credit, dock, autosave and composer groups
passed their post-fix reruns. All 24 groups have a completed result report.

The existing runner can reproduce the grouping with:

```sh
python scripts/pytest_batches.py -m "not slow" --batches 24 tests
```

The public fork had no registered Actions workflows at verification time;
no Linux CI success is claimed. PR: https://github.com/ingelibre/ingetrazo/pull/1207.

The initial diagnostic run used the host's PySide6 6.12, which the upstream
requirements explicitly exclude. Dock/order failures were reproduced on a
clean upstream worktree there. Those results are not used as supported-version
acceptance evidence. The isolated environment was then pinned to the upstream
supported range. The system-wide installation was not changed.

## Remaining review

Human Turkish CAD/BIM terminology review, Linux/macOS UI checks, screen-reader
testing and installer/release builds remain pending. The supplied terminology
reference is not regulatory certification. IFC import, vendor shortcut
emulation and Phase 3 rebranding are not part of this implementation.

See [implementation and usage](turkish-localization.md) and
`tests/test_turkish_workspace.py` for reproducible behavior checks.
