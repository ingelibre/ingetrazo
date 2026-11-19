# macOS accessibility crash in Qt 6.11.2

IngeTrazo 0.5.8 can crash on Apple Silicon when an accessibility client
inspects a tree or table. The supplied macOS 26.6.2 report reaches
`-[QMacAccessibilityElement accessibilitySelectedChildren]` at offset
`0x87434` in the bundled Cocoa plugin. Related failures occur when a
tree's model is reset.

Qt's native accessibility elements delete interfaces which are still owned
by the item view's accessibility cache. Replacing a synthesized element or
releasing rows and columns can therefore leave the view holding a freed
interface. See Qt's proposed fix
[772484](https://codereview.qt-project.org/c/qt/qtbase/+/772484)
and [QTBUG-149612](https://bugreports.qt.io/browse/QTBUG-149612).
The earlier [765434](https://codereview.qt-project.org/c/qt/qtbase/+/765434)
only protects synthesized elements; it does not address the ownership of
real cells. These are proposed upstream changes, not released fixes.

## Local correction

`core.macos_accessibility` installs a small native Objective-C shim
immediately after creating the Cocoa QApplication, before constructing
views. It follows 772484: native element cleanup leaves interface deletion
to Qt's cache. Qt still releases the native rows and columns normally.
Accessibility remains enabled, including selection and cell queries.

The shim is restricted to PySide6 and Qt 6.11.2 on Cocoa. It validates the
Objective-C methods and interface-ID layout before changing them, and its
library remains loaded through shutdown. Other operating systems and the
offscreen platform do not load it. Revisit this version pin and remove the
shim once an upstream release containing the ownership fix has passed the
same native regression tests.

Source launches compile the library with Apple's Command Line Tools. The
macOS packaging script compiles and bundles it so installed applications
do not require a compiler. Updating Python source alone does not repair an
existing `.app`; it must be rebuilt.

## Verification

```sh
python -m pytest -q tests/test_macos_accessibility_fix.py tests/test_macos_accessibility.py
python scripts/pytest_batches.py -m 'not slow' tests
packaging/build-macos-app.sh
```

The native subprocess tests use Cocoa's real event loop and inspect native
accessibility rows, columns, children and selected children across model
resets. They also verify that removing the last table row does not delete
interfaces for cells which remain in the model. The tests reproduce the
original crash without the shim and the remaining ownership failure with
the earlier partial fix. CI runs them on Apple Silicon and Intel runners.
Offscreen tests alone cannot verify this crash. Also replay the
reported model workflow in the built application: import SketchUp, save
an `.igz`, reopen it, inspect the Browser and navigate the viewport.

## Local validation — 2026-10-15

- Apple M2 Pro, macOS 26.6.2, Python 3.12.12, PySide6 / Qt 6.11.2.
- 49 focused tests passed, including all three native Cocoa subprocesses,
  loader/build checks, file opening, crash logs and packaging checks.
- Fast suite: 4,558 passed, 29 skipped, 805 deselected; one existing failure
  in `test_extension_manager.py::test_long_author_tags_and_license_wrap_within_preview_width`.
  It fails identically on an unmodified export of `d8ee8c0` with the same
  interpreter (`heightForWidth(256)` and maximum item height are both 40).
- Built app: SketchUp import, `.igz` save, three reopenings and 60 camera
  navigation updates completed with accessibility active. The final installed
  app also opened the original `.igz` through the native file dialog and
  survived orbit, zoom and external accessibility inspection.
- The installed bundle passes `--check` and strict recursive signature
  verification. Intel runtime validation is configured in CI but has not
  been run on this Apple Silicon Mac.
