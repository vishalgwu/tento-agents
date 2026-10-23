-- Forward upgrade for databases created before the streamlined MVP.
-- Take a database backup before applying. Removed workflow tables are deleted.
-- Historical operational records remain; inactive states become terminal states.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';
ALTER TABLE public.work_orders DROP COLUMN IF EXISTS approval_id;
ALTER TABLE public.execution_receipts DROP COLUMN IF EXISTS approval_id;
DROP TABLE IF EXISTS public.approvals;
DROP TABLE IF EXISTS public.reflections;
DROP TABLE IF EXISTS public.label_queue;
DROP TYPE IF EXISTS public.approval_status;
DROP TYPE IF EXISTS public.approval_action;
DROP TYPE IF EXISTS public.reject_reason;
DROP TYPE IF EXISTS public.reflection_status;
DROP TYPE IF EXISTS public.label_queue_status;

ALTER TABLE public.ticket_status_events DROP CONSTRAINT IF EXISTS ticket_status_events_state_change;

DO $$ BEGIN
IF EXISTS (SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid WHERE t.typname='ticket_status' AND e.enumlabel='awaiting_approval') THEN
CREATE TYPE ticket_status_mvp AS ENUM ('submitted', 'acknowledged', 'triaging', 'superseded', 'ready', 'blocked', 'dispatched', 'in_progress', 'resolved', 'closed', 'escalated', 'cancelled');
ALTER TABLE public.tickets ALTER COLUMN status DROP DEFAULT;
ALTER TABLE public.tickets ALTER COLUMN status TYPE ticket_status_mvp USING (CASE status::text WHEN 'awaiting_approval' THEN 'superseded' WHEN 'approved' THEN 'ready' WHEN 'rejected' THEN 'blocked' ELSE status::text END)::ticket_status_mvp;
ALTER TABLE public.tickets ALTER COLUMN status SET DEFAULT 'submitted'::ticket_status_mvp;
ALTER TABLE public.ticket_status_events ALTER COLUMN previous_status TYPE ticket_status_mvp USING (CASE previous_status::text WHEN 'awaiting_approval' THEN 'superseded' WHEN 'approved' THEN 'ready' WHEN 'rejected' THEN 'blocked' ELSE previous_status::text END)::ticket_status_mvp;
ALTER TABLE public.ticket_status_events ALTER COLUMN next_status TYPE ticket_status_mvp USING (CASE next_status::text WHEN 'awaiting_approval' THEN 'superseded' WHEN 'approved' THEN 'ready' WHEN 'rejected' THEN 'blocked' ELSE next_status::text END)::ticket_status_mvp;
DROP TYPE ticket_status;
ALTER TYPE ticket_status_mvp RENAME TO ticket_status;
END IF;
END $$;

DO $$ BEGIN
IF EXISTS (SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid WHERE t.typname='decision_mode' AND e.enumlabel='approval_required') THEN
CREATE TYPE decision_mode_mvp AS ENUM ('auto', 'abstain', 'escalate');
ALTER TABLE public.decisions ALTER COLUMN mode TYPE decision_mode_mvp USING (CASE mode::text WHEN 'approval_required' THEN 'abstain' ELSE mode::text END)::decision_mode_mvp;
DROP TYPE decision_mode;
ALTER TYPE decision_mode_mvp RENAME TO decision_mode;
END IF;
END $$;

DO $$ BEGIN
IF EXISTS (SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid WHERE t.typname='decision_status' AND e.enumlabel='awaiting_approval') THEN
CREATE TYPE decision_status_mvp AS ENUM ('proposed', 'superseded', 'executed', 'abstained', 'escalated');
ALTER TABLE public.decisions ALTER COLUMN status DROP DEFAULT;
ALTER TABLE public.decisions ALTER COLUMN status TYPE decision_status_mvp USING (CASE status::text WHEN 'awaiting_approval' THEN 'abstained' WHEN 'approved' THEN 'proposed' WHEN 'rejected' THEN 'abstained' ELSE status::text END)::decision_status_mvp;
ALTER TABLE public.decisions ALTER COLUMN status SET DEFAULT 'proposed'::decision_status_mvp;
DROP TYPE decision_status;
ALTER TYPE decision_status_mvp RENAME TO decision_status;
END IF;
END $$;

DO $$ BEGIN
IF EXISTS (SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid WHERE t.typname='agent_run_status' AND e.enumlabel='awaiting_approval') THEN
CREATE TYPE agent_run_status_mvp AS ENUM ('queued', 'running', 'completed', 'failed', 'cancelled', 'degraded');
ALTER TABLE public.agent_runs ALTER COLUMN status DROP DEFAULT;
ALTER TABLE public.agent_runs ALTER COLUMN status TYPE agent_run_status_mvp USING (CASE status::text WHEN 'awaiting_approval' THEN 'cancelled' ELSE status::text END)::agent_run_status_mvp;
ALTER TABLE public.agent_runs ALTER COLUMN status SET DEFAULT 'queued'::agent_run_status_mvp;
DROP TYPE agent_run_status;
ALTER TYPE agent_run_status_mvp RENAME TO agent_run_status;
END IF;
END $$;

ALTER TABLE public.ticket_status_events ADD CONSTRAINT ticket_status_events_state_change CHECK (previous_status IS NULL OR previous_status <> next_status);
DROP INDEX IF EXISTS public.decisions_approval_queue_idx;
CREATE INDEX IF NOT EXISTS decisions_status_idx ON public.decisions (org_id, status, priority, created_at);
COMMIT;
