-- Install in the Supabase Auth project SQL editor, not Railway Postgres.
-- An administrator assigns auth.users.raw_app_meta_data.resident_os membership.
-- Never read user_metadata: the user can edit it.
CREATE OR REPLACE FUNCTION public.resident_os_access_token_hook(event jsonb)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    membership jsonb;
    claims jsonb := event->'claims';
BEGIN
    SELECT raw_app_meta_data->'resident_os' INTO membership
    FROM auth.users WHERE id = (event->>'user_id')::uuid;
    -- Strip any stale application claims before deriving trusted membership.
    claims := claims - 'org_id' - 'person_id' - 'app_role';
    IF membership IS NOT NULL
       AND membership->>'app_role' IN ('resident','property_manager','maintenance_technician','vendor_contact','asset_owner','operations_admin') THEN
        -- Casts fail closed on invalid identifiers; no token with partial membership.
        PERFORM (membership->>'org_id')::uuid, (membership->>'person_id')::uuid;
        IF membership->>'org_id' IS NOT NULL AND membership->>'person_id' IS NOT NULL THEN
            claims := claims || jsonb_build_object(
                'org_id', membership->>'org_id',
                'person_id', membership->>'person_id',
                'app_role', membership->>'app_role'
            );
        END IF;
    END IF;
    RETURN jsonb_set(event, '{claims}', claims);
END;
$$;
REVOKE ALL ON FUNCTION public.resident_os_access_token_hook(jsonb) FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA public TO supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.resident_os_access_token_hook(jsonb) TO supabase_auth_admin;
-- Enable this function in Authentication > Hooks > Custom Access Token.
