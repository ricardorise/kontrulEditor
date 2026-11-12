"""URLs de download assinadas e temporárias (o <video> do navegador não envia Bearer)."""
import base64
import hashlib
import hmac
import time

from app.config import settings


def _sig(payload: str) -> str:
    return hmac.new(settings.api_token.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def sign(resource: str, ttl_s: int = 3600) -> tuple[str, int]:
    exp = int(time.time()) + ttl_s
    payload = f"{resource}|{exp}"
    return base64.urlsafe_b64encode(f"{payload}|{_sig(payload)}".encode()).decode(), exp


def verify(token: str) -> str | None:
    try:
        resource, exp, sig = base64.urlsafe_b64decode(token.encode()).decode().rsplit("|", 2)
    except Exception:
        return None
    if int(exp) < time.time() or not hmac.compare_digest(sig, _sig(f"{resource}|{exp}")):
        return None
    return resource
