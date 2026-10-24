
"""
Tento Resident OS — Organization A Authentication & Isolation Tests

Tests:
1. Supabase email/password authentication
2. JWT algorithm and signing key ID
3. JWT membership claims
4. Cryptographic signature verification using Supabase JWKS
5. FastAPI authentication middleware
6. Live resident tenancy endpoint
7. Cross-organization API isolation
8. Rejection of an unassigned Supabase user

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

RESIDENT_EMAIL = "vishalfulsundar2025@gmail.com"
UNASSIGNED_EMAIL = "vishalfulsundar2024@gmail.com"

EXPECTED_RESIDENT = {
    "sub": "99b63324-c536-46b9-a122-7357bb4834d1",
    "org_id": "22d72ee6-0bd3-43f6-b3e9-bef9ff26e0f6",
    "person_id": "509f7c65-e3ae-49d4-84b0-c6c2ac4e2044",
    "app_role": "resident",
    "aud": "authenticated",
}

EXPECTED_UNASSIGNED_SUB = (
    "c71bab75-9098-4ead-9dd2-f02c17b89697"
)

EXPECTED_PROPERTY = "Tento Demo Apartments"
EXPECTED_UNIT = "A-101"

FOREIGN_PROPERTY = "Tento Isolation Test Apartments"
FOREIGN_UNIT = "B-201"


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

        print(
            f"{name}:",
            "PASS" if passed else "FAIL"
        )

        claims_passed &= passed

    print(
        "JWT CLAIM CHECK:",
        "PASS" if claims_passed else "FAIL"
    )

    # Verify cryptographic JWT signature.
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

    # Test live authentication middleware.
    print("\n=== Live FastAPI Authentication ===")

    status = call_live_api(token)

    print("API HTTP status:", status)

    # The route intentionally does not exist.
    # HTTP 404 means authentication succeeded before routing.
    api_passed = status == 404

    print(
        "LIVE API AUTHENTICATION:",
        "PASS" if api_passed else "FAIL"
    )

    # Test real tenancy endpoint and tenant isolation.
    print("\n=== Organization A Tenancy Endpoint ===")

    tenancy_request = Request(
        API_URL + "/v1/tenancies",
        headers={
            "Authorization": f"Bearer {token}",
        },
        method="GET",
    )

    tenancy_passed = False
    cross_org_isolation_passed = False

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

        # Positive authorization test.
        tenancy_passed = (
            tenancy_status == 200
            and len(items) == 1
            and items[0].get("property_name") == EXPECTED_PROPERTY
            and items[0].get("unit_name") == EXPECTED_UNIT
        )

        print(
            "ORGANIZATION A TENANCY API:",
            "PASS" if tenancy_passed else "FAIL"
        )

        # Negative authorization test:
        # Organization B data must not appear.
        foreign_records = [
            item for item in items
            if item.get("property_name") == FOREIGN_PROPERTY
            or item.get("unit_name") == FOREIGN_UNIT
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

    except HTTPError as error:
        print("TENANCY HTTP STATUS:", error.code)
        print("ORGANIZATION A TENANCY API: FAIL")
        print("CROSS-ORGANIZATION API ISOLATION: FAIL")

    except URLError:
        print("ORGANIZATION A TENANCY API: NETWORK ERROR")
        print("CROSS-ORGANIZATION API ISOLATION: FAIL")



    # Step 3.60 — Organization A ticket list baseline
    print("\n=== Organization A Ticket List Baseline ===")

    ticket_request = Request(
        API_URL + "/v1/tickets",
        headers={
            "Authorization": f"Bearer {token}"
        },
        method="GET",
    )

    ticket_list_passed = False

    try:
        with urlopen(ticket_request, timeout=15) as response:
            ticket_status = response.status
            ticket_data = json.load(response)

        items = ticket_data.get("items", [])

        print("TICKET HTTP STATUS:", ticket_status)
        print("Visible tickets:", len(items))

        ticket_list_passed = (
            ticket_status == 200
            and isinstance(items, list)
        )

        print(
            "TICKET LIST BASELINE:",
            "PASS" if ticket_list_passed else "FAIL"
        )

    except HTTPError as error:
        print("TICKET HTTP STATUS:", error.code)
        print("TICKET LIST BASELINE: FAIL")

    except URLError:
        print("TICKET LIST BASELINE: NETWORK ERROR")


    # Step 3.62 — Submit Organization A maintenance ticket
    print("\n=== Organization A Maintenance Ticket Submission ===")

    ticket_payload = {
        "description": "Test maintenance request: kitchen sink faucet is dripping slowly.",
        "tenancy_id": "bd79415a-e503-41d1-b6ed-2f93dc36cbbf",
        "access_permission": False,
        "pets_present": False,
    }


    # Generate a unique idempotency key for this test submission.
    from uuid import uuid4

    submit_request = Request(
        API_URL + "/v1/tickets",
        data=json.dumps(ticket_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid4()),
        },
        method="POST",
    )



    try:
        with urlopen(submit_request, timeout=20) as response:
            submission_status = response.status
            submission_data = json.load(response)

        print("SUBMISSION HTTP STATUS:", submission_status)
        print("Ticket ID:", submission_data.get("ticket_id"))
        print("Ticket Number:", submission_data.get("ticket_number"))
        print("Agent Run ID:", submission_data.get("run_id"))
        print("Status:", submission_data.get("status"))

        submission_passed = (
            submission_status == 201
            and bool(submission_data.get("ticket_id"))
            and bool(submission_data.get("run_id"))
        )

        print(
            "TICKET SUBMISSION:",
            "PASS" if submission_passed else "FAIL"
        )

    except HTTPError as error:
        print("SUBMISSION HTTP STATUS:", error.code)
        print("Error:", error.read().decode("utf-8", errors="replace"))
        print("TICKET SUBMISSION: FAIL")

    except URLError:
        print("TICKET SUBMISSION: NETWORK ERROR")



    return (
        claims_passed
        and membership_passed
        and api_passed
        and tenancy_passed
        and cross_org_isolation_passed
        and ticket_list_passed
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
# Main test runner
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

        segments = token.split(".")

        if len(segments) != 3:
            raise ValueError("Invalid JWT structure")

        header = decode_segment(segments[0])
        claims = decode_segment(segments[1])

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
