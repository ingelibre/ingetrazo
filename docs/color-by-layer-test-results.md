# Color by layer: validation and regression follow-up

PR: https://github.com/ingelibre/ingetrazo/pull/442

Recorded 2026-10-06 on macOS arm64, Python 3.12, PySide6 6.11.2,
Qt offscreen for pytest. Feature commit: `919c1a3` (`codex/color-by-layer`).
Unmodified upstream baseline: `ingelibre/ingetrazo` main at
`6be29fe437a7cd992d4e079f71720821b25216b9`.

This report retains the original failure observations and tracks their local
resolution. The fixes are in the working checkout and are separate from the
Color by layer upstream PR.

## Local fix status — 2026-10-06

The eight reproducible macOS failures have fixes already present in the local
working tree; a fresh run of their modules plus Color by layer and saved-scene
tests passed **101 tests**. The fixes cover font-independent test fixtures,
correct opaque frame readback, native shortcut assertions, whole-line glyph
shaping and float32-aware geometry comparisons.

`tests/conftest.py` now isolates QStandardPaths application data/cache folders
for every test session. Georef, texture tint and autosave modules pass **21
tests** using ordinary pytest with no external runner. Tests requiring local
sockets must run in an environment that permits them; application code cannot
override sandbox permissions.

Completed fast-suite validation in nine fresh processes of up to 50 test
files: **3636 passed, 29 skipped, 805 deselected, zero remaining failures**.
The first pass found one additional local regression in `.igz` saving a plain
`Mesh`: folder fields were accessed unconditionally. Both layer and scene
folder fields are now optional, preserving the existing mesh-only save API.
The formerly failing batch passed on rerun (**453 passed, 3 skipped**).
Related mesh/layer/saved-view tests passed **63 tests**, and the remaining
scene-folder and `.igz` compatibility/import tests passed **14 tests**.

The aggregate uses the successful rerun for batch 5 and counts each test file
once; targeted reruns are not added. All originally recorded assertions now
pass locally. Socket tests were run with local sockets permitted. Slow/fuzz
tests remain deselected. Logs and the aggregate are preserved in
`dist/color-by-layer/validation/fixes/`.



## Feature validation

- `tests/test_layer_colors.py tests/test_saved_views.py`: **17 passed**.
- Covers `.igz` layer RGB and display toggle persistence, saved-scene recall
  after save/reload, nested-instance inheritance/transforms, hidden/locked
  layers, black edges, material preservation, compact color chips, SKP RGB
  import and a real OpenSKP export/read round trip.
- Local installed build additionally checked with a real macOS OpenGL context:
  layer-colored faces, black edges, and original material colors on toggle off.

## Broad suite and baseline comparison

- Initial `pytest -q -m 'not slow' --tb=short`: **3255 passed, 16 failed,
  28 skipped, 805 deselected** before interruption in `views/theme.py:174`.
  Theme switching became very slow after thousands of Qt widgets accumulated.
  The interrupted run is not a completed green suite.
- All **16 failing tests fail on unmodified upstream** in the same sandbox.
- Re-ran those 16 on both branches with Qt data/cache directories redirected
  to temporary folders and local socket permissions: **8 passed, 8 failed**
  on each branch, with the same failing tests and assertions.
- Re-ran all test files from `tests/test_theme.py` onward in a fresh process:
  **294 passed, 1 skipped** with temporary paths and local socket permissions.
  In the sandbox: **293 passed, 1 failed, 1 skipped** on both branches; the
  bridge start/stop test cannot start its local socket server.
- The fresh tail run overlaps the interrupted run; counts should not be added.
- Slow/fuzz tests were deselected. No new failure attributable to Color by
  layer was found in these runs; upstream CI still needs to confirm its platform.

## Original failures reproduced outside the sandbox

Each test below failed on both unmodified upstream and the feature branch
before the local fixes. The table preserves the original observations.

