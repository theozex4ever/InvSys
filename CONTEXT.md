# Inventory Control domain terms

- **Part**: A catalog item tracked by part number. A part can be a finished product, an intermediate assembly, or a material.
- **BOM (bill of materials)**: Parent-to-component links that specify the quantity of each component needed for one parent. BOMs can be nested.
- **Phantom assembly**: A BOM parent recorded on a shipment without deducting stock for the parent or intermediate assemblies. Shipping consumes the required leaf materials instead.
- **Leaf material**: A part with no child BOM in the selected BOM traversal. Its required quantity includes every path through the nested BOM.
- **BOM availability**: The leaf requirements and stock at a selected location for a requested quantity, plus the shortages and final-product build capacity derived from those same requirements.
- **Build capacity**: The number of final products that current leaf stock at a selected location can fulfill. A material shared by multiple BOM branches counts toward one aggregated requirement per final product.
- **Lot**: A traceable batch of a part. BOM shipment consumes automatically allocated lots of leaf materials.
- **BOM lot allocation**: The store's automatic assignment of required leaf materials to positive-stock lots at the shipping location, in lot-number order. The operator reviews the assignment before shipping; a changed assignment requires another review.
