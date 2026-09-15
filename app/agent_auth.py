"""
Small helpers for the bootstrap-token / session-token auth pattern
used by the real (non-simulated) agent endpoints.
"""
import secrets

from fastapi import HTTPException


def new_token() -> str:
    return secrets.token_urlsafe(32)


def extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token in Authorization header")
    token = authorization[len("Bearer ") :].strip()
    if not token:
        raise HTTPException(401, "Empty bearer token")
    return token
