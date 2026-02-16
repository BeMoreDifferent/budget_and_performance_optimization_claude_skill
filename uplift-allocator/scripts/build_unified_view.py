from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any

import pandas as pd


def build_unified_view(
    ga_csv: Path,
    ad_spend_csv: Path,
    ad_proxy_csv: Path,
    out_csv: Path,
    start_iso: Optional[str],
    end_iso: Optional[str],
    cfg_run: Dict[str, Any],
) -> None:
    """
    Builds a 12h unified view.
    GA is mandatory. Ad files are optional (can be missing/empty).
    Output columns (minimum):
      time_bucket_start, entity_id, channel_id, audience_id, campaign_id,
      revenue, purchases, spend, proxy_*
    """
    _ = cfg_run
    df_ga = pd.read_csv(ga_csv)
    df_ga["time"] = pd.to_datetime(df_ga["time"], utc=True)
    df_ga["time_bucket_start"] = df_ga["time"].dt.floor("12h")

    df_ga["channel_id"] = df_ga.get("default_channel_group", "unknown")
    if "campaign" in df_ga.columns:
        df_ga["campaign_id"] = df_ga["campaign"].astype(str)
    else:
        df_ga["campaign_id"] = df_ga["source_medium"].astype(str)

    df_ga["audience_id"] = "ga"
    df_ga["entity_id"] = "ga|" + df_ga["channel_id"].astype(str) + "|" + df_ga["campaign_id"].astype(str)

    if "revenue" not in df_ga.columns:
        df_ga["revenue"] = 0.0
    if "purchases" not in df_ga.columns:
        df_ga["purchases"] = 0.0

    ga_agg = (
        df_ga.groupby(["time_bucket_start", "entity_id", "channel_id", "audience_id", "campaign_id"], as_index=False)
        .agg({"revenue": "sum", "purchases": "sum"})
    )

    ga_agg["spend"] = 0.0

    if ad_spend_csv.exists():
        s = pd.read_csv(ad_spend_csv)
        if not s.empty:
            s["time"] = pd.to_datetime(s["time"], utc=True)
            s["time_bucket_start"] = s["time"].dt.floor("12h")
            s_agg = s.groupby(["time_bucket_start", "entity_id"], as_index=False).agg({"spend": "sum"})
            ga_agg = ga_agg.merge(s_agg, on=["time_bucket_start", "entity_id"], how="left", suffixes=("", "_ad"))
            ga_agg["spend"] = ga_agg["spend_ad"].fillna(0.0)
            ga_agg = ga_agg.drop(columns=["spend_ad"])

    if ad_proxy_csv.exists():
        p = pd.read_csv(ad_proxy_csv)
        if not p.empty:
            p["time"] = pd.to_datetime(p["time"], utc=True)
            p["time_bucket_start"] = p["time"].dt.floor("12h")
            proxy_cols = [c for c in p.columns if c.startswith("proxy_")]
            if proxy_cols:
                p_agg = p.groupby(["time_bucket_start", "entity_id"], as_index=False).agg({c: "mean" for c in proxy_cols})
                ga_agg = ga_agg.merge(p_agg, on=["time_bucket_start", "entity_id"], how="left")

    if start_iso:
        ga_agg = ga_agg[ga_agg["time_bucket_start"] >= pd.to_datetime(start_iso, utc=True)]
    if end_iso:
        ga_agg = ga_agg[ga_agg["time_bucket_start"] < pd.to_datetime(end_iso, utc=True)]

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    ga_agg.sort_values(["time_bucket_start", "entity_id"]).to_csv(out_csv, index=False)
