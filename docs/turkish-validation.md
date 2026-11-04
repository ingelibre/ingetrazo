# Turkish contribution: validation evidence

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
  The focused localization/BIM/workspace/units/dock suites: **166 passed**.
  After synchronizing AUTHORS and About credits, the translation/credits
  follow-up: **73 passed** (overlaps the focused translation tests).
- Native Windows UI captures at 100% and 200% scaling have a valid OpenGL
  context. The new guide and BIM panel were visually checked for clipping.
- A modeled 4 × 0.25 × 2.6 m wall exported as IFC4/IfcWall, with its Turkish
  name preserved. IfcOpenShell parsed it; schema validation: **0 findings**.

## Broad regression status

The complete `not slow` suite is being exercised in independent batches to
bound Qt widget memory use. Its final results will be recorded here before
this draft contribution is considered ready. Do not interpret this section
as a passing full-suite result.

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
