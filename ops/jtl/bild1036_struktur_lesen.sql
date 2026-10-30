-- Nur lesen: Zuordnungen und Struktur fuer den nativen Bildaustausch.
-- Keine Bild-Binaerdaten, keine Aenderungen, keine erneute Aufzeichnung.
USE eazybusiness;
SET NOCOUNT ON;
DECLARE @Artikel int = 40;

SELECT kArtikelbildPlattform, kArtikel, kBild, kPlattform, kShop,
       kEbayUser, nNr, nInet, cBildname
FROM dbo.tArtikelbildPlattform
WHERE kArtikel = @Artikel
ORDER BY kBild, kPlattform, kShop, kEbayUser, nNr, kArtikelbildPlattform;

SELECT b.kBild, b.cHash, b.cChecksum, b.nDateigroesse,
       b.nBreite, b.nHoehe, b.nVorschauBreite, b.nVorschauHoehe,
       b.dErstellt, b.dAenderung,
       (SELECT COUNT(*) FROM dbo.tArtikelbildPlattform p
        WHERE p.kBild = b.kBild) AS Artikelzuordnungen_gesamt
FROM dbo.tBild b
WHERE EXISTS (SELECT 1 FROM dbo.tArtikelbildPlattform p
              WHERE p.kArtikel = @Artikel AND p.kBild = b.kBild)
ORDER BY b.kBild;

SELECT s.kArtikelbildPlattformSeo, s.kArtikelbildPlattform,
       s.kSprache, s.cAlternativtext
FROM dbo.tArtikelbildPlattformSeo s
JOIN dbo.tArtikelbildPlattform p
  ON p.kArtikelbildPlattform = s.kArtikelbildPlattform
WHERE p.kArtikel = @Artikel
ORDER BY s.kArtikelbildPlattform, s.kSprache;

SELECT OBJECT_SCHEMA_NAME(c.object_id) AS SchemaName,
       OBJECT_NAME(c.object_id) AS Tabelle, c.column_id, c.name AS Spalte,
       TYPE_NAME(c.user_type_id) AS Datentyp, c.max_length,
       c.is_nullable, c.is_identity, c.is_computed, d.definition AS Standardwert
FROM sys.columns c
LEFT JOIN sys.default_constraints d ON d.object_id = c.default_object_id
WHERE c.object_id IN (OBJECT_ID(N'dbo.tBild'),
      OBJECT_ID(N'dbo.tArtikelbildPlattform'), OBJECT_ID(N'dbo.tArtikelbildPlattformSeo'))
ORDER BY c.object_id, c.column_id;

SELECT OBJECT_SCHEMA_NAME(t.parent_id) AS SchemaName,
       OBJECT_NAME(t.parent_id) AS Tabelle, t.name AS TriggerName,
       t.is_disabled, m.definition AS Definition
FROM sys.triggers t
LEFT JOIN sys.sql_modules m ON m.object_id = t.object_id
WHERE t.parent_id IN (OBJECT_ID(N'dbo.tBild'),
      OBJECT_ID(N'dbo.tArtikelbildPlattform'), OBJECT_ID(N'dbo.tArtikelbildPlattformSeo'))
ORDER BY t.parent_id, t.name;

SELECT fk.name, OBJECT_SCHEMA_NAME(fk.parent_object_id) AS QuellSchema,
       OBJECT_NAME(fk.parent_object_id) AS QuellTabelle,
       COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS QuellSpalte,
       OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS ZielSchema,
       OBJECT_NAME(fk.referenced_object_id) AS ZielTabelle,
       COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS ZielSpalte,
       fk.delete_referential_action_desc, fk.update_referential_action_desc
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
WHERE fk.parent_object_id IN (OBJECT_ID(N'dbo.tBild'),
      OBJECT_ID(N'dbo.tArtikelbildPlattform'), OBJECT_ID(N'dbo.tArtikelbildPlattformSeo'))
   OR fk.referenced_object_id IN (OBJECT_ID(N'dbo.tBild'),
      OBJECT_ID(N'dbo.tArtikelbildPlattform'), OBJECT_ID(N'dbo.tArtikelbildPlattformSeo'))
ORDER BY fk.name, fkc.constraint_column_id;

SELECT OBJECT_NAME(i.object_id) AS Tabelle, i.name AS IndexName,
       i.is_unique, i.is_primary_key, i.filter_definition,
       c.name AS Spalte, ic.key_ordinal, ic.is_included_column
FROM sys.indexes i
JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
WHERE i.object_id IN (OBJECT_ID(N'dbo.tBild'),
      OBJECT_ID(N'dbo.tArtikelbildPlattform'), OBJECT_ID(N'dbo.tArtikelbildPlattformSeo'))
ORDER BY i.object_id, i.index_id, ic.index_column_id;
