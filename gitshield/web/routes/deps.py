"""Shared request helpers for the route modules."""

from typing import Any

from fastapi import HTTPException, Request

from gitshield.web.db import Database
from gitshield.web.github import GitHubClient


def db(request: Request) -> Database:
    return request.app.state.db


def gh(request: Request) -> GitHubClient:
    return request.app.state.gh


def _review_or_404(request: Request, review_id: int) -> dict[str, Any]:
    review = db(request).get_review(review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    return review
