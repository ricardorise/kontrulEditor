import hmac

from fastapi import Depends, Header, HTTPException

from app.config import settings
from app.db import get_session  # noqa: F401  (re-export)


def require_auth(authorization: str | None = Header(default=None)) -> str:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token or not hmac.compare_digest(token, settings.api_token):
        raise HTTPException(401, "token inválido ou ausente")
    return "default"
