# Inventory Control

Parts, their lot-traceable stock, and the inventory activity that accounts for it.

## Language

**Part**:
A catalog item tracked by part number. A Part can be a finished product, an intermediate assembly, or a material.

**Lot**:
A traceable batch of one Part, identified by a lot number within that Part.

**Location**:
A named place where stock is held. An inactive Location can still hold stock recorded there earlier.

**Stock balance**:
The quantity of a Part in a particular Lot at a Location. A Part's total stock includes its balances across all Lots and Locations.

**Stock ledger**:
The transaction log together with the Stock balances it accounts for. Every balance change is posted to the ledger as a transaction row in the same database transaction. Phantom BOM rows are recorded without a balance change.

**Low stock**:
An active Part whose total stock is at or below its positive minimum quantity. A Part with a minimum quantity of zero is not classified as low stock.

**Shipment review**:
A point-in-time assessment of stock availability and expected consumption for a requested quantity of a Part at a Location. For a Part with a BOM, it includes the required leaf materials and their Lot allocations.
