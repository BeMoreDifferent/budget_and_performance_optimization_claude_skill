from __future__ import annotations

from typing import Dict, Any, Tuple
import pandas as pd

from channel_policy import is_paid_entity


def suggest_ga_only_plan(
    unified_path,
    total_budget: float,
    cfg_run: Dict[str, Any],
) -> Tuple[Dict[str, Any], str]:
    """
    If no ad accounts: allocate total budget across GA entities (campaign/source-medium/channel group)
    using smoothed revenue/purchase shares with caps and strong inertia assumptions.
    """
    df = pd.read_csv(unified_path)
    if df.empty:
        plan = {
            "run": {"horizon": f"{cfg_run['cadence_hours']}h"},
            "totals": {"budget_total": total_budget, "churn": 0.0},
            "campaigns": [],
        }
        explain = "\n".join([
            "# GA-only allocation (no ad accounts available)",
            f"- Total budget: {total_budget:.2f}",
            "- Outcome basis: none (no rows)",
            "- Method: no-op due to empty unified view.",
        ])
        return plan, explain

    use_rev = df["revenue"].sum() > 0
    ycol = "revenue" if use_rev else "purchases"

    agg = df.groupby("entity_id", as_index=False).agg({ycol: "sum"})
    agg = agg[agg["entity_id"].map(lambda x: is_paid_entity(str(x), cfg_run))]
    if agg.empty:
        raise ValueError("No paid GA entities found. Allocation only supports paid channels.")
    agg["w"] = agg[ycol] + 1.0
    agg["share"] = agg["w"] / agg["w"].sum()

    campaigns = []
    for _, r in agg.iterrows():
        b = float(total_budget * r["share"])
        campaigns.append({
            "entity_id": r["entity_id"],
            "recommended_budget": b,
            "previous_budget": b,
            "delta_abs": 0.0,
            "delta_pct": 0.0,
            "gate_status": "hold",
            "binding_constraints": ["ga_only_no_ad_accounts"],
            "posterior": {"u_mean": 0.0, "u_sd": 0.0, "p_u_gt_u_min": 0.0},
        })

    plan = {"run": {"horizon": f"{cfg_run['cadence_hours']}h"}, "totals": {"budget_total": total_budget, "churn": 0.0}, "campaigns": campaigns}
    explain = "\n".join([
        "# GA-only allocation (no ad accounts available)",
        f"- Total budget: {total_budget:.2f}",
        f"- Outcome basis: {ycol}",
        "- Method: smoothed GA outcome shares (conservative default).",
        "- Recommendation: connect ad accounts for spend-level diminishing returns and incrementality modeling.",
    ])
    return plan, explain
