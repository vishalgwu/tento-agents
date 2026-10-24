"""
Tento Resident OS — Supabase Authentication Integration Tests

Tests:
1. Supabase email/password authentication
2. JWT algorithm and signing key ID
3. JWT cryptographic signature verification
4. Expected organization, person and role claims
5. Live FastAPI authentication middleware
6. Rejection of a user without resident membership

No passwords or access tokens are printed or saved.
"""

import asyncio
import base64
import getpass
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import dotenv_values

from api.deps.auth import (
    InvalidAccessToken,
    JwtConfigurationError,
    JwtKeySetUnavailable,
    SupabaseJwtSettings,
    SupabaseJwtVerifier,
)


# --------------------------------------------------
# Configuration
# --------------------------------------------------

env = dotenv_values(".env")

SUPABASE_URL = env["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = env["SUPABASE_ANON_KEY"]

API_URL = "http://127.0.0.1:8000"

RESIDENT_EMAIL = "onepidox@gmail.com"
UNASSIGNED_EMAIL = "vishalfulsundar2024@gmail.com"

EXPECTED_RESIDENT = {
    "sub": "43a8b989-187a-4c7c-ba9b-d90fcb1a1453",
    "org_id": "ab027600-2e27-4983-b113-00f57d40d112",
    "person_id": "df893c36-4d57-4068-bc46-778db114c67d",
    "app_role": "resident",
    "aud": "authenticated",
}

EXPECTED_UNASSIGNED_SUB = (
    "c71bab75-9098-4ead-9dd2-f02c17b89697"
)


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def decode_segment(segment):
    padded = segment + "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def sign_in(email, password):
    request = Request(
        SUPABASE_URL + "/auth/v1/token?grant_type=password",
        data=json.dumps({
            "email": email,
            "password": password,
        }).encode("utf-8"),
        headers={
            "apikey": SUPABASE_KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urlopen(request, timeout=20) as response:
        return json.load(response)["access_token"]


async def verify_token(token):
    verifier = SupabaseJwtVerifier(
        SupabaseJwtSettings(
            url=SUPABASE_URL,
            audience="authenticated",
        )
    )

    return await verifier.verify(token)


def call_live_api(token):
    request = Request(
        API_URL + "/v1/__auth_probe__",
        headers={
            "Authorization": f"Bearer {token}",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=10) as response:
            return response.status
    except HTTPError as error:
        return error.code


# --------------------------------------------------
# Assigned resident test
# --------------------------------------------------

def test_resident(token, claims):
    print("\n=== Assigned Resident Verification ===")

    claims_passed = True

    for name, expected_value in EXPECTED_RESIDENT.items():
        passed = claims.get(name) == expected_value
        print(f"{name}: {'PASS' if passed else 'FAIL'}")
        claims_passed &= passed

    print(
        "JWT CLAIM CHECK:",
        "PASS" if claims_passed else "FAIL"
    )

    print("\n=== FastAPI JWT Verification ===")

    principal = asyncio.run(verify_token(token))

    membership_passed = (
        str(principal.subject_id) == EXPECTED_RESIDENT["sub"]
        and str(principal.org_id) == EXPECTED_RESIDENT["org_id"]
        and str(principal.person_id) == EXPECTED_RESIDENT["person_id"]
        and principal.role == EXPECTED_RESIDENT["app_role"]
    )

    print("API JWT SIGNATURE: PASS")
    print(
        "API MEMBERSHIP:",
        "PASS" if membership_passed else "FAIL"
    )

    print("\n=== Live FastAPI Authentication ===")

    status = call_live_api(token)

    print("API HTTP status:", status)

    # The endpoint intentionally does not exist.
    # HTTP 404 means authentication succeeded before routing.
    api_passed = status == 404

    print(
        "LIVE API AUTHENTICATION:",
        "PASS" if api_passed else "FAIL"
    )

    # Step 3.56 — Organization B tenancy endpoint
    print("\n=== Organization B Tenancy Endpoint ===")

    tenancy_request = Request(
        API_URL + "/v1/tenancies",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )

    tenancy_passed = False

    try:
        with urlopen(tenancy_request, timeout=15) as response:
            tenancy_status = response.status
            tenancy_data = json.load(response)

        items = tenancy_data.get("items", [])

        print("TENANCY HTTP STATUS:", tenancy_status)
        print("Visible tenancies:", len(items))

        for item in items:
            print("Property:", item.get("property_name"))
            print("Unit:", item.get("unit_name"))

        tenancy_passed = (
            tenancy_status == 200
            and len(items) == 1
            and items[0].get("property_name")
                == "Tento Isolation Test Apartments"
            and items[0].get("unit_name") == "B-201"
        )

        # Explicitly reject visibility of Organization A records.
        foreign_records = [
            item for item in items
            if item.get("property_name") == "Tento Demo Apartments"
            or item.get("unit_name") == "A-101"
        ]

        cross_org_isolation_passed = (
            tenancy_status == 200
            and tenancy_passed
            and len(foreign_records) == 0
        )

        print(
            "CROSS-ORGANIZATION API ISOLATION:",
            "PASS" if cross_org_isolation_passed else "FAIL"
        )










        print(
            "ORGANIZATION B TENANCY API:",
            "PASS" if tenancy_passed else "FAIL"
        )

    except HTTPError as error:
        print("TENANCY HTTP STATUS:", error.code)
        print("ORGANIZATION B TENANCY API: FAIL")

    except URLError:
        print("ORGANIZATION B TENANCY API: NETWORK ERROR")

    
    return (
        claims_passed
        and membership_passed
        and api_passed
        and tenancy_passed
        and cross_org_isolation_passed
    )



# --------------------------------------------------
# Unassigned user rejection test
# --------------------------------------------------

def test_unassigned(token, claims):
    print("\n=== Unassigned User Verification ===")

    subject_passed = (
        claims.get("sub") == EXPECTED_UNASSIGNED_SUB
    )

    no_membership = (
        not claims.get("org_id")
        and not claims.get("person_id")
        and not claims.get("app_role")
    )

    print(
        "UNASSIGNED SUBJECT:",
        "PASS" if subject_passed else "FAIL"
    )

    print(
        "NO RESIDENT MEMBERSHIP:",
        "PASS" if no_membership else "FAIL"
    )

    print("\n=== Live FastAPI Authorization ===")

    status = call_live_api(token)

    print("API HTTP status:", status)

    # A valid Supabase identity without application membership
    # must not be accepted by Tento Resident OS.
    rejection_passed = status == 401

    print(
        "UNASSIGNED USER REJECTION:",
        "PASS" if rejection_passed else "FAIL"
    )

    return (
        subject_passed
        and no_membership
        and rejection_passed
    )


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    print("\n=== Tento Resident OS Authentication Test ===\n")

    email = input("User email: ").strip().lower()

    if email not in {RESIDENT_EMAIL, UNASSIGNED_EMAIL}:
        print("TEST NOT CONFIGURED FOR THIS ACCOUNT")
        return

    password = getpass.getpass("Password: ")

    try:
        token = sign_in(email, password)

        header_part, claims_part, _ = token.split(".")

        header = decode_segment(header_part)
        claims = decode_segment(claims_part)

        print("\n=== JWT Header ===")
        print("JWT algorithm:", header.get("alg"))
        print("Signing key ID present:", bool(header.get("kid")))

        print("\nSUPABASE SIGN-IN: SUCCESS")

        if email == RESIDENT_EMAIL:
            passed = test_resident(token, claims)
        else:
            passed = test_unassigned(token, claims)

        print("\n=== Final Result ===")

        print(
            "AUTHENTICATION TEST:",
            "PASS" if passed else "FAIL"
        )

    except HTTPError as error:
        print("HTTP REQUEST FAILED")
        print("HTTP status:", error.code)

    except URLError:
        print("NETWORK ERROR")

    except InvalidAccessToken:
        print("JWT VERIFICATION: INVALID ACCESS TOKEN")

    except JwtKeySetUnavailable:
        print("JWT VERIFICATION: JWKS UNAVAILABLE")

    except JwtConfigurationError:
        print("JWT VERIFICATION: CONFIGURATION ERROR")

    except (KeyError, ValueError, IndexError, TypeError):
        print("INVALID TOKEN RESPONSE")


if __name__ == "__main__":
    main()