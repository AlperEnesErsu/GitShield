"""Request guards for a local server that acts with the user's GitHub token.

Any website the user visits can make the browser send requests to 127.0.0.1. Two attacks matter:

- CSRF: a cross-site form or fetch triggers a write (open an issue, rerun CI, submit a review).
  Every state-changing request must carry the ``X-GitShield-Client`` header. Browsers only send a
  custom header cross-origin after a CORS preflight, which this server never approves.
- DNS rebinding: a hostile domain re-resolves to 127.0.0.1 and reads responses (private code).
  Requests are only served when the Host header names the local machine.
"""

import hmac
import os
from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from gitshield.web.config import settings

CLIENT_HEADER = "x-gitshield-client"
TOKEN_COOKIE = "gitshield_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def allowed_hosts(extra: Iterable[str] | None = None) -> set[str]:
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
    def __init__(self, app, extra_hosts: Iterable[str] | None = None):
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


def _same_token(supplied: str | None, expected: str) -> bool:
    if not supplied:
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


class ApiTokenMiddleware(BaseHTTPMiddleware):
    """Optional shared secret for the API (GITSHIELD_API_TOKEN).

    Without it, any local process can call the API and act with the user's GitHub token. With it,
    every /api/* request must carry ``Authorization: Bearer <token>`` or the ``gitshield_token``
    cookie. The browser gets that cookie once by opening ``/?token=<token>``; the cookie is
    HttpOnly and SameSite=Strict, and the token is removed from the address bar by the redirect.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        expected = settings.api_token
        if not expected:
            return await call_next(request)

        supplied_in_url = request.query_params.get("token")
        if request.url.path == "/" and supplied_in_url is not None:
            if not _same_token(supplied_in_url, expected):
                return JSONResponse({"detail": "Invalid token."}, status_code=401)
            response = RedirectResponse("/", status_code=302)
            response.set_cookie(TOKEN_COOKIE, expected, httponly=True, samesite="strict", path="/")
            return response

        if request.url.path == "/api" or request.url.path.startswith("/api/"):
            scheme, _, value = request.headers.get("authorization", "").partition(" ")
            bearer = value.strip() if scheme.lower() == "bearer" else None
            if not (_same_token(bearer, expected) or _same_token(request.cookies.get(TOKEN_COOKIE), expected)):
                return JSONResponse({"detail": "API token required."}, status_code=401)
        return await call_next(request)
