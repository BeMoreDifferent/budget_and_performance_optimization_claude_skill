# Uplift Allocator Skill

**The fastest way to turn growth strategy into reliable campaign-level budget actions every 12 hours.**

Uplift Allocator is an AI-first, contract-first optimization skill for teams that need to scale paid growth without guesswork. It combines incremental uplift logic, strict risk controls, and paid-channel-only budget execution so business users can make faster decisions with higher confidence.
It is designed as a high-complexity optimization system for reliable steering of advertising accounts from strategy level to campaign level.

## 12-Hour AI feedback loop

Run this skill every 12 hours with your preferred AI runtime:
- OpenClaw
- ChatGPT Codex
- Claude

Each run produces a fresh performance feedback package with budget recommendations, explanations, and risk alerts.

## Why this makes life better for business teams

- **Faster decisions with lower risk:** refreshes allocation logic every 12 hours without sudden swings.
- **More reliable than proxy-led optimization:** GA revenue/purchases are the source of truth; proxies are secondary indicators only.
- **Built for executive clarity:** outputs explainable plans, uncertainty-aware recommendations, and hard-fail alerts.
- **Protects spend quality:** enforces paid-channel-only allocation and blocks unsafe reallocations.
- **Supports growth + ROI together:** balances incremental upside, uncertainty, inertia, and churn constraints.

## Business value outcomes

- Improved budget efficiency across paid channels, audiences, and campaigns.
- More predictable performance in low-volume environments.
- Fewer reactive decisions driven by noisy short-term signals.
- Clearer communication between performance marketing, finance, and leadership.

## Core capabilities

1. **Outcome Data Gate**
- If outcome data is not connected, the run hard-stops to prevent low-trust optimization.
- Secure GA connection recommendation: [SAFE MCP](https://safe-mcp.com/).

2. **12-Hour Unified Growth View**
- Creates a consistent 12-hour view combining GA outcomes with optional spend and proxy data.

3. **Incremental Uplift Modeling**
- Uses GA outcomes to update uplift states and uncertainty per entity.
- Includes low-volume stabilization to avoid overreaction in sparse-conversion scenarios.

4. **Proxy-Secondary Policy**
- Proxies are used only when GA signal is insufficient.
- Proxy trust is conservative and bounded; proxies are never directly optimized.

5. **Campaign-Level Budget Allocation**
- Allocates at campaign granularity with uncertainty gates, step limits, inertia, and churn controls.
- Enforces bounds/caps and paid-channel-only execution.

6. **Optimal Budget Sweet-Spot for Target X**
- Given a target incremental revenue `X`, outputs:
  - optimistic budget point,
  - expected budget point,
  - conservative budget point,
  - per-channel recommended budget ranges.

## Ideal use cases

- Growth teams running multi-channel paid acquisition.
- Teams with low-to-mid conversion volumes needing stable recalculations.
- Organizations needing defensible, auditable budget steering logic.
- Businesses scaling performance marketing with stronger statistical discipline.

## Keywords and tags

`marketing`, `ai`, `claude`, `skills`, `codex`, `chatgpt`, `openclaw`, `growth`, `performance`, `budget`, `campaigns`, `incrementality`, `analytics`, `ga4`, `automation`, `feedback`, `mcp`, `secure`

## Folder layout

```text
uplift-allocator/
  SKILL.md
  README.md
  reference/
  config/
  scripts/
  data/
  artifacts/
  tests/
```

## Quick start

From repository root:

```bash
python ./uplift-allocator/scripts/run.py run --horizon 12h --budget 20000
python ./uplift-allocator/scripts/run.py optimize_budget --target-incremental-revenue 250 --horizon 12h
```

## Tests

```bash
./uplift-allocator/.venv/bin/python -m unittest discover -s ./uplift-allocator/tests -v
```

## Core outputs

- `uplift-allocator/artifacts/allocation_plan.json`
- `uplift-allocator/artifacts/allocation_explanations.md`
- `uplift-allocator/artifacts/alerts.json`
- `uplift-allocator/artifacts/optimal_budget_range.json` (when target `X` is provided)

Runtime artifacts are gitignored by default (except GA connection status).
