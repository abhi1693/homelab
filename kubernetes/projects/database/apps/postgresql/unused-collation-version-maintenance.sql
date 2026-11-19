-- Explicit operator maintenance, one bounded transaction per batch.
-- Required psql variables: expected_database, expected_system_identifier,
-- expected_server_version, batch_size. Never run against template0.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL application_name = 'unused-collation-version-maintenance';
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '15s';
SET LOCAL client_min_messages = warning;
SET LOCAL home_lab.expected_database = :'expected_database';
SET LOCAL home_lab.expected_system_identifier = :'expected_system_identifier';
SET LOCAL home_lab.expected_server_version = :'expected_server_version';
SET LOCAL home_lab.batch_size = :'batch_size';

-- These locks fence new stored dependencies while permitting ordinary table DML.
-- The short batch/timeout also bounds interference with concurrent schema DDL.
LOCK TABLE pg_catalog.pg_collation IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE pg_catalog.pg_depend, pg_catalog.pg_attribute, pg_catalog.pg_index,
           pg_catalog.pg_class, pg_catalog.pg_type, pg_catalog.pg_range IN SHARE MODE;

DO $maintenance$
DECLARE
  target record;
  mismatches oid[];
  refreshed integer := 0;
  requested_batch integer := current_setting('home_lab.batch_size')::integer;
BEGIN
  IF current_database() <> current_setting('home_lab.expected_database')
     OR current_database() = 'template0'
     OR pg_is_in_recovery()
     OR current_setting('server_version_num') <> current_setting('home_lab.expected_server_version')
     OR (SELECT system_identifier::text FROM pg_control_system()) <>
        current_setting('home_lab.expected_system_identifier') THEN
    RAISE EXCEPTION 'Database, primary, server version or physical-cluster identity fence failed';
  END IF;
  IF requested_batch NOT BETWEEN 1 AND 64 THEN
    RAISE EXCEPTION 'Batch size must be between 1 and 64';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_database WHERE datname = current_database() AND datallowconn) THEN
    RAISE EXCEPTION 'The target database does not allow connections';
  END IF;
  IF NOT pg_try_advisory_xact_lock(763210911) THEN
    RAISE EXCEPTION 'Another collation maintenance batch holds this database';
  END IF;

  SELECT coalesce(array_agg(c.oid), ARRAY[]::oid[]) INTO mismatches
  FROM pg_collation c
  WHERE c.collprovider <> 'd'
    AND c.collversion IS DISTINCT FROM pg_collation_actual_version(c.oid);

  IF EXISTS (SELECT FROM pg_collation c JOIN pg_namespace n ON n.oid=c.collnamespace
             WHERE c.oid=ANY(mismatches) AND n.nspname<>'pg_catalog')
     OR EXISTS (SELECT FROM pg_depend WHERE refclassid='pg_collation'::regclass AND refobjid=ANY(mismatches))
     OR EXISTS (SELECT FROM pg_attribute WHERE NOT attisdropped AND attcollation=ANY(mismatches))
     OR EXISTS (SELECT FROM pg_index i WHERE i.indcollation::oid[] && mismatches)
     OR EXISTS (SELECT FROM pg_type WHERE typcollation=ANY(mismatches))
     OR EXISTS (SELECT FROM pg_range WHERE rngcollation=ANY(mismatches)) THEN
    RAISE EXCEPTION 'A mismatched collation is application-defined or has stored dependencies; reviewed rebuild required';
  END IF;

  FOR target IN
    SELECT c.oid,n.nspname,c.collname,
           to_jsonb(c)-'collversion' AS definition
    FROM pg_collation c JOIN pg_namespace n ON n.oid=c.collnamespace
    WHERE c.oid=ANY(mismatches) AND n.nspname='pg_catalog'
      AND c.collencoding IN (-1, pg_char_to_encoding(current_setting('server_encoding')))
    ORDER BY c.oid LIMIT requested_batch
  LOOP
    IF to_regcollation(format('%I.%I',target.nspname,target.collname))::oid IS DISTINCT FROM target.oid
       OR pg_collation_actual_version(target.oid) IS NULL THEN
      RAISE EXCEPTION 'Collation OID resolution or actual-version fence failed';
    END IF;
    EXECUTE format('ALTER COLLATION %I.%I REFRESH VERSION',target.nspname,target.collname);
    IF EXISTS (SELECT FROM pg_collation c WHERE c.oid=target.oid AND
               (c.collversion IS DISTINCT FROM pg_collation_actual_version(c.oid)
                OR to_jsonb(c)-'collversion' IS DISTINCT FROM target.definition)) THEN
      RAISE EXCEPTION 'Collation version or definition verification failed';
    END IF;
    refreshed := refreshed+1;
  END LOOP;
  PERFORM set_config('home_lab.refreshed',refreshed::text,true);
END
$maintenance$;

SELECT json_build_object('database',current_database(),
                         'refreshed',current_setting('home_lab.refreshed')::integer);
COMMIT;
