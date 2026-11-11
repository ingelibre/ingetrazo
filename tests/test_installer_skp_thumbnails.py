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


# ---- Uninstall hands .skp back (issue #1268) --------------------------------

def test_the_previous_opener_is_read_from_the_root_the_install_writes():
    """HKCR shows both roots merged; the uninstaller deletes only its own."""
    code = _section("Code")
    capture = code[code.index("CurStep = ssInstall"):
                   code.index("CurStep = ssPostInstall")]
    assert "RegQueryStringValue(HKA, SkpClassKey, '', PreviousOwnRootProgId)" in capture
    assert r"SkpClassKey = 'Software\Classes\.skp'" in code


def test_it_is_written_down_only_when_skp_is_taken_and_was_someone_elses():
    code = _section("Code")
    keep = code[code.index("WizardIsTaskSelected('skpdefault')"):
                code.index("procedure CurUninstallStepChanged")]
    assert "CompareText(PreviousOwnRootProgId, SkpProgId) <> 0" in keep
    assert ("RegWriteStringValue(HKA, SkpOwnKey, PreviousValueName, "
            "PreviousOwnRootProgId)") in keep


def test_uninstall_reads_it_before_the_key_goes_and_writes_it_back_after():
    code = _section("Code")
    un = code[code.index("procedure CurUninstallStepChanged"):]
    assert un.index("usUninstall then") < un.index("usPostUninstall then")
    before = un[un.index("usUninstall then"):un.index("usPostUninstall then")]
    after = un[un.index("usPostUninstall then"):]
    assert "RegQueryStringValue(HKA, SkpOwnKey, PreviousValueName, ProgIdToRestore)" in before
    assert "RegWriteStringValue(HKA, SkpClassKey, '', ProgIdToRestore)" in after


def test_a_choice_made_since_is_left_alone():
    code = _section("Code")
    after = code[code.index("usPostUninstall then"):]
    assert "(Current = '') or (CompareText(Current, SkpProgId) = 0)" in after


def test_last_the_programs_offered_for_skp_lend_their_handler():
    """A copy for one user over the one for the whole machine finds
    IngeTrazo.skp as the previous ProgID; the other program's handler was
    only under .skp's OpenWithProgids, and the previews went (minipc,
    11-11)."""
    code = _section("Code")
    post = code[code.index("CurStep = ssPostInstall"):
                code.index("procedure CurUninstallStepChanged")]
    assert post.index(r"'SystemFileAssociations\.skp'") < post.index(
        "Found := ReadOpenWithHandler(Clsid)") < post.index("if Found then")
    fn = code[code.index("function ReadOpenWithHandler"):
              code.index("procedure CurStepChanged")]
    assert r"RegGetValueNames(HKCR, '.skp\OpenWithProgids', Names)" in fn
    # Never its own ProgID, and the first that has one wins.
    assert "CompareText(Names[I], SkpProgId) <> 0" in fn
    assert "(not Result)" in fn
