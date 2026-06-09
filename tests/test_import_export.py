import csv
from datetime import datetime

import pytest

from inventory_control.backup import backup_database
import inventory_control.backup as backup_mod
from inventory_control.import_export import ImportExportService
from inventory_control.models import LotAllocation
from inventory_control.store import InventoryStore


def make_service(tmp_path):
    db_path = tmp_path / "inventory.db"
    store = InventoryStore(db_path=db_path, seed=False)
    service = ImportExportService(
        store,
        export_dir=tmp_path / "exports",
        backup_dir=tmp_path / "backups",
        db_path=db_path,
    )
    return store, service


def write_csv(path, text):
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_bom_shipment(store):
    store.add_part("KIT-001", "Service Kit")
    store.add_part("SCREW-001", "Socket Screw")
    store.add_part("NUT-001", "Lock Nut")
    store.add_bom_component("KIT-001", "SCREW-001", 2)
    store.add_bom_component("KIT-001", "NUT-001", 1)
    store.receive("SCREW-001", 10, "Stock", "LOT-1", "setup")
    store.receive("NUT-001", 10, "Stock", "LOT-1", "setup")
    store.ship(
        "KIT-001",
        2,
        "Stock",
        "Acme",
        "alice",
        component_lots=[
            LotAllocation("SCREW-001", "LOT-1", "Stock", 4),
            LotAllocation("NUT-001", "LOT-1", "Stock", 2),
        ],
    )


def test_export_parts_csv_creates_expected_headers_and_rows(tmp_path):
    store, service = make_service(tmp_path)
    store.add_part("ABC-1", "Widget", minimum_quantity=3)

    result = service.export_parts_csv()

    rows = read_csv(result.path)
    assert result.rows_exported == 1
    assert list(rows[0].keys()) == ["part_number", "description", "default_location", "minimum_quantity", "active"]
    assert rows[0]["part_number"] == "ABC-1"


def test_export_inventory_csv_includes_lot_level_balances(tmp_path):
    store, service = make_service(tmp_path)
    store.add_part("ABC-1", "Widget", minimum_quantity=3)
    store.receive("ABC-1", 5, "Stock", "LOT-A", "alice")

    rows = read_csv(service.export_inventory_csv().path)

    assert rows[0]["part_number"] == "ABC-1"
    assert rows[0]["location"] == "Stock"
    assert rows[0]["lot_number"] == "LOT-A"
    assert rows[0]["quantity"] == "5"


def test_export_transactions_csv_includes_trace_fields(tmp_path):
    store, service = make_service(tmp_path)
    store.add_part("ABC-1", "Widget")
    store.receive("ABC-1", 5, "Stock", "LOT-A", "alice", reference="PO-1", notes="rush")

    rows = read_csv(service.export_transactions_csv().path)

    assert rows[0]["lot_number"] == "LOT-A"
    assert rows[0]["operator"] == "alice"
    assert rows[0]["reference"] == "PO-1"
    assert rows[0]["notes"] == "rush"


def test_export_shipments_csv_includes_normal_and_bom_component_summaries(tmp_path):
    store, service = make_service(tmp_path)
    store.add_part("ABC-1", "Widget")
    store.receive("ABC-1", 5, "Stock", "LOT-A", "alice")
    store.ship("ABC-1", 1, "Stock", "Acme", "bob", "LOT-A")
    build_bom_shipment(store)

    rows = read_csv(service.export_shipments_csv().path)

    normal = next(row for row in rows if row["part_number"] == "ABC-1")
    bom = next(row for row in rows if row["part_number"] == "KIT-001")
    assert normal["consumed_components"] == ""
    assert "SCREW-001|LOT-1|Stock|4" in bom["consumed_components"]
    assert "NUT-001|LOT-1|Stock|2" in bom["consumed_components"]


def test_export_bom_csv_exports_direct_links(tmp_path):
    store, service = make_service(tmp_path)
    store.add_part("KIT-001", "Service Kit")
    store.add_part("SCREW-001", "Socket Screw")
    store.add_bom_component("KIT-001", "SCREW-001", 4)

    rows = read_csv(service.export_bom_csv().path)

    assert rows == [{"parent_part_number": "KIT-001", "component_part_number": "SCREW-001", "quantity_per": "4"}]


