-- Resident OS tenant isolation and audit-integrity controls.
--
-- Requirements: SR-004, SR-005, SR-007, QR-002.
-- Rollback: use a new forward migration that replaces a policy or trigger. Do
-- not disable RLS or remove append-only protections from a populated system.
--
-- Application requests and background jobs must use SET LOCAL for all three
-- settings after authentication and before data access:
--   app.current_org_id       UUID of the authorised organisation
--   app.current_person_id    UUID of the authenticated person, when applicable
--   app.current_role         resident or an authorised staff role

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
SET LOCAL idle_in_transaction_session_timeout = '60s';

-- These helpers fail closed: an unset organisation or person context evaluates
-- to NULL, which makes every RLS predicate false. They are SECURITY INVOKER so
-- they cannot be used to bypass the caller's RLS protections.
CREATE FUNCTION public.app_current_org_id()
RETURNS uuid
LANGUAGE sql
STABLE
PARALLEL SAFE
SET search_path = pg_catalog
AS $$
    SELECT NULLIF(current_setting('app.current_org_id', true), '')::uuid;
$$;

CREATE FUNCTION public.app_current_person_id()
RETURNS uuid
LANGUAGE sql
STABLE
PARALLEL SAFE
SET search_path = pg_catalog
AS $$
    SELECT NULLIF(current_setting('app.current_person_id', true), '')::uuid;
$$;

CREATE FUNCTION public.app_current_role()
RETURNS text
LANGUAGE sql
STABLE
PARALLEL SAFE
SET search_path = pg_catalog
AS $$
    SELECT NULLIF(current_setting('app.current_role', true), '');
$$;

CREATE FUNCTION public.app_is_tenant_staff()
RETURNS boolean
LANGUAGE sql
STABLE
PARALLEL SAFE
SET search_path = pg_catalog
AS $$
    SELECT public.app_current_role() IN (
        'property_manager',
        'maintenance_technician',
        'asset_owner',
        'operations_admin'
    );
$$;

CREATE FUNCTION public.app_is_resident()
RETURNS boolean
LANGUAGE sql
STABLE
PARALLEL SAFE
SET search_path = pg_catalog
AS $$
    SELECT public.app_current_role() = 'resident';
$$;

-- The organisation root has no org_id column. Every other table is protected
-- by the generated tenant policy immediately below.
ALTER TABLE public.orgs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.orgs FORCE ROW LEVEL SECURITY;

CREATE POLICY orgs_current_org_select
    ON public.orgs
    AS PERMISSIVE
    FOR SELECT
    TO PUBLIC
    USING (id = public.app_current_org_id());

-- Keep the table inventory explicit. Adding a table requires adding it here in
-- the same migration that creates the table; a missing policy must never become
-- an implicit cross-tenant access path.
DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'properties',
        'buildings',
        'units',
        'people',
        'roles',
        'tenancies',
        'assets',
        'vendors',
        'vendor_scores',
        'tickets',
        'ticket_media',
        'ticket_assets',
        'ticket_status_events',
        'work_orders',
        'prompt_versions',
        'agent_runs',
        'agent_steps',
        'llm_calls',
        'kb_documents',
        'kb_chunks',
        'retrievals',
        'retrieval_results',
        'episodic_memory',
        'reflections',
        'guardrail_events',
        'decisions',
        'decision_claims',
        'decision_evidence',
        'approvals',
        'execution_receipts',
        'idempotency_records',
        'eval_datasets',
        'eval_items',
        'eval_runs',
        'eval_results',
        'failure_events',
        'metric_rollups',
        'label_queue'
    ]
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'CREATE POLICY %I ON public.%I AS PERMISSIVE FOR ALL TO PUBLIC '
            || 'USING (org_id = public.app_current_org_id() AND public.app_is_tenant_staff()) '
            || 'WITH CHECK (org_id = public.app_current_org_id() AND public.app_is_tenant_staff())',
            table_name || '_tenant_staff_access',
            table_name
        );
    END LOOP;
END;
$$;

