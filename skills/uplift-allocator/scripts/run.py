from __future__ import annotations

import argparse
from pathlib import Path

from skill_io import read_yaml, read_json, write_json, write_text
from ga_gate import enforce_ga_connected_or_stop
from build_unified_view import build_unified_view
from proxy_eval import evaluate_proxies
from model_update import update_model_state
from allocate import solve_allocation
from verify import verify_and_challenge
from suggest_ga_only_plan import suggest_ga_only_plan
from optimize_budget import optimize_budget_for_target
from channel_policy import filter_model_state_paid


ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config"
DATA = ROOT / "data"
ART = ROOT / "artifacts"


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)

    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument("--start", default=None)
    run.add_argument("--end", default=None)
    run.add_argument("--horizon", default="12h")
    run.add_argument("--budget", default=None)
    run.add_argument("--target-incremental-revenue", default=None)

    sub.add_parser("build")
    sub.add_parser("proxies")
    sub.add_parser("model")
    sub.add_parser("allocate")
    sub.add_parser("verify")
    optimize = sub.add_parser("optimize_budget")
    optimize.add_argument("--target-incremental-revenue", required=True, type=float)
    optimize.add_argument("--horizon", default="12h")

    args = p.parse_args()

    cfg_run = read_yaml(CFG / "run.yaml")
    cfg_constraints = read_yaml(CFG / "constraints.yaml")
    cfg_value = read_yaml(CFG / "value.yaml")
    cfg_entities = read_yaml(CFG / "entities.yaml")

    if args.cmd == "run" and args.budget is not None:
        cfg_constraints["budget_total"] = float(args.budget)

    enforce_ga_connected_or_stop(ART / "ga_connection_status.json")

    unified_path = ART / "unified_view.csv"
    proxies_path = ART / "proxies_catalog.json"
    state_path = ART / "model_state.json"
    alloc_path = ART / "allocation_plan.json"
    explain_path = ART / "allocation_explanations.md"
    alerts_path = ART / "alerts.json"
    optimal_budget_path = ART / "optimal_budget_range.json"
    optimal_budget_explain_path = ART / "optimal_budget_explanations.md"

    if args.cmd in ("run", "build"):
        build_unified_view(
            ga_csv=DATA / "ga" / "ga_export_example.csv",
            ad_spend_csv=DATA / "ad" / "spend_example.csv",
            ad_proxy_csv=DATA / "ad" / "proxy_example.csv",
            out_csv=unified_path,
            start_iso=getattr(args, "start", None),
            end_iso=getattr(args, "end", None),
            cfg_run=cfg_run,
        )

    if args.cmd in ("run", "proxies"):
        prior = read_json(proxies_path, default={})
        catalog, report = evaluate_proxies(unified_path, prior, cfg_run)
        write_json(proxies_path, catalog)
        write_text(ART / "proxy_report.md", report)

    if args.cmd in ("run", "model"):
        catalog = read_json(proxies_path, default={})
        prev = read_json(state_path, default={})
        state, diag = update_model_state(unified_path, prev, catalog, cfg_run)
        write_json(state_path, state)
        write_json(ART / "fit_diagnostics.json", diag)

    if args.cmd in ("run", "allocate"):
        state_raw = read_json(state_path, default={})
        state = filter_model_state_paid(state_raw, cfg_run)
        prev_alloc = read_json(alloc_path, default={})
        has_ad_entities = bool(cfg_entities.get("entities"))

        # Contract-first behavior: if ad accounts are not configured, always use GA-only plan.
        if not has_ad_entities:
            plan, explain = suggest_ga_only_plan(
                unified_path=unified_path,
                total_budget=float(cfg_constraints["budget_total"]),
                cfg_run=cfg_run,
            )
        else:
            plan, explain = solve_allocation(
                model_state=state,
                prev_allocation=prev_alloc,
                constraints_cfg=cfg_constraints,
                cfg_value=cfg_value,
                cfg_run=cfg_run,
                horizon=getattr(args, "horizon", "12h"),
            )

        write_json(alloc_path, plan)
        write_text(explain_path, explain)

        catalog = read_json(proxies_path, default={})
        alerts = verify_and_challenge(
            unified_path=unified_path,
            model_state=state,
            proxy_catalog=catalog,
            allocation_plan=plan,
            cfg_run=cfg_run,
            constraints_cfg=cfg_constraints,
        )
        write_json(alerts_path, alerts)

    if args.cmd == "verify":
        state = filter_model_state_paid(read_json(state_path, default={}), cfg_run)
        catalog = read_json(proxies_path, default={})
        plan = read_json(alloc_path, default={})
        alerts = verify_and_challenge(
            unified_path=unified_path,
            model_state=state,
            proxy_catalog=catalog,
            allocation_plan=plan,
            cfg_run=cfg_run,
            constraints_cfg=cfg_constraints,
        )
        write_json(alerts_path, alerts)

    if args.cmd in ("run", "optimize_budget"):
        target = (
            float(getattr(args, "target_incremental_revenue", 0.0))
            if getattr(args, "target_incremental_revenue", None) is not None
            else None
        )
        if target is not None:
            state = filter_model_state_paid(read_json(state_path, default={}), cfg_run)
            prev_alloc = read_json(alloc_path, default={})
            optimal, explain = optimize_budget_for_target(
                model_state=state,
                prev_allocation=prev_alloc,
                constraints_cfg=cfg_constraints,
                cfg_value=cfg_value,
                cfg_run=cfg_run,
                target_incremental_revenue=target,
                horizon=getattr(args, "horizon", "12h"),
            )
            write_json(optimal_budget_path, optimal)
            write_text(optimal_budget_explain_path, explain)


if __name__ == "__main__":
    main()
