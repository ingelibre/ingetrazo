# macOS test regressions — 2026-10-06

Recorded while implementing macOS SpaceMouse input. All eight failures below
were reproduced individually on the **unmodified baseline commit**
`6be29fe437a7cd992d4e079f71720821b25216b9`, exported to a temporary directory.
They predate the SpaceMouse changes. All eight have now been addressed; the
original observations below are retained as reproduction history.

## Fixes

- MAC-01: use a narrower title-block fixture that demonstrates the original
  shrinkage with macOS font metrics, keeping the size assertions intact.
- MAC-02: reinterpret copied FBO bytes as straight RGB before dropping alpha,
  avoiding Qt unpremultiplication overflow. Regression coverage checks white,
  blue and yellow in ARGB32, premultiplied ARGB32 and premultiplied RGBA8888.
- MAC-03: compare native shortcut labels before and after translation and
  assert English names independently through portable serialization.
- MAC-04/05/06: derive expected native labels from the configured shortcuts;
  preserve the repeat-state and live toolbar-update assertions.
- MAC-07: shape the complete line through QTextLayout and use its glyph
  positions and fallback fonts for each mesh. Additional tests cover kerning,
  ligatures, combining marks, supplementary Unicode and right-to-left layout.
- MAC-08: use a float32-aware relative tolerance for QVector3D marker radii,
  preserving the pivot, angle and screen-size assertions.

Validation after these fixes: **111 passed** on macOS with Qt 6.11.2,
covering all seven originally failing test modules plus text-tool, frame
background, raster pen and shortcut integration tests. Before publication,
the fast suite passed in a clean checkout: **3,579 passed, 29 skipped,
805 deselected**. The nine theme tests ran in a separate process to avoid
the accumulated-window slowdown observed during the original investigation.

A subsequent validation of the current working tree completed every fast
suite file in nine fresh processes: **3636 passed, 29 skipped, 805 deselected**,
including the corrected macOS tests. The `.igz` mesh-only folder-field regression
found during that run was fixed and its batch rerun successfully. See
[color-by-layer-test-results.md](color-by-layer-test-results.md) for the
follow-up and preserved logs.

## Reproduction environment

- macOS 26.3, Apple Silicon / arm64.
- Python 3.12.13; PySide6 and Qt 6.11.2; NumPy 2.5.3.
- Dependencies from `requirements.txt`, including its pinned OpenSKP commit.
- `QT_QPA_PLATFORM=offscreen`; fonts are those installed on this Mac.
- Test-only Qt data/cache directories redirected to temporary directories;
  `tests/conftest.py` already isolates QSettings.
- Run outside a restrictive sandbox: existing AI-bridge tests need local
  socket binding, and normal Qt app-data paths must be writable or isolated.

The broad run reached `8 failed, 3268 passed, 28 skipped, 805 deselected`
before being interrupted during expensive global theme switching. The
remaining files, starting with `tests/test_theme.py`, were rerun in a fresh
process: `294 passed, 1 skipped`. The theme slowdown with accumulated windows
is an execution observation, not an additional confirmed assertion failure.
SpaceMouse and preferences tests separately passed: `32 passed, 1 skipped`.

## MAC-01 — title-block sizing test depends on font metrics

Test: `tests/test_composer_cajetin_rows.py::test_every_value_now_reads_at_about_one_size`.

The assertion demonstrating the old defect expects
`min(equal) < max(equal) * 0.85`. On this Mac, `min(equal) = 4.3472` and
`max(equal) = 4.94`, so that demonstration fails. This does **not** establish
that the corrected layout is broken: the failure occurs in the comparison
with the old equal-height layout.

Inspect `views/composer.py::cajetin_row_heights` and the test's `_value_sizes`
helper. Investigate font fallback/metrics and make the regression fixture
demonstrate the defect reliably across platforms.

## MAC-02 — opaque frame conversion changes a white pixel

Test: `tests/test_composer_frame_annots.py::test_raster_frame_image_is_made_opaque`.

The test constructs a premultiplied ARGB image filled with `0xCFFFFFFF`.
After `ComposerWindow.render_frame`, the result is opaque, but the checked
pixel is `0xFF3A3A3A`, rather than the expected white RGB `0xFFFFFF`.

Inspect `views/composer.py::ComposerWindow.render_frame`. The fixture puts RGB
channels above alpha in a premultiplied image; investigate how Qt converts
that invalid premultiplied input before deciding whether to fix the fixture,
the conversion, or both. Preserve the intended regression protection against
colored artifacts in exported frames.