-- Resident access is deliberately narrower than organisation-wide staff access.
-- A current tenancy is the only authority for a resident to read a unit or its
-- operational records. Date checks prevent a former resident from using a
-- historical tenancy to access a unit after move-out.
CREATE POLICY people_resident_self_select
    ON public.people
    AS PERMISSIVE
    FOR SELECT
    TO PUBLIC
    USING (
        public.app_is_resident()
        AND org_id = public.app_current_org_id()
        AND id = public.app_current_person_id()
    );

CREATE POLICY roles_resident_self_select
    ON public.roles
    AS PERMISSIVE
    FOR SELECT
    TO PUBLIC
    USING (
        public.app_is_resident()
        AND org_id = public.app_current_org_id()
        AND person_id = public.app_current_person_id()
    );

CREATE POLICY tenancies_resident_self_select
    ON public.tenancies
    AS PERMISSIVE
    FOR SELECT
    TO PUBLIC
    USING (
        public.app_is_resident()
        AND org_id = public.app_current_org_id()
        AND person_id = public.app_current_person_id()
    );

CREATE POLICY properties_resident_current_tenancy_select
    ON public.properties
    AS PERMISSIVE
    FOR SELECT
    TO PUBLIC
    USING (
        public.app_is_resident()
        AND org_id = public.app_current_org_id()
        AND EXISTS (
            SELECT 1
            FROM public.tenancies AS tenancy
            WHERE tenancy.org_id = properties.org_id
              AND tenancy.property_id = properties.id
              AND tenancy.person_id = public.app_current_person_id()
              AND tenancy.status = 'active'
              AND tenancy.starts_on <= CURRENT_DATE
              AND (tenancy.ends_on IS NULL OR tenancy.ends_on >= CURRENT_DATE)
        )
    );

CREATE POLICY buildings_resident_current_tenancy_select
    ON public.buildings
    AS PERMISSIVE
    FOR SELECT
    TO PUBLIC
    USING (
        public.app_is_resident()
        AND org_id = public.app_current_org_id()
        AND EXISTS (
            SELECT 1
            FROM public.tenancies AS tenancy
            JOIN public.units AS unit
              ON unit.org_id = tenancy.org_id
             AND unit.property_id = tenancy.property_id
             AND unit.id = tenancy.unit_id
            WHERE tenancy.org_id = buildings.org_id
              AND unit.property_id = buildings.property_id
              AND unit.building_id = buildings.id
              AND tenancy.person_id = public.app_current_person_id()
              AND tenancy.status = 'active'
              AND tenancy.starts_on <= CURRENT_DATE
              AND (tenancy.ends_on IS NULL OR tenancy.ends_on >= CURRENT_DATE)
        )
    );

CREATE POLICY units_resident_current_tenancy_select
    ON public.units
    AS PERMISSIVE
    FOR SELECT
    TO PUBLIC
    USING (
        public.app_is_resident()
        AND org_id = public.app_current_org_id()
        AND EXISTS (
            SELECT 1
            FROM public.tenancies AS tenancy
            WHERE tenancy.org_id = units.org_id
              AND tenancy.unit_id = units.id
              AND tenancy.person_id = public.app_current_person_id()
              AND tenancy.status = 'active'
              AND tenancy.starts_on <= CURRENT_DATE
              AND (tenancy.ends_on IS NULL OR tenancy.ends_on >= CURRENT_DATE)
        )
    );

CREATE POLICY assets_resident_current_unit_select
    ON public.assets
    AS PERMISSIVE
    FOR SELECT
    TO PUBLIC
    USING (
        public.app_is_resident()
        AND org_id = public.app_current_org_id()
        AND unit_id IS NOT NULL
        AND EXISTS (
            SELECT 1
            FROM public.tenancies AS tenancy
            WHERE tenancy.org_id = assets.org_id
              AND tenancy.unit_id = assets.unit_id
              AND tenancy.person_id = public.app_current_person_id()
              AND tenancy.status = 'active'
              AND tenancy.starts_on <= CURRENT_DATE
              AND (tenancy.ends_on IS NULL OR tenancy.ends_on >= CURRENT_DATE)
        )
    );

