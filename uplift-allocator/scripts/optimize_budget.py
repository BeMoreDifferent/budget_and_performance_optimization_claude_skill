from __future__ import annotations

from typing import Dict, Any, Tuple

from allocate import solve_allocation
from channel_policy import parse_channel_from_entity


def _sat(b: float, a: float, theta: float) -> float:
    b = max(0.0, float(b))
    return (b**a) / (b**a + theta**a + 1e-12)


def _expected_incremental(
    plan: Dict[str, Any],
    model_state: Dict[str, Any],
    cfg_value: Dict[str, Any],
    z_score: float,
) -> Dict[str, float]:
    entities = model_state.get("entities", {})
    v_rev = float(cfg_value["default_value_per_revenue_eur"])
    v_pur = float(cfg_value["default_value_per_purchase"])

    optimistic = 0.0
    expected = 0.0
    conservative = 0.0

    for c in plan.get("campaigns", []):
        ent_id = c["entity_id"]
        s = entities.get(ent_id, {})
        if not s:
            continue
        curve = s["curve"]
        g = _sat(float(c["recommended_budget"]), float(curve["a"]), float(curve["theta"]))

        v = v_rev if s.get("outcome_col") == "revenue" else v_pur
        mu = float(s["u_mean"])
        sd = float(s["u_sd"])

        u_low = max(0.0, mu - z_score * sd)
        u_high = max(0.0, mu + z_score * sd)

        expected += v * mu * g
        conservative += v * u_low * g
        optimistic += v * u_high * g

    return {
        "optimistic": float(optimistic),
        "expected": float(expected),
        "conservative": float(conservative),
    }


def _channel_aggregate(plan: Dict[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for c in plan.get("campaigns", []):
        ch = parse_channel_from_entity(c["entity_id"])
        out[ch] = out.get(ch, 0.0) + float(c["recommended_budget"])
    return out


def optimize_budget_for_target(
    model_state: Dict[str, Any],
    prev_allocation: Dict[str, Any],
    constraints_cfg: Dict[str, Any],
    cfg_value: Dict[str, Any],
    cfg_run: Dict[str, Any],
    target_incremental_revenue: float,
    horizon: str,
) -> Tuple[Dict[str, Any], str]:
    entities = model_state.get("entities", {})
    if not entities:
        raise ValueError("No paid entities available for optimization.")

    prev_map = {
        c["entity_id"]: float(c.get("recommended_budget", 0.0))
        for c in prev_allocation.get("campaigns", [])
    }

    step_pct = float(cfg_run["step_pct_limit"])
    min_budget = 0.0
    max_budget = 0.0
    for ent_id in entities:
        b_prev = float(prev_map.get(ent_id, 0.0))
        step = step_pct * max(1.0, b_prev)
        min_budget += max(0.0, b_prev - step)
        max_budget += b_prev + step

    if max_budget < min_budget:
        max_budget = min_budget

    z_score = float(cfg_run.get("optimizer", {}).get("z_score", 1.28))
    grid_points = int(cfg_run.get("optimizer", {}).get("grid_points", 41))
    grid_points = max(5, grid_points)

    candidates = []
    if abs(max_budget - min_budget) < 1e-9:
        budgets = [min_budget]
    else:
        budgets = [
            min_budget + (max_budget - min_budget) * i / (grid_points - 1)
            for i in range(grid_points)
        ]

    for b in budgets:
        c_cfg = dict(constraints_cfg)
        c_cfg["budget_total"] = float(b)
        plan, _ = solve_allocation(
            model_state=model_state,
            prev_allocation=prev_allocation,
            constraints_cfg=c_cfg,
            cfg_value=cfg_value,
            cfg_run=cfg_run,
            horizon=horizon,
        )
        fit = _expected_incremental(plan, model_state, cfg_value, z_score)
        candidates.append({"budget": float(b), "fit": fit, "plan": plan})

    def first_budget(metric: str) -> float | None:
        for row in candidates:
            if row["fit"][metric] >= target_incremental_revenue:
                return float(row["budget"])
        return None

    b_opt = first_budget("optimistic")
    b_exp_hit = first_budget("expected")
    b_con = first_budget("conservative")
    b_exp = b_exp_hit if b_exp_hit is not None else float(candidates[-1]["budget"])

    plan_by_budget = {round(c["budget"], 8): c["plan"] for c in candidates}

    def get_plan(b: float | None) -> Dict[str, Any] | None:
        if b is None:
            return None
        return plan_by_budget.get(round(float(b), 8))

    p_opt = get_plan(b_opt)
    p_exp = get_plan(b_exp)
    p_con = get_plan(b_con)

    base_low = _channel_aggregate(p_exp if p_exp is not None else candidates[-1]["plan"])
    base_high = _channel_aggregate(p_con if p_con is not None else (p_exp if p_exp is not None else candidates[-1]["plan"]))

    channel_ranges = []
    keys = sorted(set(base_low) | set(base_high))
    for k in keys:
        lo = float(base_low.get(k, 0.0))
        hi = float(base_high.get(k, lo))
        channel_ranges.append(
            {
                "channel_id": k,
                "min_recommended": min(lo, hi),
                "max_recommended": max(lo, hi),
            }
        )

    result = {
        "run": {"horizon": horizon},
        "target_incremental_revenue": float(target_incremental_revenue),
        "feasibility": {
            "optimistic": b_opt is not None,
            "expected": b_exp_hit is not None,
            "conservative": b_con is not None,
        },
        "budget_points": {
            "optimistic_budget": b_opt,
            "expected_budget": b_exp,
            "conservative_budget": b_con,
            "search_bounds": {"min": float(min_budget), "max": float(max_budget)},
        },
        "channel_budget_ranges": channel_ranges,
    }

    explain = "\n".join(
        [
            "# Optimal budget range for target incremental revenue",
            f"- Target incremental revenue: {target_incremental_revenue:.2f}",
            f"- Budget search bounds: [{min_budget:.2f}, {max_budget:.2f}]",
            f"- Expected budget point: {float(b_exp):.2f}" + ("" if b_exp_hit is not None else " (fallback max budget; target not reached)"),
            f"- Conservative budget point: {('not reachable' if b_con is None else f'{float(b_con):.2f}')}",
            "- Channel ranges are derived from expected-to-conservative plans for reliable spend bands.",
        ]
    )

    return result, explain
