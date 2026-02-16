# CONTRACT (GA-first uplift allocator)

## Minimum data
- Always: GA revenue (preferred) or purchases (fallback), bucketed to 12h.
- Optional: ad spend by campaign; optional platform proxies.

## Entity identity (campaign-level)
entity_id: "<channel>|<audience>|<campaign>"
If ad accounts unavailable:
entity_id: "ga|<default_channel_group>|<ga_campaign_or_source_medium>"

## Proxy secondary rule
Define per-entity information score I over fit window W:
- If revenue exists: I = count of buckets with revenue > 0
- Else: I = sum of purchases

If I >= I_min -> proxies OFF for that entity (ignored in update).
If I < I_min -> proxies ON (indicator-only, conservative noise).

## Latent uplift state
u_{i,t} >= 0

Outcome model (GA-first):
- Use revenue if available:
  R_{i,t} ~ LogNormal(log(mu_{i,t}), sigma_R)
- Else purchases:
  Y_{i,t} ~ NegBin(mu_{i,t}, kappa)

mu_{i,t} = baseline_{i,t} + u_{i,t} * g_i(spend_{i,t})

g_i(b) is concave saturation:
g(b) = b^a / (b^a + theta^a)

Proxy indicator model (only if proxies ON):
p_{k,i,t} ~ Normal(a_{k,i} + w_k u_{i,t}, sigma_k^2)
Shrinkage w_k ~ Normal(0, tau^2), tau small
sigma_k starts high and is reduced only if it improves held-out GA outcome prediction.

## Allocation
Risk-adjusted score:
score_i(b) = E[value_i(u_i,g_i(b))] - gamma * SD(value) - lambda*(b - b_prev)^2

Constraints:
- sum b_i = total budget
- bounds per entity
- step limit |b_i - b_prev| <= step_pct * max(1, b_prev)
- churn cap (relative)

Uncertainty gate:
Increase budget only if P(u_i > u_min) >= 1 - alpha

## Verification hard fails
- GA not connected
- constraint violations
- step/churn violations
- proxy dominance flags
