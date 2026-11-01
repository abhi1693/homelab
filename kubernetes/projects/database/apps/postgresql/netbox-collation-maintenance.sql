-- Run only after every CNPG instance is healthy on the intended image.
-- Execute with psql -X -U postgres -d netbox -v ON_ERROR_STOP=1.
-- Concurrent reindex commands must run outside a transaction block.
\set ON_ERROR_STOP on
SET application_name = 'netbox-collation-maintenance';
SET lock_timeout = '5s';
SET statement_timeout = '10min';

SELECT current_database() = 'netbox' AND NOT pg_is_in_recovery() AS correct_target \gset
\if :correct_target
\else
  \echo 'ERROR: connect to the netbox database on the current primary'
  \quit 1
\endif

SELECT EXISTS (
  SELECT FROM pg_collation
  WHERE oid = 'public.natural_sort'::regcollation
    AND collprovider = 'i'
    AND collversion IS DISTINCT FROM pg_collation_actual_version(oid)
) AS needs_rebuild \gset

\if :needs_rebuild
  SELECT format('REINDEX INDEX CONCURRENTLY %I.%I;', n.nspname, r.relname)
  FROM pg_index i
  JOIN pg_class r ON r.oid = i.indexrelid
  JOIN pg_namespace n ON n.oid = r.relnamespace
  WHERE 'public.natural_sort'::regcollation::oid = ANY (i.indcollation::oid[])
  ORDER BY n.nspname, r.relname
  \gexec

  SELECT NOT EXISTS (
    SELECT FROM pg_index i
    WHERE 'public.natural_sort'::regcollation::oid = ANY (i.indcollation::oid[])
      AND (NOT i.indisvalid OR NOT i.indisready OR NOT i.indislive)
  ) AS indexes_valid \gset
  \if :indexes_valid
    ALTER COLLATION public.natural_sort REFRESH VERSION;
  \else
    \echo 'ERROR: invalid natural_sort indexes remain; collation version not refreshed'
    \quit 1
  \endif
\else
  \echo 'natural_sort collation version already matches; no rebuild required'
\endif

SELECT collname, collversion,
       pg_collation_actual_version(oid) AS actual_version
FROM pg_collation
WHERE oid = 'public.natural_sort'::regcollation;
