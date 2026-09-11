-- Durable response replay for Phase-1 API idempotency.
--
-- Requirements: SR-004, SR-007, QR-002.
-- Rollback: retain completed records until their 24-hour expiry. If response
-- replay must be disabled, deploy a forward application change that stops
-- reading these columns; do not delete historical request receipts.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
SET LOCAL idle_in_transaction_session_timeout = '60s';

-- Earlier schema revisions could record a status but not a response body. Such
-- rows cannot be replayed safely, so expire them at migration time. They are a
-- 24-hour retry cache rather than a durable business or audit receipt.
UPDATE public.idempotency_records
SET response_status = NULL,
    expires_at = GREATEST(now(), created_at + interval '1 microsecond')
WHERE response_status IS NOT NULL;

ALTER TABLE public.idempotency_records
    ADD COLUMN response_body bytea,
    ADD COLUMN response_headers jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN response_media_type text,
    ADD CONSTRAINT idempotency_records_response_headers_object_check
        CHECK (jsonb_typeof(response_headers) = 'object'),
    ADD CONSTRAINT idempotency_records_completed_response_check
        CHECK (
            (response_status IS NULL
                AND response_body IS NULL
                AND response_media_type IS NULL
                AND response_headers = '{}'::jsonb)
            OR (response_status IS NOT NULL AND response_body IS NOT NULL)
        );

-- The generated staff policy in 0002 already permits staff access. Residents
-- may create and replay only their own request records, matching the resident
-- ticket-insert boundary without opening another organisation's ledger.
CREATE POLICY idempotency_records_resident_own_access
    ON public.idempotency_records
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (
        public.app_is_resident()
        AND org_id = public.app_current_org_id()
        AND principal_person_id = public.app_current_person_id()
    )
    WITH CHECK (
        public.app_is_resident()
        AND org_id = public.app_current_org_id()
        AND principal_person_id = public.app_current_person_id()
    );

COMMENT ON TABLE public.idempotency_records IS
    'Tenant-scoped replay ledger. Stores hashed keys and requests, plus a bounded response for 24-hour retry safety.';

COMMIT;
