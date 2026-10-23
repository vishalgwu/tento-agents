-- Persistent resident reports, fenced worker leases, and source-backed policy.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

ALTER TABLE public.agent_runs
    ADD COLUMN result_json jsonb,
    ADD COLUMN lease_id uuid,
    ADD COLUMN lease_expires_at timestamptz,
    ADD COLUMN attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    ADD COLUMN last_error_code text,
    ADD CONSTRAINT agent_runs_result_object CHECK (result_json IS NULL OR jsonb_typeof(result_json) = 'object'),
    ADD CONSTRAINT agent_runs_lease_pair CHECK ((lease_id IS NULL) = (lease_expires_at IS NULL));
CREATE INDEX agent_runs_worker_claim_idx ON public.agent_runs (org_id, created_at, id)
    WHERE status IN ('queued', 'running');
ALTER TABLE public.properties ADD COLUMN in_house_trades trade[] NOT NULL DEFAULT '{}';

CREATE TABLE public.kb_policy_claims (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    kb_document_id uuid NOT NULL,
    policy_key text NOT NULL CHECK (btrim(policy_key) <> ''),
    outcome text NOT NULL CHECK (btrim(outcome) <> ''),
    source_start integer NOT NULL CHECK (source_start >= 0),
    source_end integer NOT NULL CHECK (source_end > source_start),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT kb_policy_claims_document_fk FOREIGN KEY (org_id, kb_document_id)
        REFERENCES public.kb_documents (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT kb_policy_claims_identity UNIQUE (org_id, kb_document_id, policy_key, outcome, source_start, source_end)
);
ALTER TABLE public.kb_policy_claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.kb_policy_claims FORCE ROW LEVEL SECURITY;
CREATE POLICY kb_policy_claims_tenant_staff_access ON public.kb_policy_claims
    FOR ALL TO PUBLIC
    USING (org_id = public.app_current_org_id() AND public.app_is_tenant_staff())
    WITH CHECK (org_id = public.app_current_org_id() AND public.app_is_tenant_staff());
CREATE TRIGGER kb_policy_claims_append_only BEFORE UPDATE OR DELETE ON public.kb_policy_claims
    FOR EACH ROW EXECUTE FUNCTION public.prevent_audit_mutation();

-- Tighten the resident ticket boundary to the reporter as well as active tenancy.
DROP POLICY tickets_resident_current_unit_select ON public.tickets;
CREATE POLICY tickets_resident_current_unit_select ON public.tickets FOR SELECT TO PUBLIC USING (
    public.app_is_resident() AND org_id = public.app_current_org_id()
    AND reporter_person_id = public.app_current_person_id()
    AND EXISTS (SELECT 1 FROM public.tenancies t WHERE t.org_id = tickets.org_id
        AND t.unit_id = tickets.unit_id AND t.person_id = public.app_current_person_id()
        AND t.status = 'active' AND t.starts_on <= CURRENT_DATE
        AND (t.ends_on IS NULL OR t.ends_on >= CURRENT_DATE))
);
CREATE POLICY agent_runs_resident_own_select ON public.agent_runs FOR SELECT TO PUBLIC USING (
    public.app_is_resident() AND org_id = public.app_current_org_id()
    AND EXISTS (SELECT 1 FROM public.tickets t WHERE t.org_id = agent_runs.org_id
        AND t.id = agent_runs.ticket_id AND t.reporter_person_id = public.app_current_person_id())
);
CREATE POLICY agent_runs_resident_own_insert ON public.agent_runs FOR INSERT TO PUBLIC WITH CHECK (
    public.app_is_resident() AND org_id = public.app_current_org_id()
    AND status = 'queued' AND workflow_version = 'maintenance-v1'
    AND trigger_kind = 'resident_submission' AND result_json IS NULL
    AND lease_id IS NULL AND attempt_count = 0
    AND EXISTS (SELECT 1 FROM public.tickets t WHERE t.org_id = agent_runs.org_id
        AND t.id = agent_runs.ticket_id AND t.reporter_person_id = public.app_current_person_id())
);
CREATE POLICY agent_steps_resident_own_select ON public.agent_steps FOR SELECT TO PUBLIC USING (
    public.app_is_resident() AND org_id = public.app_current_org_id()
    AND EXISTS (SELECT 1 FROM public.agent_runs r WHERE r.org_id = agent_steps.org_id
        AND r.id = agent_steps.agent_run_id)
);
CREATE POLICY guardrail_events_resident_own_select ON public.guardrail_events FOR SELECT TO PUBLIC USING (
    public.app_is_resident() AND org_id = public.app_current_org_id()
    AND EXISTS (SELECT 1 FROM public.agent_runs r WHERE r.org_id = guardrail_events.org_id
        AND r.id = guardrail_events.agent_run_id)
);
COMMIT;
