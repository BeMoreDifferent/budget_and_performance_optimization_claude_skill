from __future__ import annotations

from typing import Dict, Any, Tuple

import numpy as np
import pandas as pd
from math import erf, sqrt


def _sat(b: float, a: float, theta: float) -> float:
    b = max(0.0, float(b))
    return (b**a) / (b**a + theta**a + 1e-12)


def update_model_state(
    unified_path,
    prev_state: Dict[str, Any],
    proxy_catalog: Dict[str, Any],
    cfg_run: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    df = pd.read_csv(unified_path)
    if df.empty:
        return {"updated_at": None, "entities": {}}, {
            "outcome_col": "revenue",
            "fit_window_days": int(cfg_run["fit_window_days"]),
            "n_entities": 0,
            "last_bucket": None,
        }

    df["time_bucket_start"] = pd.to_datetime(df["time_bucket_start"], utc=True)

    fit_days = int(cfg_run["fit_window_days"])
    end_t = df["time_bucket_start"].max()
    start_t = end_t - pd.Timedelta(days=fit_days)
    dfw = df[df["time_bucket_start"] >= start_t].copy()

    use_revenue = dfw["revenue"].sum() > 0
    outcome_col = "revenue" if use_revenue else "purchases"

    I_min_rev = int(cfg_run["I_min_buckets_with_revenue"])
    I_min_pur = int(cfg_run["I_min_purchases_sum"])

    a = 0.8
    theta = max(50.0, float(dfw["spend"].median() + 1e-9))

    state_prev = prev_state.get("entities", {})
    u_min = float(cfg_run["u_min"])
    tau_w = float(cfg_run["proxy"]["tau_w"])

    last_bucket = dfw["time_bucket_start"].max()
    smooth_cfg = cfg_run.get("stability", {})
    smoothing_buckets = int(smooth_cfg.get("smoothing_buckets", 4))
    min_update_weight = float(smooth_cfg.get("min_update_weight", 0.20))
    info_for_full_update = float(smooth_cfg.get("info_for_full_update", 12.0))

    entities_out: Dict[str, Any] = {}

    for ent_id in sorted(dfw["entity_id"].unique()):
        prior = state_prev.get(ent_id, {})
        mu0 = float(prior.get("u_mean", 0.02))
        sd0 = float(prior.get("u_sd", 0.03))
        var0 = sd0 * sd0

        dwe = dfw[dfw["entity_id"] == ent_id]
        d_tail = dwe.sort_values("time_bucket_start").tail(max(1, smoothing_buckets))
        spend = float(d_tail["spend"].mean())
        y = float(d_tail[outcome_col].mean())
        if use_revenue:
            I = int((dwe["revenue"] > 0).sum())
            proxies_on = I < I_min_rev
        else:
            I = float(dwe["purchases"].sum())
            proxies_on = I < I_min_pur

        m = _sat(spend, a, theta)
        base = float(dwe[outcome_col].median())

        grid = np.linspace(0.0, 0.25, 501)
        prior_ll = -0.5 * ((grid - mu0) ** 2) / (var0 + 1e-12)

        lam = np.clip(base + grid * m, 1e-9, None)
        ll_y = y * np.log(lam) - lam

        ll_p = 0.0
        if proxies_on:
            proxy_cols = [c for c in d_tail.columns if c.startswith("proxy_")]
            proxies = {c: float(d_tail[c].mean()) for c in proxy_cols}
            for name, p_val in proxies.items():
                if name not in proxy_catalog or np.isnan(p_val):
                    continue
                sigma = float(proxy_catalog[name].get("sigma", 3.0))
                w = 1.0
                ll_p += -0.5 * ((p_val - w * grid) ** 2) / (sigma**2 + 1e-12)
                ll_p += -0.5 * (w**2) / (tau_w**2 + 1e-12)

        logp = prior_ll + ll_y + ll_p
        logp = logp - np.max(logp)
        wts = np.exp(logp)
        wts = wts / (np.sum(wts) + 1e-12)

        mu_post = float(np.sum(grid * wts))
        var_post = float(np.sum((grid - mu_post) ** 2 * wts))
        sd_post = float(np.sqrt(max(var_post, 1e-12)))

        info_ratio = float(np.clip(float(I) / max(1e-9, info_for_full_update), 0.0, 1.0))
        blend = max(min_update_weight, info_ratio)
        mu = float((1.0 - blend) * mu0 + blend * mu_post)
        sd = float(max(sd_post, (1.0 - blend) * sd0))

        z = (u_min - mu) / (sd + 1e-12)
        p_gt = float(np.clip(0.5 * (1.0 - erf(z / sqrt(2.0))), 0.0, 1.0))

        entities_out[ent_id] = {
            "u_mean": mu,
            "u_sd": sd,
            "p_u_gt_u_min": p_gt,
            "proxies_on": bool(proxies_on),
            "info_score_I": float(I),
            "outcome_col": outcome_col,
            "curve": {"a": a, "theta": theta},
            "last_bucket": str(last_bucket),
        }

    state = {"updated_at": str(last_bucket), "entities": entities_out}
    diag = {
        "outcome_col": outcome_col,
        "fit_window_days": fit_days,
        "n_entities": len(entities_out),
        "last_bucket": str(last_bucket),
    }
    return state, diag
