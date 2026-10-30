-- Einmalige Einrichtung der eigenen Transaktionsquittungen, keine Bildaenderung.
USE eazybusiness;
SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF SCHEMA_ID(N'KrautlBilddienst') IS NULL
    EXEC(N'CREATE SCHEMA KrautlBilddienst AUTHORIZATION dbo');
IF OBJECT_ID(N'KrautlBilddienst.Auftrag', N'U') IS NULL
BEGIN
    CREATE TABLE KrautlBilddienst.Auftrag (
        Auftrag uniqueidentifier NOT NULL PRIMARY KEY,
        Artikel int NOT NULL,
        Altbild int NOT NULL,
        Neubild int NOT NULL,
        Dateihash varchar(64) NOT NULL,
        BestaetigtUTC datetime2(7) NOT NULL DEFAULT SYSUTCDATETIME()
    );
END;
COMMIT;