CREATE POLICY tickets_resident_current_unit_select
    ON public.tickets
    AS PERMISSIVE
    FOR SELECT
    TO PUBLIC
    USING (
        public.app_is_resident()
        AND org_id = public.app_current_org_id()
        AND EXISTS (
            SELECT 1
            FROM public.tenancies AS tenancy
            WHERE tenancy.org_id = tickets.org_id
              AND tenancy.unit_id = tickets.unit_id
              AND tenancy.person_id = public.app_current_person_id()
              AND tenancy.status = 'active'
              AND tenancy.starts_on <= CURRENT_DATE
              AND (tenancy.ends_on IS NULL OR tenancy.ends_on >= CURRENT_DATE)
        )
    );

CREATE POLICY tickets_resident_current_unit_insert
    ON public.tickets
    AS PERMISSIVE
    FOR INSERT
    TO PUBLIC
    WITH CHECK (
        public.app_is_resident()
        AND org_id = public.app_current_org_id()
        AND reporter_person_id = public.app_current_person_id()
        AND EXISTS (
            SELECT 1
            FROM public.tenancies AS tenancy
            WHERE tenancy.org_id = tickets.org_id
              AND tenancy.unit_id = tickets.unit_id
              AND tenancy.person_id = public.app_current_person_id()
              AND tenancy.status = 'active'
              AND tenancy.starts_on <= CURRENT_DATE
              AND (tenancy.ends_on IS NULL OR tenancy.ends_on >= CURRENT_DATE)
        )
    );

CREATE POLICY ticket_media_resident_current_unit_select
    ON public.ticket_media
    AS PERMISSIVE
    FOR SELECT
    TO PUBLIC
    USING (
        public.app_is_resident()
        AND org_id = public.app_current_org_id()
        AND EXISTS (
            SELECT 1
            FROM public.tickets AS ticket
            JOIN public.tenancies AS tenancy
              ON tenancy.org_id = ticket.org_id
             AND tenancy.unit_id = ticket.unit_id
            WHERE ticket.org_id = ticket_media.org_id
              AND ticket.id = ticket_media.ticket_id
              AND tenancy.person_id = public.app_current_person_id()
              AND tenancy.status = 'active'
              AND tenancy.starts_on <= CURRENT_DATE
              AND (tenancy.ends_on IS NULL OR tenancy.ends_on >= CURRENT_DATE)
        )
    );

CREATE POLICY ticket_media_resident_current_unit_insert
    ON public.ticket_media
    AS PERMISSIVE
    FOR INSERT
    TO PUBLIC
    WITH CHECK (
        public.app_is_resident()
        AND org_id = public.app_current_org_id()
        AND EXISTS (
            SELECT 1
            FROM public.tickets AS ticket
            JOIN public.tenancies AS tenancy
              ON tenancy.org_id = ticket.org_id
             AND tenancy.unit_id = ticket.unit_id
            WHERE ticket.org_id = ticket_media.org_id
              AND ticket.id = ticket_media.ticket_id
              AND tenancy.person_id = public.app_current_person_id()
              AND tenancy.status = 'active'
              AND tenancy.starts_on <= CURRENT_DATE
              AND (tenancy.ends_on IS NULL OR tenancy.ends_on >= CURRENT_DATE)
        )
    );

CREATE POLICY ticket_assets_resident_current_unit_select
    ON public.ticket_assets
    AS PERMISSIVE
    FOR SELECT
    TO PUBLIC
    USING (
        public.app_is_resident()
        AND org_id = public.app_current_org_id()
        AND EXISTS (
            SELECT 1
            FROM public.tickets AS ticket
            JOIN public.tenancies AS tenancy
              ON tenancy.org_id = ticket.org_id
             AND tenancy.unit_id = ticket.unit_id
            WHERE ticket.org_id = ticket_assets.org_id
              AND ticket.id = ticket_assets.ticket_id
              AND tenancy.person_id = public.app_current_person_id()
              AND tenancy.status = 'active'
              AND tenancy.starts_on <= CURRENT_DATE
              AND (tenancy.ends_on IS NULL OR tenancy.ends_on >= CURRENT_DATE)
        )
    );

