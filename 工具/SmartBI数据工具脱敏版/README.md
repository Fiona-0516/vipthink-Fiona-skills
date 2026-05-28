# SmartBI DATA CLI Internal Package

Internal package date: 2026-05-26

This package is for trusted internal operators who already have SmartBI
permission. It contains the latest SmartBI DATA CLI, read-only export helpers,
selected writeback DevKit commands, BI route helpers, refreshed BI knowledge
maps, and the latest report ID / route index artifacts.

## Safety Boundary

- Credentials must come from environment variables:
  `SMARTBI_USERNAME` and `SMARTBI_PASSWORD`.
- Do not write credentials into configs, docs, logs, screenshots, or chat.
- Do not share exported Excel/CSV files, `run.json`, screenshots, cookies, or
  browser session files outside the approved internal scope.
- `writeback-upload --confirm` is a real SmartBI write operation. Run it only
  after explicit owner/operator approval.
- `SIMPLE_REPORT` export uses browser/Playwright by design. `SPREADSHEET_REPORT`
  export and writeback DevKit use SmartBI HTTP/RMI/Servlet paths.

## First Commands

Run offline checks first:

```bash
python3 scripts/smartbi_cli.py doctor --json
python3 scripts/smoke_smartbi_cli.py --json
```

After credentials are injected, run the online preflight:

```bash
python3 scripts/smartbi_cli.py doctor --online --json
```

Query the refreshed BI map:

```bash
python3 scripts/query_bi_profiles.py --query "FB港澳" --json --limit 3
python3 scripts/query_bi_profiles.py --query "教学中心" --json --limit 3
```

Validate the route matrix:

```bash
python3 scripts/run_bi_route_matrix.py \
  --config configs/bi_route_matrix_p0.json \
  --run-id package-smoke \
  --json
```

## Included BI Map Artifacts

- `inputs/bi_knowledge_maps/current/report_profiles_v2.json`
- `inputs/bi_knowledge_maps/current/kb_bi_business_data_map.json`
- `inputs/bi_knowledge_maps/current/filter_learning_inventory.json`
- `outputs/bi_catalog_registry/smartbi_report_id_registry_current.json`
- `outputs/bi_catalog_registry/smartbi_report_id_registry_20260526.json`
- `outputs/bi_catalog_registry/bi_report_route_index_current.json`
- `outputs/bi_catalog_registry/bi_report_route_index_20260526.json`
- `outputs/bi_catalog_registry/bi_report_route_join_report_current.md`
- `outputs/bi_catalog_registry/bi_report_route_join_report_20260526.md`

The refreshed maps include overseas live BI profiles and the newly provided
domestic math / teaching profile data. Current SmartBI catalog permission
matched 412 of 619 profiles to report IDs. Unmatched teaching-center entries
remain searchable as candidates but do not yet have report IDs in the route
index.

## Read First

- `docs/security_boundary.md`
- `docs/error_codes.md`
- `docs/smartbi_cli_v1.md`
- `docs/smartbi_writeback_devkit_operator_guide.md`
- `recipes/read_only_export_chain.md`
- `recipes/writeback_shadow_validation.md`

