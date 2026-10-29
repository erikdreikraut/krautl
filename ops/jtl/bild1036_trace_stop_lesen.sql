-- Stoppt zuerst die Aufzeichnung. Dateien bleiben auf dem SQL-Server erhalten.
USE master;
SET NOCOUNT ON;
IF NOT EXISTS (SELECT 1 FROM sys.dm_xe_sessions WHERE name=N'Krautl_Bild1036')
 THROW 50000, 'Keine laufende Aufzeichnung. Es werden keine alten Ergebnisse ausgegeben. Startmeldung prüfen.', 1;
SELECT dropped_event_count,dropped_buffer_count
FROM sys.dm_xe_sessions WHERE name=N'Krautl_Bild1036';
IF EXISTS(SELECT 1 FROM sys.dm_xe_sessions WHERE name=N'Krautl_Bild1036')
 ALTER EVENT SESSION [Krautl_Bild1036] ON SERVER STATE=STOP;
DECLARE @file nvarchar(4000);
SELECT @file=CONVERT(nvarchar(4000),f.value)
FROM sys.server_event_sessions s
JOIN sys.server_event_session_targets t ON t.event_session_id=s.event_session_id
JOIN sys.server_event_session_fields f ON f.event_session_id=t.event_session_id AND f.object_id=t.target_id
WHERE s.name=N'Krautl_Bild1036' AND t.name=N'event_file' AND f.name=N'filename';
IF @file IS NULL THROW 50000, 'Aufzeichnung oder Dateipfad nicht gefunden.', 1;
DECLARE @pattern nvarchar(4000)=LEFT(@file,LEN(@file)-4)+N'*.xel';
SELECT @pattern AS Gesicherte_Dateien;
;WITH events AS (
 SELECT CAST(event_data AS xml) AS x,file_name,file_offset
 FROM sys.fn_xe_file_target_read_file(@pattern,NULL,NULL,NULL)
), parsed AS (
 SELECT x.value('(event/@timestamp)[1]','datetime2(7)') AS Zeit_UTC,
 x.value('(event/@name)[1]','nvarchar(128)') AS Ereignis,
 x.value('(event/action[@name="session_id"]/value)[1]','int') AS Sitzung,
 x.value('(event/data[@name="object_id"]/value)[1]','int') AS Objekt_ID,
 x.value('(event/data[@name="statement"]/value)[1]','nvarchar(max)') AS Anweisung,
 file_name,file_offset FROM events
)
SELECT Zeit_UTC,Ereignis,Sitzung,Objekt_ID,
 OBJECT_SCHEMA_NAME(Objekt_ID,DB_ID(N'eazybusiness')) AS Objektschema,
 OBJECT_NAME(Objekt_ID,DB_ID(N'eazybusiness')) AS Objektname,
 LEFT(Anweisung,4000) AS Anweisung_bis_4000_Zeichen,
 LEN(Anweisung) AS Original_Zeichen,file_name,file_offset
FROM parsed ORDER BY Zeit_UTC,file_name,file_offset;
-- Nach erfolgreichem Export separat ausführbar. Löscht keine XEL-Dateien:
-- DROP EVENT SESSION [Krautl_Bild1036] ON SERVER;
