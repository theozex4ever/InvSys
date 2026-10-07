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

**BOM (bill of materials)**:
Parent-to-component links that specify the quantity of each component needed for one parent. BOMs can be nested.

**Phantom assembly**:
A BOM parent recorded on a shipment without deducting stock for the parent or intermediate assemblies. Shipping consumes the required leaf materials instead.

**Leaf material**:
A Part with no child BOM in the selected BOM traversal. Its required quantity includes every path through the nested BOM.

**BOM availability**:
The leaf requirements and stock at a selected Location for a requested quantity, plus the shortages and build capacity derived from those same requirements.

**Build capacity**:
The number of final products that current leaf stock at a selected Location can fulfill. A material shared by multiple BOM branches counts toward one aggregated requirement per final product.

**BOM lot allocation**:
The store's automatic assignment of required leaf materials to positive-stock Lots at the shipping Location, in lot-number order. The operator reviews the assignment before shipping; a changed assignment requires another review.

**Shipment review**:
A point-in-time assessment of stock availability and expected consumption for a requested quantity of a Part at a Location. For a Part with a BOM, it includes the required leaf materials and their BOM lot allocations.
