from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]


class UpliftAllocatorSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = SKILL_DIR / ".tmp_test"
        if self.tmp.exists():
            shutil.rmtree(self.tmp)
        shutil.copytree(
            SKILL_DIR,
            self.tmp,
            ignore=shutil.ignore_patterns(".venv", ".tmp_test", "__pycache__", "*.pyc"),
            dirs_exist_ok=True,
        )

    def tearDown(self) -> None:
        if self.tmp.exists():
            shutil.rmtree(self.tmp)

    def _run(self, *args: str):
        return subprocess.run(
            [sys.executable, str(self.tmp / "scripts" / "run.py"), *args],
            cwd=str(self.tmp),
            text=True,
            capture_output=True,
            check=False,
        )

    def _import_from_tmp_scripts(self, module_name: str):
        scripts_path = str(self.tmp / "scripts")
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        if module_name in sys.modules:
            del sys.modules[module_name]
        return importlib.import_module(module_name)

    def test_end_to_end_run_writes_required_outputs(self) -> None:
        proc = self._run("run", "--horizon", "12h", "--budget", "20000")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

        alloc = self.tmp / "artifacts" / "allocation_plan.json"
        explain = self.tmp / "artifacts" / "allocation_explanations.md"
        alerts = self.tmp / "artifacts" / "alerts.json"
        self.assertTrue(alloc.exists())
        self.assertTrue(explain.exists())
        self.assertTrue(alerts.exists())

        plan = json.loads(alloc.read_text(encoding="utf-8"))
        self.assertIn("campaigns", plan)
        self.assertGreater(len(plan["campaigns"]), 0)
        self.assertTrue(all("Organic Search" not in c["entity_id"] for c in plan["campaigns"]))

        alerts_obj = json.loads(alerts.read_text(encoding="utf-8"))
        self.assertFalse(alerts_obj["hard_fail"])

    def test_ga_gate_hard_stop_when_disconnected(self) -> None:
        status = self.tmp / "artifacts" / "ga_connection_status.json"
        status.write_text('{"connected": false}', encoding="utf-8")

        proc = self._run("run")
        self.assertNotEqual(proc.returncode, 0)
        text = proc.stderr + proc.stdout
        self.assertIn("Google Analytics is required", text)
        self.assertIn("https://safe-mcp.com/", text)

    def test_verify_budget_mismatch_hard_fail(self) -> None:
        verify = self._import_from_tmp_scripts("verify")

        unified = self.tmp / "artifacts" / "unified_view.csv"
        unified.write_text(
            "time_bucket_start,entity_id,revenue,purchases\n"
            "2026-02-15T00:00:00Z,ga|A|c1,1,1\n",
            encoding="utf-8",
        )

        alerts = verify.verify_and_challenge(
            unified_path=unified,
            model_state={"entities": {}},
            proxy_catalog={},
            allocation_plan={
                "totals": {"churn": 0.0},
                "campaigns": [
                    {"entity_id": "ga|A|c1", "recommended_budget": 10.0, "previous_budget": 10.0},
                ],
            },
            cfg_run={"step_pct_limit": 0.05, "daily_churn_limit": 0.10, "proxy": {"sigma_floor": 1.0}},
            constraints_cfg={"budget_total": 20.0},
        )
        self.assertTrue(alerts["hard_fail"])
        self.assertTrue(any(a["type"] == "budget_total_mismatch" for a in alerts["alerts"]))

    def test_ga_only_path_respects_custom_budget(self) -> None:
        proc = self._run("run", "--budget", "12345.67")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

        plan = json.loads((self.tmp / "artifacts" / "allocation_plan.json").read_text(encoding="utf-8"))
        alerts = json.loads((self.tmp / "artifacts" / "alerts.json").read_text(encoding="utf-8"))
        total = sum(c["recommended_budget"] for c in plan["campaigns"])

        self.assertAlmostEqual(plan["totals"]["budget_total"], 12345.67, places=2)
        self.assertAlmostEqual(total, 12345.67, places=2)
        self.assertFalse(alerts["hard_fail"])

    def test_proxy_eval_conservative_sigma_direction(self) -> None:
        proxy_eval = self._import_from_tmp_scripts("proxy_eval")

        unified = self.tmp / "artifacts" / "unified_proxy.csv"
        unified.write_text(
            "time_bucket_start,entity_id,revenue,purchases,proxy_good,proxy_bad\n"
            "2026-02-15T00:00:00Z,ga|A|c1,1,1,1,\n"
            "2026-02-15T12:00:00Z,ga|A|c1,2,2,2,\n"
            "2026-02-16T00:00:00Z,ga|A|c1,3,3,3,\n"
            "2026-02-16T12:00:00Z,ga|A|c1,4,4,4,\n",
            encoding="utf-8",
        )
        cfg_run = {"proxy": {"tau_w": 0.03, "sigma_init": 3.0, "sigma_floor": 1.0, "sigma_ceiling": 8.0}}

        catalog, _ = proxy_eval.evaluate_proxies(unified, prior_catalog={}, cfg_run=cfg_run)
        self.assertLessEqual(catalog["proxy_good"]["sigma"], 3.0)
        self.assertGreater(catalog["proxy_bad"]["sigma"], 3.0)

    def test_model_update_proxy_gate_responds_to_information(self) -> None:
        model_update = self._import_from_tmp_scripts("model_update")

        unified = self.tmp / "artifacts" / "unified_gate.csv"
        unified.write_text(
            "time_bucket_start,entity_id,revenue,purchases,spend,proxy_clicks\n"
            "2026-02-13T00:00:00Z,ga|A|high,1,1,50,1\n"
            "2026-02-13T12:00:00Z,ga|A|high,1,1,50,2\n"
            "2026-02-14T00:00:00Z,ga|A|high,1,1,50,3\n"
            "2026-02-14T12:00:00Z,ga|A|high,1,1,50,4\n"
            "2026-02-15T00:00:00Z,ga|A|high,1,1,50,5\n"
            "2026-02-16T12:00:00Z,ga|A|high,1,1,50,6\n"
            "2026-02-16T12:00:00Z,ga|A|low,0,0,20,4\n",
            encoding="utf-8",
        )

        state, _ = model_update.update_model_state(
            unified_path=unified,
            prev_state={},
            proxy_catalog={"proxy_clicks": {"sigma": 3.0}},
            cfg_run={
                "fit_window_days": 28,
                "I_min_buckets_with_revenue": 6,
                "I_min_purchases_sum": 10,
                "u_min": 0.02,
                "proxy": {"tau_w": 0.03},
            },
        )
        self.assertFalse(state["entities"]["ga|A|high"]["proxies_on"])
        self.assertTrue(state["entities"]["ga|A|low"]["proxies_on"])

    def test_allocation_uncertainty_gate_blocks_increase(self) -> None:
        allocate = self._import_from_tmp_scripts("allocate")

        plan, _ = allocate.solve_allocation(
            model_state={
                "entities": {
                    "ga|A|c1": {
                        "u_mean": 0.2,
                        "u_sd": 0.001,
                        "p_u_gt_u_min": 0.0,
                        "outcome_col": "revenue",
                        "curve": {"a": 0.8, "theta": 50.0},
                    }
                }
            },
            prev_allocation={"campaigns": [{"entity_id": "ga|A|c1", "recommended_budget": 100.0}]},
            constraints_cfg={"budget_total": 120.0},
            cfg_value={"default_value_per_revenue_eur": 1.0, "default_value_per_purchase": 100.0},
            cfg_run={"step_pct_limit": 0.5, "alpha_gate": 0.1, "gamma_risk": 0.0, "lambda_inertia": 0.0},
            horizon="12h",
        )
        campaign = plan["campaigns"][0]
        self.assertEqual(campaign["recommended_budget"], 100.0)
        self.assertIn("uncertainty_gate", campaign["binding_constraints"])

    def test_optimize_budget_outputs_channel_ranges(self) -> None:
        proc = self._run("run")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

        proc = self._run("optimize_budget", "--target-incremental-revenue", "0.05", "--horizon", "12h")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

        out = json.loads((self.tmp / "artifacts" / "optimal_budget_range.json").read_text(encoding="utf-8"))
        self.assertEqual(out["target_incremental_revenue"], 0.05)
        self.assertGreater(len(out["channel_budget_ranges"]), 0)
        self.assertTrue(all("organic" not in r["channel_id"].lower() for r in out["channel_budget_ranges"]))
        self.assertIn("expected_budget", out["budget_points"])

    def test_optimize_budget_unreachable_target_flags_expected_false(self) -> None:
        proc = self._run("run")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

        proc = self._run("optimize_budget", "--target-incremental-revenue", "1000000000", "--horizon", "12h")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        out = json.loads((self.tmp / "artifacts" / "optimal_budget_range.json").read_text(encoding="utf-8"))
        self.assertFalse(out["feasibility"]["expected"])

    def test_ad_mode_cold_start_is_budget_feasible(self) -> None:
        entities_cfg = self.tmp / "config" / "entities.yaml"
        entities_cfg.write_text(
            "entities:\n"
            "  - entity_id: \"ga|Paid Search|prospecting\"\n"
            "  - entity_id: \"ga|Paid Social|retarget\"\n"
            "parents: []\n",
            encoding="utf-8",
        )

        proc = self._run("run", "--budget", "20000")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        alerts = json.loads((self.tmp / "artifacts" / "alerts.json").read_text(encoding="utf-8"))
        self.assertFalse(alerts["hard_fail"])

        plan = json.loads((self.tmp / "artifacts" / "allocation_plan.json").read_text(encoding="utf-8"))
        total = sum(float(c["recommended_budget"]) for c in plan["campaigns"])
        self.assertAlmostEqual(total, 20000.0, places=3)

    def test_allocator_respects_campaign_bounds_and_channel_caps(self) -> None:
        allocate = self._import_from_tmp_scripts("allocate")

        model_state = {
            "entities": {
                "ga|Paid Search|A": {"u_mean": 0.1, "u_sd": 0.01, "p_u_gt_u_min": 1.0, "outcome_col": "revenue", "curve": {"a": 0.8, "theta": 50.0}},
                "ga|Paid Search|B": {"u_mean": 0.1, "u_sd": 0.01, "p_u_gt_u_min": 1.0, "outcome_col": "revenue", "curve": {"a": 0.8, "theta": 50.0}},
            }
        }
        prev = {"campaigns": [{"entity_id": "ga|Paid Search|A", "recommended_budget": 150.0}, {"entity_id": "ga|Paid Search|B", "recommended_budget": 150.0}]}
        plan, _ = allocate.solve_allocation(
            model_state=model_state,
            prev_allocation=prev,
            constraints_cfg={
                "budget_total": 250.0,
                "bounds_default": {"min": 0.0, "max": 1000.0},
                "campaign_bounds": {"ga|Paid Search|A": {"max": 100.0}},
                "channel_caps": {"Paid Search": 250.0},
            },
            cfg_value={"default_value_per_revenue_eur": 1.0, "default_value_per_purchase": 100.0},
            cfg_run={"step_pct_limit": 1.0, "alpha_gate": 0.1, "gamma_risk": 0.0, "lambda_inertia": 0.0},
            horizon="12h",
        )
        by_id = {c["entity_id"]: c["recommended_budget"] for c in plan["campaigns"]}
        self.assertLessEqual(by_id["ga|Paid Search|A"], 100.0 + 1e-6)
        self.assertLessEqual(sum(by_id.values()), 250.0 + 1e-6)

    def test_model_update_low_info_shrinks_toward_prior(self) -> None:
        model_update = self._import_from_tmp_scripts("model_update")

        unified = self.tmp / "artifacts" / "unified_low_info.csv"
        unified.write_text(
            "time_bucket_start,entity_id,revenue,purchases,spend,proxy_clicks\n"
            "2026-02-15T00:00:00Z,ga|Paid Search|c1,0,1,50,10\n"
            "2026-02-15T12:00:00Z,ga|Paid Search|c1,0,0,50,10\n"
            "2026-02-16T00:00:00Z,ga|Paid Search|c1,0,0,50,10\n"
            "2026-02-16T12:00:00Z,ga|Paid Search|c1,0,0,50,10\n",
            encoding="utf-8",
        )
        state, _ = model_update.update_model_state(
            unified_path=unified,
            prev_state={"entities": {"ga|Paid Search|c1": {"u_mean": 0.02, "u_sd": 0.03}}},
            proxy_catalog={"proxy_clicks": {"sigma": 3.0}},
            cfg_run={
                "fit_window_days": 28,
                "I_min_buckets_with_revenue": 6,
                "I_min_purchases_sum": 10,
                "u_min": 0.02,
                "proxy": {"tau_w": 0.03},
                "stability": {"smoothing_buckets": 4, "min_update_weight": 0.2, "info_for_full_update": 12},
            },
        )
        self.assertGreater(len(state["entities"]), 0)
        mu = next(iter(state["entities"].values()))["u_mean"]
        self.assertGreaterEqual(mu, 0.0)
        self.assertLess(abs(mu - 0.02), 0.02)

    def test_paid_channel_policy_exact_lists_take_precedence(self) -> None:
        channel_policy = self._import_from_tmp_scripts("channel_policy")

        cfg = {
            "paid_channel_policy": {
                "exact_paid_channels": ["Paid Social"],
                "exact_unpaid_channels": ["Paid Social Organic"],
                "include_keywords": ["paid", "social"],
                "exclude_keywords": ["organic"],
            }
        }
        self.assertTrue(channel_policy.is_paid_entity("ga|Paid Social|x", cfg))
        self.assertFalse(channel_policy.is_paid_entity("ga|Paid Social Organic|x", cfg))


if __name__ == "__main__":
    unittest.main()
