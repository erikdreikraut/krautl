-- SSMS, Wawi-SQL-Server. Keine Artikeldatenänderung.
USE master;
SET NOCOUNT ON;
DECLARE @pid int = 7768;
DECLARE @host nvarchar(128) = N'K21153W5072';
DECLARE @db int = DB_ID(N'eazybusiness');
IF @db IS NULL THROW 50000, 'Datenbank eazybusiness fehlt.', 1;
IF NOT EXISTS (SELECT 1 FROM sys.dm_exec_sessions WHERE host_process_id=@pid
 AND host_name=@host AND database_id=@db AND program_name LIKE N'%JTL-Wawi%')
 THROW 50000, 'Wawi-PID nicht mehr aktuell. Im Task-Manager prüfen und oben anpassen.', 1;
IF EXISTS (SELECT 1 FROM sys.dm_xe_sessions WHERE name=N'Krautl_Bild1036')
 THROW 50000, 'Aufzeichnung läuft bereits. Erst mit Stoppskript sichern; kein Neustart ausgeführt.', 1;
IF NOT EXISTS (SELECT 1 FROM sys.dm_xe_objects WHERE name=N'client_pid' AND object_type=N'pred_source')
 THROW 50000, 'XE-Filter client_pid nicht verfügbar. Nicht ungefiltert fortfahren.', 1;
DECLARE @log nvarchar(4000)=CONVERT(nvarchar(4000),SERVERPROPERTY('ErrorLogFileName'));
IF @log IS NULL OR CHARINDEX(N'\',REVERSE(@log))=0
 THROW 50000, 'SQL-Logverzeichnis nicht ermittelbar.', 1;
DECLARE @file nvarchar(4000)=LEFT(@log,LEN(@log)-CHARINDEX(N'\',REVERSE(@log))+1)
 + N'Krautl_Bild1036_' + REPLACE(CONVERT(nvarchar(36),NEWID()),N'-',N'') + N'.xel';
DECLARE @filter nvarchar(max)=N' WHERE ([sqlserver].[client_pid]=('+CONVERT(nvarchar(12),@pid)
 +N') AND [sqlserver].[client_hostname]=N'''+REPLACE(@host,N'''',N'''''')
 +N''' AND [sqlserver].[database_id]=('+CONVERT(nvarchar(12),@db)+N'))';
DECLARE @actions nvarchar(max)=N'ACTION(sqlserver.session_id,sqlserver.client_pid,sqlserver.database_name)';
DECLARE @sql nvarchar(max)=N'CREATE EVENT SESSION [Krautl_Bild1036] ON SERVER
 ADD EVENT sqlserver.module_end('+@actions+@filter+N'),
 ADD EVENT sqlserver.sp_statement_completed('+@actions+@filter+N'),
 ADD EVENT sqlserver.sql_statement_completed('+@actions+@filter+N')
 ADD TARGET package0.event_file(SET filename=N'''+REPLACE(@file,N'''',N'''''')+N''',max_file_size=(20),max_rollover_files=(2))
 WITH(MAX_MEMORY=4096 KB,EVENT_RETENTION_MODE=ALLOW_SINGLE_EVENT_LOSS,
 MAX_DISPATCH_LATENCY=1 SECONDS,TRACK_CAUSALITY=ON,STARTUP_STATE=OFF);';
BEGIN TRY
 -- Nur eine gestoppte Definition entfernen. Vorhandene XEL-Dateien bleiben erhalten.
 IF EXISTS (SELECT 1 FROM sys.server_event_sessions WHERE name=N'Krautl_Bild1036')
  DROP EVENT SESSION [Krautl_Bild1036] ON SERVER;
 EXEC sys.sp_executesql @sql;
 ALTER EVENT SESSION [Krautl_Bild1036] ON SERVER STATE=START;
 IF NOT EXISTS (SELECT 1 FROM sys.dm_xe_sessions WHERE name=N'Krautl_Bild1036')
  THROW 50000, 'Aufzeichnung wurde nicht gestartet. Bild nicht ersetzen.', 1;
 SELECT N'AUFZEICHNUNG LAEUFT - jetzt Austausch und Speichern, danach sofort Stoppskript.' AS Status,
  SYSDATETIMEOFFSET() AS Kontrollzeit_mit_Zeitzone,
  @pid AS Wawi_PID,@host AS Wawi_Rechner,@file AS Neue_Datei;
END TRY
BEGIN CATCH
 THROW;
END CATCH;
