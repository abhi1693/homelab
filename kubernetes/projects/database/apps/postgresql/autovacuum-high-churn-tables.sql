\set ON_ERROR_STOP on

\connect wardn_hub
-- Keep lock acquisition bounded so this maintenance fails safely rather than
-- queueing application writes behind an unexpected long-running transaction.
SET lock_timeout = '5s';
SET statement_timeout = '10min';
SET vacuum_cost_delay = '2ms';
SET vacuum_cost_limit = 200;
ALTER TABLE public.event_records SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.01
);
VACUUM (ANALYZE) public.event_records;

\connect devfeed
SET lock_timeout = '5s';
ALTER TABLE public.articles SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE public.article_analysis_jobs SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE public.research_verification_jobs SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE public.topic_analysis_jobs SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE public.topic_relation_proposals SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.01
);

\connect harbor
SET lock_timeout = '5s';
ALTER TABLE public.artifact SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE public.artifact_blob SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE public.artifact_reference SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE public.blob SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE public.tag SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.01
);
ALTER TABLE public.task SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.01
);

\connect shipyardhq
SET lock_timeout = '5s';
SET statement_timeout = '10min';
SET vacuum_cost_delay = '2ms';
SET vacuum_cost_limit = 200;
ALTER TABLE public."EventEnvelope" SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_analyze_scale_factor = 0.01
);
VACUUM (ANALYZE) public."EventEnvelope";
