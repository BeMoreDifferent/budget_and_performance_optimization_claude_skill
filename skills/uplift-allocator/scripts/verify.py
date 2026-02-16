from __future__ import annotations

from typing import Dict, Any, List
import pandas as pd
from channel_policy import is_paid_entity


def verify_and_challenge(
    unified_path,
    model_state: Dict[str, Any],
    proxy_catalog: Dict[str, Any],
    allocation_plan: Dict[str, Any],
    cfg_run: Dict[str, Any],
    constraints_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    _ = model_state
    alerts: List[Dict[str, Any]] = []
    hard_fail = False

    B = float(constraints_cfg["budget_total"])
    total = sum(float(c["recommended_budget"]) for c in allocation_plan.get("campaigns", []))
    if abs(total - B) > 1e-6 * max(1.0, B):
        hard_fail = True
        alerts.append({"type": "budget_total_mismatch", "severity": "hard", "detail": f"sum={total}, expected={B}"})

    step_pct = float(cfg_run["step_pct_limit"])
    for c in allocation_plan.get("campaigns", []):
        if not is_paid_entity(str(c["entity_id"]), cfg_run):
            hard_fail = True
            alerts.append({"type": "unpaid_channel_allocation", "severity": "hard", "detail": c["entity_id"]})

        b = float(c["recommended_budget"])
        b_prev = float(c["previous_budget"])
        step = step_pct * max(1.0, b_prev)
        if abs(b - b_prev) > step + 1e-9:
            hard_fail = True
            alerts.append({"type": "step_limit_violation", "severity": "hard", "detail": c["entity_id"]})

    churn_limit = float(cfg_run["daily_churn_limit"])
    churn = float(allocation_plan.get("totals", {}).get("churn", 0.0))
    if churn > churn_limit:
        hard_fail = True
        alerts.append({"type": "churn_limit_violation", "severity": "hard", "detail": f"churn={churn:.4f}"})

    for name, meta in proxy_catalog.items():
        if float(meta.get("sigma", 999.0)) < float(cfg_run["proxy"]["sigma_floor"]):
            alerts.append({"type": "proxy_too_trusted", "severity": "warn", "detail": f"{name} sigma={meta.get('sigma')}"})

    df = pd.read_csv(unified_path)
    rev_sum = float(df["revenue"].sum()) if "revenue" in df.columns else 0.0
    pur_sum = float(df["purchases"].sum()) if "purchases" in df.columns else 0.0
    if rev_sum <= 0 and pur_sum < 5:
        alerts.append({"type": "very_low_signal", "severity": "warn", "detail": "GA outcomes sparse; allocator will mostly hold due to gating"})

    return {"hard_fail": hard_fail, "alerts": alerts}
