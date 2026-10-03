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

**Low stock**:
An active Part whose total stock is at or below its positive minimum quantity. A Part with a minimum quantity of zero is not classified as low stock.
