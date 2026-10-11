import asyncio
import sqlite3

import pytest

pytest.importorskip("fastapi")

from gitshield.web import llm
from gitshield.web.config import Settings
from gitshield.web.db import Database, hours_ago
from gitshield.web.fixes import FixOutput
from gitshield.web.llm import AnthropicProvider, BudgetedProvider, LLMError, get_provider


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self):
        self.calls = 0

    async def complete(self, system, user, schema):
        self.calls += 1
        return schema(start_line=1, end_line=1, replacement="x", explanation="y")


def test_cost_control_defaults(monkeypatch):
    for var in ("GITSHIELD_MAX_DIFF_CHARS", "LLM_EFFORT", "GITSHIELD_MAX_LLM_CALLS_PER_DAY",
                "GITSHIELD_MAX_AUTO_REVIEWS_PER_DAY", "GITSHIELD_API_TOKEN", "GITSHIELD_GAMIFICATION"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(github_token="t", llm_provider="none")
    assert s.max_diff_chars == 150000
    assert s.llm_effort == "medium"
    assert s.max_llm_calls_per_day == 200
    assert s.max_auto_reviews_per_day == 20
    assert s.api_token == "" and s.gamification_enabled is True


def test_cost_control_env_overrides(monkeypatch):
    monkeypatch.setenv("LLM_EFFORT", " High ")
    monkeypatch.setenv("GITSHIELD_MAX_LLM_CALLS_PER_DAY", "0")
    monkeypatch.setenv("GITSHIELD_GAMIFICATION", "off")
    s = Settings(github_token="t", llm_provider="none")
    assert s.llm_effort == "high" and s.max_llm_calls_per_day == 0
    assert s.gamification_enabled is False


def test_llm_daily_cap_stops_calls_with_a_clear_message(tmp_path):
    with Database(tmp_path / "b.db") as db:
        fake = FakeProvider()
        wrapped = BudgetedProvider(fake, db, daily_limit=2)
        for _ in range(2):
            asyncio.run(wrapped.complete("s", "u", FixOutput))
        with pytest.raises(LLMError, match="Günlük LLM çağrı limiti"):
            asyncio.run(wrapped.complete("s", "u", FixOutput))
        assert fake.calls == 2, "a refused call never reaches the provider"
        assert wrapped.name == "fake" and wrapped.model == "fake-model"


def test_llm_budget_zero_means_unlimited(tmp_path):
    with Database(tmp_path / "b.db") as db:
        fake = FakeProvider()
        wrapped = BudgetedProvider(fake, db, daily_limit=0)
        for _ in range(5):
            asyncio.run(wrapped.complete("s", "u", FixOutput))
        assert fake.calls == 5


def test_llm_budget_is_a_rolling_24_hour_window(tmp_path):
    with Database(tmp_path / "b.db") as db:
        db._exec("INSERT INTO llm_calls (created_at) VALUES (?)", (hours_ago(30),))
        assert db.reserve_llm_call(1) is True, "a call older than 24 hours does not count"
        assert db.reserve_llm_call(1) is False


def test_get_provider_is_metered(tmp_path, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(llm, "_make_provider", lambda: fake)
    with Database(tmp_path / "b.db") as db:
        assert isinstance(get_provider(db), BudgetedProvider)
    monkeypatch.setattr(llm, "_make_provider", lambda: None)
    with Database(tmp_path / "c.db") as db:
        assert get_provider(db) is None, "scanner-only mode has nothing to meter"


class FakeMessages:
    def __init__(self):
        self.kwargs = None

    async def parse(self, **kwargs):
        self.kwargs = kwargs

        class Response:
            stop_reason = "end_turn"
            parsed_output = FixOutput(start_line=1, end_line=1, replacement="x", explanation="y")

        return Response()


class FakeAnthropic:
    def __init__(self):
        self.beta = type("Beta", (), {"messages": FakeMessages()})()


def test_anthropic_effort_comes_from_config(monkeypatch):
    import anthropic

    client = FakeAnthropic()
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda: client)
    provider = AnthropicProvider("claude-test", "low")
    asyncio.run(provider.complete("s", "u", FixOutput))
    assert client.beta.messages.kwargs["output_config"] == {"effort": "low"}

    assert AnthropicProvider("claude-test").effort == "medium"
    assert AnthropicProvider("claude-test", "turbo").effort == "medium", "unknown levels fall back"


def test_database_close_releases_the_connection(tmp_path):
    db = Database(tmp_path / "c.db")
    db.set_setting("k", "v")
    db.close()
    with pytest.raises(sqlite3.ProgrammingError):
        db.get_setting("k")
    with Database(tmp_path / "d.db") as scoped:
        scoped.set_setting("k", "v")
    with pytest.raises(sqlite3.ProgrammingError):
        scoped.get_setting("k")
