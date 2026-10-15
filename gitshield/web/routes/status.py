from typing import Any

from fastapi import APIRouter, Request

from gitshield import __version__
from gitshield.web.config import settings
from gitshield.web.github import GitHubError
from gitshield.web.routes.deps import gh

router = APIRouter()


@router.get("/api/status")
async def status(request: Request) -> dict[str, Any]:
    login = None
    error = None
    if settings.github_token:
        try:
            login = (await gh(request).viewer())["login"]
        except GitHubError as e:
            error = e.message
    else:
        error = "GITHUB_TOKEN tanımlı değil."
    return {
        "version": __version__,
        "github": {"login": login, "error": error},
        "llm": {"provider": settings.llm_provider, "model": settings.llm_model},
        "review_language": settings.review_language,
    }
