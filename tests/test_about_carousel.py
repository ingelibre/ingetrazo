"""Help ▸ About: the contributors roll up like film credits (Marco, 23-09)."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from views.about_dialog import CONTRIBUTORS, AboutDialog, _credits_html

_app = QApplication.instance() or QApplication([])


def test_everyone_is_in_the_credits():
    html = _credits_html(CONTRIBUTORS)
    for who in ("Pedro Caeiro", "Rafael García Rodríguez", "Ahsan Mehmood",
                "dafrobozao", "Félix Riestra", "Sherod Taylor"):
        assert who in html


def test_the_credits_roll_by_themselves_and_loop():
    dlg = AboutDialog(None, "0.0.0")
    dlg.resize(520, 600)
    dlg.show()
    _app.processEvents()
    roll = dlg.credits
    assert roll.running                       # nothing to click
    assert roll.span > roll.height()          # more names than the band shows
    start = roll.offset
    roll.tick()
    assert roll.offset != start               # it moves
    for _ in range(roll.span + 5):
        roll.tick()
    assert 0 <= roll.offset < roll.span       # and comes round again
    dlg.close()


def test_every_contributor_in_authors_is_in_the_credits():
    # The About roll and AUTHORS name the same people: a new contributor
    # added to one and not the other is caught here.
    import re
    from pathlib import Path
    authors = (Path(__file__).resolve().parents[1] / "AUTHORS").read_text()
    handles = set(re.findall(r"github\.com/([\w.-]+)\)", authors))
    links = {link.rsplit("/", 1)[-1] for _n, _r, link in CONTRIBUTORS if link}
    missing = handles - links - {"tuxiasumari"}
    assert not missing, f"in AUTHORS but not in About: {sorted(missing)}"


def test_the_pointer_stops_the_roll_and_the_wheel_scrolls_it():
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QEnterEvent, QWheelEvent
    dlg = AboutDialog(None, "0.0.0")
    dlg.resize(520, 600)
    dlg.show()
    _app.processEvents()
    roll = dlg.credits
    QApplication.sendEvent(roll, QEnterEvent(QPointF(5, 5), QPointF(5, 5),
                                             QPointF(5, 5)))
    assert not roll.running
    start = roll.offset
    down = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, -120),
                       Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(roll, down)
    assert roll.offset != start               # on down the list
    up = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, 120),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(roll, up)
    assert abs(roll.offset - start) < 1e-6    # and back
    QApplication.sendEvent(roll, QEvent(QEvent.Leave))
    assert roll.running
    dlg.close()


def test_every_credit_line_is_translated():
    """A new line in CONTRIBUTORS needs its translations, or the About box
    shows it in English whatever the interface language (#1271)."""
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "i18n"
    lines = [what for _, what, _ in CONTRIBUTORS]
    lines.append("Thanks as well to all the authors of the extensions catalogue")
    missing = {}
    for path in sorted(root.glob("*.json")):
        if path.stem == "en":
            continue
        catalog = json.loads(path.read_text(encoding="utf-8"))
        gaps = [line[:40] for line in lines if not catalog.get(line)]
        if gaps:
            missing[path.stem] = gaps
    assert not missing, missing
