"""Authentication and workspace scoping (issue #19; PRD §23).

**Authentication is not a gate on the graph.** PRD §23 is explicit that "the
canonical Process graph may be system-wide while user notes, watchlists,
hypotheses, and annotations remain permissioned", and that line is the whole
design. A Process discovered from public evidence belongs to nobody. Requiring a
session to read one would have been the easier thing to build and would have
quietly turned a shared research asset into a per-tenant silo.

So identity is *optional* on ontology reads and *required* on the handful of
endpoints that touch a workspace. `viewer` yields None where there is no token;
`member` raises. Two dependencies, and the choice at each call site is visible
in the signature.

Tokens are verified against Clerk's JWKS. Verified, not decoded: an unverified
JWT is a request body the client wrote, and treating one as identity is the
whole vulnerability. Where no issuer is configured the API runs open and says so
at startup, because a deployment that silently accepts anything is worse than
one that announces it.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from econiq_data_models import Workspace, WorkspaceMember
from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from econiq_api.deps import SessionDep

logger = logging.getLogger("econiq.api.auth")

#: Clerk's issuer, e.g. https://your-app.clerk.accounts.dev. Absent means the
#: API runs unauthenticated, which is the local-development default.
ISSUER_ENV = "CLERK_ISSUER"

#: Cached because JWKS rotation is measured in months and a fetch per request
#: would make every read depend on Clerk being up.
_JWKS_TTL = 3600.0


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is asking. Never trusted beyond what the token was signed for."""

    user_id: str
    #: Clerk organization id where the session has one, else None for personal.
    organization_id: str | None = None
    email: str | None = None

    @property
    def workspace_external_id(self) -> str:
        """The workspace this session acts in.

        An organization session acts in the organization's workspace; a personal
        session acts in its own. Derived rather than sent by the client, because
        a client-supplied workspace id is an access-control decision made by the
        party being controlled.
        """
        return self.organization_id or self.user_id


class _Verifier:
    def __init__(self) -> None:
        self._issuer = os.getenv(ISSUER_ENV)
        self._client: PyJWKClient | None = None
        self._fetched = 0.0

    @property
    def enabled(self) -> bool:
        return self._issuer is not None

    def _keys(self) -> PyJWKClient:
        now = time.monotonic()
        if self._client is None or now - self._fetched > _JWKS_TTL:
            self._client = PyJWKClient(f"{self._issuer}/.well-known/jwks.json")
            self._fetched = now
        return self._client

    def verify(self, token: str) -> Principal:
        signing_key = self._keys().get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=self._issuer,
            # Clerk session tokens carry no audience by default; the issuer and
            # the signature are what establish origin.
            options={"verify_aud": False},
        )
        subject = claims.get("sub")
        if not subject:
            raise jwt.InvalidTokenError("token has no subject")
        return Principal(
            user_id=str(subject),
            organization_id=claims.get("org_id"),
            email=claims.get("email"),
        )


_verifier = _Verifier()


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token if scheme.lower() == "bearer" and token else None


async def verify_presented_token(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Reject a bad token on *any* route, including the open ones.

    Middleware rather than a dependency on thirty endpoints. The rule is that
    presenting a forged credential is not the same as presenting none: an
    invalid token on an open route must fail rather than fall through as
    anonymous, or an attack looks identical to a preference. Attaching this to
    each route would have meant the rule held wherever somebody remembered it.
    """
    token = _bearer(request)
    if token is not None and _verifier.enabled:
        try:
            request.state.principal = _verifier.verify(token)
        except jwt.PyJWTError as exc:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": f"invalid token: {exc}"},
            )
    return await call_next(request)


async def viewer(request: Request) -> Principal | None:
    """Identity if the request carries one. Never required.

    Reads what the middleware already verified, so no route can accidentally
    skip verification by forgetting this dependency.
    """
    principal: Principal | None = getattr(request.state, "principal", None)
    if principal is None and _bearer(request) is not None and not _verifier.enabled:
        logger.warning("bearer token presented but %s is unset; ignoring", ISSUER_ENV)
    return principal


async def member(principal: Annotated[Principal | None, Depends(viewer)]) -> Principal:
    """Identity, required. Used only where a workspace is touched."""
    if principal is None:
        if not _verifier.enabled:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=(
                    f"{ISSUER_ENV} is not configured, so this deployment has no "
                    "identity provider and cannot scope workspace data."
                ),
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="sign in required")
    return principal


ViewerDep = Annotated[Principal | None, Depends(viewer)]
MemberDep = Annotated[Principal, Depends(member)]


async def current_workspace(session: SessionDep, principal: MemberDep) -> Workspace:
    """The caller's workspace, created on first use.

    Created rather than required-to-exist: a person who has just signed up has a
    workspace conceptually and nothing in the database, and making their first
    action fail would be a worse introduction than a row appearing.
    """
    external_id = principal.workspace_external_id
    found = (
        await session.execute(select(Workspace).where(Workspace.external_id == external_id))
    ).scalar_one_or_none()
    if found is not None:
        return found

    workspace = Workspace(
        workspace_id=uuid.uuid4(),
        external_id=external_id,
        name=principal.email or ("Organization" if principal.organization_id else "Personal"),
        kind="organization" if principal.organization_id else "personal",
    )
    session.add(workspace)
    await session.flush()
    session.add(
        WorkspaceMember(
            workspace_id=workspace.workspace_id,
            external_user_id=principal.user_id,
            role="owner",
        )
    )
    await session.commit()
    return workspace


WorkspaceDep = Annotated[Workspace, Depends(current_workspace)]


def describe() -> dict[str, object]:
    """What the health endpoint should say about auth.

    A deployment running open must say so rather than looking identical to a
    protected one.
    """
    return {
        "enabled": _verifier.enabled,
        "issuer_env": ISSUER_ENV,
        "note": (
            "Ontology reads are public by design (PRD §23). Only workspace "
            "objects require a session."
            if _verifier.enabled
            else "No identity provider configured; workspace endpoints return 501."
        ),
    }


async def is_member(session: AsyncSession, workspace_id: uuid.UUID, principal: Principal) -> bool:
    row = await session.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.external_user_id == principal.user_id,
        )
    )
    return row.scalar_one_or_none() is not None
