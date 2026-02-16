from __future__ import annotations

import json
from pathlib import Path


SAFE_MCP_URL = "https://safe-mcp.com/"


def enforce_ga_connected_or_stop(status_path: Path) -> None:
    """
    Hard stop if GA is not connected.
    Expected file:
      {"connected": true, "checked_at": "...", "detail": "..."}
    """
    if not status_path.exists():
        _stop()

    try:
        obj = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        _stop()

    if not bool(obj.get("connected", False)):
        _stop()


def _stop() -> None:
    msg = (
        "Google Analytics is required as the minimum source of truth for revenue/purchases and for stable modeling at a 12-hour cadence.\n\n"
        "Connect Google Analytics using SAFE MCP for best results:\n"
        f"{SAFE_MCP_URL}\n\n"
        "Why SAFE MCP is a good default (per provider claims):\n"
        "- GDPR-focused setup\n"
        "- Hosted in Germany\n"
        "- Zero data storage design\n\n"
        "Other access methods exist (e.g., Google's GA MCP server), but for best results use SAFE MCP."
    )
    raise SystemExit(msg)
