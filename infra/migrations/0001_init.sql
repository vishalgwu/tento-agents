-- Resident OS initial schema.
--
-- Requirements: FR-701, SR-004, SR-005, SR-006, SR-007, QR-003, QR-006.
-- Rollback: only in an unreleased, empty environment; drop the database or the
-- schema created by the migration runner. Production rollback must be a new,
-- forward-only migration because audit records are never deleted.
--
-- This migration deliberately does not create protected-attribute fields.
-- Those attributes are neither collected nor inferred by Resident OS.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
SET LOCAL idle_in_transaction_session_timeout = '60s';

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TYPE priority AS ENUM ('p0', 'p1', 'p2', 'p3');
CREATE TYPE ticket_status AS ENUM (
    'submitted',
    'acknowledged',
    'triaging',
    'awaiting_approval',
    'approved',
    'rejected',
    'dispatched',
    'in_progress',
    'resolved',
    'closed',
    'escalated',
    'cancelled'
);
CREATE TYPE work_order_status AS ENUM (
    'proposed',
    'authorised',
    'sent_to_vendor',
    'accepted',
    'declined',
    'scheduled',
    'in_progress',
    'completed',
    'cancelled',
    'failed'
);
CREATE TYPE tenancy_status AS ENUM ('active', 'ended', 'cancelled');
CREATE TYPE asset_status AS ENUM ('active', 'inactive', 'retired');
CREATE TYPE app_role AS ENUM (
    'resident',
    'property_manager',
    'maintenance_technician',
    'vendor_contact',
    'asset_owner',
    'operations_admin'
);
CREATE TYPE role_scope AS ENUM ('organisation', 'property');
CREATE TYPE trade AS ENUM (
    'general_maintenance',
    'plumbing',
    'electrical',
    'hvac',
    'appliance',
    'pest_control',
    'restoration',
    'roofing',
    'locksmith',
    'other'
);
CREATE TYPE responsible_party AS ENUM ('owner', 'resident', 'vendor', 'undetermined');
CREATE TYPE authority AS ENUM ('statute', 'lease', 'internal_sop', 'vendor_contract');
CREATE TYPE decision_mode AS ENUM ('auto', 'approval_required', 'abstain', 'escalate');
CREATE TYPE decision_status AS ENUM (
    'proposed',
    'awaiting_approval',
    'approved',
    'rejected',
    'superseded',
    'executed',
    'abstained',
    'escalated'
);
CREATE TYPE approval_status AS ENUM ('pending', 'approved', 'rejected', 'expired', 'cancelled');
CREATE TYPE approval_action AS ENUM ('approve', 'edit', 'reassign', 'reject');
CREATE TYPE reject_reason AS ENUM (
    'insufficient_evidence',
    'incorrect_priority',
    'incorrect_routing',
    'cost_or_scope',
    'policy_conflict',
    'other'
);
CREATE TYPE agent_run_status AS ENUM (
    'queued',
    'running',
    'awaiting_approval',
    'completed',
    'failed',
    'cancelled',
    'degraded'
);
CREATE TYPE agent_step_status AS ENUM ('pending', 'running', 'completed', 'failed', 'skipped');
CREATE TYPE guardrail_kind AS ENUM (
    'tenant_authorisation',
    'rate_limit',
    'payload_size',
    'pii_redaction',
    'prompt_injection',
    'content_safety',
    'schema_validation',
    'citation_verification',
    'numeric_sanity',
    'policy_compliance',
    'fair_housing',
    'output_pii',
    'grant_scope',
    'idempotency',
    'cost_budget',
    'latency_budget'
);
CREATE TYPE guardrail_stage AS ENUM (
    'api_ingress',
    'pre_model',
    'post_model',
    'pre_decision',
    'pre_send',
    'tool_invocation',
    'gateway'
);
CREATE TYPE guardrail_outcome AS ENUM ('passed', 'blocked', 'escalated', 'degraded');
CREATE TYPE kb_document_status AS ENUM ('draft', 'active', 'superseded', 'retired');
CREATE TYPE memory_status AS ENUM ('active', 'expired', 'superseded', 'rejected');
CREATE TYPE reflection_status AS ENUM ('proposed', 'approved', 'rejected', 'superseded');
CREATE TYPE eval_dataset_status AS ENUM ('draft', 'active', 'retired');
CREATE TYPE eval_run_status AS ENUM ('queued', 'running', 'completed', 'failed', 'cancelled');
CREATE TYPE failure_kind AS ENUM (
    'schema_violation',
    'citation_failure',
    'retrieval_miss',
    'provider_failure',
    'timeout',
    'budget_breach',
    'tool_failure',
    'guardrail_block',
    'authorisation_failure',
    'idempotency_conflict',
    'unexpected_error'
);
CREATE TYPE failure_severity AS ENUM ('info', 'warning', 'error', 'critical');
CREATE TYPE label_queue_status AS ENUM ('pending', 'in_review', 'labelled', 'dismissed');
CREATE TYPE notification_tier AS ENUM ('u0', 'u1', 'u2', 'u3');

-- Tenant root. Other tables carry org_id and use composite foreign keys so a
-- parent reference cannot cross an organisation boundary.
CREATE TABLE orgs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL,
    name text NOT NULL,
    timezone text NOT NULL DEFAULT 'UTC',
    is_demo boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT orgs_slug_not_blank CHECK (btrim(slug) <> ''),
    CONSTRAINT orgs_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT orgs_slug_unique UNIQUE (slug)
);

CREATE TABLE properties (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    external_ref text,
    name text NOT NULL,
    timezone text NOT NULL,
    address_line_1 text NOT NULL,
    address_line_2 text,
    locality text NOT NULL,
    region_code text NOT NULL,
    postal_code text NOT NULL,
    country_code char(2) NOT NULL DEFAULT 'US',
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT properties_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT properties_org_external_ref_unique UNIQUE (org_id, external_ref),
    CONSTRAINT properties_valid_range CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT properties_org_fk
        FOREIGN KEY (org_id) REFERENCES orgs (id) ON DELETE RESTRICT
);

