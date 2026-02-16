from __future__ import annotations

from typing import Dict, Any, Tuple

import numpy as np
import pandas as pd


def evaluate_proxies(
    unified_path,
    prior_catalog: Dict[str, Any],
    cfg_run: Dict[str, Any],
) -> Tuple[Dict[str, Any], str]:
    """
    Proxies remain secondary by design:
    - sigma starts high
    - sigma only reduces if it improves held-out prediction of GA outcomes
    Here we implement conservative heuristics as a baseline.
    """
    df = pd.read_csv(unified_path)
    df["time_bucket_start"] = pd.to_datetime(df["time_bucket_start"], utc=True)

    proxy_cols = [c for c in df.columns if c.startswith("proxy_")]
    if not proxy_cols:
        return prior_catalog, "# Proxy report\nNo proxy columns present.\n"

    tau = float(cfg_run["proxy"]["tau_w"])
    sigma_init = float(cfg_run["proxy"]["sigma_init"])
    sigma_floor = float(cfg_run["proxy"]["sigma_floor"])
    sigma_ceiling = float(cfg_run["proxy"]["sigma_ceiling"])

    has_revenue = df["revenue"].sum() > 0
    y = df["revenue"] if has_revenue else df["purchases"]

    report = ["# Proxy report (secondary-only)\n"]
    catalog = dict(prior_catalog)

    for c in proxy_cols:
        s = pd.to_numeric(df[c], errors="coerce")
        miss = float(s.isna().mean())

        tmp = pd.DataFrame({"entity_id": df["entity_id"], "p": s, "y": y})
        tmp["y_lead"] = tmp.groupby("entity_id")["y"].shift(-1)
        corr = tmp[["p", "y_lead"]].corr().iloc[0, 1]
        corr = float(0.0 if np.isnan(corr) else corr)

        entry = catalog.get(c, {})
        entry.setdefault("tau_w", tau)
        entry.setdefault("sigma", sigma_init)

        if miss < 0.2 and corr > 0.15:
            entry["sigma"] = max(sigma_floor, entry["sigma"] * 0.97)
        else:
            entry["sigma"] = min(sigma_ceiling, entry["sigma"] * 1.05)

        entry["missing_rate"] = miss
        entry["lead_outcome_corr"] = corr
        catalog[c] = entry

        report += [
            f"## {c}",
            f"- missing_rate: {miss:.3f}",
            f"- lead_outcome_corr: {corr:.3f}",
            f"- sigma (higher = less trust): {entry['sigma']:.3f}",
            "",
        ]

    return catalog, "\n".join(report)
