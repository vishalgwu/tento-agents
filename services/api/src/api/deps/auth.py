"""Supabase access-token verification for public API requests.

This module verifies user tokens locally against the project's *public* JWKS.
It intentionally has no Supabase client and never reads a service-role secret:
the authenticated principal is the only authority passed to request code.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final, cast
from urllib.parse import urlparse
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.db import AppRole, TenantContext, VALID_APP_ROLES


_REQUIRED_JWT_CLAIMS: Final = frozenset({"iss", "aud", "exp", "iat", "sub", "role"})
_ALLOWED_JWT_ALGORITHMS: Final = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EdDSA"}
)
_AUTHENTICATION_ERROR_DETAIL: Final = "Invalid authentication credentials"
_KEYSET_UNAVAILABLE_DETAIL: Final = "Authentication temporarily unavailable"


class InvalidAccessToken(Exception):
    """The bearer token is missing a required, authentic application identity."""


class JwtKeySetUnavailable(Exception):
    """The public signing keys cannot be retrieved or parsed safely."""


class JwtConfigurationError(Exception):
    """The API is missing valid, non-secret JWT-verification configuration."""


@dataclass(frozen=True, slots=True)
class SupabaseJwtSettings:
    """Non-secret configuration needed to validate Supabase access tokens."""

    url: str
    audience: str = "authenticated"
    jwks_cache_ttl_seconds: int = 300

    def __post_init__(self) -> None:
        parsed_url = urlparse(self.url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise JwtConfigurationError("SUPABASE_URL must be an absolute HTTP(S) URL")
        if parsed_url.scheme != "https" and parsed_url.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise JwtConfigurationError(
                "SUPABASE_URL must use HTTPS outside local development"
            )
        if not self.audience.strip():
            raise JwtConfigurationError("SUPABASE_JWT_AUDIENCE must not be empty")
        if not 1 <= self.jwks_cache_ttl_seconds <= 3_600:
            raise JwtConfigurationError(
                "SUPABASE_JWKS_CACHE_TTL_SECONDS must be between 1 and 3600"
            )

    @property
    def issuer(self) -> str:
        return f"{self.url.rstrip('/')}/auth/v1"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/.well-known/jwks.json"

    @classmethod
    def from_environment(cls) -> SupabaseJwtSettings:
        raw_ttl = os.environ.get("SUPABASE_JWKS_CACHE_TTL_SECONDS", "300")
        try:
            cache_ttl = int(raw_ttl)
        except ValueError as error:
            raise JwtConfigurationError(
                "SUPABASE_JWKS_CACHE_TTL_SECONDS must be an integer"
            ) from error

        return cls(
            url=os.environ.get("SUPABASE_URL", "").strip(),
            audience=os.environ.get("SUPABASE_JWT_AUDIENCE", "authenticated").strip(),
            jwks_cache_ttl_seconds=cache_ttl,
        )


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Verified identity and tenant claims carried by a Supabase access token."""

    subject_id: UUID
    org_id: UUID
    person_id: UUID
    role: AppRole

    @property
    def tenant_context(self) -> TenantContext:
        """Return the exact context Postgres RLS expects for this user request."""

        return TenantContext(
            org_id=self.org_id, person_id=self.person_id, role=self.role
        )


@dataclass(frozen=True, slots=True)
class _CachedJwks:
    keys_by_id: Mapping[str, jwt.PyJWK]
    expires_at: float


