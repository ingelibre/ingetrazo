# SPDX-License-Identifier: GPL-3.0-or-later
"""The Components tray's category tree: the rules (depth, names, hiding,
what a delete does) and the widget that shows them."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from core.component_categories import (DEFAULT_PATHS, MAX_DEPTH,
                                         UNCATEGORIZED, Taxonomy,
                                         TaxonomyError)

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def tax():
    return Taxonomy(":memory:")


def _names(tax, parent=None):
    return [n.name for n in tax.children(parent)]


def _in(tax, key, default=()):
    """The names of the categories an item is listed in."""
    return sorted(n.name for n in tax.nodes_of(key, default))


# ---- the rules -------------------------------------------------------------

def test_a_fresh_file_starts_with_the_default_tree_once(tmp_path):
    path = tmp_path / "c.sqlite"
    first = Taxonomy(path)
    assert "Outdoor" in _names(first)
    assert _names(first, first.find(("Furniture",)).id) == ["Living room"]
    first.delete(first.find(("Vehicles",)).id)
    # reopened: a deleted default does not come back
    again = Taxonomy(path)
    assert "Vehicles" not in _names(again)


def test_every_shipped_default_path_exists(tax):
    for path in DEFAULT_PATHS.values():
        assert tax.find(path) is not None, path


def test_nesting_stops_at_three_levels(tax):
    top = tax.create("Hardware")
    mid = tax.create("Fasteners", top.id)
    low = tax.create("Screws", mid.id)
    assert tax.depth(low.id) == MAX_DEPTH == 3
    with pytest.raises(TaxonomyError):
        tax.create("Too deep", low.id)


def test_sibling_names_are_unique_ignoring_case_and_spaces(tax):
    tax.create("Lighting")
    with pytest.raises(TaxonomyError):
        tax.create("  lighting ")
    other = tax.create("Lamps")
    with pytest.raises(TaxonomyError):
        tax.rename(other.id, "LIGHTING")
    with pytest.raises(TaxonomyError):
        tax.create("   ")
    # the same name under different parents is fine
    a, b = tax.create("A"), tax.create("B")
    tax.create("Shared", a.id)
    tax.create("Shared", b.id)


def test_rename_keeps_the_contents(tax):
    node = tax.create("Lamps")
    tax.add_to("component:x", node.id)
    tax.rename(node.id, "Lighting")
    assert _in(tax, "component:x") == ["Lighting"]


def test_move_respects_depth_cycles_and_name_clashes(tax):
    a = tax.create("A")
    b = tax.create("B", a.id)
    c = tax.create("C", b.id)
    with pytest.raises(TaxonomyError):
        tax.move(a.id, c.id)              # into its own descendant
    with pytest.raises(TaxonomyError):
        tax.move(a.id, a.id)
    d = tax.create("D")
    d1 = tax.create("D1", d.id)
    with pytest.raises(TaxonomyError):
        tax.move(a.id, d1.id)             # A's subtree is 3 deep: 2 + 3 > 3
    tax.move(c.id, None)                  # a level back up to the top
    assert tax.depth(c.id) == 1
    tax.create("Plants", a.id)
    clash = tax.create("Plants")
    with pytest.raises(TaxonomyError):
        tax.move(clash.id, a.id)


def test_hiding_a_category_hides_what_is_inside_it(tax):
    top = tax.create("Hardware")
    sub = tax.create("Bearings", top.id)
    tax.set_hidden(top.id, True)
    assert tax.is_hidden(top.id) and tax.is_hidden(sub.id)
    assert not tax.is_hidden(tax.find(("Outdoor",)).id)
    tax.set_hidden(top.id, False)
    assert not tax.is_hidden(sub.id)


def test_an_unmoved_item_follows_its_default_then_uncategorized(tax):
    key = "component:sofa"
    assert _in(tax, key) == ["Living room"]
    lr = tax.find(("Furniture", "Living room"))
    tax.delete(lr.id)                          # its default is gone
    assert _in(tax, key) == [UNCATEGORIZED]
    assert _in(tax, "component:never.heard.of") == [UNCATEGORIZED]
    assert _in(tax, "person:x", ("People",)) == ["People"]


def test_deleting_a_category_moves_its_items_up_and_drops_its_children(tax):
    top = tax.create("Hardware")
    mid = tax.create("Bearings", top.id)
    low = tax.create("Ball", mid.id)
    tax.add_to("component:b1", mid.id)
    tax.add_to("component:b2", low.id)
    tax.delete(mid.id)
    assert tax.get(low.id) is None
    assert _in(tax, "component:b1") == ["Hardware"]
    assert _in(tax, "component:b2") == ["Hardware"]
    tax.delete(top.id)                         # top level → Uncategorized
    assert _in(tax, "component:b1") == [UNCATEGORIZED]


def test_deleting_uncategorized_is_allowed_and_it_returns_when_needed(tax):
    assert _in(tax, "component:orphan") == [UNCATEGORIZED]
    tax.delete(tax.find((UNCATEGORIZED,)).id)
    assert tax.find((UNCATEGORIZED,)) is None
    assert _in(tax, "component:orphan") == [UNCATEGORIZED]


def test_move_choices_leave_out_the_category_itself_and_too_deep_targets(tax):
    a = tax.create("A")
    b = tax.create("B", a.id)
    labels = dict(tax.choices(exclude=a.id))
    assert a.id not in labels and b.id not in labels
    deep = tax.create("C", b.id)
    assert deep.id in dict(tax.choices())
    # a category with a level below it cannot land on the deepest level
    x = tax.create("X")
    tax.create("X1", x.id)
    assert deep.id not in dict(tax.choices(exclude=x.id, max_depth=MAX_DEPTH - 2))


# ---- one component, several categories --------------------------------------

def test_a_component_can_be_listed_in_several_categories(tax):
    fan = "component:roof.fan"
    electrical = tax.create("Electrical devices")
    living = tax.create("Living room")
    living_roof = tax.create("Roof", living.id)
    bedroom = tax.create("Bedroom")
    bedroom_roof = tax.create("Roof", bedroom.id)
    for node in (electrical, living_roof, bedroom_roof):
        tax.add_to(fan, node.id)
    assert _in(tax, fan) == ["Electrical devices", "Roof", "Roof"]
    assert {n.id for n in tax.nodes_of(fan)} == {
        electrical.id, living_roof.id, bedroom_roof.id}


def test_adding_a_category_keeps_the_default_one(tax):
    sofa = "component:sofa"
    bedroom = tax.create("Bedroom")
    tax.add_to(sofa, bedroom.id)
    assert _in(tax, sofa) == ["Bedroom", "Living room"]
    # and the default does not override what the user chose afterwards
    tax.remove_from(sofa, tax.find(("Furniture", "Living room")).id)
    assert _in(tax, sofa) == ["Bedroom"]


def test_adding_twice_is_harmless(tax):
    node = tax.create("Lighting")
    tax.add_to("component:x", node.id)
    tax.add_to("component:x", node.id)
    assert _in(tax, "component:x") == ["Lighting"]


def test_moving_changes_one_category_and_leaves_the_others(tax):
    fan = "component:roof.fan"
    a, b, c = (tax.create(n) for n in ("A", "B", "C"))
    tax.add_to(fan, a.id)
    tax.add_to(fan, b.id)
    tax.move_item(fan, a.id, c.id)
    assert _in(tax, fan) == ["B", "C"]
    tax.move_item(fan, b.id, c.id)             # already there: just leaves B
    assert _in(tax, fan) == ["C"]


def test_the_last_category_cannot_be_removed_it_becomes_uncategorized(tax):
    node = tax.create("Lighting")
    tax.add_to("component:x", node.id)
    tax.remove_from("component:x", node.id)
    assert _in(tax, "component:x") == [UNCATEGORIZED]


def test_deleting_a_category_only_moves_up_what_would_be_stranded(tax):
    top = tax.create("Hardware")
    bearings = tax.create("Bearings", top.id)
    electrical = tax.create("Electrical")
    tax.add_to("component:both", bearings.id)
    tax.add_to("component:both", electrical.id)
    tax.add_to("component:only", bearings.id)
    tax.delete(bearings.id)
    assert _in(tax, "component:both") == ["Electrical"]     # no stray listing
    assert _in(tax, "component:only") == ["Hardware"]       # not lost


# ---- the widget ------------------------------------------------------------

def _entries():
    from views.component_tree import ComponentEntry
    made = []
    rows = [("component:sofa", "Sofa"),
            ("component:banco", "Bench"),
            ("component:suv", "SUV"),
            ("person:sumari", "Sumari")]
    out = [ComponentEntry(k, n, f"tip {n}", (lambda n=n: made.append(n)),
                          default_path=("People",) if k.startswith("person")
                          else ()) for k, n in rows]
    return out, made


@pytest.fixture
def widget(tax):
    QSettings().remove("components/show_all_categories")
    QSettings().remove("components/expanded_categories")
    from views.component_tree import ComponentTree
    entries, made = _entries()
    w = ComponentTree(tax, entries)
    w.made = made
    return w


def test_components_are_listed_under_their_categories(widget):
    assert sorted(widget.leaf_labels()) == [
        "Bench", "SUV", "Sofa", "Sumari"]
    sofa = widget.find_item("component:sofa")
    assert sofa.parent().text(0).startswith("Living room")
    assert sofa.parent().parent().text(0).startswith("Furniture")


def test_a_hidden_category_hides_its_components_until_show_all(widget, tax):
    widget.set_category_hidden(tax.find(("Vehicles",)).id, True)
    assert "SUV" not in widget.leaf_labels()
    widget.show_all.setChecked(True)
    assert "SUV" in widget.leaf_labels()
    row = widget.find_item(tax.find(("Vehicles",)).id)
    assert "hidden" in row.text(0)
    widget.show_all.setChecked(False)
    assert "SUV" not in widget.leaf_labels()


def test_show_all_is_remembered(widget):
    widget.show_all.setChecked(True)
    from views.component_tree import ComponentTree
    again = ComponentTree(widget._tax, _entries()[0])
    assert again.show_all.isChecked()
    widget.show_all.setChecked(False)


def test_activating_a_component_inserts_it_but_a_category_only_folds(widget):
    widget._on_activated(widget.find_item("component:sofa"))
    assert widget.made == ["Sofa"]
    cat = widget.find_item(widget._tax.find(("Outdoor",)).id)
    before = cat.isExpanded()
    widget._on_activated(cat)
    assert cat.isExpanded() != before and widget.made == ["Sofa"]


def test_moving_a_component_to_another_category(widget, tax):
    target = tax.create("Kitchen")
    cab = "component:banco"
    cabinets = widget._tax.find(("Outdoor",)).id
    widget.move_item(cab, cabinets, target.id)
    rows = widget.find_items(cab)
    assert [r.parent().text(0).split("  ")[0] for r in rows] == ["Kitchen"]


def test_a_component_in_three_categories_shows_under_each(widget, tax):
    fan = "component:roof.fan"
    from views.component_tree import ComponentEntry
    widget.set_entries(_entries()[0] + [
        ComponentEntry(fan, "Roof fan", "tip", lambda: None)])
    places = [tax.create(n).id for n in ("Electrical", "Living roof", "Bed roof")]
    for node_id in places:
        widget.add_item(fan, node_id)
    rows = widget.find_items(fan)
    assert len(rows) == 3
    assert sorted(r.parent().text(0).split("  ")[0] for r in rows) == [
        "Bed roof", "Electrical", "Living roof"]
    # listed three times, inserted as the one component
    widget._on_activated(rows[0])
    assert widget.made == []          # (its callback here is a no-op)


def test_a_parent_counts_a_shared_component_once(widget, tax):
    from views.component_tree import ComponentEntry
    fan = "component:roof.fan"
    widget.set_entries(_entries()[0] + [
        ComponentEntry(fan, "Roof fan", "tip", lambda: None)])
    living = tax.create("Living")
    a = tax.create("Roof", living.id)
    b = tax.create("Ceiling", living.id)
    widget.add_item(fan, a.id)
    widget.add_item(fan, b.id)
    assert widget.find_item(living.id).text(0).startswith("Living  (1)")


def test_hiding_one_of_its_categories_keeps_it_in_the_visible_ones(widget, tax):
    from views.component_tree import ComponentEntry
    fan = "component:roof.fan"
    widget.set_entries(_entries()[0] + [
        ComponentEntry(fan, "Roof fan", "tip", lambda: None)])
    elec, bed = tax.create("Electrical"), tax.create("Bedroom")
    widget.add_item(fan, elec.id)
    widget.add_item(fan, bed.id)
    widget.set_category_hidden(elec.id, True)
    assert len(widget.find_items(fan)) == 1
    widget.show_all.setChecked(True)
    assert len(widget.find_items(fan)) == 2
    widget.show_all.setChecked(False)


def test_creating_and_deleting_categories_through_the_widget(widget, tax):
    top = widget.create_category("Lighting")
    sub = widget.create_category("Lamps", top)
    assert widget.find_item(sub) is not None
    widget.delete_category(top)
    assert widget.find_item(top) is None and widget.find_item(sub) is None


def test_a_dropped_component_or_category_is_moved_in_the_model(widget, tax):
    kitchen = tax.create("Kitchen")
    sofa = "component:sofa"
    living = tax.find(("Furniture", "Living room")).id
    widget._on_dropped("item", sofa, living, kitchen.id, False)    # a move
    assert _in(tax, sofa) == ["Kitchen"]
    widget._on_dropped("item", sofa, kitchen.id, living, True)     # Alt: a copy
    assert _in(tax, sofa) == ["Kitchen", "Living room"]
    widget._on_dropped("cat", kitchen.id, None, tax.find(("Outdoor",)).id, False)
    assert tax.depth(kitchen.id) == 2
    widget._on_dropped("cat", kitchen.id, None, None, False)       # empty space
    assert tax.depth(kitchen.id) == 1


def test_a_refused_edit_warns_instead_of_raising(widget, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: shown.append(a[2]))
    assert widget._guarded(widget.create_category, "Outdoor", None) is False
    assert shown and "already exists" in shown[0]


def test_search_filters_and_ignores_empty_categories(widget):
    widget.search.setText("sofa")
    assert widget.leaf_labels() == ["Sofa"]
    top = [widget.tree.topLevelItem(i).text(0)
           for i in range(widget.tree.topLevelItemCount())]
    assert len(top) == 1 and top[0].startswith("Furniture")
    widget.search.setText("")
    assert len(set(widget.leaf_labels())) == 4


def test_the_tree_grows_to_its_rows_then_scrolls(widget):
    from PySide6.QtCore import Qt
    from views.component_tree import MAX_ROWS
    assert widget.tree.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    for i in range(MAX_ROWS + 5):
        widget._tax.create(f"Extra {i}")
    widget.refresh()
    assert widget.tree.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded


def test_the_panel_lists_the_bundled_components_in_the_real_window():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        tree = win.tray.components.tree
        assert "Sofa" in tree.leaf_labels()
        assert any(tree.tree.topLevelItem(i).text(0).startswith("People")
                   for i in range(tree.tree.topLevelItemCount()))
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
