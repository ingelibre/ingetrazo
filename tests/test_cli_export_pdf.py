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


def test_it_really_exports(tmp_path):
    """The whole run, in a process of its own. 0.6.2 died opening the
    document: the open's progress bar grew a ``canceled`` signal that the
    command line's stand-in did not have."""
    import os
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    out = tmp_path / "plan.pdf"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    done = subprocess.run(
        [sys.executable, str(root / "main.py"), "-i",
         str(root / "examples" / "arco-yanque.igz"), "-p", "-o", str(out)],
        cwd=str(root), env=env, stdin=subprocess.DEVNULL,
        capture_output=True, timeout=300)
    # 3: a view would not render — no OpenGL on the offscreen platform.
    assert done.returncode in (0, 3), done.stderr.decode("utf-8", "replace")
    assert out.read_bytes().startswith(b"%PDF")