| Test | Observed failure | Follow-up |
| --- | --- | --- |
| `tests/test_composer_cajetin_rows.py::test_every_value_now_reads_at_about_one_size` | `4.3472 < 4.94 * 0.85` is false. | Check the font-dependent fixture/measurement on macOS. |
| `tests/test_composer_frame_annots.py::test_raster_frame_image_is_made_opaque` | `img.pixel(3, 3) & 0xFFFFFF` is not white; pixel is `4282006074`. | Check premultiplied-alpha conversion and frame background compositing. |
| `tests/test_qt_translator.py::test_shortcuts_keep_their_english_key_names` | Actual `⇧⌘⇞`; expected `Ctrl+Shift+PgUp`. | Account for Qt native macOS shortcut labels. |
| `tests/test_repeat_last_command.py::test_the_status_bar_says_what_would_repeat_only_in_select` | Actual `⇧R: repeat Line`; expected `Shift+R: repeat Line`. | Check portable/native shortcut formatting. |
| `tests/test_repeat_last_command.py::test_the_hint_names_the_keys_it_has_now` | Actual `⇧⌘Y: repeat Line`; expected `Ctrl+Shift+Y: repeat Line`. | Check portable/native shortcut formatting. |
| `tests/test_shortcuts.py::test_la_barra_muestra_el_atajo_configurado_y_no_el_de_fabrica` | Actual tooltip `Line  (⌥⌘L)` lacks expected `Ctrl+Alt+L`. | Check portable/native shortcut formatting. |
| `tests/test_text3d_letters.py::test_letters_lay_out_exactly_like_the_one_piece_text` | Per-letter and one-piece text coordinates differ beyond `1e-6`. | Investigate glyph positioning/kerning and font metrics. |
| `tests/test_texture_position_tool.py::test_the_protractor_sits_on_the_red_pin_with_its_zero_on_the_start_arm` | Radius delta `2.9802322387695312e-08` exceeds `1e-9`. | Check the tolerance against QVector3D float32 precision. |

Follow-up suggestions are hypotheses, not confirmed fixes.

## Environment-only failures observed in the sandbox

These originally failed on both branches in the sandbox and passed with
temporary data/cache paths and local socket permissions. Test-data isolation
is now built into conftest; socket permissions remain an execution requirement.

| Test | Observed failure |
| --- | --- |
| `tests/test_ai_bridge.py::test_bridge_runs_python_transactionally` | `srv.bind(...)`: `PermissionError: [Errno 1] Operation not permitted`. |
| `tests/test_georef_utm_ui.py::TestCoordModeSelector::test_choice_is_remembered_everywhere` | Permission denied creating the georef tile cache under Library/Application Support. |
| `tests/test_georef_utm_ui.py::TestLocationDialogUtm::test_center_fills_both_coordinate_rows` | Same tile-cache directory permission failure. |
| `tests/test_georef_utm_ui.py::TestLocationDialogUtm::test_typed_utm_moves_the_pin` | Same tile-cache directory permission failure. |
| `tests/test_single_instance.py::TestSingleInstanceSocket::test_second_launch_delivers_the_path_to_the_first` | `server.listen(_NAME)` returns false. |
| `tests/test_single_instance.py::TestSingleInstanceSocket::test_unresponsive_peer_gives_no_ack` | `server.listen(_NAME)` returns false. |
| `tests/test_single_instance.py::TestSingleInstanceSocket::test_stale_socket_is_reclaimed` | `s1.listen(_NAME)` returns false. |
| `tests/test_texture_tint.py::test_retinting_starts_from_the_base_never_from_the_last_result` | Retint paths differ (`ingetrazo-tex-.../piedra_laja.png`); passes with a writable isolated cache. |
| `tests/test_tray_panels.py::test_the_bridge_section_starts_and_stops` | `section.running` is false because its local server cannot start. |

## Preserved evidence and reproduction

Full logs, failed node IDs and the isolated Qt test runner are preserved locally
in `dist/color-by-layer/validation/` (ignored build output). This report is
kept in `docs/` so the backlog remains readable after temporary files disappear.

In either the clean baseline or feature checkout, using the same Python/Qt
runtime and permitting local test sockets:

```bash
QT_QPA_PLATFORM=offscreen python /absolute/path/to/run-isolated-tests.py -q \
  tests/test_layer_colors.py tests/test_saved_views.py --tb=short
```

For the existing 16 failures, pass the node IDs listed in `failed-nodes.txt`
to the same runner instead. Run baseline and feature socket tests sequentially:
the single-instance tests share a fixed local server name.
