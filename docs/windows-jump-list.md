# Windows taskbar recent files

Successfully opened or saved `.igz` documents and successfully imported `.skp`
files appear under **Recent** when the IngeTrazo taskbar icon is right-clicked.
Hover over an entry and click its pin to keep it under **Pinned**. Windows owns
the list, pins, removals and history settings; IngeTrazo reports successful file
operations and does not rebuild or clear that list at startup.

Each entry opens the file in a new IngeTrazo window, including when SketchUp
is the default `.skp` application. The current window's model stays open.
**File > Open Recent** retains its existing native-document-only behavior.

The implementation uses `SHAddToRecentDocs(SHARD_APPIDINFOLINK)` with a Unicode
shell link, explicit executable/arguments, icon and `PKEY_Title`. It uses ctypes
and the system COM libraries; no new runtime dependencies are required. Other
platforms and model tests that do not initialize the GUI entry point do not
write Windows history. A shell failure never fails a model operation.

The stable `IngeTrazo.IngeTrazo` AppUserModelID is set before Qt creates any UI
and matches the installer's shortcuts and file-type registrations. For a
portable upgrade, an old taskbar shortcut may need to be unpinned and the
running app pinned again so it uses that identity.

Validation: `python -m pytest tests/test_windows_recent.py tests/test_recent_files.py`.
The Windows integration check should also read back entries using
`IApplicationDocumentLists` and verify their target, arguments and title.
