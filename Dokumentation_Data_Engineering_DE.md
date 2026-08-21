# Data Engineering – Ablauf und Ergebnis

**Projekt:** AIRCO-Systems GmbH · Altdaten aus Sage 100 für die Odoo-Migration
**Bearbeitung:** mosaiic GmbH · **Stand:** 17.08.2026

> Dieses Dokument erklärt in einfacher Sprache, **was wir gemacht haben und warum** –
> gedacht zum Verstehen und Weitererzählen (kein technisches Handbuch). Fachbegriffe
> sind am Ende im Glossar erklärt.

---

## 1. Ziel in einem Satz

Wir machen die Altdaten aus dem bisherigen System **Sage 100** nutzbar: Wir holen den
kompletten **Artikelstamm** (alle Artikel mit ihren Nummern) samt zugehöriger
Geschäftsdaten und deren **Verknüpfungen** in **eine einzige, handliche Datei** – als
Grundlage für die Bereinigung und die Migration nach **Odoo** (Go-Live September 2026).

## 2. Ausgangslage

- Es gibt **keinen direkten Zugang** zur Live-Datenbank von AIRCO (internes Netz, kein
  externer Login).
- Wir haben stattdessen ein **vollständiges Backup** der Sage-100-Datenbank erhalten:
  eine Datei von **ca. 130 GB**, abgelegt in einem OneDrive-/SharePoint-Ordner.
- Wichtig: Dieses Backup enthält **nicht nur** die eigentlichen Geschäftsdaten, sondern
  auch ein riesiges **Dokumentenarchiv** (gescannte Belege o. Ä.) direkt in der
  Datenbank – das macht den Löwenanteil der 130 GB aus. Für unsere Aufgabe brauchen wir
  davon **nichts**; die relevanten Artikel-/Stammdaten sind nur wenige Dutzend MB.

## 3. Die Herausforderungen – und wie wir sie gelöst haben

| Herausforderung | Lösung |
|---|---|
| Die 130-GB-Datei lag nur in der Cloud (OneDrive-„Platzhalter", 0 Byte lokal). | Datei zunächst **vollständig heruntergeladen** („Immer auf diesem Gerät behalten"). |
| Auf dem Systemlaufwerk (C:) war **zu wenig Platz** für die Wiederherstellung. | Die Arbeitsablage der Test-Datenbank auf die **große Platte (D:)** verlegt. |
| Die Datenbank ist technisch **nicht teilbar** – man kann nicht „nur die Artikeltabellen" einspielen. | **Ganze Datenbank** wiederhergestellt (inkl. Dokumentenarchiv) und danach **nur die relevanten Daten** herausgezogen. |
| Das **Produktivsystem darf nicht gefährdet** werden. | Alles läuft in einer **abgeschotteten, wegwerfbaren Test-Datenbank**; das Backup wird nur **lesend** verwendet; das AIRCO-System wurde nie berührt. |

## 4. Vorgehen Schritt für Schritt

1. **Backup lokal verfügbar gemacht** – die 130-GB-Datei aus der Cloud vollständig
   heruntergeladen.
2. **Abgeschottete Test-Datenbank aufgesetzt** – ein „Wegwerf"-Datenbankserver auf dem
   eigenen Rechner (Technik: SQL Server in einem Docker-Container).
3. **Backup wiederhergestellt** (~26 Minuten). Ergebnis: die vollständige
   AIRCO-Datenbank steht lokal zur Analyse bereit.
