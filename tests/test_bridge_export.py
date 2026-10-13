"""CSV exports through the public bridge, using real disposable inventory and files."""

import csv
import json
import os
import sys
from pathlib import Path

import pytest

from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore
from inventory_control.utilities import UtilityContext


def launch(tmp_path):
    database = tmp_path / "inventory.db"
    store = InventoryStore(database, seed=False)
    context = UtilityContext.for_launch(database)
    return store, InventoryBridge(store, context), context


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def test_export_parts_reports_the_real_file_and_preserves_catalog_fields(tmp_path):
    store, bridge, context = launch(tmp_path)
    store.add_part("A", 'Bearing, 3" — café', minimum_quantity=5, location="Receiving")
    store.set_part_active("A", False)

    result = bridge.export_csv("parts")

    assert result["ok"] is True
    exported = result["data"]
    assert exported["kind"] == "parts"
    assert exported["rows_exported"] == 1
    assert Path(exported["path"]).parent == context.exports
    headers, rows = read_csv(exported["path"])
    assert headers == [
        "part_number",
        "description",
        "default_location",
        "minimum_quantity",
        "active",
    ]
    assert rows == [
        {
            "part_number": "A",
            "description": 'Bearing, 3" — café',
            "default_location": "Receiving",
            "minimum_quantity": "5",
            "active": "False",
        }
    ]
    json.dumps(result, allow_nan=False)


def test_export_inventory_preserves_each_lot_and_location(tmp_path):
    store, bridge, _context = launch(tmp_path)
    store.add_part("A", "Bearing", minimum_quantity=5)
    store.receive("A", 7, "Stock", "L1", "Pat")
    store.receive("A", 3, "Receiving", "L2", "Pat")
    exported = bridge.export_csv("inventory")["data"]
    headers, rows = read_csv(exported["path"])
    assert headers == [
        "part_number",
        "description",
        "location",
        "lot_number",
        "quantity",
        "minimum_quantity",
    ]
    assert exported["rows_exported"] == 2
    assert {(row["lot_number"], row["location"], row["quantity"]) for row in rows} == {
        ("L1", "Stock", "7"),
        ("L2", "Receiving", "3"),
    }
    assert all(row["part_number"] == "A" and row["minimum_quantity"] == "5" for row in rows)


def test_export_transactions_preserves_audit_metadata(tmp_path):
    store, bridge, _context = launch(tmp_path)
    store.add_part("A", "Bearing")
    store.receive("A", 7, "Stock", "L1", "Pat", reference="PO-47", notes="Check, carefully")
    exported = bridge.export_csv("transactions")["data"]
    headers, rows = read_csv(exported["path"])
    assert headers == [
        "timestamp",
        "tx_type",
        "part_number",
        "lot_number",
        "quantity_change",
        "location_from",
        "location_to",
        "operator",
        "reference",
        "notes",
    ]
    assert exported["rows_exported"] == 1
    assert rows == [
        {
            "timestamp": store.transactions[0].timestamp,
            "tx_type": "RECEIVE",
            "part_number": "A",
            "lot_number": "L1",
            "quantity_change": "7",
            "location_from": "",
            "location_to": "Stock",
            "operator": "Pat",
            "reference": "PO-47",
            "notes": "Check, carefully",
        }
    ]


def test_export_shipments_preserves_original_component_snapshots_after_bom_edit(tmp_path):
    store, bridge, _context = launch(tmp_path)
    for part in ("KIT", "SUB", "A"):
        store.add_part(part, part)
    store.add_bom_component("KIT", "SUB", 2)
    store.add_bom_component("SUB", "A", 3)
    store.receive("A", 4, "Stock", "L1", "Pat")
    store.receive("A", 10, "Stock", "L2", "Pat")
    standard = store.ship("A", 1, "Stock", "Acme", "Pat", "L2", carrier="Post", tracking="T47")
    plan = store.prepare_bom_shipment("KIT", 1, "Stock")
    bom = store.ship("KIT", 1, "Stock", "Acme", "Pat", expected_bom_plan=plan)
    store.add_bom_component("SUB", "A", 9)

    exported = bridge.export_csv("shipments")["data"]
    headers, rows = read_csv(exported["path"])
    assert headers == [
        "shipment_number",
        "timestamp",
        "part_number",
        "quantity",
        "recipient",
        "carrier",
        "tracking_number",
        "consumed_components",
    ]
    assert exported["rows_exported"] == 2
    ordinary = next(row for row in rows if row["shipment_number"] == standard)
    assert (ordinary["recipient"], ordinary["carrier"], ordinary["tracking_number"]) == (
        "Acme",
        "Post",
        "T47",
    )
    assert ordinary["consumed_components"] == ""
    assembly = next(row for row in rows if row["shipment_number"] == bom)
    assert assembly["quantity"] == "1"
    assert set(assembly["consumed_components"].split(";")) == {"A|L1|Stock|4", "A|L2|Stock|2"}