## MAC-03 — shortcut translation test expects non-native text

Test: `tests/test_qt_translator.py::test_shortcuts_keep_their_english_key_names`.

Expected `Ctrl+Shift+PgUp`; observed `⇧⌘⇞` from
`QKeySequence.toString(QKeySequence.NativeText)`.

Inspect `main.py::_install_qt_translator` and the test's format choice.
macOS native shortcut symbols are not evidence of Spanish translation.
Keep the anti-translation check while deciding explicitly between native
display and portable serialization.

## MAC-04 — default repeat hint expects a literal Shift label

Test: `tests/test_repeat_last_command.py::test_the_status_bar_says_what_would_repeat_only_in_select`.

Expected `Shift+R: repeat Line`; observed `⇧R: repeat Line`.

Inspect `views/main_window.py::MainWindow._refresh_repeat_hint` and its
`NativeText` formatting. Preserve the checks that the hint follows the last
command and only appears in Select; account for the platform's key labels.

## MAC-05 — customized repeat hint expects literal Ctrl/Shift labels

Test: `tests/test_repeat_last_command.py::test_the_hint_names_the_keys_it_has_now`.

Expected `Ctrl+Shift+Y: repeat Line`; observed `⇧⌘Y: repeat Line`.

Same display-policy question as MAC-04. Preserve the regression check that
the hint uses the user's current shortcut rather than the default shortcut.

## MAC-06 — customized toolbar shortcut expects non-native text

Test: `tests/test_shortcuts.py::test_la_barra_muestra_el_atajo_configurado_y_no_el_de_fabrica`.

Expected tooltip to contain `Ctrl+Alt+L`; observed `Line  (⌥⌘L)`.

Inspect `views/shortcuts.py` and its `QKeySequence.NativeText` usage.
The observed tooltip does show the customized key combination, but with
macOS symbols. Preserve the assertion about updating customized shortcuts
while correcting the platform assumption.

## MAC-07 — separate 3D letters change the whole text's width

Test: `tests/test_text3d_letters.py::test_letters_lay_out_exactly_like_the_one_piece_text`.

For `IngeTrazo`, font `Sans`, bold, height `0.25`, depth `0.05`, the face-count
check passes, but the extents differ by more than `1e-6`:

- Whole mesh: X range `[0.0165289249, 1.2053806782]`.
- Separate letters: X range `[0.0165289249, 1.2108820677]`.
- Width difference: approximately `0.0055013895` scene metres.
- Both Z ranges are `[0, 0.25]`.

Inspect `core/text3d.py::_rings`, `build_text_mesh` and `build_text_letters`.
Investigate font fallback, shaping, kerning and glyph advances; the exact
cause has not been established. Do not merely relax the tolerance to hide
this observable layout difference.

## MAC-08 — texture protractor equality is stricter than float precision

Test: `tests/test_texture_position_tool.py::test_the_protractor_sits_on_the_red_pin_with_its_zero_on_the_start_arm`.

The two square-marker radii are `0.35743194818496704` and
`0.35743197798728943`. Their difference, `2.9802322387695312e-08`, fails
the assertion requiring less than `1e-9`.

Inspect `tools/texture_position.py::_protractor_segments` and the test's
`QVector3D.length()` comparison. QVector3D uses float components; determine
whether the construction needs correction or the test needs a justified
float-aware tolerance. Preserve the pivot, angle and screen-size checks.

## Targeted reproduction command

With the environment above and writable/isolated Qt application data:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q \
  tests/test_composer_cajetin_rows.py::test_every_value_now_reads_at_about_one_size \
  tests/test_composer_frame_annots.py::test_raster_frame_image_is_made_opaque \
  tests/test_qt_translator.py::test_shortcuts_keep_their_english_key_names \
  tests/test_repeat_last_command.py::test_the_status_bar_says_what_would_repeat_only_in_select \
  tests/test_repeat_last_command.py::test_the_hint_names_the_keys_it_has_now \
  tests/test_shortcuts.py::test_la_barra_muestra_el_atajo_configurado_y_no_el_de_fabrica \
  tests/test_text3d_letters.py::test_letters_lay_out_exactly_like_the_one_piece_text \
  tests/test_texture_position_tool.py::test_the_protractor_sits_on_the_red_pin_with_its_zero_on_the_start_arm
```
