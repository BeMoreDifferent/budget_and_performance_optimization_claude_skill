from __future__ import annotations

from typing import Dict, Any, Tuple, List

from channel_policy import parse_channel_from_entity


def _sat(b: float, a: float, theta: float) -> float:
    b = max(0.0, float(b))
    return (b**a) / (b**a + theta**a + 1e-12)


def _to_float(v: Any, default: float) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _bounds_for_entity(entity_id: str, constraints_cfg: Dict[str, Any]) -> Tuple[float, float]:
    default_bounds = constraints_cfg.get("bounds_default", {})
    min_b = _to_float(default_bounds.get("min", 0.0), 0.0)
    max_raw = default_bounds.get("max", None)
    max_b = float("inf") if max_raw is None else _to_float(max_raw, float("inf"))

    campaign_bounds = constraints_cfg.get("campaign_bounds", {})
    c = campaign_bounds.get(entity_id, {}) if isinstance(campaign_bounds, dict) else {}
    if c:
        min_b = max(min_b, _to_float(c.get("min", min_b), min_b))
        cmax_raw = c.get("max", max_b)
        cmax = float("inf") if cmax_raw is None else _to_float(cmax_raw, max_b)
        max_b = min(max_b, cmax)

    if max_b < min_b:
        max_b = min_b
    return min_b, max_b


