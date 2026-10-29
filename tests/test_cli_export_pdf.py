"""The window-less command line: ``ingetrazo -i Casa.igz -p [-o Casa.pdf]``."""
from pathlib import Path

import pytest


def test_only_the_cli_flags_leave_the_gui():
    from main import _wants_cli
    assert _wants_cli(["-i", "Casa.igz", "-p"])
    assert _wants_cli(["--input-file=Casa.igz", "--create-pdf"])
    # A double-click hands the document alone; File ▸ New Window its flag.
    assert not _wants_cli(["Casa.igz"])
    assert not _wants_cli(["--new-window"])
    assert not _wants_cli([])


def test_the_output_is_optional():
    from main import _parse_cli
    args = _parse_cli(["-i", "Casa.igz", "-p"])
    assert args.input_file == Path("Casa.igz")
    assert args.output_file is None
    assert args.create_pdf
    args = _parse_cli(["--input-file", "Casa.igz", "--create-pdf",
                       "--output-file", "out/plan.pdf"])
    assert args.output_file == Path("out/plan.pdf")


@pytest.mark.parametrize("argv", [["-i", "Casa.igz"], ["-p"]])
def test_without_a_document_or_a_task_it_refuses(argv):
    from main import _parse_cli
    with pytest.raises(SystemExit):
        _parse_cli(argv)
