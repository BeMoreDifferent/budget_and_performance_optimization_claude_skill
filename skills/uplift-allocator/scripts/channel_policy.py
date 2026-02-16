from __future__ import annotations

from typing import Dict, Any
import re


def _default_policy() -> Dict[str, list[str]]:
    return {
        "include_keywords": [
            "paid",
            "cpc",
            "ppc",
            "display",
            "shopping",
            "affiliate",
            "sponsored",
            "ads",
            "retarget",
            "prospecting",
            "meta",
            "facebook",
            "instagram",
            "tiktok",
            "linkedin",
            "youtube",
            "google ads",
            "bing ads",
            "snapchat",
            "pinterest",
        ],
        "exclude_keywords": [
            "organic",
            "direct",
            "referral",
            "seo",
            "unassigned",
            "(none)",
        ],
    }


def parse_channel_from_entity(entity_id: str) -> str:
    parts = str(entity_id).split("|")
    if len(parts) >= 3 and parts[0].lower() == "ga":
        return parts[1]
    if parts:
        return parts[0]
    return ""


def _norm(s: str) -> str:
    x = re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()
    return re.sub(r"\s+", " ", x)


def is_paid_entity(entity_id: str, cfg_run: Dict[str, Any]) -> bool:
    policy = cfg_run.get("paid_channel_policy", _default_policy())
    include = [_norm(k) for k in policy.get("include_keywords", [])]
    exclude = [_norm(k) for k in policy.get("exclude_keywords", [])]
    exact_paid = {_norm(k) for k in policy.get("exact_paid_channels", [])}
    exact_unpaid = {_norm(k) for k in policy.get("exact_unpaid_channels", [])}

    channel = _norm(parse_channel_from_entity(entity_id))
    whole = _norm(str(entity_id))

    if channel in exact_unpaid:
        return False
    if channel in exact_paid:
        return True

    if any(k in channel or k in whole for k in exclude):
        return False
    return any(k in channel or k in whole for k in include)


def filter_model_state_paid(model_state: Dict[str, Any], cfg_run: Dict[str, Any]) -> Dict[str, Any]:
    entities = model_state.get("entities", {})
    paid_entities = {
        ent_id: s for ent_id, s in entities.items() if is_paid_entity(ent_id, cfg_run)
    }
    out = dict(model_state)
    out["entities"] = paid_entities
    return out
