"""Database-backed response replay for mutating public API requests.

The raw key and request body are never persisted.  The tenant-scoped ledger
stores SHA-256 digests plus a bounded response representation, allowing an
ambiguous retry to receive the original result without duplicating an action.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from api.deps.tenancy import TenantScope
from api.middleware.errors import (
    IDEMPOTENCY_KEY_REQUIRED,
    IDEMPOTENCY_KEY_REUSED,
    IDEMPOTENCY_RESPONSE_TOO_LARGE,
    ProblemDetailsException,
    REQUEST_IN_PROGRESS,
    TENANT_CONTEXT_UNAVAILABLE,
)


IDEMPOTENCY_KEY_HEADER: Final = "Idempotency-Key"
IDEMPOTENCY_TTL_HOURS: Final = 24
MAX_CACHED_RESPONSE_BYTES: Final = 1_048_576
_MUTATING_METHODS: Final = frozenset({"POST", "PUT", "PATCH"})
_CACHE_EXCLUDED_HEADERS: Final = frozenset(
    {
        "connection",
        "content-length",
        "content-type",
        "set-cookie",
        "transfer-encoding",
    }
)


class IdempotencyResponseTooLarge(Exception):
    """A response cannot be safely persisted for a future replay."""


@dataclass(frozen=True, slots=True)
class IdempotencyRequest:
    """Hashed, tenant-bound identity of one mutating HTTP request."""

    org_id: UUID
    person_id: UUID
    method: str
    path: str
    key_hash: str
    request_digest: str


@dataclass(frozen=True, slots=True)
class CachedResponse:
    """The safe replay representation held for the 24-hour idempotency window."""

    status_code: int
    body: bytes
    headers: Mapping[str, str]
    media_type: str | None

    def to_response(self) -> Response:
        """Build a fresh response so no original response iterator is reused."""

        return Response(
            content=self.body,
            status_code=self.status_code,
            headers=dict(self.headers),
            media_type=self.media_type,
        )


@dataclass(frozen=True, slots=True)
class NewIdempotencyRecord:
    """This request owns the record and may execute the route."""

    record_id: UUID


@dataclass(frozen=True, slots=True)
class ReplayedIdempotencyRecord:
    """A completed identical request can return the cached response immediately."""

    response: CachedResponse


@dataclass(frozen=True, slots=True)
class ConflictingIdempotencyRecord:
    """The key was valid but it describes different request content."""


@dataclass(frozen=True, slots=True)
class InProgressIdempotencyRecord:
    """A malformed historic record has no completed response to replay."""


IdempotencyLookup = (
    NewIdempotencyRecord
    | ReplayedIdempotencyRecord
    | ConflictingIdempotencyRecord
    | InProgressIdempotencyRecord
)


class PostgresIdempotencyStore:
    """Use the RLS-protected ledger as the durable idempotency authority."""

    async def begin(
        self,
        session: AsyncSession,
        request: IdempotencyRequest,
    ) -> IdempotencyLookup:
        """Reserve an idempotency key or return its completed original response."""

        parameters = _request_parameters(request)
        await session.execute(
            text(
                """
                DELETE FROM idempotency_records
                WHERE org_id = :org_id
                  AND principal_person_id = :person_id
                  AND request_method = :method
                  AND request_path = :path
                  AND idempotency_key_hash = :key_hash
                  AND expires_at <= now()
                """
            ),
            parameters,
        )
        inserted = await session.execute(
            text(
                """
                INSERT INTO idempotency_records (
                    org_id,
                    principal_person_id,
                    request_method,
                    request_path,
                    idempotency_key_hash,
                    request_digest,
                    expires_at
                )
                VALUES (
                    :org_id,
                    :person_id,
                    :method,
                    :path,
                    :key_hash,
                    :request_digest,
                    now() + (:ttl_hours * interval '1 hour')
                )
                ON CONFLICT ON CONSTRAINT idempotency_records_request_key_unique
                DO NOTHING
                RETURNING id
                """
            ),
            {**parameters, "ttl_hours": IDEMPOTENCY_TTL_HOURS},
        )
        record_id = inserted.scalar_one_or_none()
        if record_id is not None:
            return NewIdempotencyRecord(record_id=record_id)

        existing = await session.execute(
            text(
                """
                SELECT request_digest,
                       response_status,
                       response_body,
                       response_headers,
                       response_media_type
                FROM idempotency_records
                WHERE org_id = :org_id
                  AND principal_person_id = :person_id
                  AND request_method = :method
                  AND request_path = :path
                  AND idempotency_key_hash = :key_hash
                """
            ),
            parameters,
        )
        row = existing.mappings().one_or_none()
        if row is None:
            # A concurrent request could have rolled back after our insert saw
            # its unique-key conflict. The caller can safely retry its request.
            return InProgressIdempotencyRecord()
        if row["request_digest"] != request.request_digest:
            return ConflictingIdempotencyRecord()
        if row["response_status"] is None or row["response_body"] is None:
            return InProgressIdempotencyRecord()

        headers = row["response_headers"]
        if not isinstance(headers, dict) or not all(
            isinstance(name, str) and isinstance(value, str)
            for name, value in headers.items()
        ):
            raise RuntimeError("Stored idempotency response headers are invalid")
        return ReplayedIdempotencyRecord(
            response=CachedResponse(
                status_code=int(row["response_status"]),
                body=bytes(row["response_body"]),
                headers=headers,
                media_type=(
                    str(row["response_media_type"])
                    if row["response_media_type"] is not None
                    else None
                ),
            )
        )

    async def complete(
        self,
        session: AsyncSession,
        request: IdempotencyRequest,
        record_id: UUID,
        response: CachedResponse,
    ) -> None:
        """Persist the exact safe response before the request transaction commits."""

        result = await session.execute(
            text(
                """
                UPDATE idempotency_records
                SET response_status = :response_status,
                    response_body = :response_body,
                    response_headers = CAST(:response_headers AS jsonb),
                    response_media_type = :response_media_type
                WHERE id = :record_id
                  AND org_id = :org_id
                  AND principal_person_id = :person_id
                  AND request_method = :method
                  AND request_path = :path
                  AND idempotency_key_hash = :key_hash
                """
            ),
            {
                **_request_parameters(request),
                "record_id": record_id,
                "response_status": response.status_code,
                "response_body": response.body,
                "response_headers": _json_headers(response.headers),
                "response_media_type": response.media_type,
            },
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            raise RuntimeError("Idempotency record was not available to complete")

    async def release(
        self,
        session: AsyncSession,
        request: IdempotencyRequest,
        record_id: UUID,
    ) -> None:
        """Remove a reservation whose route did not produce a replayable result."""

        await session.execute(
            text(
                """
                DELETE FROM idempotency_records
                WHERE id = :record_id
                  AND org_id = :org_id
                  AND principal_person_id = :person_id
                  AND request_method = :method
                  AND request_path = :path
                  AND idempotency_key_hash = :key_hash
                """
            ),
            {**_request_parameters(request), "record_id": record_id},
        )


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Require replay protection for every mutating `/v1` request."""

    _API_PREFIX = "/v1/"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method not in _MUTATING_METHODS or not request.url.path.startswith(
            self._API_PREFIX
        ):
            return await call_next(request)

        scope = getattr(request.state, "tenant_scope", None)
        session = getattr(request.state, "db_session", None)
        if not isinstance(scope, TenantScope) or not isinstance(session, AsyncSession):
            raise ProblemDetailsException(TENANT_CONTEXT_UNAVAILABLE)

        idempotency_key = _idempotency_key(request)
        body = await request.body()
        idempotency_request = _build_idempotency_request(
            scope,
            request.method,
            request.url.path,
            request.url.query,
            idempotency_key,
            body,
        )
        store = getattr(request.app.state, "idempotency_store", None)
        if not isinstance(store, PostgresIdempotencyStore):
            raise ProblemDetailsException(TENANT_CONTEXT_UNAVAILABLE)

        lookup = await store.begin(session, idempotency_request)
        if isinstance(lookup, ReplayedIdempotencyRecord):
            response = lookup.response.to_response()
            response.headers["Idempotency-Replayed"] = "true"
            return response
        if isinstance(lookup, ConflictingIdempotencyRecord):
            raise ProblemDetailsException(IDEMPOTENCY_KEY_REUSED)
        if isinstance(lookup, InProgressIdempotencyRecord):
            raise ProblemDetailsException(
                REQUEST_IN_PROGRESS, headers={"Retry-After": "1"}
            )

        try:
            response = await call_next(request)
            # A server error must not become a durable replay result. The tenant
            # middleware rolls back the shared transaction before it is returned.
            if response.status_code >= 500:
                await store.release(session, idempotency_request, lookup.record_id)
                return response
            replayable_response, cached_response = await capture_response(response)
            await store.complete(
                session,
                idempotency_request,
                lookup.record_id,
                cached_response,
            )
            return replayable_response
        except IdempotencyResponseTooLarge as error:
            await store.release(session, idempotency_request, lookup.record_id)
            raise ProblemDetailsException(IDEMPOTENCY_RESPONSE_TOO_LARGE) from error


