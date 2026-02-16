# DATA MAPPING

## GA export columns expected (minimum)
- time (ISO)
- default_channel_group (or channel grouping)
- campaign (preferred) OR source_medium
- revenue (preferred) OR purchases

These will be bucketed into 12h and mapped to:
channel_id = default_channel_group
campaign_id = campaign or source_medium
audience_id = "ga"

entity_id = "ga|<channel_id>|<campaign_id>"

## Optional ad spend/proxy inputs
- spend file: time, entity_id, spend
- proxy file: time, entity_id, proxy_<name>...

If ad accounts exist, entity_id should match "<channel>|<audience>|<campaign>".
If mapping is partial, allocator will:
- allocate mapped entities directly
- allocate remaining budget to GA entities by smoothed shares
