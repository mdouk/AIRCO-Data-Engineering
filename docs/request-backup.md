# Requesting the Sage 100 backup from AIRCO

A **recent full backup already exists**, so the only ask is a **file handover** — no
one at AIRCO needs to install or run anything of ours. Everything (restore, extraction)
happens on our side from that copy.

## What we need
- The recent **full `.bak`** of the **Sage 100 company (Mandant) database** — the one
  behind Sage 100 (`SAGE 100 (6GB + 170 GB Dokumente)` on the SQL Server / TS-FIBU).
  *We need the ~6 GB database backup, not the 170 GB documents.*
- Ideally **compressed/zipped** (a `.bak` shrinks a lot).
- A transfer channel: **SharePoint / FileServer link**, or a drive.

## Nice to have (not blocking)
- The **database name** (so we target the right Mandant DB).
- Which **SQL Server version** produced it (2016 / 2017 / 2019 / 2022) — lets us match
  the restore engine. If unknown, no problem: our restore step reads it from the file.

## Why AIRCO can say yes without worry
- A **full backup is read-only** against the live DB and **non-destructive** — the most
  routine SQL Server operation. If it's the existing nightly file, that work is already done.
- **Nothing of ours runs on AIRCO systems.** We restore into a disposable, isolated
  local container and work only on that copy. Production is never touched.

---

## Ready-to-send message (DE)

> Betreff: Sage-100-Datenbank – vorhandenes Backup zur Auswertung
>
> Hallo Oliver,
>
> für das Data-Engineering (Aufbereitung des Artikelstamms für die ODOO-Migration)
> bräuchten wir eine **Kopie des kürzlich erstellten Voll-Backups der Sage-100-Datenbank**
> (die ~6-GB-Datenbank, nicht die 170 GB Dokumente).
>
> Es muss dafür **nichts installiert oder ausgeführt werden** – wir arbeiten
> ausschließlich mit dieser Kopie auf unserer Seite; das Produktivsystem wird nicht
> berührt. Am einfachsten wäre die `.bak`-Datei **gezippt** über einen
> **SharePoint-/FileServer-Link**.
>
> Falls bekannt, wären zwei Angaben hilfreich (sonst kein Problem):
> - Name der Datenbank (Mandant),
> - SQL-Server-Version (2016/2017/2019/2022).
>
> Vielen Dank und viele Grüße