def _idempotency_key(request: Request) -> str:
    values = request.headers.getlist(IDEMPOTENCY_KEY_HEADER)
    if len(values) != 1 or not values[0].strip() or len(values[0]) > 255:
        raise ProblemDetailsException(IDEMPOTENCY_KEY_REQUIRED)
    return values[0]


def _build_idempotency_request(
    scope: TenantScope,
    method: str,
    path: str,
    query: str,
    key: str,
    body: bytes,
) -> IdempotencyRequest:
    return IdempotencyRequest(
        org_id=scope.org_id,
        person_id=scope.person_id,
        method=method,
        path=path,
        key_hash=_sha256(key.encode("utf-8")),
        request_digest=_request_digest(method, path, query, body),
    )


def _request_digest(method: str, path: str, query: str, body: bytes) -> str:
    digest = hashlib.sha256()
    for part in (
        method.encode("ascii"),
        path.encode("utf-8"),
        query.encode("utf-8"),
        body,
    ):
        digest.update(len(part).to_bytes(8, byteorder="big"))
        digest.update(part)
    return digest.hexdigest()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _request_parameters(request: IdempotencyRequest) -> dict[str, Any]:
    return {
        "org_id": request.org_id,
        "person_id": request.person_id,
        "method": request.method,
        "path": request.path,
        "key_hash": request.key_hash,
        "request_digest": request.request_digest,
    }


def _json_headers(headers: Mapping[str, str]) -> str:
    """Serialize only already-sanitised response headers for PostgreSQL JSONB."""

    import json

    return json.dumps(dict(headers), sort_keys=True, separators=(",", ":"))


async def capture_response(response: Response) -> tuple[Response, CachedResponse]:
    """Buffer a bounded response once, then return a fresh sendable response."""

    body = await _response_body(response)
    if len(body) > MAX_CACHED_RESPONSE_BYTES:
        raise IdempotencyResponseTooLarge

    headers = {
        name: value
        for name, value in response.headers.items()
        if name.lower() not in _CACHE_EXCLUDED_HEADERS
    }
    cached = CachedResponse(
        status_code=response.status_code,
        body=body,
        headers=headers,
        media_type=response.media_type,
    )
    return (
        Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
            background=response.background,
        ),
        cached,
    )


async def _response_body(response: Response) -> bytes:
    direct_body = getattr(response, "body", None)
    if isinstance(direct_body, bytes):
        return direct_body

    chunks: list[bytes] = []
    total_size = 0
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        total_size += len(chunk)
        if total_size > MAX_CACHED_RESPONSE_BYTES:
            raise IdempotencyResponseTooLarge
        chunks.append(chunk)
    return b"".join(chunks)
