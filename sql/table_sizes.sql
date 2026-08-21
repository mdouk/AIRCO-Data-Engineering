/* Read-only diagnostic: which tables make up the AIRCO database size?
   Safe metadata query (no data scan). Run in SSMS against the AIRCO DB.
   The document/BLOB archive tables will be at the top (multi-GB); the master
   tables we need (KHKArtikel, ...) will be tiny further down. */

USE [AIRCO];
SELECT TOP 40
    s.name                                                      AS [schema],
    t.name                                                      AS [table],
    SUM(ps.row_count)                                           AS row_count,
    CAST(SUM(ps.reserved_page_count) * 8 / 1024.0 AS decimal(12,1)) AS size_mb
FROM sys.dm_db_partition_stats ps
JOIN sys.tables  t ON t.object_id = ps.object_id
JOIN sys.schemas s ON s.schema_id = t.schema_id
WHERE ps.index_id IN (0, 1)
GROUP BY s.name, t.name
ORDER BY size_mb DESC;