CREATE TABLE buildings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    property_id uuid NOT NULL,
    external_ref text,
    name text NOT NULL,
    code text,
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT buildings_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT buildings_org_property_id_unique UNIQUE (org_id, property_id, id),
    CONSTRAINT buildings_property_external_ref_unique UNIQUE (org_id, property_id, external_ref),
    CONSTRAINT buildings_valid_range CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT buildings_property_fk
        FOREIGN KEY (org_id, property_id) REFERENCES properties (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE units (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    property_id uuid NOT NULL,
    building_id uuid NOT NULL,
    external_ref text,
    unit_number text NOT NULL,
    floor_label text,
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT units_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT units_org_property_id_unique UNIQUE (org_id, property_id, id),
    CONSTRAINT units_org_property_building_id_unique UNIQUE (org_id, property_id, building_id, id),
    CONSTRAINT units_building_unit_number_unique UNIQUE (org_id, building_id, unit_number),
    CONSTRAINT units_property_external_ref_unique UNIQUE (org_id, property_id, external_ref),
    CONSTRAINT units_valid_range CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT units_property_fk
        FOREIGN KEY (org_id, property_id) REFERENCES properties (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT units_building_fk
        FOREIGN KEY (org_id, property_id, building_id)
        REFERENCES buildings (org_id, property_id, id) ON DELETE RESTRICT
);

CREATE TABLE people (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    auth_subject_id uuid,
    external_ref text,
    display_name text NOT NULL,
    contact_email text,
    contact_phone text,
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT people_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT people_org_auth_subject_unique UNIQUE (org_id, auth_subject_id),
    CONSTRAINT people_org_external_ref_unique UNIQUE (org_id, external_ref),
    CONSTRAINT people_display_name_not_blank CHECK (btrim(display_name) <> ''),
    CONSTRAINT people_valid_range CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT people_org_fk
        FOREIGN KEY (org_id) REFERENCES orgs (id) ON DELETE RESTRICT
);

CREATE TABLE roles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    person_id uuid NOT NULL,
    role app_role NOT NULL,
    scope role_scope NOT NULL DEFAULT 'organisation',
    property_id uuid,
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT roles_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT roles_scope_property_check CHECK (
        (scope = 'organisation' AND property_id IS NULL)
        OR (scope = 'property' AND property_id IS NOT NULL)
    ),
    CONSTRAINT roles_valid_range CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT roles_person_fk
        FOREIGN KEY (org_id, person_id) REFERENCES people (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT roles_property_fk
        FOREIGN KEY (org_id, property_id) REFERENCES properties (org_id, id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX roles_active_assignment_unique
    ON roles (org_id, person_id, role, scope, property_id) NULLS NOT DISTINCT
    WHERE valid_to IS NULL;

CREATE TABLE tenancies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    property_id uuid NOT NULL,
    unit_id uuid NOT NULL,
    person_id uuid NOT NULL,
    status tenancy_status NOT NULL DEFAULT 'active',
    starts_on date NOT NULL,
    ends_on date,
    is_primary_contact boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tenancies_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT tenancies_date_range CHECK (ends_on IS NULL OR ends_on >= starts_on),
    CONSTRAINT tenancies_property_fk
        FOREIGN KEY (org_id, property_id) REFERENCES properties (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT tenancies_unit_fk
        FOREIGN KEY (org_id, property_id, unit_id)
        REFERENCES units (org_id, property_id, id) ON DELETE RESTRICT,
    CONSTRAINT tenancies_person_fk
        FOREIGN KEY (org_id, person_id) REFERENCES people (org_id, id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX tenancies_active_person_unit_unique
    ON tenancies (org_id, person_id, unit_id)
    WHERE status = 'active';

CREATE TABLE assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    property_id uuid NOT NULL,
    building_id uuid,
    unit_id uuid,
    external_ref text,
    asset_type text NOT NULL,
    manufacturer text,
    model_number text,
    serial_number text,
    installed_on date,
    warranty_expires_on date,
    status asset_status NOT NULL DEFAULT 'active',
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT assets_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT assets_org_external_ref_unique UNIQUE (org_id, external_ref),
    CONSTRAINT assets_valid_range CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT assets_unit_requires_building CHECK (unit_id IS NULL OR building_id IS NOT NULL),
    CONSTRAINT assets_warranty_after_install CHECK (
        warranty_expires_on IS NULL OR installed_on IS NULL OR warranty_expires_on >= installed_on
    ),
    CONSTRAINT assets_property_fk
        FOREIGN KEY (org_id, property_id) REFERENCES properties (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT assets_building_fk
        FOREIGN KEY (org_id, property_id, building_id)
        REFERENCES buildings (org_id, property_id, id) ON DELETE RESTRICT,
    CONSTRAINT assets_unit_fk
        FOREIGN KEY (org_id, property_id, building_id, unit_id)
        REFERENCES units (org_id, property_id, building_id, id) ON DELETE RESTRICT
);

CREATE TABLE vendors (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    external_ref text,
    name text NOT NULL,
    primary_trade trade NOT NULL,
    contact_name text,
    contact_email text,
    contact_phone text,
    service_region_codes text[] NOT NULL DEFAULT '{}',
    insurance_expires_on date,
    active boolean NOT NULL DEFAULT true,
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vendors_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT vendors_org_external_ref_unique UNIQUE (org_id, external_ref),
    CONSTRAINT vendors_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT vendors_valid_range CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT vendors_org_fk
        FOREIGN KEY (org_id) REFERENCES orgs (id) ON DELETE RESTRICT
);

CREATE TABLE vendor_scores (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    vendor_id uuid NOT NULL,
    trade trade NOT NULL,
    measured_at timestamptz NOT NULL,
    availability_score numeric(5,4) NOT NULL,
    response_time_minutes integer,
    acceptance_rate numeric(5,4) NOT NULL,
    first_time_fix_rate numeric(5,4) NOT NULL,
    cost_variance_rate numeric(7,4),
    warranty_eligible boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vendor_scores_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT vendor_scores_unique UNIQUE (org_id, vendor_id, trade, measured_at),
    CONSTRAINT vendor_scores_availability_range CHECK (availability_score BETWEEN 0 AND 1),
    CONSTRAINT vendor_scores_acceptance_range CHECK (acceptance_rate BETWEEN 0 AND 1),
    CONSTRAINT vendor_scores_first_time_fix_range CHECK (first_time_fix_rate BETWEEN 0 AND 1),
    CONSTRAINT vendor_scores_response_time_nonnegative CHECK (
        response_time_minutes IS NULL OR response_time_minutes >= 0
    ),
    CONSTRAINT vendor_scores_vendor_fk
        FOREIGN KEY (org_id, vendor_id) REFERENCES vendors (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE tickets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    property_id uuid NOT NULL,
    building_id uuid NOT NULL,
    unit_id uuid NOT NULL,
    reporter_person_id uuid,
    ticket_number bigint GENERATED ALWAYS AS IDENTITY,
    status ticket_status NOT NULL DEFAULT 'submitted',
    priority priority,
    category text,
    symptom_summary text,
    reported_text text NOT NULL,
    access_permission boolean,
    pets_present boolean,
    preferred_access_start timestamptz,
    preferred_access_end timestamptz,
    acknowledged_at timestamptz,
    submitted_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tickets_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT tickets_org_ticket_number_unique UNIQUE (org_id, ticket_number),
    CONSTRAINT tickets_reported_text_not_blank CHECK (btrim(reported_text) <> ''),
    CONSTRAINT tickets_access_window_check CHECK (
        preferred_access_end IS NULL
        OR preferred_access_start IS NULL
        OR preferred_access_end > preferred_access_start
    ),
    CONSTRAINT tickets_property_fk
        FOREIGN KEY (org_id, property_id) REFERENCES properties (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT tickets_building_fk
        FOREIGN KEY (org_id, property_id, building_id)
        REFERENCES buildings (org_id, property_id, id) ON DELETE RESTRICT,
    CONSTRAINT tickets_unit_fk
        FOREIGN KEY (org_id, property_id, building_id, unit_id)
        REFERENCES units (org_id, property_id, building_id, id) ON DELETE RESTRICT,
    CONSTRAINT tickets_reporter_fk
        FOREIGN KEY (org_id, reporter_person_id) REFERENCES people (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE ticket_media (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    ticket_id uuid NOT NULL,
    object_key text NOT NULL,
    media_type text NOT NULL,
    byte_size bigint NOT NULL,
    content_sha256 char(64) NOT NULL,
    captured_at timestamptz,
    uploaded_at timestamptz NOT NULL DEFAULT now(),
    redacted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ticket_media_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT ticket_media_object_key_unique UNIQUE (org_id, object_key),
    CONSTRAINT ticket_media_byte_size_positive CHECK (byte_size > 0),
    CONSTRAINT ticket_media_sha256_format CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ticket_media_ticket_fk
        FOREIGN KEY (org_id, ticket_id) REFERENCES tickets (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE ticket_assets (
    org_id uuid NOT NULL,
    ticket_id uuid NOT NULL,
    asset_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, ticket_id, asset_id),
    CONSTRAINT ticket_assets_ticket_fk
        FOREIGN KEY (org_id, ticket_id) REFERENCES tickets (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT ticket_assets_asset_fk
        FOREIGN KEY (org_id, asset_id) REFERENCES assets (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE ticket_status_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    ticket_id uuid NOT NULL,
    previous_status ticket_status,
    next_status ticket_status NOT NULL,
    actor_person_id uuid,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    reason_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ticket_status_events_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT ticket_status_events_state_change CHECK (
        previous_status IS NULL OR previous_status <> next_status
    ),
    CONSTRAINT ticket_status_events_ticket_fk
        FOREIGN KEY (org_id, ticket_id) REFERENCES tickets (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT ticket_status_events_actor_fk
        FOREIGN KEY (org_id, actor_person_id) REFERENCES people (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE work_orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    ticket_id uuid NOT NULL,
    asset_id uuid,
    vendor_id uuid,
    external_ref text,
    status work_order_status NOT NULL DEFAULT 'proposed',
    trade trade NOT NULL,
    scheduled_start timestamptz,
    scheduled_end timestamptz,
    estimated_cost_cents bigint,
    authorised_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT work_orders_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT work_orders_org_external_ref_unique UNIQUE (org_id, external_ref),
    CONSTRAINT work_orders_scheduled_window_check CHECK (
        scheduled_end IS NULL OR scheduled_start IS NULL OR scheduled_end > scheduled_start
    ),
    CONSTRAINT work_orders_estimated_cost_nonnegative CHECK (
        estimated_cost_cents IS NULL OR estimated_cost_cents >= 0
    ),
    CONSTRAINT work_orders_ticket_fk
        FOREIGN KEY (org_id, ticket_id) REFERENCES tickets (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT work_orders_asset_fk
        FOREIGN KEY (org_id, asset_id) REFERENCES assets (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT work_orders_vendor_fk
        FOREIGN KEY (org_id, vendor_id) REFERENCES vendors (org_id, id) ON DELETE RESTRICT
);

-- Prompt content remains versioned in source control. The database records the
-- immutable identity and hash required for replay without storing raw prompts.
CREATE TABLE prompt_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    prompt_name text NOT NULL,
    version text NOT NULL,
    template_uri text NOT NULL,
    content_sha256 char(64) NOT NULL,
    is_active boolean NOT NULL DEFAULT false,
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT prompt_versions_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT prompt_versions_identity_unique UNIQUE (org_id, prompt_name, version),
    CONSTRAINT prompt_versions_sha256_format CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT prompt_versions_org_fk
        FOREIGN KEY (org_id) REFERENCES orgs (id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX prompt_versions_one_active_per_name
    ON prompt_versions (org_id, prompt_name)
    WHERE is_active;

CREATE TABLE agent_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    ticket_id uuid NOT NULL,
    root_run_id uuid,
    status agent_run_status NOT NULL DEFAULT 'queued',
    workflow_version text NOT NULL,
    trigger_kind text NOT NULL,
    idempotency_key_hash char(64),
    correlation_id uuid NOT NULL DEFAULT gen_random_uuid(),
    started_at timestamptz,
    completed_at timestamptz,
    degradation_level smallint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT agent_runs_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT agent_runs_degradation_level_range CHECK (degradation_level BETWEEN 0 AND 4),
    CONSTRAINT agent_runs_completed_after_started CHECK (
        completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at
    ),
    CONSTRAINT agent_runs_idempotency_hash_format CHECK (
        idempotency_key_hash IS NULL OR idempotency_key_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT agent_runs_ticket_fk
        FOREIGN KEY (org_id, ticket_id) REFERENCES tickets (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT agent_runs_root_run_fk
        FOREIGN KEY (org_id, root_run_id) REFERENCES agent_runs (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE agent_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    agent_run_id uuid NOT NULL,
    parent_step_id uuid,
    sequence_number integer NOT NULL,
    component_name text NOT NULL,
    status agent_step_status NOT NULL DEFAULT 'pending',
    input_digest char(64) NOT NULL,
    output_digest char(64),
    error_code text,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT agent_steps_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT agent_steps_sequence_unique UNIQUE (org_id, agent_run_id, sequence_number),
    CONSTRAINT agent_steps_sequence_positive CHECK (sequence_number > 0),
    CONSTRAINT agent_steps_input_digest_format CHECK (input_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT agent_steps_output_digest_format CHECK (
        output_digest IS NULL OR output_digest ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT agent_steps_completed_after_started CHECK (
        completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at
    ),
    CONSTRAINT agent_steps_run_fk
        FOREIGN KEY (org_id, agent_run_id) REFERENCES agent_runs (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT agent_steps_parent_fk
        FOREIGN KEY (org_id, parent_step_id) REFERENCES agent_steps (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE llm_calls (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    agent_run_id uuid NOT NULL,
    agent_step_id uuid NOT NULL,
    prompt_version_id uuid NOT NULL,
    task_kind text NOT NULL,
    provider text NOT NULL,
    model_name text NOT NULL,
    model_version text NOT NULL,
    request_digest char(64) NOT NULL,
    response_digest char(64),
    input_tokens integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    cached_input_tokens integer NOT NULL DEFAULT 0,
    latency_ms integer,
    cost_microusd bigint NOT NULL DEFAULT 0,
    attempt_number smallint NOT NULL DEFAULT 1,
    outcome text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT llm_calls_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT llm_calls_request_digest_format CHECK (request_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT llm_calls_response_digest_format CHECK (
        response_digest IS NULL OR response_digest ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT llm_calls_token_counts_nonnegative CHECK (
        input_tokens >= 0 AND output_tokens >= 0 AND cached_input_tokens >= 0
    ),
    CONSTRAINT llm_calls_latency_nonnegative CHECK (latency_ms IS NULL OR latency_ms >= 0),
    CONSTRAINT llm_calls_cost_nonnegative CHECK (cost_microusd >= 0),
    CONSTRAINT llm_calls_attempt_positive CHECK (attempt_number > 0),
    CONSTRAINT llm_calls_completed_after_started CHECK (
        completed_at IS NULL OR completed_at >= started_at
    ),
    CONSTRAINT llm_calls_run_fk
        FOREIGN KEY (org_id, agent_run_id) REFERENCES agent_runs (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT llm_calls_step_fk
        FOREIGN KEY (org_id, agent_step_id) REFERENCES agent_steps (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT llm_calls_prompt_version_fk
        FOREIGN KEY (org_id, prompt_version_id) REFERENCES prompt_versions (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE kb_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    document_key text NOT NULL,
    version text NOT NULL,
    title text NOT NULL,
    authority authority NOT NULL,
    jurisdiction_code text NOT NULL,
    source_uri text NOT NULL,
    content_sha256 char(64) NOT NULL,
    status kb_document_status NOT NULL DEFAULT 'draft',
    effective_from timestamptz NOT NULL,
    effective_to timestamptz,
    supersedes_document_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT kb_documents_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT kb_documents_identity_unique UNIQUE (org_id, document_key, version),
    CONSTRAINT kb_documents_sha256_format CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT kb_documents_effective_range CHECK (
        effective_to IS NULL OR effective_to > effective_from
    ),
    CONSTRAINT kb_documents_org_fk
        FOREIGN KEY (org_id) REFERENCES orgs (id) ON DELETE RESTRICT,
    CONSTRAINT kb_documents_supersedes_fk
        FOREIGN KEY (org_id, supersedes_document_id) REFERENCES kb_documents (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE kb_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    kb_document_id uuid NOT NULL,
    chunk_index integer NOT NULL,
    heading_path text NOT NULL,
    source_start integer NOT NULL,
    source_end integer NOT NULL,
    content text NOT NULL,
    content_sha256 char(64) NOT NULL,
    embedding_model text,
    embedding halfvec(1536),
    content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    token_count integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT kb_chunks_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT kb_chunks_document_index_unique UNIQUE (org_id, kb_document_id, chunk_index),
    CONSTRAINT kb_chunks_source_span_valid CHECK (source_start >= 0 AND source_end > source_start),
    CONSTRAINT kb_chunks_sha256_format CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT kb_chunks_token_count_nonnegative CHECK (token_count >= 0),
    CONSTRAINT kb_chunks_document_fk
        FOREIGN KEY (org_id, kb_document_id) REFERENCES kb_documents (org_id, id) ON DELETE RESTRICT
);

CREATE INDEX kb_chunks_content_tsv_gin_idx ON kb_chunks USING gin (content_tsv);
CREATE INDEX kb_chunks_embedding_hnsw_idx
    ON kb_chunks USING hnsw (embedding halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE TABLE retrievals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    agent_run_id uuid NOT NULL,
    agent_step_id uuid NOT NULL,
    query_digest char(64) NOT NULL,
    ticket_timestamp timestamptz NOT NULL,
    retrieval_strategy text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT retrievals_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT retrievals_query_digest_format CHECK (query_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT retrievals_run_fk
        FOREIGN KEY (org_id, agent_run_id) REFERENCES agent_runs (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT retrievals_step_fk
        FOREIGN KEY (org_id, agent_step_id) REFERENCES agent_steps (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE retrieval_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    retrieval_id uuid NOT NULL,
    kb_chunk_id uuid NOT NULL,
    bm25_rank integer,
    vector_rank integer,
    rrf_score numeric(12,8),
    rerank_score numeric(12,8),
    final_rank integer NOT NULL,
    used_in_context boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT retrieval_results_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT retrieval_results_retrieval_chunk_unique UNIQUE (org_id, retrieval_id, kb_chunk_id),
    CONSTRAINT retrieval_results_final_rank_positive CHECK (final_rank > 0),
    CONSTRAINT retrieval_results_bm25_rank_positive CHECK (bm25_rank IS NULL OR bm25_rank > 0),
    CONSTRAINT retrieval_results_vector_rank_positive CHECK (vector_rank IS NULL OR vector_rank > 0),
    CONSTRAINT retrieval_results_retrieval_fk
        FOREIGN KEY (org_id, retrieval_id) REFERENCES retrievals (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT retrieval_results_chunk_fk
        FOREIGN KEY (org_id, kb_chunk_id) REFERENCES kb_chunks (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE episodic_memory (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    ticket_id uuid NOT NULL,
    agent_run_id uuid,
    summary text NOT NULL,
    content_sha256 char(64) NOT NULL,
    embedding_model text,
    embedding halfvec(1536),
    occurred_at timestamptz NOT NULL,
    expires_at timestamptz,
    status memory_status NOT NULL DEFAULT 'active',
    valid_to timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT episodic_memory_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT episodic_memory_sha256_format CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT episodic_memory_expiry_check CHECK (expires_at IS NULL OR expires_at > occurred_at),
    CONSTRAINT episodic_memory_valid_to_check CHECK (valid_to IS NULL OR valid_to > occurred_at),
    CONSTRAINT episodic_memory_ticket_fk
        FOREIGN KEY (org_id, ticket_id) REFERENCES tickets (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT episodic_memory_run_fk
        FOREIGN KEY (org_id, agent_run_id) REFERENCES agent_runs (org_id, id) ON DELETE RESTRICT
);

CREATE INDEX episodic_memory_embedding_hnsw_idx
    ON episodic_memory USING hnsw (embedding halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE TABLE reflections (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    episodic_memory_id uuid NOT NULL,
    proposed_by_run_id uuid,
    reviewed_by_person_id uuid,
    status reflection_status NOT NULL DEFAULT 'proposed',
    proposal text NOT NULL,
    evidence_digest char(64) NOT NULL,
    reviewed_at timestamptz,
    valid_to timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT reflections_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT reflections_evidence_digest_format CHECK (evidence_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT reflections_review_state_check CHECK (
        (status = 'proposed' AND reviewed_by_person_id IS NULL AND reviewed_at IS NULL)
        OR (status <> 'proposed' AND reviewed_by_person_id IS NOT NULL AND reviewed_at IS NOT NULL)
    ),
    CONSTRAINT reflections_memory_fk
        FOREIGN KEY (org_id, episodic_memory_id) REFERENCES episodic_memory (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT reflections_proposer_fk
        FOREIGN KEY (org_id, proposed_by_run_id) REFERENCES agent_runs (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT reflections_reviewer_fk
        FOREIGN KEY (org_id, reviewed_by_person_id) REFERENCES people (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE guardrail_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    agent_run_id uuid,
    agent_step_id uuid,
    ticket_id uuid,
    kind guardrail_kind NOT NULL,
    stage guardrail_stage NOT NULL,
    outcome guardrail_outcome NOT NULL,
    rule_version text NOT NULL,
    content_digest char(64),
    reason_code text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT guardrail_events_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT guardrail_events_content_digest_format CHECK (
        content_digest IS NULL OR content_digest ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT guardrail_events_run_fk
        FOREIGN KEY (org_id, agent_run_id) REFERENCES agent_runs (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT guardrail_events_step_fk
        FOREIGN KEY (org_id, agent_step_id) REFERENCES agent_steps (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT guardrail_events_ticket_fk
        FOREIGN KEY (org_id, ticket_id) REFERENCES tickets (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE decisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    ticket_id uuid NOT NULL,
    agent_run_id uuid NOT NULL,
    sequence_number integer NOT NULL,
    mode decision_mode NOT NULL,
    status decision_status NOT NULL DEFAULT 'proposed',
    priority priority,
    proposed_trade trade,
    proposed_responsible_party responsible_party NOT NULL DEFAULT 'undetermined',
    proposed_vendor_id uuid,
    proposed_asset_id uuid,
    proposed_window_start timestamptz,
    proposed_window_end timestamptz,
    estimated_cost_cents bigint,
    confidence numeric(5,4),
    citation_verified boolean NOT NULL DEFAULT false,
    rationale text NOT NULL,
    unknowns text,
    supersedes_decision_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT decisions_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT decisions_ticket_sequence_unique UNIQUE (org_id, ticket_id, sequence_number),
    CONSTRAINT decisions_sequence_positive CHECK (sequence_number > 0),
    CONSTRAINT decisions_window_check CHECK (
        proposed_window_end IS NULL
        OR proposed_window_start IS NULL
        OR proposed_window_end > proposed_window_start
    ),
    CONSTRAINT decisions_estimated_cost_nonnegative CHECK (
        estimated_cost_cents IS NULL OR estimated_cost_cents >= 0
    ),
    CONSTRAINT decisions_confidence_range CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    CONSTRAINT decisions_ticket_fk
        FOREIGN KEY (org_id, ticket_id) REFERENCES tickets (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT decisions_run_fk
        FOREIGN KEY (org_id, agent_run_id) REFERENCES agent_runs (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT decisions_vendor_fk
        FOREIGN KEY (org_id, proposed_vendor_id) REFERENCES vendors (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT decisions_asset_fk
        FOREIGN KEY (org_id, proposed_asset_id) REFERENCES assets (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT decisions_supersedes_fk
        FOREIGN KEY (org_id, supersedes_decision_id) REFERENCES decisions (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE decision_claims (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    decision_id uuid NOT NULL,
    claim_index integer NOT NULL,
    claim_text text NOT NULL,
    is_material boolean NOT NULL DEFAULT true,
    is_unknown boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT decision_claims_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT decision_claims_index_unique UNIQUE (org_id, decision_id, claim_index),
    CONSTRAINT decision_claims_index_positive CHECK (claim_index > 0),
    CONSTRAINT decision_claims_text_not_blank CHECK (btrim(claim_text) <> ''),
    CONSTRAINT decision_claims_decision_fk
        FOREIGN KEY (org_id, decision_id) REFERENCES decisions (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE decision_evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    decision_claim_id uuid NOT NULL,
    kb_chunk_id uuid NOT NULL,
    source_start integer NOT NULL,
    source_end integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT decision_evidence_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT decision_evidence_claim_chunk_unique UNIQUE (org_id, decision_claim_id, kb_chunk_id, source_start, source_end),
    CONSTRAINT decision_evidence_span_valid CHECK (source_start >= 0 AND source_end > source_start),
    CONSTRAINT decision_evidence_claim_fk
        FOREIGN KEY (org_id, decision_claim_id) REFERENCES decision_claims (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT decision_evidence_chunk_fk
        FOREIGN KEY (org_id, kb_chunk_id) REFERENCES kb_chunks (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE approvals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    decision_id uuid NOT NULL,
    requested_by_run_id uuid NOT NULL,
    approval_chain_id uuid NOT NULL DEFAULT gen_random_uuid(),
    supersedes_approval_id uuid,
    required_role app_role NOT NULL,
    status approval_status NOT NULL DEFAULT 'pending',
    action approval_action,
    rejection_reason reject_reason,
    acted_by_person_id uuid,
    approval_token_hash char(64),
    action_scope text NOT NULL,
    requested_at timestamptz NOT NULL DEFAULT now(),
    acted_at timestamptz,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT approvals_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT approvals_org_id_id_chain_unique UNIQUE (org_id, id, approval_chain_id),
    CONSTRAINT approvals_token_hash_format CHECK (
        approval_token_hash IS NULL OR approval_token_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT approvals_expiry_check CHECK (expires_at > requested_at),
    CONSTRAINT approvals_action_state_check CHECK (
        (status = 'pending' AND supersedes_approval_id IS NULL AND approval_token_hash IS NOT NULL AND action IS NULL AND rejection_reason IS NULL AND acted_by_person_id IS NULL AND acted_at IS NULL)
        OR (status = 'approved' AND supersedes_approval_id IS NOT NULL AND approval_token_hash IS NULL AND action IN ('approve', 'edit', 'reassign') AND rejection_reason IS NULL AND acted_by_person_id IS NOT NULL AND acted_at IS NOT NULL)
        OR (status = 'rejected' AND supersedes_approval_id IS NOT NULL AND approval_token_hash IS NULL AND action = 'reject' AND rejection_reason IS NOT NULL AND acted_by_person_id IS NOT NULL AND acted_at IS NOT NULL)
        OR (status IN ('expired', 'cancelled') AND supersedes_approval_id IS NOT NULL AND approval_token_hash IS NULL AND action IS NULL AND rejection_reason IS NULL AND acted_by_person_id IS NULL AND acted_at IS NULL)
    ),
    CONSTRAINT approvals_decision_fk
        FOREIGN KEY (org_id, decision_id) REFERENCES decisions (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT approvals_run_fk
        FOREIGN KEY (org_id, requested_by_run_id) REFERENCES agent_runs (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT approvals_supersedes_fk
        FOREIGN KEY (org_id, supersedes_approval_id, approval_chain_id)
        REFERENCES approvals (org_id, id, approval_chain_id) ON DELETE RESTRICT,
    CONSTRAINT approvals_actor_fk
        FOREIGN KEY (org_id, acted_by_person_id) REFERENCES people (org_id, id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX approvals_pending_token_unique
    ON approvals (approval_token_hash)
    WHERE approval_token_hash IS NOT NULL;
CREATE UNIQUE INDEX approvals_single_successor_unique
    ON approvals (org_id, supersedes_approval_id)
    WHERE supersedes_approval_id IS NOT NULL;

ALTER TABLE work_orders
    ADD COLUMN decision_id uuid,
    ADD COLUMN approval_id uuid,
    ADD CONSTRAINT work_orders_decision_fk
        FOREIGN KEY (org_id, decision_id) REFERENCES decisions (org_id, id) ON DELETE RESTRICT,
    ADD CONSTRAINT work_orders_approval_fk
        FOREIGN KEY (org_id, approval_id) REFERENCES approvals (org_id, id) ON DELETE RESTRICT;

CREATE TABLE execution_receipts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    agent_run_id uuid NOT NULL,
    decision_id uuid NOT NULL,
    approval_id uuid,
    work_order_id uuid,
    receipt_kind text NOT NULL,
    external_ref text,
    outcome text NOT NULL,
    payload_digest char(64) NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT execution_receipts_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT execution_receipts_payload_digest_format CHECK (payload_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT execution_receipts_run_fk
        FOREIGN KEY (org_id, agent_run_id) REFERENCES agent_runs (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT execution_receipts_decision_fk
        FOREIGN KEY (org_id, decision_id) REFERENCES decisions (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT execution_receipts_approval_fk
        FOREIGN KEY (org_id, approval_id) REFERENCES approvals (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT execution_receipts_work_order_fk
        FOREIGN KEY (org_id, work_order_id) REFERENCES work_orders (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE idempotency_records (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    principal_person_id uuid NOT NULL,
    request_method text NOT NULL,
    request_path text NOT NULL,
    idempotency_key_hash char(64) NOT NULL,
    request_digest char(64) NOT NULL,
    resource_type text,
    resource_id uuid,
    response_status integer,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT idempotency_records_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT idempotency_records_request_key_unique UNIQUE (org_id, principal_person_id, request_method, request_path, idempotency_key_hash),
    CONSTRAINT idempotency_records_key_hash_format CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT idempotency_records_request_digest_format CHECK (request_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT idempotency_records_expiry_check CHECK (expires_at > created_at),
    CONSTRAINT idempotency_records_response_status_check CHECK (
        response_status IS NULL OR response_status BETWEEN 100 AND 599
    ),
    CONSTRAINT idempotency_records_principal_fk
        FOREIGN KEY (org_id, principal_person_id) REFERENCES people (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE eval_datasets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    dataset_name text NOT NULL,
    version text NOT NULL,
    source_uri text NOT NULL,
    content_sha256 char(64) NOT NULL,
    status eval_dataset_status NOT NULL DEFAULT 'draft',
    is_synthetic boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT eval_datasets_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT eval_datasets_identity_unique UNIQUE (org_id, dataset_name, version),
    CONSTRAINT eval_datasets_sha256_format CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT eval_datasets_org_fk
        FOREIGN KEY (org_id) REFERENCES orgs (id) ON DELETE RESTRICT
);

CREATE TABLE eval_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    eval_dataset_id uuid NOT NULL,
    item_key text NOT NULL,
    input_digest char(64) NOT NULL,
    expected_digest char(64) NOT NULL,
    must_cite_document_keys text[] NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT eval_items_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT eval_items_dataset_key_unique UNIQUE (org_id, eval_dataset_id, item_key),
    CONSTRAINT eval_items_input_digest_format CHECK (input_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT eval_items_expected_digest_format CHECK (expected_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT eval_items_dataset_fk
        FOREIGN KEY (org_id, eval_dataset_id) REFERENCES eval_datasets (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE eval_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    eval_dataset_id uuid NOT NULL,
    trigger_run_id uuid,
    status eval_run_status NOT NULL DEFAULT 'queued',
    git_sha char(40) NOT NULL,
    seed bigint,
    judge_provider text NOT NULL,
    judge_model text NOT NULL,
    judge_model_version text NOT NULL,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT eval_runs_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT eval_runs_git_sha_format CHECK (git_sha ~ '^[0-9a-f]{40}$'),
    CONSTRAINT eval_runs_completed_after_started CHECK (
        completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at
    ),
    CONSTRAINT eval_runs_dataset_fk
        FOREIGN KEY (org_id, eval_dataset_id) REFERENCES eval_datasets (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT eval_runs_trigger_run_fk
        FOREIGN KEY (org_id, trigger_run_id) REFERENCES agent_runs (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE eval_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    eval_run_id uuid NOT NULL,
    eval_item_id uuid NOT NULL,
    outcome text NOT NULL,
    score numeric(7,6),
    output_digest char(64) NOT NULL,
    failure_kind failure_kind,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT eval_results_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT eval_results_run_item_unique UNIQUE (org_id, eval_run_id, eval_item_id),
    CONSTRAINT eval_results_score_range CHECK (score IS NULL OR score BETWEEN 0 AND 1),
    CONSTRAINT eval_results_output_digest_format CHECK (output_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT eval_results_run_fk
        FOREIGN KEY (org_id, eval_run_id) REFERENCES eval_runs (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT eval_results_item_fk
        FOREIGN KEY (org_id, eval_item_id) REFERENCES eval_items (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE failure_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    agent_run_id uuid,
    agent_step_id uuid,
    ticket_id uuid,
    eval_run_id uuid,
    kind failure_kind NOT NULL,
    severity failure_severity NOT NULL,
    error_code text NOT NULL,
    safe_summary text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT failure_events_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT failure_events_resolved_after_occurred CHECK (
        resolved_at IS NULL OR resolved_at >= occurred_at
    ),
    CONSTRAINT failure_events_run_fk
        FOREIGN KEY (org_id, agent_run_id) REFERENCES agent_runs (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT failure_events_step_fk
        FOREIGN KEY (org_id, agent_step_id) REFERENCES agent_steps (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT failure_events_ticket_fk
        FOREIGN KEY (org_id, ticket_id) REFERENCES tickets (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT failure_events_eval_run_fk
        FOREIGN KEY (org_id, eval_run_id) REFERENCES eval_runs (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE metric_rollups (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    eval_run_id uuid,
    metric_name text NOT NULL,
    scope_type text NOT NULL,
    scope_key text NOT NULL,
    bucket_start timestamptz NOT NULL,
    bucket_end timestamptz NOT NULL,
    sample_size bigint NOT NULL,
    metric_value numeric(14,8) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT metric_rollups_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT metric_rollups_identity_unique UNIQUE (
        org_id, metric_name, scope_type, scope_key, bucket_start, bucket_end
    ),
    CONSTRAINT metric_rollups_bucket_range CHECK (bucket_end > bucket_start),
    CONSTRAINT metric_rollups_sample_size_nonnegative CHECK (sample_size >= 0),
    CONSTRAINT metric_rollups_eval_run_fk
        FOREIGN KEY (org_id, eval_run_id) REFERENCES eval_runs (org_id, id) ON DELETE RESTRICT
);

CREATE TABLE label_queue (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL,
    failure_event_id uuid,
    ticket_id uuid,
    status label_queue_status NOT NULL DEFAULT 'pending',
    prompt text NOT NULL,
    expected text,
    labelled_by_person_id uuid,
    labelled_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT label_queue_org_id_id_unique UNIQUE (org_id, id),
    CONSTRAINT label_queue_source_check CHECK (failure_event_id IS NOT NULL OR ticket_id IS NOT NULL),
    CONSTRAINT label_queue_label_state_check CHECK (
        (status = 'labelled' AND expected IS NOT NULL AND labelled_by_person_id IS NOT NULL AND labelled_at IS NOT NULL)
        OR (status <> 'labelled' AND labelled_at IS NULL)
    ),
    CONSTRAINT label_queue_failure_fk
        FOREIGN KEY (org_id, failure_event_id) REFERENCES failure_events (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT label_queue_ticket_fk
        FOREIGN KEY (org_id, ticket_id) REFERENCES tickets (org_id, id) ON DELETE RESTRICT,
    CONSTRAINT label_queue_labeller_fk
        FOREIGN KEY (org_id, labelled_by_person_id) REFERENCES people (org_id, id) ON DELETE RESTRICT
);

-- Query paths used by the Phase 1 API, run trace, approval queue, and
-- operations rollups. RLS in 0002 remains the final tenant boundary.
CREATE INDEX properties_org_idx ON properties (org_id, id);
CREATE INDEX buildings_property_idx ON buildings (org_id, property_id, id);
CREATE INDEX units_building_idx ON units (org_id, building_id, id);
CREATE INDEX people_org_idx ON people (org_id, id);
CREATE INDEX roles_person_idx ON roles (org_id, person_id, valid_to);
CREATE INDEX tenancies_unit_idx ON tenancies (org_id, unit_id, status, starts_on DESC);
CREATE INDEX assets_unit_idx ON assets (org_id, unit_id, status);
CREATE INDEX vendors_trade_idx ON vendors (org_id, primary_trade, active, insurance_expires_on);
CREATE INDEX vendor_scores_vendor_idx ON vendor_scores (org_id, vendor_id, measured_at DESC);
CREATE INDEX tickets_queue_idx ON tickets (org_id, status, priority, submitted_at DESC, id DESC);
CREATE INDEX tickets_unit_idx ON tickets (org_id, unit_id, submitted_at DESC);
CREATE INDEX ticket_media_ticket_idx ON ticket_media (org_id, ticket_id, uploaded_at);
CREATE INDEX ticket_status_events_ticket_idx ON ticket_status_events (org_id, ticket_id, occurred_at);
CREATE INDEX work_orders_ticket_idx ON work_orders (org_id, ticket_id, status, created_at DESC);
CREATE INDEX work_orders_vendor_idx ON work_orders (org_id, vendor_id, status, scheduled_start);
CREATE INDEX agent_runs_ticket_idx ON agent_runs (org_id, ticket_id, created_at DESC);
CREATE INDEX agent_runs_correlation_idx ON agent_runs (org_id, correlation_id);
CREATE INDEX agent_steps_run_idx ON agent_steps (org_id, agent_run_id, sequence_number);
CREATE INDEX llm_calls_run_idx ON llm_calls (org_id, agent_run_id, started_at);
CREATE INDEX retrievals_run_idx ON retrievals (org_id, agent_run_id, created_at);
CREATE INDEX retrieval_results_context_idx ON retrieval_results (org_id, retrieval_id, used_in_context, final_rank);
CREATE INDEX guardrail_events_run_idx ON guardrail_events (org_id, agent_run_id, occurred_at);
CREATE INDEX guardrail_events_ticket_idx ON guardrail_events (org_id, ticket_id, occurred_at);
CREATE INDEX decisions_ticket_idx ON decisions (org_id, ticket_id, sequence_number DESC);
CREATE INDEX decisions_approval_queue_idx ON decisions (org_id, status, priority, created_at);
CREATE INDEX approvals_pending_idx ON approvals (org_id, status, expires_at) WHERE status = 'pending';
CREATE INDEX execution_receipts_run_idx ON execution_receipts (org_id, agent_run_id, occurred_at);
CREATE INDEX idempotency_records_expiry_idx ON idempotency_records (org_id, expires_at);
CREATE INDEX kb_documents_lookup_idx ON kb_documents (org_id, document_key, status, effective_from DESC);
CREATE INDEX episodic_memory_ticket_idx ON episodic_memory (org_id, ticket_id, occurred_at DESC);
CREATE INDEX reflections_memory_idx ON reflections (org_id, episodic_memory_id, status);
CREATE INDEX eval_runs_dataset_idx ON eval_runs (org_id, eval_dataset_id, created_at DESC);
CREATE INDEX failure_events_ops_idx ON failure_events (org_id, occurred_at DESC, severity, kind);
CREATE INDEX metric_rollups_ops_idx ON metric_rollups (org_id, metric_name, bucket_start DESC);
CREATE INDEX label_queue_pending_idx ON label_queue (org_id, status, created_at) WHERE status IN ('pending', 'in_review');

COMMENT ON TABLE agent_steps IS
    'Agent-step payloads are represented only by digests; raw inputs and outputs are not logged here.';
COMMENT ON TABLE llm_calls IS
    'Append-only model-call receipt containing hashes, versions, tokens, cost, and latency but no prompt or response body.';
COMMENT ON TABLE decisions IS
    'Append-only decision record. Corrections use a successor linked by supersedes_decision_id.';
COMMENT ON TABLE approvals IS
    'Append-only approval receipt. approval_token_hash stores only a single-use token hash.';
COMMENT ON TABLE guardrail_events IS
    'Append-only guardrail receipt. Content is represented by a digest, never raw ingress material.';
COMMENT ON TABLE label_queue IS
    'expected is intentionally nullable until a human labels the queued item.';
COMMENT ON COLUMN kb_chunks.embedding IS
    '1536-dimension half-precision embedding for pgvector similarity search.';

COMMIT;
