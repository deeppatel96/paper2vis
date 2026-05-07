"""Clerk JWT verification for FastAPI.

If CLERK_JWKS_URL is not set the dependency returns "dev" so the app
continues to work in local development without a Clerk account.
"""
from __future__ import annotations

import os

from fastapi import Header, HTTPException

_jwks_client = None
_jwks_ready = False


def _build_client():
    global _jwks_client, _jwks_ready
    if _jwks_ready:
        return _jwks_client
    url = os.environ.get("CLERK_JWKS_URL", "")
    if url:
        from jwt import PyJWKClient
        _jwks_client = PyJWKClient(url, cache_jwk_set=True, lifespan=300)
    _jwks_ready = True
    return _jwks_client


def verify_token(authorization: str = Header(default="")) -> str:
    """FastAPI dependency. Returns the Clerk user ID (sub claim).

    In local dev (CLERK_JWKS_URL not set) returns "dev" without checking.
    """
    client = _build_client()

    if client is None:
        # Auth not configured — local dev, skip verification
        return "dev"

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = authorization[7:]
    try:
        import jwt as pyjwt
        signing_key = client.get_signing_key_from_jwt(token)
        data = pyjwt.decode(token, signing_key.key, algorithms=["RS256"])
        return data["sub"]
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