CREATE POLICY ticket_status_events_resident_current_unit_select
    ON public.ticket_status_events
    AS PERMISSIVE
    FOR SELECT
    TO PUBLIC
    USING (
        public.app_is_resident()
        AND org_id = public.app_current_org_id()
        AND EXISTS (
            SELECT 1
            FROM public.tickets AS ticket
            JOIN public.tenancies AS tenancy
              ON tenancy.org_id = ticket.org_id
             AND tenancy.unit_id = ticket.unit_id
            WHERE ticket.org_id = ticket_status_events.org_id
              AND ticket.id = ticket_status_events.ticket_id
              AND tenancy.person_id = public.app_current_person_id()
              AND tenancy.status = 'active'
              AND tenancy.starts_on <= CURRENT_DATE
              AND (tenancy.ends_on IS NULL OR tenancy.ends_on >= CURRENT_DATE)
        )
    );

CREATE POLICY work_orders_resident_current_unit_select
    ON public.work_orders
    AS PERMISSIVE
    FOR SELECT
    TO PUBLIC
    USING (
        public.app_is_resident()
        AND org_id = public.app_current_org_id()
        AND EXISTS (
            SELECT 1
            FROM public.tickets AS ticket
            JOIN public.tenancies AS tenancy
              ON tenancy.org_id = ticket.org_id
             AND tenancy.unit_id = ticket.unit_id
            WHERE ticket.org_id = work_orders.org_id
              AND ticket.id = work_orders.ticket_id
              AND tenancy.person_id = public.app_current_person_id()
              AND tenancy.status = 'active'
              AND tenancy.starts_on <= CURRENT_DATE
              AND (tenancy.ends_on IS NULL OR tenancy.ends_on >= CURRENT_DATE)
        )
    );

-- Audit receipts are insert-only. The first three triggers are required by the
-- Phase 0 contract; approvals, claims, evidence, and receipts are protected as
-- part of the same immutable audit trail.
CREATE FUNCTION public.prevent_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION USING
        ERRCODE = '55000',
        MESSAGE = format('%I records are append-only', TG_TABLE_NAME),
        HINT = 'Insert a successor or a new receipt; do not update or delete audit history.';
END;
$$;

CREATE TRIGGER decisions_append_only
    BEFORE UPDATE OR DELETE ON public.decisions
    FOR EACH ROW EXECUTE FUNCTION public.prevent_audit_mutation();

CREATE TRIGGER llm_calls_append_only
    BEFORE UPDATE OR DELETE ON public.llm_calls
    FOR EACH ROW EXECUTE FUNCTION public.prevent_audit_mutation();

CREATE TRIGGER guardrail_events_append_only
    BEFORE UPDATE OR DELETE ON public.guardrail_events
    FOR EACH ROW EXECUTE FUNCTION public.prevent_audit_mutation();

CREATE TRIGGER approvals_append_only
    BEFORE UPDATE OR DELETE ON public.approvals
    FOR EACH ROW EXECUTE FUNCTION public.prevent_audit_mutation();

CREATE TRIGGER decision_claims_append_only
    BEFORE UPDATE OR DELETE ON public.decision_claims
    FOR EACH ROW EXECUTE FUNCTION public.prevent_audit_mutation();

CREATE TRIGGER decision_evidence_append_only
    BEFORE UPDATE OR DELETE ON public.decision_evidence
    FOR EACH ROW EXECUTE FUNCTION public.prevent_audit_mutation();

CREATE TRIGGER execution_receipts_append_only
    BEFORE UPDATE OR DELETE ON public.execution_receipts
    FOR EACH ROW EXECUTE FUNCTION public.prevent_audit_mutation();

COMMENT ON FUNCTION public.app_current_org_id() IS
    'Returns the transaction-scoped organisation context. An unset context denies RLS access.';
COMMENT ON FUNCTION public.prevent_audit_mutation() IS
    'Rejects updates and deletes for immutable audit records.';
COMMENT ON POLICY units_resident_current_tenancy_select ON public.units IS
    'Resident-own-unit policy: permits only a current, active tenancy for the authenticated person.';

COMMIT;
