# Potential next deliverables — AIRCO Data Engineering

All items below read only from `output/sage_extract.sqlite` — no Docker / SQL Server needed.
Ordered by business value for the Odoo migration (go-live September 2026).

---

## High priority

### 1. Old→new article number mapping
- Resolve `KHKArtikel.Ersatzartikelnummer` chains transitively (A → B → C becomes A → C)
- Output: `output/Artikelnummern_Mapping_AIRCO.xlsx` — old number, new number, chain depth
- Prevents ghost / duplicate products in Odoo from retired article numbers
- Status: **not done**

### 2. Migration scope filter ("Migrieren Ja/Nein")
- One Excel sheet: `Artikelnummer`, name, group, active flag, supplier count, has-price, has-BOM, computed `Migrieren` column
- Exclusion criteria: `Aktiv = 0`, starts with `999`, empty `Bezeichnung1`, `IstEinmalartikel = Ja`
- Vanessa / Thorsten override rows before Odoo import runs — this is the decision gate
- Output: add sheet to `Artikelstamm_AIRCO.xlsx` or standalone `output/Migrationsliste_AIRCO.xlsx`
- Status: **not done**

### 3. BOM where-used (Verwendungsnachweis)
- Invert `KHKArtikelStueckliste`: for each component, which parent assemblies use it?
- Critical for spare-parts business: components used in many BOMs can't be safely archived
- Maps to Odoo `mrp.bom` — needed before any BOM import
- Output: add sheet `Verwendungsnachweis` to `Artikelstamm_AIRCO.xlsx`
- Status: **not done**

---

## Medium priority

### 4. Price completeness matrix
- Join `KHKArtikel` → `KHKVKPreise` (sales) → `KHKArtikelLieferant` (purchase)
- Flag articles with sales price but no purchase price (margin blind spot) and articles with neither (not ready for Odoo)
- Output: sheet `Preise_Vollstaendigkeit` in `Artikelstamm_AIRCO.xlsx`
- Status: **not done**

### 5. Supplier consolidation summary
- `KHKArtikelLieferant` grouped by `Lieferant`: article count, min/max/avg `Einzelpreis`, count with `Mindestbestellmenge > 0`
- Determines which Sage suppliers become Odoo `res.partner` records and which can be merged/dropped
- Output: add sheet to `Artikel_Lieferanten_AIRCO.xlsx`
- Status: **not done**

### 6. Product group hierarchy tree
- `KHKArtikelgruppen.VaterArtikelgruppe` is a self-referential parent FK — currently shown flat
- Build a multi-level pivot (Ebene 1 → 2 → 3) with article counts per node
- Maps directly to Odoo `product.category` hierarchy — functional team needs to validate the tree before import
- Output: replace / extend `Warengruppen` sheet in `Artikelstamm_AIRCO.xlsx`
- Status: partial (flat list only)

---

## Lower priority (fast to generate)

### 7. Duplicate candidates
- Same `Matchcode` or `HArtikelnummer` (manufacturer part number) on different `Artikelnummer` rows
- Not every hit is a real duplicate — output is a review list for Vanessa / Thorsten
- Output: sheet `Duplikate_Kandidaten` in `Artikelstamm_AIRCO.xlsx`
- Status: **not done**

### 8. Number range analysis
- `KHKNummernkreise` already in SQLite (included via `EXTRA_TABLES`)
- Odoo needs to know which number sequences to carry over vs. reset
- Output: sheet `Nummernkreise` — range name, prefix, last used number, format
- Status: **not done**

---

## Already done

- `output/sage_extract.sqlite` (~374 MB) — ~70 curated tables, 263,933 articles, 419 declared + 1,537 inferred relationships, 46 real FK constraints
- `output/Artikelstamm_AIRCO.xlsx` — Uebersicht (data-quality KPIs), Artikelstamm, Warengruppen (flat), Stuecklisten (BOM flat)
- `output/Artikel_Lieferanten_AIRCO.xlsx` — article ↔ supplier ↔ supplier part number + price
- FK teardown: `src/add_foreign_keys.py` rebuilds SQLite with real composite FK constraints for DBeaver ER diagram

## Still outstanding (from original scope)

- Final Docker teardown (`docker compose down -v` — reclaims ~187 GB on D:)
- Handoff / sign-off with Oliver, Vanessa, Thorsten, Jens
