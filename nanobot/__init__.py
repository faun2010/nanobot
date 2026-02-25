"""
nanobot - A lightweight AI agent framework
"""


def _ensure_httpx_compat() -> None:
    """Backfill httpx transport exports for mismatched dependency sets.

    Some third-party SDK versions still import BaseTransport directly from
    `httpx`. In mixed environments this symbol may be absent from the top-level
    module even though the transport classes still exist internally.
    """
    try:
        import httpx  # type: ignore
    except Exception:
        return

    if hasattr(httpx, "BaseTransport"):
        return

    try:
        from httpx._transports.base import AsyncBaseTransport, BaseTransport  # type: ignore
    except Exception:
        return

    httpx.BaseTransport = BaseTransport  # type: ignore[attr-defined]
    httpx.AsyncBaseTransport = AsyncBaseTransport  # type: ignore[attr-defined]


_ensure_httpx_compat()

__version__ = "0.1.4.post2"
__logo__ = "🐈"
