"""Generate reviewable Excel workbooks from output/sage_extract.sqlite.

Produces (in output/):
  - Artikelstamm_AIRCO.xlsx : Uebersicht (key figures + data-quality flags),
    Artikelstamm (one row per article, readable columns + product-group name +
    supplier count + BOM flag), Warengruppen, Stuecklisten (BOM).
  - Artikel_Lieferanten_AIRCO.xlsx : article <-> supplier <-> supplier part no + price.

Reads only the SQLite file — no SQL Server needed. Everything is German (Sage column
names kept, since the functional reviewers know them).

    python src/extract_artikelstamm.py
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime

import pandas as pd

DB = "output/sage_extract.sqlite"
OUT_MAIN = "output/Artikelstamm_AIRCO.xlsx"
OUT_SUPP = "output/Artikel_Lieferanten_AIRCO.xlsx"

HEADER_BG = "#1F3864"

# Curated, readable columns from KHKArtikel (only those that exist are used).
ART_COLS = [
    "Artikelnummer", "Bezeichnung1", "Bezeichnung2", "Matchcode",
    "Artikelgruppe", "Artikelart", "Stuecklistentyp",
    "IstVerkaufsartikel", "IstBestellartikel", "IstErsatzteil", "IstVerschleissteil",
    "IstFertigungsartikel", "IstUnterbaugruppe", "IstEinmalartikel",
    "Ersatzartikelnummer", "Hersteller", "HArtikelnummer", "Zeichnungsnummer",
    "Basismengeneinheit", "Verkaufsmengeneinheit", "Lagermengeneinheit",
    "Lagerfuehrung", "Chargenpflicht", "Aktiv", "Warennummer", "Ursprungsland",
]
FLAG_COLS = [
    "IstVerkaufsartikel", "IstBestellartikel", "IstErsatzteil", "IstVerschleissteil",
    "IstFertigungsartikel", "IstUnterbaugruppe", "IstEinmalartikel",
    "Lagerfuehrung", "Chargenpflicht", "Aktiv",
]


def write_sheet(writer, df: pd.DataFrame, sheet: str) -> None:
    df.to_excel(writer, sheet_name=sheet[:31], index=False)
    wb, ws = writer.book, writer.sheets[sheet[:31]]
    hdr = wb.add_format({"bold": True, "bg_color": HEADER_BG, "font_color": "white", "border": 1})
    for i, col in enumerate(df.columns):
        ws.write(0, i, str(col), hdr)
        sample = df[col].astype(str).head(2000)
        width = min(max(len(str(col)) + 2, (sample.str.len().max() if len(sample) else 10) + 1), 48)
        ws.set_column(i, i, width)
    if len(df):
        ws.autofilter(0, 0, len(df), len(df.columns) - 1)
    ws.freeze_panes(1, 0)


def main() -> None:
    if not os.path.exists(DB):
        raise SystemExit(f"{DB} not found — run export_to_sqlite.py first.")
    con = sqlite3.connect(DB)
    q = lambda s: pd.read_sql(s, con)

    existing = {r[1] for r in con.execute('PRAGMA table_info("KHKArtikel")')}
    present = [c for c in ART_COLS if c in existing]
    collist = ", ".join('"%s"' % c for c in present)
    art = q(f"SELECT {collist}, Mandant FROM KHKArtikel")

    # product-group name (dedupe so a group code can't multiply article rows)
    grp = q('SELECT Mandant, Artikelgruppe, Bezeichnung AS Warengruppe FROM KHKArtikelgruppen') \
        .drop_duplicates(subset=["Mandant", "Artikelgruppe"])
    art = art.merge(grp, on=["Mandant", "Artikelgruppe"], how="left")

    # supplier count per article
    sc = q("""SELECT Mandant, Artikelnummer, COUNT(*) AS AnzahlLieferanten
              FROM KHKArtikelLieferant GROUP BY Mandant, Artikelnummer""")
    art = art.merge(sc, on=["Mandant", "Artikelnummer"], how="left")
    art["AnzahlLieferanten"] = art["AnzahlLieferanten"].fillna(0).astype(int)

    # BOM parent flag
    bomp = q("SELECT DISTINCT Mandant, Stueckliste AS Artikelnummer FROM KHKArtikelStueckliste")
    bomp["HatStueckliste"] = 1
    art = art.merge(bomp, on=["Mandant", "Artikelnummer"], how="left")
    art["HatStueckliste"] = art["HatStueckliste"].fillna(0).astype(int)

    # ---- data-quality metrics (from raw numeric values, before Ja/Nein mapping) ----
    def cnt(mask) -> int:
        return int(mask.sum())
    # Sage 'bit' TRUE arrives as -1 via pymssql/FreeTDS, so truthy = non-zero (not ==1).
    b = lambda c: (art[c].fillna(0) != 0) if c in art else pd.Series(False, index=art.index)
    total = len(art)
    metrics = [
        ("Gesamtzahl Artikel", total),
        ("davon Verkaufsartikel", cnt(b("IstVerkaufsartikel"))),
        ("davon Bestellartikel", cnt(b("IstBestellartikel"))),
        ("Verkauf UND Einkauf", cnt(b("IstVerkaufsartikel") & b("IstBestellartikel"))),
        ("weder Verkauf noch Einkauf", cnt(~b("IstVerkaufsartikel") & ~b("IstBestellartikel"))),
        ("als Ersatzteil markiert", cnt(b("IstErsatzteil"))),
        ("als Verschleissteil markiert", cnt(b("IstVerschleissteil"))),
        ("Fertigungsartikel", cnt(b("IstFertigungsartikel"))),
        ("Unterbaugruppen", cnt(b("IstUnterbaugruppe"))),
        ("mit Stueckliste (Vater)", cnt(art["HatStueckliste"] == 1)),
        ("mit mindestens 1 Lieferant", cnt(art["AnzahlLieferanten"] > 0)),
        ("inaktiv (Aktiv = Nein)", cnt(art["Aktiv"] == 0) if "Aktiv" in art else 0),
        ("ohne Bezeichnung1", cnt(art["Bezeichnung1"].isna() | (art["Bezeichnung1"].astype(str).str.strip() == ""))),
        ("ohne zugeordnete Warengruppe", cnt(art["Warengruppe"].isna())),
        ("Artikelnummer beginnt mit '999'", cnt(art["Artikelnummer"].astype(str).str.strip().str.startswith("999"))),
        ("Anzahl Warengruppen", len(grp)),
        ("Anzahl Lieferanten-Zuordnungen", int(sc["AnzahlLieferanten"].sum())),
        ("Anzahl Stuecklisten-Positionen", int(q("SELECT COUNT(*) n FROM KHKArtikelStueckliste").iloc[0, 0])),
    ]
    uebersicht = pd.DataFrame(metrics, columns=["Kennzahl", "Wert"])

    # ---- Warengruppen with counts ----
    grp_full = q("""SELECT Artikelgruppe, Bezeichnung, VaterArtikelgruppe,
                           Gruppenebene, HatUntergruppen FROM KHKArtikelgruppen""")
    gc = art.groupby("Artikelgruppe").size().rename("AnzahlArtikel").reset_index()
    warengruppen = grp_full.merge(gc, on="Artikelgruppe", how="left")
    warengruppen["AnzahlArtikel"] = warengruppen["AnzahlArtikel"].fillna(0).astype(int)
    warengruppen = warengruppen.sort_values("AnzahlArtikel", ascending=False)

    # ---- Stuecklisten (BOM) with names ----
    bom = q("""SELECT s.Stueckliste AS "Vater-Artikel", pa.Bezeichnung1 AS "Vater-Bezeichnung",
                      s.Element AS "Komponente", ka.Bezeichnung1 AS "Komponenten-Bezeichnung",
                      s.Menge, s.Sortierung
               FROM KHKArtikelStueckliste s
               LEFT JOIN KHKArtikel pa ON pa.Artikelnummer=s.Stueckliste AND pa.Mandant=s.Mandant
               LEFT JOIN KHKArtikel ka ON ka.Artikelnummer=s.Element   AND ka.Mandant=s.Mandant
               ORDER BY s.Stueckliste, s.Sortierung""")

    # ---- prettify Artikelstamm for output ----
    for c in FLAG_COLS:
        if c in art:  # bit TRUE = -1 via FreeTDS; non-zero -> "Ja"
            art[c] = art[c].map(lambda v: "" if pd.isna(v) else ("Ja" if v != 0 else "Nein"))
    ordered = present + ["Warengruppe", "AnzahlLieferanten", "HatStueckliste"]
    art_out = art[[c for c in ordered if c in art.columns]].copy()
    art_out["HatStueckliste"] = art_out["HatStueckliste"].map({1: "Ja", 0: "Nein"})

    os.makedirs("output", exist_ok=True)
    stamp = datetime.now().strftime("%d.%m.%Y %H:%M")
    with pd.ExcelWriter(OUT_MAIN, engine="xlsxwriter") as w:
        note = pd.DataFrame({"Kennzahl": [f"Quelle: sage_extract.sqlite (Sage 100 / Mandant AIRCO)",
                                          f"Erstellt: {stamp}", ""], "Wert": ["", "", ""]})
        write_sheet(w, pd.concat([note, uebersicht], ignore_index=True), "Uebersicht")
        write_sheet(w, art_out, "Artikelstamm")
        write_sheet(w, warengruppen, "Warengruppen")
        write_sheet(w, bom, "Stuecklisten")
    print(f"Wrote {OUT_MAIN}  ({os.path.getsize(OUT_MAIN)/1e6:.1f} MB, {len(art_out):,} Artikel)")

    # ---- supplier workbook (pandas merge — a SQLite join here is pathologically slow) ----
    lief = q("""SELECT Artikelnummer, Mandant, Lieferant,
                       Bestellnummer AS "Lieferanten-Bestellnr", Bezeichnung1 AS "Lief-Bezeichnung1",
                       Einzelpreis, Rabattsatz, Mindestbestellmenge, Wiederbeschaffungszeit,
                       Einkaufsmengeneinheit
                FROM KHKArtikelLieferant""")
    anames = q('SELECT Artikelnummer, Mandant, Bezeichnung1 AS "Artikel-Bezeichnung" FROM KHKArtikel') \
        .drop_duplicates(subset=["Artikelnummer", "Mandant"])
    supp = (lief.merge(anames, on=["Artikelnummer", "Mandant"], how="left")
                .sort_values(["Artikelnummer", "Lieferant"])
                .drop(columns=["Mandant"]))
    supp = supp[["Artikelnummer", "Artikel-Bezeichnung", "Lieferant", "Lieferanten-Bestellnr",
                 "Lief-Bezeichnung1", "Einzelpreis", "Rabattsatz", "Mindestbestellmenge",
                 "Wiederbeschaffungszeit", "Einkaufsmengeneinheit"]]
    with pd.ExcelWriter(OUT_SUPP, engine="xlsxwriter") as w:
        write_sheet(w, supp, "Lieferanten_je_Artikel")
    print(f"Wrote {OUT_SUPP}  ({os.path.getsize(OUT_SUPP)/1e6:.1f} MB, {len(supp):,} Zuordnungen)")

    con.close()


if __name__ == "__main__":
    main()