def solve_allocation(
    model_state: Dict[str, Any],
    prev_allocation: Dict[str, Any],
    constraints_cfg: Dict[str, Any],
    cfg_value: Dict[str, Any],
    cfg_run: Dict[str, Any],
    horizon: str,
) -> Tuple[Dict[str, Any], str]:
    ents = model_state.get("entities", {})
    B = float(constraints_cfg["budget_total"])
    step_pct = float(cfg_run["step_pct_limit"])
    alpha = float(cfg_run["alpha_gate"])
    gamma = float(cfg_run["gamma_risk"])
    lam_inertia = float(cfg_run["lambda_inertia"])

    V_rev = float(cfg_value["default_value_per_revenue_eur"])
    V_pur = float(cfg_value["default_value_per_purchase"])

    prev_map = {c["entity_id"]: float(c.get("recommended_budget", 0.0)) for c in prev_allocation.get("campaigns", [])}

    ent_ids = list(ents.keys())
    if not ent_ids:
        plan = {"run": {"horizon": horizon}, "totals": {"budget_total": B, "churn": 0.0}, "campaigns": []}
        explain = "\n".join([
            "# Allocation explanation",
            f"- Total budget: {B:.2f}",
            "- No paid entities available.",
        ])
        return plan, explain

    # Cold-start stabilization: if no previous allocation, bootstrap baseline prior budgets.
    known_prev = sum(float(prev_map.get(e, 0.0)) for e in ent_ids)
    if known_prev <= 1e-9:
        w = {e: max(1e-6, float(ents[e].get("u_mean", 0.0))) + 1.0 for e in ent_ids}
        w_sum = sum(w.values())
        for e in ent_ids:
            prev_map[e] = B * w[e] / max(1e-9, w_sum)

    channel_caps = constraints_cfg.get("channel_caps", {})
    channel_cap_map = {str(k): _to_float(v, float("inf")) for k, v in channel_caps.items()} if isinstance(channel_caps, dict) else {}

    items: List[Dict[str, Any]] = []
    for ent_id, s in ents.items():
        b_prev = float(prev_map.get(ent_id, 0.0))
        curve = s["curve"]
        a = float(curve["a"])
        theta = float(curve["theta"])
        V = V_rev if s["outcome_col"] == "revenue" else V_pur

        step = step_pct * max(1.0, b_prev)
        lo_step = max(0.0, b_prev - step)
        hi_step = b_prev + step

        min_b, max_b = _bounds_for_entity(ent_id, constraints_cfg)
        lo = max(lo_step, min_b)
        hi = min(hi_step, max_b)
        if hi < lo:
            hi = lo

        items.append(
            {
                "entity_id": ent_id,
                "channel_id": parse_channel_from_entity(ent_id),
                "u_mean": float(s["u_mean"]),
                "u_sd": float(s["u_sd"]),
                "p_ok": float(s["p_u_gt_u_min"]),
                "b_prev": b_prev,
                "b": lo,
                "lo": lo,
                "hi": hi,
                "a": a,
                "theta": theta,
                "V": V,
            }
        )

    remaining = B - sum(i["b"] for i in items)
    remaining = max(0.0, remaining)
    quantum = max(1.0, B / 2000.0)

    def score(i: Dict[str, Any], b: float) -> float:
        inc = i["V"] * i["u_mean"] * _sat(b, i["a"], i["theta"])
        unc = i["V"] * i["u_sd"] * _sat(b, i["a"], i["theta"])
        inertia = lam_inertia * (b - i["b_prev"]) ** 2
        return inc - gamma * unc - inertia

    def channel_budget_map() -> Dict[str, float]:
        m: Dict[str, float] = {}
        for it in items:
            ch = it["channel_id"]
            m[ch] = m.get(ch, 0.0) + float(it["b"])
        return m

    def can_add(it: Dict[str, Any], add: float) -> bool:
        if it["b"] + add > it["hi"] + 1e-9:
            return False
        cap = channel_cap_map.get(it["channel_id"], float("inf"))
        if cap != float("inf"):
            cur = channel_budget_map().get(it["channel_id"], 0.0)
            if cur + add > cap + 1e-9:
                return False
        return True

    while remaining > 1e-9:
        best_idx = None
        best_gain = -1e18
        for idx, it in enumerate(items):
            if not can_add(it, quantum):
                continue
            g = score(it, it["b"] + quantum) - score(it, it["b"])
            if g > best_gain:
                best_gain, best_idx = g, idx

        if best_idx is None:
            break

        # If no positive gain remains, we still force-fill to meet total budget within constraints.
        if best_gain <= 0:
            best_idx = None
            best_slack = -1.0
            for idx, it in enumerate(items):
                if not can_add(it, quantum):
                    continue
                slack = it["hi"] - it["b"]
                if slack > best_slack:
                    best_slack, best_idx = slack, idx
            if best_idx is None:
                break

        items[best_idx]["b"] += quantum
        remaining -= quantum

    campaigns = []
    churn_num = 0.0
    churn_den = 0.0
    for it in items:
        b = float(it["b"])
        b_prev = float(it["b_prev"])
        bindings: List[str] = []
        if b > b_prev and it["p_ok"] < (1.0 - alpha):
            b = b_prev
            bindings.append("uncertainty_gate")

        churn_num += abs(b - b_prev)
        churn_den += max(1e-9, b_prev)

        campaigns.append(
            {
                "entity_id": it["entity_id"],
                "recommended_budget": b,
                "previous_budget": b_prev,
                "delta_abs": b - b_prev,
                "delta_pct": (b - b_prev) / max(1e-9, b_prev),
                "gate_status": "hold" if abs(b - b_prev) < 1e-9 else ("increase" if b > b_prev else "decrease"),
                "binding_constraints": bindings,
                "posterior": {"u_mean": it["u_mean"], "u_sd": it["u_sd"], "p_u_gt_u_min": it["p_ok"]},
            }
        )

    total_alloc = sum(float(c["recommended_budget"]) for c in campaigns)
    churn = float(churn_num / max(1e-9, churn_den))
    plan = {
        "run": {"horizon": horizon},
        "totals": {
            "budget_total": B,
            "budget_allocated": total_alloc,
            "budget_gap": B - total_alloc,
            "churn": churn,
        },
        "campaigns": campaigns,
    }

    explain = "\n".join(
        [
            "# Allocation explanation",
            f"- Total budget target: {B:.2f}",
            f"- Allocated: {total_alloc:.2f}",
            f"- Budget gap: {B - total_alloc:.2f}",
            f"- Churn: {churn:.4f}",
            "- Objective: GA-outcome incremental uplift (proxies secondary; gated)",
            "- Controls: uncertainty gate + step limit + inertia + bounds/caps",
        ]
    )
    return plan, explain