4. **Datenbank inventarisiert** – Überblick verschafft: 891 Tabellen; der Artikelstamm
   (Tabelle `KHKArtikel`) enthält **263.933 Artikel** mit je 114 Merkmalen (u. a.
   Artikelnummer, Bezeichnungen, Warengruppe, Hersteller, Kennzeichen
   „Verkaufsartikel/Bestellartikel", Stücklisten-Typ).
5. **Relevante Geschäftsdaten + Verknüpfungen extrahiert** – in **eine Datei**
   (`sage_extract.sqlite`, ~374 MB). Enthalten: Artikel, Artikelvarianten,
   Lieferanten-Zuordnungen, Kunden/Adressen, Stücklisten, Preislisten, Warengruppen,
   Nummernkreise, Lager – **plus die Beziehungen** dazwischen. Das 169-GB-Dokumentenarchiv
   wurde bewusst **weggelassen**.
6. **Echte Beziehungen ergänzt** – die Verknüpfungen zwischen den Tabellen so hinterlegt,
   dass sie sich als **Diagramm** darstellen und per Klick navigieren lassen.
7. **Daten sichtbar gemacht** – über einen kleinen **Web-Viewer im Browser** (Datasette)
   bzw. das Desktop-Tool **DBeaver**: durchsehen, filtern, verknüpfen – **ohne
   Programmierung**.

## 5. Was jetzt vorliegt (das Ergebnis)

- **Eine einzige Datei** `sage_extract.sqlite` (~374 MB), die man frei kopieren, öffnen,
  durchsuchen und auswerten kann – ohne spezielle Server-Infrastruktur.
- Darin: die zentralen **Geschäftsobjekte** (Artikel, Lieferanten, Kunden/Adressen,
  Stücklisten, Preise, Warengruppen, Nummernkreise, Lager) und die **Beziehungen**
  zwischen ihnen. Die Beziehungen sind dokumentiert (als „vom System bestätigt" bzw. „von
  uns abgeleitet"); die wichtigsten sind zusätzlich als **navigierbares Diagramm**
  hinterlegt.
- **Ansehen** im Browser unter `http://localhost:8001` oder in DBeaver (inkl.
  Beziehungsdiagramm).

## 6. Warum das wertvoll ist

- Erstmals **voller, verlässlicher Überblick** über den tatsächlichen Artikelstamm –
  bisher gab es dazu nur widersprüchliche Einzelaussagen.
- **Grundlage für die Bereinigung**: echtes Produkt vs. Ersatzteil, Dubletten, „Müll" auf
  der frei vergebbaren Sammelnummer 999 – und für die **Attribuierung** im Sinne des
  Odoo-Modells (Ware/Dienstleistung, verkaufbar/einkaufbar, Stückliste).
- **Basis für die Odoo-Migration** – inklusive der Möglichkeit, ein
  **Alt-/Neu-Nummern-Mapping** aufzubauen (alte und neue Artikelnummer parallel führen,
  damit Ersatzteil-Bestellungen zu Altanlagen auffindbar bleiben).
- Wiederverwendbar für **Sofortmaßnahmen** (Aftersales, Service, Vertrieb) gemäß
  Projektskizze.

## 7. Grundsätze, die wir eingehalten haben

- **Produktivsystem nie angefasst** – ausschließlich Arbeit mit einer Backup-Kopie in
  einer abgeschotteten Umgebung.
- **Keine Kundendaten im Programm-Repository** – die großen Datendateien bleiben lokal.
- **Nachvollziehbarkeit** – jeder Schritt ist als kleines, wiederholbares Skript
  festgehalten; Beziehungen sind als „deklariert" (vom System bestätigt) oder „abgeleitet"
  (von uns erschlossen) gekennzeichnet.

## 8. Nächste Schritte (Vorschlag)

1. **Excel-Artikelliste** aus der Datei erzeugen – gut lesbar für die fachliche Prüfung
   (z. B. mit Vanessa): Artikelnummer, Bezeichnungen, Warengruppe, Hersteller-Nummer,
   Verkauf/Einkauf-Kennzeichen, Stückliste – plus ein **Datenqualitäts-Blatt**
   (Auffälligkeiten wie Nummer 999, fehlende Angaben).
2. **Bereinigung und Attribuierung** gemeinsam mit AIRCO.
3. **Speicher freigeben** – die große Test-Datenbank nach Abschluss löschen; die
   Ergebnis-Datei bleibt erhalten.

## 9. Glossar (Fachbegriffe kurz erklärt)

- **Sage 100** – das bisherige ERP-/Warenwirtschaftssystem von AIRCO.
- **Odoo** – das künftige ERP-System (Ziel der Migration).
- **Backup / `.bak`-Datei** – eine vollständige Sicherungskopie einer Datenbank.
- **Restore (Wiederherstellung)** – das Backup wieder in eine lauffähige Datenbank
  einspielen.
- **SQL Server** – das Datenbanksystem, in dem Sage 100 seine Daten speichert.
- **Docker / Container** – eine „Sandbox" auf dem eigenen Rechner, in der wir eine
  wegwerfbare Test-Datenbank betreiben – sauber getrennt vom übrigen System.
- **Filegroup** – interne Speicher-Einteilung einer Datenbank; hier liegt alles in einem
  Block, daher nicht teilweise wiederherstellbar.
- **SQLite** – ein sehr einfaches, dateibasiertes Datenbankformat: die ganze Datenbank
  ist **eine Datei**, ohne Server, überall lesbar.
- **Foreign Key (Fremdschlüssel)** – eine definierte Verknüpfung zwischen Tabellen (z. B.
  „diese Stücklisten-Zeile gehört zu jenem Artikel").
- **Mandant** – die Firma/der Buchungskreis in Sage; hier „AIRCO".
- **KHK…-Tabellen** – die technischen Namen der Sage-Tabellen (z. B. `KHKArtikel` =
  Artikelstamm).
- **Datasette / DBeaver** – Werkzeuge zum Ansehen und Abfragen der Daten (im Browser bzw.
  als Desktop-Programm), ohne Programmierkenntnisse bedienbar.

---
*Erstellt im Rahmen des Arbeitspakets „Data Engineering" (mosaiic GmbH für
AIRCO-Systems GmbH).*