def test_export_all_writes_five_files_with_same_timestamp(tmp_path):
    _, service = make_service(tmp_path)

    results = service.export_all()

    assert {result.kind for result in results} == {"parts", "inventory", "transactions", "shipments", "bom"}
    stems = [result.path.rsplit("_", 2)[-2:] for result in results]
    assert len({tuple(stem) for stem in stems}) == 1


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("description\nWidget", "part_number"),
        ("part_number,description\nABC-1,", "description"),
        ("part_number,description,minimum_quantity\nABC-1,Widget,nope", "minimum_quantity"),
        ("part_number,description,default_location\nABC-1,Widget,Narnia", "default_location"),
    ],
)
def test_parts_preview_rejects_invalid_rows(tmp_path, text, field):
    _, service = make_service(tmp_path)

    preview = service.preview_parts_import_csv(write_csv(tmp_path / "parts.csv", text))

    assert not preview.can_import
    assert any(error.field == field for error in preview.errors)


def test_parts_preview_warns_for_ignored_columns(tmp_path):
    _, service = make_service(tmp_path)

    preview = service.preview_parts_import_csv(
        write_csv(tmp_path / "parts.csv", "part_number,description,barcode\nABC-1,Widget,123")
    )

    assert preview.can_import
    assert preview.warnings[0].field == "barcode"


def test_parts_import_creates_and_updates_parts_and_creates_backup(tmp_path):
    store, service = make_service(tmp_path)
    store.add_part("ABC-1", "Old", minimum_quantity=1)
    path = write_csv(
        tmp_path / "parts.csv",
        """
        part_number,description,default_location,minimum_quantity,active
        ABC-1,Updated,Receiving,4,false
        XYZ-2,New Part,Stock,2,true
        """,
    )

    result = service.import_parts_csv(path, "alice")

    assert result.rows_imported == 2
    assert "pre-import" in result.backup_path
    assert store.parts["ABC-1"].description == "Updated"
    assert store.parts["ABC-1"].minimum_quantity == 4
    assert store.parts["ABC-1"].active is False
    assert "XYZ-2" in store.parts


def test_parts_import_rejects_duplicate_rows_and_leaves_parts_unchanged(tmp_path):
    store, service = make_service(tmp_path)
    store.add_part("ABC-1", "Original")
    path = write_csv(
        tmp_path / "parts.csv",
        """
        part_number,description
        ABC-1,Changed
        ABC-1,Changed Again
        """,
    )

    with pytest.raises(ValueError):
        service.import_parts_csv(path, "alice")

    assert store.parts["ABC-1"].description == "Original"


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("part_number,location,quantity\nABC-1,Stock,5", "lot_number"),
        ("part_number,location,lot_number,quantity\nGHOST,Stock,LOT-1,5", "part_number"),
        ("part_number,location,lot_number,quantity\nABC-1,Narnia,LOT-1,5", "location"),
        ("part_number,location,lot_number,quantity\nABC-1,Stock,LOT-1,0", "quantity"),
    ],
)
def test_inventory_preview_rejects_invalid_rows(tmp_path, text, field):
    store, service = make_service(tmp_path)
    store.add_part("ABC-1", "Widget")

    preview = service.preview_inventory_import_csv(write_csv(tmp_path / "inventory.csv", text))

    assert not preview.can_import
    assert any(error.field == field for error in preview.errors)


def test_inventory_preview_rejects_duplicate_part_location_lot_rows(tmp_path):
    store, service = make_service(tmp_path)
    store.add_part("ABC-1", "Widget")
    path = write_csv(
        tmp_path / "inventory.csv",
        """
        part_number,location,lot_number,quantity
        ABC-1,Stock,LOT-1,5
        ABC-1,Stock,LOT-1,3
        """,
    )

    preview = service.preview_inventory_import_csv(path)

    assert not preview.can_import
    assert any("Duplicate" in error.message for error in preview.errors)


def test_inventory_import_receives_stock_lots_transactions_and_backup(tmp_path):
    store, service = make_service(tmp_path)
    store.add_part("ABC-1", "Widget")
    path = write_csv(
        tmp_path / "inventory.csv",
        "part_number,location,lot_number,quantity,reference,notes\nABC-1,Stock,lot-a,5,OPENING,spreadsheet",
    )

    result = service.import_inventory_csv(path, "alice")

    assert result.rows_imported == 1
    assert "pre-import" in result.backup_path
    assert store.stock_at("ABC-1", "Stock", "LOT-A") == 5
    tx = store.transactions[0]
    assert tx.tx_type == "RECEIVE"
    assert tx.operator == "alice"
    assert tx.reference == "OPENING"
    assert tx.notes == "spreadsheet"


