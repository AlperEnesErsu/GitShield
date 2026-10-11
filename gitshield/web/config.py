import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Used when the primary model times out or returns 5xx (LLM_FALLBACK_MODEL overrides).
DEFAULT_FALLBACK_MODELS = {
    "gemini": "gemini-3.5-flash",
}

DEFAULT_MODELS = {
    "anthropic": "claude-opus-5-5",
    "gemini": "gemini-flash-latest",  # free tier has no Pro quota
    "openai": "gpt-5",
}


def _github_token() -> str:
    """GITHUB_TOKEN from the environment, falling back to the GitHub CLI's login."""
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token or not shutil.which("gh"):
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _detect_provider() -> str:
    explicit = os.getenv("LLM_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "none"


@dataclass
class Settings:
    github_token: str = field(default_factory=_github_token)
    github_api_url: str = field(
        default_factory=lambda: os.getenv("GITHUB_API_URL", "https://api.github.com")
    )
    llm_provider: str = field(default_factory=_detect_provider)
    llm_model_override: str | None = field(default_factory=lambda: os.getenv("LLM_MODEL"))
    db_path: Path = field(
        default_factory=lambda: Path(os.getenv("GITSHIELD_DB", ".gitshield/web.db"))
    )
    # Upper bound on diff characters sent to the LLM; files beyond it are listed as skipped.
    max_diff_chars: int = field(
        default_factory=lambda: int(os.getenv("GITSHIELD_MAX_DIFF_CHARS", "150000"))
    )
    # Anthropic reasoning effort (LLM_EFFORT): lower is cheaper and faster.
    llm_effort: str = field(
        default_factory=lambda: os.getenv("LLM_EFFORT", "medium").strip().lower() or "medium"
    )
    # Daily cap on LLM requests (review, verification, fix, CI deep-dive); 0 = unlimited.
    max_llm_calls_per_day: int = field(
        default_factory=lambda: int(os.getenv("GITSHIELD_MAX_LLM_CALLS_PER_DAY", "200"))
    )
    # Daily cap on reviews the watcher starts on its own; 0 = unlimited.
    max_auto_reviews_per_day: int = field(
        default_factory=lambda: int(os.getenv("GITSHIELD_MAX_AUTO_REVIEWS_PER_DAY", "20"))
    )
    # When set, every /api/* request must present it (Bearer header or the gitshield_token cookie).
    api_token: str = field(default_factory=lambda: os.getenv("GITSHIELD_API_TOKEN", "").strip())
    # "off" hides the gamification API and its XP / streak scoring.
    gamification_enabled: bool = field(
        default_factory=lambda: os.getenv("GITSHIELD_GAMIFICATION", "on").strip().lower()
        not in ("off", "0", "false", "no")
    )

    # Seconds between auto-review polls of opted-in repos; 0 disables the watcher.
    auto_review_interval: int = field(
        default_factory=lambda: int(os.getenv("GITSHIELD_AUTO_REVIEW_INTERVAL", "300"))
    )
    # Natural language the reviewer writes comments in.
    review_language: str = field(
        default_factory=lambda: os.getenv("GITSHIELD_REVIEW_LANGUAGE", "Turkish")
    )

    @property
    def llm_fallback_model(self) -> str | None:
        return os.getenv("LLM_FALLBACK_MODEL") or DEFAULT_FALLBACK_MODELS.get(self.llm_provider)

    @property
    def llm_model(self) -> str:
        return self.llm_model_override or DEFAULT_MODELS.get(self.llm_provider, "")


settings = Settings()
