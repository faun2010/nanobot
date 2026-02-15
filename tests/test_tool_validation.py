from pathlib import Path
from typing import Any

import pytest
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, _resolve_path
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.session.manager import Session
from nanobot.utils.secrets import extract_secret_values, redact_sensitive_text


class SampleTool(Tool):
    @property
    def name(self) -> str:
        return "sample"

    @property
    def description(self) -> str:
        return "sample tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 2},
                "count": {"type": "integer", "minimum": 1, "maximum": 10},
                "mode": {"type": "string", "enum": ["fast", "full"]},
                "meta": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},
                        "flags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["tag"],
                },
            },
            "required": ["query", "count"],
        }

    async def execute(self, **kwargs: Any) -> str:
        return "ok"


def test_validate_params_missing_required() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi"})
    assert "missing required count" in "; ".join(errors)


def test_validate_params_type_and_range() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi", "count": 0})
    assert any("count must be >= 1" in e for e in errors)

    errors = tool.validate_params({"query": "hi", "count": "2"})
    assert any("count should be integer" in e for e in errors)


def test_validate_params_enum_and_min_length() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "h", "count": 2, "mode": "slow"})
    assert any("query must be at least 2 chars" in e for e in errors)
    assert any("mode must be one of" in e for e in errors)


def test_validate_params_nested_object_and_array() -> None:
    tool = SampleTool()
    errors = tool.validate_params(
        {
            "query": "hi",
            "count": 2,
            "meta": {"flags": [1, "ok"]},
        }
    )
    assert any("missing required meta.tag" in e for e in errors)
    assert any("meta.flags[0] should be string" in e for e in errors)


def test_validate_params_ignores_unknown_fields() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi", "count": 2, "extra": "x"})
    assert errors == []


async def test_registry_returns_validation_error() -> None:
    reg = ToolRegistry()
    reg.register(SampleTool())
    result = await reg.execute("sample", {"query": "hi"})
    assert "Invalid parameters" in result


def test_resolve_path_rejects_leading_or_trailing_whitespace() -> None:
    with pytest.raises(ValueError, match="leading or trailing whitespace"):
        _resolve_path(" /Users/panzm/.nanobot/workspace/memory/MEMORY.md")


def test_resolve_path_rejects_absolute_like_relative_path() -> None:
    with pytest.raises(ValueError, match="missing leading '/'"):
        _resolve_path("Users/panzm/.nanobot/workspace/memory/MEMORY.md")


@pytest.mark.asyncio
async def test_write_file_rejects_absolute_like_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    tool = WriteFileTool()

    result = await tool.execute(path="Users/alice/file.txt", content="x")

    assert result.startswith("Error:")
    assert "missing leading '/'" in result
    assert not (tmp_path / "Users").exists()


@pytest.mark.asyncio
async def test_write_file_allows_normal_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    tool = WriteFileTool()

    result = await tool.execute(path="notes/test.txt", content="hello")

    assert result.startswith("Successfully wrote")
    assert (tmp_path / "notes" / "test.txt").read_text(encoding="utf-8") == "hello"


class DummyProvider(LLMProvider):
    def __init__(self, content: str | None):
        super().__init__(api_key=None, api_base=None)
        self._content = content

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        return LLMResponse(content=self._content)

    def get_default_model(self) -> str:
        return "dummy"


class DummySessions:
    def save(self, session: Session) -> None:
        return None


class InMemorySessions:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def get_or_create(self, key: str) -> Session:
        return self._sessions.setdefault(key, Session(key=key))

    def save(self, session: Session) -> None:
        self._sessions[session.key] = session

    def invalidate(self, key: str) -> None:
        self._sessions.pop(key, None)


def test_extract_secret_values_from_config_like_dict() -> None:
    data = {
        "channels": {
            "email": {
                "imapPassword": "imap-secret-123",
                "smtpPassword": "smtp-secret-456",
                "imapHost": "imap.gmail.com",
            },
            "telegram": {"token": "123456:AA-telegram-token"},
        },
        "providers": {"openai": {"apiKey": "sk-test-987654321"}},
    }

    values = extract_secret_values(data)
    assert "imap-secret-123" in values
    assert "smtp-secret-456" in values
    assert "123456:AA-telegram-token" in values
    assert "sk-test-987654321" in values
    assert "imap.gmail.com" not in values


def test_redact_sensitive_text_masks_key_values_and_known_secret() -> None:
    text = (
        '{"imapPassword":"imap-secret-123","normal":"ok"}\n'
        "SMTP_PASSWORD=smtp-secret-456\n"
        "token: 123456:AA-telegram-token\n"
        "raw=sk-test-987654321\n"
    )
    output = redact_sensitive_text(text, known_secrets=["sk-test-987654321"])

    assert "imap-secret-123" not in output
    assert "smtp-secret-456" not in output
    assert "123456:AA-telegram-token" not in output
    assert "sk-test-987654321" not in output
    assert "***" in output


@pytest.mark.asyncio
async def test_read_file_tool_redacts_sensitive_pairs(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"channels":{"email":{"imapPassword":"imap-secret-123"}}}\n'
        "SMTP_PASSWORD=smtp-secret-456\n",
        encoding="utf-8",
    )

    tool = ReadFileTool()
    output = await tool.execute(path=str(config_path))

    assert "imap-secret-123" not in output
    assert "smtp-secret-456" not in output
    assert "***" in output


@pytest.mark.asyncio
async def test_agent_loop_redacts_known_secret_in_final_response(tmp_path: Path) -> None:
    loop = AgentLoop(
        bus=MessageBus(),
        provider=DummyProvider("Your imapPassword is imap-secret-123"),
        workspace=tmp_path,
        session_manager=InMemorySessions(),
        secret_values=["imap-secret-123"],
    )

    response = await loop.process_direct("show secret")
    assert "imap-secret-123" not in response
    assert "***" in response


def test_parse_consolidation_result_handles_code_fence_and_prefix(tmp_path: Path) -> None:
    loop = AgentLoop(bus=MessageBus(), provider=DummyProvider(None), workspace=tmp_path)
    wrapped = (
        "Here is JSON:\n```json\n"
        '{"history_entry":"h","memory_update":"m"}\n'
        "```"
    )
    parsed = loop._parse_consolidation_result(wrapped)
    assert parsed["history_entry"] == "h"
    assert parsed["memory_update"] == "m"


@pytest.mark.asyncio
async def test_consolidate_memory_fallback_trims_and_records_history(tmp_path: Path) -> None:
    loop = AgentLoop(
        bus=MessageBus(),
        provider=DummyProvider(""),
        workspace=tmp_path,
        memory_window=4,
    )
    loop.sessions = DummySessions()

    session = Session(
        key="cli:test",
        messages=[
            {"role": "user", "content": "u1", "timestamp": "2026-01-01T00:00:00"},
            {"role": "assistant", "content": "a1", "timestamp": "2026-01-01T00:00:01"},
            {"role": "user", "content": "u2", "timestamp": "2026-01-01T00:00:02"},
            {"role": "assistant", "content": "a2", "timestamp": "2026-01-01T00:00:03"},
            {"role": "user", "content": "u3", "timestamp": "2026-01-01T00:00:04"},
            {"role": "assistant", "content": "a3", "timestamp": "2026-01-01T00:00:05"},
        ],
    )

    await loop._consolidate_memory(session)

    assert len(session.messages) == 2
    history_text = (tmp_path / "memory" / "HISTORY.md").read_text(encoding="utf-8")
    assert "Consolidation fallback" in history_text