def test_inventory_failed_import_leaves_balances_and_transactions_unchanged(tmp_path):
    store, service = make_service(tmp_path)
    store.add_part("ABC-1", "Widget")
    path = write_csv(
        tmp_path / "inventory.csv",
        """
        part_number,location,lot_number,quantity
        ABC-1,Stock,LOT-1,5
        GHOST,Stock,LOT-2,2
        """,
    )

    with pytest.raises(ValueError):
        service.import_inventory_csv(path, "alice")

    assert store.stock_at("ABC-1", "Stock") == 0
    assert store.transactions == []


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("parent_part_number,component_part_number,quantity_per\nGHOST,COMP-1,1", "parent_part_number"),
        ("parent_part_number,component_part_number,quantity_per\nPARENT-1,GHOST,1", "component_part_number"),
        ("parent_part_number,component_part_number,quantity_per\nPARENT-1,PARENT-1,1", "component_part_number"),
        ("parent_part_number,component_part_number,quantity_per\nPARENT-1,COMP-1,0", "quantity_per"),
    ],
)
def test_bom_preview_rejects_invalid_rows(tmp_path, text, field):
    store, service = make_service(tmp_path)
    store.add_part("PARENT-1", "Parent")
    store.add_part("COMP-1", "Component")

    preview = service.preview_bom_import_csv(write_csv(tmp_path / "bom.csv", text))

    assert not preview.can_import
    assert any(error.field == field for error in preview.errors)


def test_bom_preview_rejects_duplicates_and_cycles(tmp_path):
    store, service = make_service(tmp_path)
    store.add_part("A", "A")
    store.add_part("B", "B")
    store.add_bom_component("A", "B", 1)
    duplicate = write_csv(
        tmp_path / "dup.csv",
        "parent_part_number,component_part_number,quantity_per\nA,B,1\nA,B,2",
    )
    cycle = write_csv(tmp_path / "cycle.csv", "parent_part_number,component_part_number,quantity_per\nB,A,1")

    assert any("Duplicate" in error.message for error in service.preview_bom_import_csv(duplicate).errors)
    assert any("circular BOM" in error.message for error in service.preview_bom_import_csv(cycle).errors)


def test_bom_import_creates_and_updates_links_and_creates_backup(tmp_path):
    store, service = make_service(tmp_path)
    store.add_part("KIT", "Kit")
    store.add_part("SCREW", "Screw")
    store.add_part("NUT", "Nut")
    store.add_bom_component("KIT", "SCREW", 1)
    path = write_csv(
        tmp_path / "bom.csv",
        """
        parent_part_number,component_part_number,quantity_per
        KIT,SCREW,4
        KIT,NUT,2
        """,
    )

    result = service.import_bom_csv(path, "alice")

    assert result.rows_imported == 2
    assert "pre-import" in result.backup_path
    assert store.bom_components["KIT"] == {"SCREW": 4, "NUT": 2}


def test_bom_failed_import_leaves_links_unchanged(tmp_path):
    store, service = make_service(tmp_path)
    store.add_part("KIT", "Kit")
    store.add_part("SCREW", "Screw")
    store.add_bom_component("KIT", "SCREW", 1)
    path = write_csv(
        tmp_path / "bom.csv",
        """
        parent_part_number,component_part_number,quantity_per
        KIT,SCREW,4
        KIT,GHOST,2
        """,
    )

    with pytest.raises(ValueError):
        service.import_bom_csv(path, "alice")

    assert store.bom_components["KIT"] == {"SCREW": 1}


def test_backup_filename_reason_suffixes_and_collision_safety(tmp_path, monkeypatch):
    db_path = tmp_path / "inventory.db"
    store = InventoryStore(db_path=db_path, seed=False)
    store.add_part("ABC-1", "Widget")

    class FixedDateTime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 6, 9, 12, 0, 0)

    monkeypatch.setattr(backup_mod, "datetime", FixedDateTime)
    first = backup_database(db_path, tmp_path / "backups", reason="manual")
    second = backup_database(db_path, tmp_path / "backups", reason="pre-import")
    third = backup_database(db_path, tmp_path / "backups", reason="manual")

    assert first.name == "inventory-20260609-120000-manual.db"
    assert second.name == "inventory-20260609-120000-pre-import.db"
    assert third.name == "inventory-20260609-120000-manual-01.db"


def test_backup_retention_keeps_newest_files(tmp_path):
    db_path = tmp_path / "inventory.db"
    store = InventoryStore(db_path=db_path, seed=False)
    store.add_part("ABC-1", "Widget")

    backup_database(db_path, tmp_path / "backups", keep=1, reason="manual")
    backup_database(db_path, tmp_path / "backups", keep=1, reason="pre-import")

    assert len(list((tmp_path / "backups").glob("inventory-*.db"))) == 1
