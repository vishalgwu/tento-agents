from __future__ import annotations

import json
import time
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from jwt.algorithms import RSAAlgorithm

from api.deps.auth import (
    InvalidAccessToken,
    JwtKeySetUnavailable,
    SupabaseJwtSettings,
    SupabaseJwtVerifier,
    _CachedJwks,
    _parse_jwks,
)


@pytest.fixture
def signing_material() -> tuple[object, dict[str, object]]:
    private_key = generate_private_key(public_exponent=65_537, key_size=2_048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update(
        {
            "kid": "test-signing-key",
            "alg": "RS256",
            "use": "sig",
            "key_ops": ["verify"],
        }
    )
    return private_key, public_jwk


@pytest.fixture
def settings() -> SupabaseJwtSettings:
    return SupabaseJwtSettings(url="https://resident-os.supabase.co")


def _signed_token(
    private_key: object,
    settings: SupabaseJwtSettings,
    **overrides: object,
) -> str:
    claims: dict[str, object] = {
        "iss": settings.issuer,
        "aud": settings.audience,
        "exp": int(time.time()) + 60,
        "iat": int(time.time()),
        "sub": str(uuid4()),
        "org_id": str(uuid4()),
        "person_id": str(uuid4()),
        "role": "property_manager",
    }
    claims.update(overrides)
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": "test-signing-key"},
    )


@pytest.mark.asyncio
async def test_verifier_accepts_signed_token_with_required_tenant_claims(
    signing_material: tuple[object, dict[str, object]], settings: SupabaseJwtSettings
) -> None:
    private_key, public_jwk = signing_material
    verifier = SupabaseJwtVerifier(settings)
    verifier._cache = _CachedJwks(  # noqa: SLF001 - verifies the cache consumption path.
        keys_by_id=_parse_jwks({"keys": [public_jwk]}),
        expires_at=time.monotonic() + 60,
    )

    token = _signed_token(private_key, settings)
    principal = await verifier.verify(token)

    assert isinstance(principal.subject_id, UUID)
    assert isinstance(principal.org_id, UUID)
    assert isinstance(principal.person_id, UUID)
    assert principal.role == "property_manager"
    assert principal.tenant_context.org_id == principal.org_id


@pytest.mark.asyncio
async def test_verifier_rejects_signed_token_without_person_claim(
    signing_material: tuple[object, dict[str, object]], settings: SupabaseJwtSettings
) -> None:
    private_key, public_jwk = signing_material
    verifier = SupabaseJwtVerifier(settings)
    verifier._cache = _CachedJwks(  # noqa: SLF001 - verifies the cache consumption path.
        keys_by_id=_parse_jwks({"keys": [public_jwk]}),
        expires_at=time.monotonic() + 60,
    )
    token = _signed_token(private_key, settings, person_id=None)

    with pytest.raises(InvalidAccessToken):
        await verifier.verify(token)


@pytest.mark.asyncio
async def test_verifier_rejects_wrong_audience_before_claims_are_trusted(
    signing_material: tuple[object, dict[str, object]], settings: SupabaseJwtSettings
) -> None:
    private_key, public_jwk = signing_material
    verifier = SupabaseJwtVerifier(settings)
    verifier._cache = _CachedJwks(  # noqa: SLF001 - verifies the cache consumption path.
        keys_by_id=_parse_jwks({"keys": [public_jwk]}),
        expires_at=time.monotonic() + 60,
    )
    token = _signed_token(private_key, settings, aud="another-api")

    with pytest.raises(InvalidAccessToken):
        await verifier.verify(token)


def test_jwks_rejects_symmetric_or_duplicate_key_material(
    signing_material: tuple[object, dict[str, object]],
) -> None:
    symmetric_key = {
        "kid": "symmetric",
        "alg": "HS256",
        "kty": "oct",
        "k": "not-a-public-key",
    }
    with pytest.raises(JwtKeySetUnavailable):
        _parse_jwks({"keys": [symmetric_key]})

    _, duplicate_key = signing_material
    with pytest.raises(JwtKeySetUnavailable):
        _parse_jwks({"keys": [duplicate_key, duplicate_key]})

    malformed_key = {
        "kid": "malformed",
        "alg": "RS256",
        "kty": "RSA",
        "n": "AQAB",
        "e": "AQAB",
    }
    with pytest.raises(JwtKeySetUnavailable):
        _parse_jwks({"keys": [malformed_key]})
