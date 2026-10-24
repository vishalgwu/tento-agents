-- Run once as database administrator after all migrations.
-- Set each login password through your database console or secret manager.
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='resident_api') THEN
        CREATE ROLE resident_api LOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='resident_worker') THEN
        CREATE ROLE resident_worker LOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO resident_api, resident_worker;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO resident_api, resident_worker;
GRANT INSERT ON public.tickets, public.agent_runs TO resident_api;
GRANT INSERT, UPDATE, DELETE ON public.idempotency_records TO resident_api;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO resident_api, resident_worker;
GRANT INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO resident_worker;
-- RLS still requires transaction-local org/person/application-role context.
-- Do not give either role superuser, BYPASSRLS, or database-owner privileges.



-- Protect the migration ledger from runtime accounts.
-- Must remain after the broad worker GRANT statement.
REVOKE INSERT, UPDATE, DELETE
ON TABLE public.schema_migrations
FROM resident_api, resident_worker;

