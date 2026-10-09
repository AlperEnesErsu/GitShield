import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

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
    llm_model_override: Optional[str] = field(default_factory=lambda: os.getenv("LLM_MODEL"))
    db_path: Path = field(
        default_factory=lambda: Path(os.getenv("GITSHIELD_DB", ".gitshield/web.db"))
    )
    # Upper bound on diff characters sent to the LLM; files beyond it are listed as skipped.
    max_diff_chars: int = field(
        default_factory=lambda: int(os.getenv("GITSHIELD_MAX_DIFF_CHARS", "400000"))
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
    def llm_model(self) -> str:
        return self.llm_model_override or DEFAULT_MODELS.get(self.llm_provider, "")


settings = Settings()
