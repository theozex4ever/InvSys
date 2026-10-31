"""NumericTableWidgetItem must sort integer text numerically, not lexically."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget

from inventory_control.ui.views import NumericTableWidgetItem


def make_table(qtbot, values):
    table = QTableWidget(len(values), 1)
    qtbot.addWidget(table)
    for row, value in enumerate(values):
        table.setItem(row, 0, NumericTableWidgetItem(value))
    return table


def sorted_column(table, order):
    table.sortItems(0, order)
    return [table.item(row, 0).text() for row in range(table.rowCount())]


def test_numeric_column_sorts_9_before_10(qtbot):
    table = make_table(qtbot, ["10", "9", "100", "2"])
    assert sorted_column(table, Qt.AscendingOrder) == ["2", "9", "10", "100"]
    assert sorted_column(table, Qt.DescendingOrder) == ["100", "10", "9", "2"]


def test_signed_quantity_changes_sort_numerically(qtbot):
    table = make_table(qtbot, ["+10", "-3", "+9", "+0", "-12"])
    assert sorted_column(table, Qt.AscendingOrder) == ["-12", "-3", "+0", "+9", "+10"]


def test_non_numeric_text_sorts_as_text_without_raising(qtbot):
    table = make_table(qtbot, ["n/a", "", "a"])
    assert sorted_column(table, Qt.AscendingOrder) == ["", "a", "n/a"]
    mixed = make_table(qtbot, ["10", "n/a", "9", ""])
    assert sorted(sorted_column(mixed, Qt.AscendingOrder)) == ["", "10", "9", "n/a"]


@pytest.mark.parametrize("left,right", [("9", "10"), ("-3", "+0"), ("-12", "-3")])
def test_comparison_operators_are_consistent(qtbot, left, right):
    a, b = NumericTableWidgetItem(left), NumericTableWidgetItem(right)
    assert (a < b, a <= b, b > a, b >= a) == (True, True, True, True)
    assert (b < a, b <= a, a > b, a >= b) == (False, False, False, False)
    same = NumericTableWidgetItem(left)
    assert (a <= same, a >= same, a < same, a > same) == (True, True, False, False)
