/* ============================================================================
   Records-only extract of the AIRCO database's RELATIONAL tables, EXCLUDING the
   large document/BLOB archive tables (that archive is the bulk of the ~130 GB and
   is NOT needed for the article master / migration).

   - Reads the source read-only (SELECT INTO), writes into a separate temp DB.
   - Backs that small DB up to a movable .bak, then drops the temp DB.
   - A table is skipped when its size exceeds @MaxTableMB (documents/BLOBs).

   Run in SSMS while connected to the AIRCO database (needs rights to CREATE/BACKUP
   a DB; sa works). Adjust @OutFile / @MaxTableMB if needed.
   ============================================================================ */

USE [AIRCO];                          -- <-- source = the Mandant DB
SET NOCOUNT ON;

DECLARE @ExtractDb sysname       = N'AIRCO_Extract';
DECLARE @OutFile   nvarchar(400) = N'C:\Temp\AIRCO_Extract.bak';  -- reachable path on the server
DECLARE @MaxTableMB int          = 1000;    -- skip tables larger than this (the document archive)

/* 1) fresh temp extract DB (separate from AIRCO; source is never modified) */
IF DB_ID(@ExtractDb) IS NOT NULL
    EXEC(N'ALTER DATABASE '+QUOTENAME(@ExtractDb)+N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE '+QUOTENAME(@ExtractDb)+N';');
EXEC(N'CREATE DATABASE '+QUOTENAME(@ExtractDb)+N';');

/* 2) size of every table in the current (source) DB */
DECLARE @sizes TABLE (sch sysname, tbl sysname, size_mb decimal(12,1));
INSERT INTO @sizes
SELECT s.name, t.name, CAST(SUM(ps.reserved_page_count) * 8 / 1024.0 AS decimal(12,1))
FROM sys.dm_db_partition_stats ps
JOIN sys.tables  t ON t.object_id = ps.object_id
JOIN sys.schemas s ON s.schema_id = t.schema_id
WHERE ps.index_id IN (0, 1)
GROUP BY s.name, t.name;

/* 3) copy the rows of the SMALL tables into the extract DB (SELECT INTO = no indexes) */
DECLARE @sch sysname, @tbl sysname, @mb decimal(12,1), @sql nvarchar(max);
DECLARE c CURSOR LOCAL FAST_FORWARD FOR SELECT sch, tbl, size_mb FROM @sizes ORDER BY size_mb DESC;
OPEN c; FETCH NEXT FROM c INTO @sch, @tbl, @mb;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF @mb > @MaxTableMB
        PRINT 'SKIP (' + CAST(@mb AS varchar(20)) + ' MB): ' + @sch + '.' + @tbl;
    ELSE
    BEGIN
        SET @sql = N'SELECT * INTO ' + QUOTENAME(@ExtractDb) + N'.' + QUOTENAME(@sch) + N'.' + QUOTENAME(@tbl) +
                   N' FROM ' + QUOTENAME(@sch) + N'.' + QUOTENAME(@tbl) + N';';
        BEGIN TRY EXEC(@sql); END TRY
        BEGIN CATCH PRINT '  ! ' + @sch + '.' + @tbl + ' : ' + ERROR_MESSAGE(); END CATCH
    END
    FETCH NEXT FROM c INTO @sch, @tbl, @mb;
END
CLOSE c; DEALLOCATE c;

/* 4) back up the slim extract DB (compressed if supported) */
DECLARE @bk nvarchar(max) = N'BACKUP DATABASE ' + QUOTENAME(@ExtractDb) +
    N' TO DISK = N''' + @OutFile + N''' WITH INIT, COMPRESSION, STATS = 10;';
BEGIN TRY EXEC(@bk); END TRY
BEGIN CATCH
    EXEC(N'BACKUP DATABASE ' + QUOTENAME(@ExtractDb) + N' TO DISK = N''' + @OutFile + N''' WITH INIT, STATS = 10;');
END CATCH

/* 5) drop the temp DB (keep the .bak) */
EXEC(N'ALTER DATABASE ' + QUOTENAME(@ExtractDb) + N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE ' + QUOTENAME(@ExtractDb) + N';');
PRINT 'Done. Move this file to your laptop -> restore/ : ' + @OutFile;
