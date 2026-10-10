"""Request guards for a local server that acts with the user's GitHub token.

Any website the user visits can make the browser send requests to 127.0.0.1. Two attacks matter:

- CSRF: a cross-site form or fetch triggers a write (open an issue, rerun CI, submit a review).
  Every state-changing request must carry the ``X-GitShield-Client`` header. Browsers only send a
  custom header cross-origin after a CORS preflight, which this server never approves.
- DNS rebinding: a hostile domain re-resolves to 127.0.0.1 and reads responses (private code).
  Requests are only served when the Host header names the local machine.
"""

import os
from typing import Iterable, Optional, Set
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

CLIENT_HEADER = "x-gitshield-client"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def allowed_hosts(extra: Optional[Iterable[str]] = None) -> Set[str]:
    hosts = set(LOCAL_HOSTS)
    hosts.update(h.strip().lower() for h in os.getenv("GITSHIELD_ALLOWED_HOSTS", "").split(",") if h.strip())
    hosts.update(extra or [])
    return hosts


def hostname(value: str) -> str:
    """'localhost:8000' -> 'localhost', '[::1]:8000' -> '::1'."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[1:value.find("]")]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, extra_hosts: Optional[Iterable[str]] = None):
        super().__init__(app)
        self.hosts = allowed_hosts(extra_hosts)

    async def dispatch(self, request: Request, call_next):
        if hostname(request.headers.get("host", "")) not in self.hosts:
            return JSONResponse({"detail": "Host not allowed."}, status_code=400)
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and hostname(urlsplit(origin).netloc) not in self.hosts:
                return JSONResponse({"detail": "Cross-origin request refused."}, status_code=403)
            if request.headers.get(CLIENT_HEADER) is None:
                return JSONResponse({"detail": f"Missing {CLIENT_HEADER} header."}, status_code=403)
        return await call_next(request)