def test_export_bom_preserves_direct_nested_definitions(tmp_path):
    store, bridge, _context = launch(tmp_path)
    for part in ("KIT", "SUB", "A"):
        store.add_part(part, part)
    store.add_bom_component("KIT", "SUB", 2)
    store.add_bom_component("SUB", "A", 3)
    exported = bridge.export_csv("bom")["data"]
    headers, rows = read_csv(exported["path"])
    assert headers == ["parent_part_number", "component_part_number", "quantity_per"]
    assert exported["rows_exported"] == 2
    assert rows == [
        {"parent_part_number": "KIT", "component_part_number": "SUB", "quantity_per": "2"},
        {"parent_part_number": "SUB", "component_part_number": "A", "quantity_per": "3"},
    ]


@pytest.mark.parametrize("kind", ["parts", "inventory", "transactions", "shipments", "bom"])
def test_empty_export_still_writes_headers_and_reports_zero_rows(tmp_path, kind):
    _store, bridge, context = launch(tmp_path)
    result = bridge.export_csv(kind)
    assert result["ok"] is True
    assert result["data"]["rows_exported"] == 0
    path = Path(result["data"]["path"])
    assert path.parent == context.exports
    headers, rows = read_csv(path)
    assert headers
    assert rows == []


def test_all_exports_use_selected_inventory_and_leave_its_state_unchanged(tmp_path, monkeypatch):
    first, bridge, context = launch(tmp_path / "selected inventory")
    other, _other_bridge, other_context = launch(tmp_path / "other")
    first.add_part("A", "Selected inventory")
    first.receive("A", 7, "Stock", "L1", "Pat")
    other.add_part("B", "Other inventory")
    before = first.part_detail("A"), first.transactions, first.shipments, first.bom_components
    monkeypatch.chdir(other_context.database.parent)
    for kind in ("parts", "inventory", "transactions", "shipments", "bom"):
        result = bridge.export_csv(kind)
        assert result["ok"] is True
        assert Path(result["data"]["path"]).parent == context.exports
    _, rows = read_csv(bridge.export_csv("parts")["data"]["path"])
    assert [row["part_number"] for row in rows] == ["A"]
    assert not other_context.exports.exists()
    assert before == (
        first.part_detail("A"),
        first.transactions,
        first.shipments,
        first.bom_components,
    )
    reopened = InventoryStore(context.database, seed=False)
    assert before == (
        reopened.part_detail("A"),
        reopened.transactions,
        reopened.shipments,
        reopened.bom_components,
    )


def test_default_launch_exports_to_invsys_home():
    context = UtilityContext.for_launch()
    store = InventoryStore(context.database, seed=False)
    bridge = InventoryBridge(store, context)
    result = bridge.export_csv("parts")
    assert result["ok"] is True
    path = Path(result["data"]["path"])
    assert path.parent == context.exports
    assert path.is_relative_to(Path(os.environ["INVSYS_HOME"]).resolve())
    assert path.is_file()


@pytest.mark.parametrize("kind", ["parts", "inventory", "transactions", "shipments", "bom"])
def test_file_failure_is_reported_without_mutating_inventory(tmp_path, kind):
    store, bridge, context = launch(tmp_path)
    store.add_part("A", "Bearing")
    store.receive("A", 7, "Stock", "L1", "Pat")
    before = store.part_detail("A"), store.transactions, store.shipments
    context.exports.write_text("blocked", encoding="utf-8")
    result = bridge.export_csv(kind)
    assert result["ok"] is False
    assert result["error"]["code"] == "FILE_ERROR"
    assert str(context.exports) in result["error"]["message"]
    assert context.exports.read_text(encoding="utf-8") == "blocked"
    assert before == (store.part_detail("A"), store.transactions, store.shipments)


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permissions enforced for the current user",
)
def test_unwritable_export_folder_is_reported(tmp_path):
    _store, bridge, context = launch(tmp_path)
    context.exports.mkdir()
    context.exports.chmod(0o500)
    try:
        result = bridge.export_csv("parts")
        assert result["ok"] is False
        assert result["error"]["code"] == "FILE_ERROR"
        assert list(context.exports.iterdir()) == []
    finally:
        context.exports.chmod(0o700)


@pytest.mark.parametrize(
    "kind", ["all", "../parts", "/arbitrary/parts.csv", "", "PARTS", 3, None, {"kind": "parts"}]
)
def test_export_rejects_unknown_kinds_and_arbitrary_paths(tmp_path, kind):
    _store, bridge, context = launch(tmp_path)
    result = bridge.export_csv(kind)
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION"
    assert not context.exports.exists()


def test_export_requires_a_launch_context(tmp_path):
    bridge = InventoryBridge(InventoryStore(tmp_path / "inventory.db", seed=False))
    result = bridge.export_csv("parts")
    assert result["ok"] is False
    assert result["error"]["code"] == "UNAVAILABLE"
