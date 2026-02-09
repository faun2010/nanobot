"""Tool to return current local time."""

from datetime import datetime
from typing import Any

from nanobot.agent.tools.base import Tool


class NowTimeTool(Tool):
    """Return current local time as an ISO-8601 string."""

    @property
    def name(self) -> str:
        return "now_time"

    @property
    def description(self) -> str:
        return "Return the current local time string in ISO-8601 format with timezone."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")