class SupabaseJwtVerifier:
    """Cache and verify the public signing keys for one Supabase project.

    A token with an unrecognised ``kid`` triggers at most one JWKS refresh every
    ten seconds. That admits normal key rotation without making a random-``kid``
    bearer-token flood a remote-call amplification path.
    """

    _HTTP_TIMEOUT_SECONDS: Final = 5.0
    _UNKNOWN_KID_REFRESH_COOLDOWN_SECONDS: Final = 10.0

    def __init__(self, settings: SupabaseJwtSettings) -> None:
        self._settings = settings
        self._cache: _CachedJwks | None = None
        self._cache_lock = asyncio.Lock()
        self._last_refresh_at = 0.0

    async def verify(self, encoded_token: str) -> AuthenticatedPrincipal:
        """Verify one bearer token and return only the claims routes may trust."""

        header = self._unverified_header(encoded_token)
        key_id = header.get("kid")
        algorithm = header.get("alg")
        if not isinstance(key_id, str) or not key_id or not isinstance(algorithm, str):
            raise InvalidAccessToken from None
        if algorithm not in _ALLOWED_JWT_ALGORITHMS:
            raise InvalidAccessToken

        key = await self._get_key(key_id)
        if key.algorithm_name != algorithm:
            raise InvalidAccessToken

        try:
            claims = jwt.decode(
                encoded_token,
                key=key.key,
                algorithms=[algorithm],
                audience=self._settings.audience,
                issuer=self._settings.issuer,
                options={"require": list(_REQUIRED_JWT_CLAIMS)},
            )
        except jwt.PyJWTError as error:
            raise InvalidAccessToken from error

        return _principal_from_claims(claims)

    @staticmethod
    def _unverified_header(encoded_token: str) -> Mapping[str, Any]:
        try:
            return jwt.get_unverified_header(encoded_token)
        except jwt.PyJWTError as error:
            raise InvalidAccessToken from error

    async def _get_key(self, key_id: str) -> jwt.PyJWK:
        now = time.monotonic()
        cached_key = self._get_cached_key(key_id, now)
        if cached_key is not None:
            return cached_key

        async with self._cache_lock:
            now = time.monotonic()
            cached_key = self._get_cached_key(key_id, now)
            if cached_key is not None:
                return cached_key

            # Refresh stale caches. For a fresh cache, permit one bounded
            # refresh for a new signing key; subsequent unknown kids fail closed
            # until the short cooldown passes.
            cache_is_fresh = self._cache is not None and now < self._cache.expires_at
            refresh_is_rate_limited = (
                now - self._last_refresh_at < self._UNKNOWN_KID_REFRESH_COOLDOWN_SECONDS
            )
            if cache_is_fresh and refresh_is_rate_limited:
                raise InvalidAccessToken

            await self._refresh_keys(now)
            if self._cache is None:
                raise JwtKeySetUnavailable
            refreshed_key = self._cache.keys_by_id.get(key_id)
            if refreshed_key is None:
                raise InvalidAccessToken
            return refreshed_key

    def _get_cached_key(self, key_id: str, now: float) -> jwt.PyJWK | None:
        if self._cache is None or now >= self._cache.expires_at:
            return None
        return self._cache.keys_by_id.get(key_id)

    async def _refresh_keys(self, now: float) -> None:
        try:
            async with httpx.AsyncClient(
                timeout=self._HTTP_TIMEOUT_SECONDS,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    self._settings.jwks_url,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise JwtKeySetUnavailable from error

        keys = _parse_jwks(payload)
        self._cache = _CachedJwks(
            keys_by_id=keys,
            expires_at=now + self._settings.jwks_cache_ttl_seconds,
        )
        self._last_refresh_at = now


def _parse_jwks(payload: object) -> Mapping[str, jwt.PyJWK]:
    if not isinstance(payload, Mapping):
        raise JwtKeySetUnavailable
    raw_keys = payload.get("keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise JwtKeySetUnavailable

    keys_by_id: dict[str, jwt.PyJWK] = {}
    for raw_key in raw_keys:
        if not isinstance(raw_key, dict):
            raise JwtKeySetUnavailable
        key_id = raw_key.get("kid")
        algorithm = raw_key.get("alg")
        key_type = raw_key.get("kty")
        use = raw_key.get("use")
        key_operations = raw_key.get("key_ops")
        if (
            not isinstance(key_id, str)
            or not key_id
            or not isinstance(algorithm, str)
            or algorithm not in _ALLOWED_JWT_ALGORITHMS
            or key_type not in {"RSA", "EC", "OKP"}
            or use not in {None, "sig"}
            or (
                key_operations is not None
                and (
                    not isinstance(key_operations, list)
                    or "verify" not in key_operations
                )
            )
            or key_id in keys_by_id
        ):
            raise JwtKeySetUnavailable
        try:
            signing_key = jwt.PyJWK.from_dict(raw_key, algorithm=algorithm)
        except (jwt.PyJWTError, TypeError, ValueError) as error:
            raise JwtKeySetUnavailable from error
        if signing_key.algorithm_name != algorithm:
            raise JwtKeySetUnavailable
        keys_by_id[key_id] = signing_key

    return keys_by_id


def _principal_from_claims(claims: Mapping[str, Any]) -> AuthenticatedPrincipal:
    role = claims.get("role")
    if not isinstance(role, str) or role not in VALID_APP_ROLES:
        raise InvalidAccessToken

    return AuthenticatedPrincipal(
        subject_id=_claim_uuid(claims, "sub"),
        org_id=_claim_uuid(claims, "org_id"),
        person_id=_claim_uuid(claims, "person_id"),
        role=cast(AppRole, role),
    )


def _claim_uuid(claims: Mapping[str, Any], claim_name: str) -> UUID:
    value = claims.get(claim_name)
    if not isinstance(value, str) or not value:
        raise InvalidAccessToken
    try:
        return UUID(value)
    except ValueError as error:
        raise InvalidAccessToken from error


_bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def get_supabase_jwt_verifier() -> SupabaseJwtVerifier:
    """Create the process-local verifier without making a network request."""

    return SupabaseJwtVerifier(SupabaseJwtSettings.from_environment())


async def authenticate_bearer_authorization(
    authorization_header: str | None,
    verifier: SupabaseJwtVerifier,
) -> AuthenticatedPrincipal:
    """Verify one raw HTTP ``Authorization`` header without exposing its value."""

    if authorization_header is None:
        raise InvalidAccessToken
    scheme, separator, encoded_token = authorization_header.partition(" ")
    if scheme.lower() != "bearer" or not separator or not encoded_token.strip():
        raise InvalidAccessToken
    return await verifier.verify(encoded_token.strip())


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    verifier: SupabaseJwtVerifier = Depends(get_supabase_jwt_verifier),
) -> AuthenticatedPrincipal:
    """FastAPI dependency requiring a verified bearer token with tenant claims."""

    try:
        if credentials is None:
            raise InvalidAccessToken
        return await authenticate_bearer_authorization(
            f"{credentials.scheme} {credentials.credentials}", verifier
        )
    except InvalidAccessToken as error:
        raise _authentication_http_error() from error
    except (JwtKeySetUnavailable, JwtConfigurationError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_KEYSET_UNAVAILABLE_DETAIL,
            headers={"WWW-Authenticate": "Bearer"},
        ) from error


def _authentication_http_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_AUTHENTICATION_ERROR_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )
