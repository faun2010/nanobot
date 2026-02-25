"""LLM provider wrapper that logs full request/response exchanges."""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.utils.helpers import ensure_dir, safe_filename

_DATA_URL_RE = re.compile(
    r"data:(?P<mime>[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+);base64,(?P<data>[A-Za-z0-9+/=\s]+)"
)


class _LLMExchangeLogger:
    """Writes LLM request/response traces to workspace logs."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.logs_dir = self._resolve_logs_dir(workspace)
        self.attachments_root = self._resolve_attachments_dir(self.logs_dir)
        self._write_lock = threading.Lock()

    @staticmethod
    def _resolve_logs_dir(workspace: Path) -> Path:
        candidates = [
            workspace / "logs",
            Path.home() / ".nanobot" / "logs",
            Path("/tmp/nanobot-logs"),
        ]
        for path in candidates:
            try:
                return ensure_dir(path)
            except Exception:
                continue
        # Final fallback: disable attachment writes but keep object usable.
        return Path("/tmp")

    @staticmethod
    def _resolve_attachments_dir(logs_dir: Path) -> Path:
        try:
            return ensure_dir(logs_dir / "attachments")
        except Exception:
            return logs_dir

    def new_call_id(self) -> str:
        now = datetime.now()
        return f"{now.strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:8]}"

    def log_exchange(
        self,
        *,
        call_id: str,
        provider: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any] | None,
        error: str | None,
        duration_ms: int,
    ) -> None:
        """Append one LLM exchange record."""
        try:
            request_attachments: list[dict[str, Any]] = []
            response_attachments: list[dict[str, Any]] = []
            request_logged = self._decode_data_urls(
                request_payload,
                call_id=call_id,
                direction="request",
                attachments=request_attachments,
                path_hint="request",
            )
            response_logged = self._decode_data_urls(
                response_payload,
                call_id=call_id,
                direction="response",
                attachments=response_attachments,
                path_hint="response",
            )

            entry = {
                "timestamp": datetime.now().isoformat(),
                "call_id": call_id,
                "provider": provider,
                "duration_ms": duration_ms,
                "request": request_logged,
                "response": response_logged,
                "error": error,
                "attachments": request_attachments + response_attachments,
            }
            self._append_jsonl(entry)
        except Exception:
            # Tracing must never affect the main request path.
            return

    def _append_jsonl(self, payload: dict[str, Any]) -> None:
        day = datetime.now().strftime("%Y-%m-%d")
        log_file = self.logs_dir / f"llm_api_{day}.jsonl"
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with self._write_lock:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def _decode_data_urls(
        self,
        value: Any,
        *,
        call_id: str,
        direction: str,
        attachments: list[dict[str, Any]],
        path_hint: str,
    ) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                child_path = f"{path_hint}.{k}"
                out[k] = self._decode_data_urls(
                    v,
                    call_id=call_id,
                    direction=direction,
                    attachments=attachments,
                    path_hint=child_path,
                )
            return out
        if isinstance(value, list):
            out_list: list[Any] = []
            for i, item in enumerate(value):
                child_path = f"{path_hint}[{i}]"
                out_list.append(
                    self._decode_data_urls(
                        item,
                        call_id=call_id,
                        direction=direction,
                        attachments=attachments,
                        path_hint=child_path,
                    )
                )
            return out_list
        if isinstance(value, str):
            return self._decode_data_urls_in_text(
                value,
                call_id=call_id,
                direction=direction,
                attachments=attachments,
                path_hint=path_hint,
            )
        return value

    def _decode_data_urls_in_text(
        self,
        text: str,
        *,
        call_id: str,
        direction: str,
        attachments: list[dict[str, Any]],
        path_hint: str,
    ) -> str:
        matches = list(_DATA_URL_RE.finditer(text))
        if not matches:
            return text

        parts: list[str] = []
        last_end = 0
        for m in matches:
            parts.append(text[last_end:m.start()])
            mime = m.group("mime")
            b64 = re.sub(r"\s+", "", m.group("data"))
            try:
                raw = base64.b64decode(b64, validate=True)
            except Exception:
                parts.append(m.group(0))
                last_end = m.end()
                continue

            meta = self._write_attachment(
                raw=raw,
                mime=mime,
                call_id=call_id,
                direction=direction,
                index=len(attachments) + 1,
                source_path=path_hint,
            )
            attachments.append(meta)
            parts.append(
                f"[decoded_attachment path={meta['path']} mime={meta['mime']} bytes={meta['bytes']}]"
            )
            last_end = m.end()

        parts.append(text[last_end:])
        return "".join(parts)

    def _write_attachment(
        self,
        *,
        raw: bytes,
        mime: str,
        call_id: str,
        direction: str,
        index: int,
        source_path: str,
    ) -> dict[str, Any]:
        day = datetime.now().strftime("%Y-%m-%d")
        target_dir = ensure_dir(self.attachments_root / day)
        ext = mimetypes.guess_extension(mime) or ".bin"
        filename = safe_filename(f"{call_id}_{direction}_{index}{ext}")
        path = target_dir / filename
        path.write_bytes(raw)
        try:
            rel_path = str(path.relative_to(self.workspace))
        except Exception:
            rel_path = str(path)
        return {
            "path": rel_path,
            "mime": mime,
            "bytes": len(raw),
            "source": source_path,
        }


class LLMLoggingProvider(LLMProvider):
    """Wraps a provider and records every chat() request/response exchange."""

    def __init__(self, inner: LLMProvider, workspace: Path):
        super().__init__(api_key=getattr(inner, "api_key", None), api_base=getattr(inner, "api_base", None))
        self._inner = inner
        self._logger = _LLMExchangeLogger(workspace)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        call_id = self._logger.new_call_id()
        started = time.perf_counter()
        error: str | None = None
        response: LLMResponse | None = None

        request_payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
            "tools": tools,
        }

        try:
            response = await self._inner.chat(
                messages=messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            response_payload = self._response_to_dict(response) if response is not None else None
            self._logger.log_exchange(
                call_id=call_id,
                provider=self._inner.__class__.__name__,
                request_payload=request_payload,
                response_payload=response_payload,
                error=error,
                duration_ms=duration_ms,
            )

    @staticmethod
    def _response_to_dict(response: LLMResponse) -> dict[str, Any]:
        return {
            "content": response.content,
            "reasoning_content": response.reasoning_content,
            "finish_reason": response.finish_reason,
            "usage": response.usage,
            "tool_calls": [
                {
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                }
                for tc in response.tool_calls
            ],
        }

    def get_default_model(self) -> str:
        return self._inner.get_default_model()
