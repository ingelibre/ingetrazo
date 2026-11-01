# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Windows installer keeps the previews of .skp files (issue #804).

Explorer shows a thumbnail through the handler of the file's ProgID. The
installer makes IngeTrazo.skp the default for .skp, and that ProgID has no
handler, so the previews of the program that owned the extension before
disappeared. The [Code] section copies that handler to IngeTrazo.skp. Inno
Setup does not run on every machine, so this reads the script as text.
"""
from __future__ import annotations

import re
from pathlib import Path

ISS = Path(__file__).resolve().parent.parent / "installer" / "ingetrazo.iss"
THUMBNAIL_PROVIDER = "{E357FCCD-A995-4576-B01F-234630154E96}"


def _script() -> str:
    return ISS.read_text(encoding="utf-8-sig")


def _section(name: str) -> str:
    match = re.search(rf"^\[{name}\]\n(.*?)(?=^\[\w+\]|\Z)", _script(),
                      re.MULTILINE | re.DOTALL)
    assert match, f"no [{name}] section"
    return match.group(1)


def test_app_id_is_unchanged():
    assert "AppId={{63D1C88D-591C-48C8-A13B-5E41810D05E4}" in _script()


def test_skp_progid_key_is_still_deleted_on_uninstall():
    entries = _section("Registry").replace("\\\n", " ").splitlines()
    entry = next(line for line in entries
                 if r'Subkey: "Software\Classes\IngeTrazo.skp";' in line)
    assert "uninsdeletekey" in entry


def test_previous_progid_is_read_before_registry_overwrites_it():
    code = _section("Code")
    assert "CurStep = ssInstall" in code
    assert code.index("CurStep = ssInstall") < code.index("CurStep = ssPostInstall")
    capture = code[code.index("CurStep = ssInstall"):code.index("CurStep = ssPostInstall")]
    assert "RegQueryStringValue(HKCR, '.skp', ''" in capture


def test_thumbnail_handler_is_copied_to_the_skp_progid():
    code = _section("Code")
    assert THUMBNAIL_PROVIDER in code
    write = next(line for line in code.splitlines() if "RegWriteStringValue" in line)
    assert "HKA" in write and "SkpProgId" in write
    assert "SkpProgId = 'IngeTrazo.skp'" in code


def test_handler_is_searched_in_progid_extension_and_system_associations():
    code = _section("Code")
    lookups = re.findall(r"Found := ReadThumbnailHandler\(([^,]+),", code)
    assert lookups == ["PreviousSkpProgId", "'.skp'",
                       r"'SystemFileAssociations\.skp'"]


def test_an_upgrade_does_not_take_its_own_progid_as_the_source():
    assert "CompareText(PreviousSkpProgId, SkpProgId) = 0" in _section("Code")
