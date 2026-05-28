# SmartBI Data CLI

This is the current foundation for read-only SmartBI report collection.

## Boundary

V1 does:

- discover Smartbi catalog resources
- inspect `SPREADSHEET_REPORT` parameters
- generate config drafts from a catalog folder
- run config-defined Excel exports
- validate the exported `.xlsx`
- write a local `run.json`
- record per-step export timings in `run.json.timings`
- run offline BI route matrix checks that turn business questions into
  reviewable dry-run packets and summary artifacts
- run bounded multi-task dry-run batches without logging into SmartBI

V1 does not:

- write to Feishu
- push recurring jobs to production without a human-reviewed automation entry
- expose generic `SIMPLE_REPORT` or `INSIGHT` export as a first-class CLI command
- store BI credentials
- treat BI route matrix results as permission to export data or change filters

Current project-specific chain runners can export selected `SIMPLE_REPORT`
sources through the browser-backed helper in
`scripts/run_aftee_order_monitor_chain.py`. Keep that as a chain-level escape
hatch until at least two more non-AFTEE reports need the same behavior. Do not
promote it into the generic CLI just for code neatness.

Credentials must be supplied by environment variables or CLI flags:

```bash
export SMARTBI_USERNAME='...'
export SMARTBI_PASSWORD='...'
```

Do not write credentials into config files.

## Commands

Run teammate preflight checks without logging into SmartBI:

```bash
python3 scripts/smartbi_cli.py doctor --json
```

Run online preflight checks after credentials are injected. This logs in and
reads catalog metadata only; it does not export Excel or upload files:

```bash
python3 scripts/smartbi_cli.py doctor --online --json
```

List a catalog folder:

```bash
python3 scripts/smartbi_cli.py catalog-list \
  --path '分析报表/海外直播业务线/海外产运/外呼'
```

Inspect one report:

```bash
python3 scripts/smartbi_cli.py inspect-report \
  --report-id I2c92808701977a217a21f809019785f3deca42cb \
  --report-path '分析报表/海外直播业务线/海外产运/外呼/益智外呼质量监控' \
  --json
```

Generate a config draft for one catalog folder:

```bash
python3 scripts/smartbi_cli.py catalog-draft \
  --path '分析报表/海外直播业务线/海外产运/外呼' \
  --out outputs/bi_catalog_drafts/outbound_catalog_draft_YYYY-MM-DD.json \
  --json
```

Dry-run a configured task without logging into BI:

```bash
python3 scripts/smartbi_cli.py run \
  --config configs/smartbi_tasks.json \
  --task outbound_quality_hk_nonbulk_previous_week \
  --dry-run \
  --json
```

Run the offline BI route matrix without logging into BI:

```bash
python3 scripts/smartbi_cli.py route-matrix \
  --config configs/bi_route_matrix_p0.json \
  --run-id p0-acceptance \
  --json
```

This reuses the local BI route index and writes:

- `outputs/bi_catalog_registry/matrix_runs/<run-id>/matrix-summary.json`
- `outputs/bi_catalog_registry/matrix_runs/<run-id>/matrix-summary.md`
- one dry-run packet and one offline-validated SmartBI config draft per case

The command is intentionally offline. It does not require
`SMARTBI_USERNAME` / `SMARTBI_PASSWORD`, does not open SmartBI, and does not
write to `outputs/bi_exports`.

Run a bounded dry-run batch without logging into BI:

```bash
python3 scripts/run_smartbi_batch.py \
  --config configs/smartbi_tasks.json \
  --task outbound_quality_hk_nonbulk_previous_week \
  --task outbound_quality_daily_default \
  --max-workers 3 \
  --json
```

This writes:

- `outputs/smartbi_batch_runs/<run-id>/batch-summary.json`
- `outputs/smartbi_batch_runs/<run-id>/batch-summary.md`

The batch runner defaults to dry-run mode. It does not read credentials, log
into SmartBI, export Excel, or write to external systems unless `--execute` is
explicitly passed.

Run a bounded real-export batch after human confirmation:

```bash
python3 scripts/run_smartbi_batch.py \
  --config configs/smartbi_tasks.json \
  --task outbound_quality_hk_nonbulk_previous_week \
  --task outbound_quality_daily_default \
  --max-workers 3 \
  --execute \
  --json
```

Real-export batch rules:

- `--execute` is required; dry-run remains the default.
- credentials are read only from `SMARTBI_USERNAME` and `SMARTBI_PASSWORD`
- do not pass passwords as CLI flags to the batch runner
- `--max-workers` defaults to `3`; lower it for cautious runs or raise it only
  after a separate confirmation gate
- when `--max-workers` is greater than `3`, the batch still runs, but
  `batch-summary.json/md` records a high-concurrency warning for audit
- `--worker-timeout-sec <seconds>` can be used to cap each task subprocess;
  timed-out tasks are marked failed with return code `124`, while successful
  task outputs remain available
- each worker runs an isolated `smartbi_cli.py run` subprocess, so sessions and
  cookies do not mix across tasks
- partial success is allowed: successful task outputs remain, failed tasks are
  marked in `batch-summary.json/md`

Run a configured export:

```bash
python3 scripts/smartbi_cli.py run \
  --config configs/smartbi_tasks.json \
  --task outbound_quality_hk_nonbulk_previous_week \
  --overwrite \
  --json
```

Successful exports include timing data in the task `run.json`:

```json
{
  "timings": {
    "total_sec": 34.211,
    "steps": [
      {"name": "login", "duration_sec": 1.234},
      {"name": "open_report_context", "duration_sec": 0.456},
      {"name": "export_spreadsheet_report", "duration_sec": 29.876}
    ]
  }
}
```

## Config Schema

The maintained config is:

```text
configs/smartbi_tasks.json
```

Top-level shape:

```json
{
  "version": 1,
  "base_url": "https://bi.61info.cn/smartbi/vision",
  "tasks": {
    "task_name": {}
  }
}
```

Task shape:

```json
{
  "enabled": true,
  "description": "human readable purpose",
  "report": {
    "id": "Smartbi resource id",
    "path": "分析报表/...",
    "type": "SPREADSHEET_REPORT"
  },
  "filters": {
    "mode": "default",
    "date_window": "previous_week",
    "overrides": [
      {
        "key": "区域细分",
        "value": "中国香港",
        "displayValue": "中国香港"
      }
    ],
    "extra_params": []
  },
  "output": {
    "type": "file",
    "dir": "outputs/bi_exports/{task}/{run_date}"
  }
}
```

Supported `date_window` values:

- `previous_week`
- `current_week_snapshot`
- `previous_month`

Supported output placeholders:

- `{task}`
- `{run_date}`
- `{run_id}`

Relative `output.dir` values are resolved from the project root, not from the
directory containing the config file. Prefer `outputs/...` for local artifacts
or an absolute path for handoff destinations.

Filter override matching checks `id`, `name`, and `alias`. Prefer business-facing `alias` keys when they are stable, such as `区域细分` or `是否批量外呼`.

## Validation

Offline config validation:

```bash
python3 scripts/validate_smartbi_config.py configs/smartbi_tasks.json
```

Offline smoke checks:

```bash
python3 scripts/smoke_smartbi_cli.py
```

Smoke checks can target a non-default config and task:

```bash
python3 scripts/smoke_smartbi_cli.py \
  --config outputs/chain_tests/m5w2_mon_fri/smartbi_chain_tasks.json \
  --task m5w2_mon_fri_general_source \
  --json
```

Audit all maintained SmartBI-backed reporting automations without logging into
BI:

```bash
python3 scripts/audit_smartbi_automation_readiness.py --json
```

This checks the four maintained business scenarios:

| Scenario | Source | Delivery Chain | Automation |
|---|---|---|---|
| 外呼周报 | `configs/weekly_outbound_chain.json` | `scripts/run_weekly_outbound_chain.py` | `weekly-outbound-chain-mvp`, Monday 14:00 |
| 外呼费用月报 | `configs/outbound_cost_smartbi_tasks.json` + monthly quote manifest | `scripts/run_outbound_cost_chain.py` | `outbound-cost-monthly-production`, monthly day 1 14:00 |
| AFTEE 订单/GMV 周报 | `configs/aftee_order_monitor_chain.json` | `scripts/run_aftee_order_monitor_chain.py` | `aftee-order-monitor-weekly`, Monday 14:30 |
| AFTEE 分期退费周报 | `configs/aftee_installment_analysis_chain.json` | `scripts/run_aftee_installment_analysis_chain.py` | `aftee`, Monday 15:00 |

The smoke script does not log into BI. It checks:

- Python syntax
- JSON parsing
- config schema
- one dry-run task
- existing catalog draft shape when present
- no plaintext BI credentials in scripts, configs, or docs

Offline BI route matrix acceptance:

```bash
python3 scripts/smartbi_cli.py route-matrix \
  --config configs/bi_route_matrix_p0.json \
  --run-id p0-acceptance-v2 \
  --json
```

Current P0 expectation:

- `fb_material_roi2` routes to `投放FB链路指标--素材维度`
- `taiwan_channel_cost` routes to `台湾商务-链路达成数据`
- `fb_channel_trend` routes to `海外投放FB渠道日监控`
- summary count should be `3 pass / 0 weak / 0 fail`

## Weekly Outbound Chain MVP

The chain runner wraps the current weekly outbound flow:

1. validate the Smartbi task config
2. smoke-check both Smartbi tasks from the selected config
3. optionally export the general source and Hong Kong TMK source
4. run the weekly outbound report dry-run
5. generate the weekly workbook
6. apply confirmed enhancements
7. verify the final workbook contains the reporting week in the expected sheets

Offline mode uses existing source files:

```bash
python3 scripts/run_weekly_outbound_chain.py \
  --skip-export \
  --json
```

Real export mode requires credentials from environment variables:

```bash
python3 scripts/run_weekly_outbound_chain.py \
  --publish-output \
  --json
```

Real export mode can use the bounded batch runner after explicit confirmation:

```bash
python3 scripts/run_weekly_outbound_chain.py \
  --parallel-export \
  --parallel-export-workers 3 \
  --json
```

Default behavior remains serial export. `--parallel-export` only changes the
SmartBI source export step; workbook generation, enhancements, validation, and
optional publishing keep the same order. The chain writes
`smartbi_export_mode` and `parallel_export_workers` to `chain_result.json`, and
the nested batch summary is stored under the chain run directory.

Publish guard:

- the chain only copies to `outputs/外呼数据周报_<week>.xlsx` when
  `publish_guard.allowed` is true
- `publish_guard.allowed` requires all chain steps to pass, workbook validation
  to pass, the final workbook to exist, and parallel export outputs to exist
- if the parallel batch command returns success but a selected task output is
  missing, the export step is marked failed and the chain must not publish
- if `weekly_dry_run` fails, `weekly_generate` and
  `apply_confirmed_enhancements` are skipped so a bad source cannot cascade into
  a noisy or misleading publish attempt
- inspect `chain_result.json.publish_guard` before treating a run as
  publication-ready

By default, the runner uses `--date-window previous_week`, derives the target
week label such as `M5W2`, resolves the previous week baseline automatically,
and materializes the Smartbi task config into the run directory with the correct
`开始日期` and `结束日期`.

The Taiwan weekly outbound number count is read from:

```text
configs/weekly_outbound_chain.json -> weekly_report.tw_weekly_number_count
```

It is currently `28`. If the business value changes, update that config value
and rerun the affected week. A one-off override is also available:

```bash
python3 scripts/run_weekly_outbound_chain.py \
  --tw-weekly-number-count 28 \
  --json
```

For deterministic testing, override the logical run date:

```bash
python3 scripts/run_weekly_outbound_chain.py \
  --today 2026-05-18 \
  --skip-export \
  --json
```

The runner writes `chain_result.json`, `chain_result.md`, the intermediate workbook, and the final enhanced workbook under:

```text
outputs/chain_runs/<run-label>/<week>/<run-id>/
```

When `--publish-output` is used, it also copies the final workbook to:

```text
outputs/外呼数据周报_<week>.xlsx
```

The first automation MVP is registered as:

```text
weekly-outbound-chain-mvp
```

It is scheduled for Monday 14:00 and runs in the project directory. The automation prompt does not include credentials; real exports require `SMARTBI_USERNAME` and `SMARTBI_PASSWORD` to be available in the automation runtime environment. Without those environment variables, the automation still performs the offline validation pass.

## Teammate Handoff Rules

- Teammates should start from the short recipes instead of rediscovering this
  full document:
  - `recipes/new_report_onboarding.md`
  - `recipes/read_only_export_chain.md`
  - `recipes/writeback_shadow_validation.md`
- Use `docs/security_boundary.md` for sharing and writeback safety rules.
- Use `docs/error_codes.md` when a JSON command returns an error code.
- Approved writeback operators should also read
  `docs/smartbi_writeback_devkit_operator_guide.md`.
- Start with `catalog-list` and `catalog-draft` for new `SPREADSHEET_REPORT`
  sources. Add tasks through JSON config; do not hard-code report IDs in new
  scripts unless the downstream analysis is already specialized.
- For unknown report paths, run `scripts/probe_smartbi_report.py` first. It
  resolves catalog type, inspects `SPREADSHEET_REPORT` parameters, and probes
  `SIMPLE_REPORT` row counts before download.
- For downloaded workbooks, run `scripts/inspect_smartbi_workbook.py` when the
  downstream parser is not already report-specific. It uses pandas-backed shape
  detection because some SmartBI `.xlsx` files report unreliable dimensions
  through openpyxl read-only mode.
- Use project-specific chain scripts when the output is a business report, not
  just a raw export. The CLI's job is source collection; skills own cleaning and
  report shape.
- Keep credentials in `SMARTBI_USERNAME` and `SMARTBI_PASSWORD`; never put them
  in configs, automation prompts, docs, or run logs.
- For large `SIMPLE_REPORT` sources, require Smartbi-side filters before export
  and add a source validation guard. The AFTEE main-order chain is the reference
  example: Taiwan filters are mandatory before download.
- Use `scripts/run_smartbi_batch.py --execute` only after a human confirmation
  approves real export concurrency for the selected tasks.
- Use `--worker-timeout-sec` when batch tasks may hang. This is task-local and
  does not publish, retry, or change successful task outputs.
- Before enabling or changing automation, run
  `python3 scripts/audit_smartbi_automation_readiness.py --json` and inspect
  the scenario-specific failures.

## Route Map and Obsidian Sync

Use a two-layer map:

| Layer | Source of truth | Purpose |
|---|---|---|
| Execution map | JSON registry, route index, SmartBI config, dry-run packet | Machine routing, `report_id`, filters, dry-run and export commands |
| Collaboration map | Obsidian / KnowledgeOS source notes | Human explanation, metric ownership, filter rationale, risk notes, test workflow |

Do not make Obsidian Markdown the runtime source for `report_id`, task filters,
or export commands. Markdown is useful for asking questions and preserving
context, but it is too easy for formatting or manual edits to drift from the
CLI's executable JSON contract.

Synchronization rule:

1. Update or regenerate the execution map first:
   - route index
   - report registry
   - SmartBI task config
   - dry-run packet
2. Compute and record a lightweight trace for the execution map:
   - source JSON path
   - generated_at or captured_at
   - source hash when available
   - included task ids or report ids
   - known risk flags
3. Update Obsidian only as a companion note that points back to those JSON paths
   and explains the business meaning. Do not copy raw exports, credentials,
   customer rows, or full workbook data into Obsidian.
4. If JSON and Obsidian disagree, JSON wins for execution and Obsidian is marked
   stale until refreshed.
5. Before using an Obsidian note for a business decision, check the referenced
   JSON path exists and the route matrix or dry-run batch still passes.

Recommended sync scenarios:

| Scenario | Action | Stop condition |
|---|---|---|
| New BI report enters route index | Generate dry-run packet, then add/update Obsidian explanation note | No `report_id` or filter risk unresolved |
| Existing task filter changes | Update JSON config and dry-run batch first, then update Obsidian rationale | Dry-run fails or human-owned filter is unclear |
| Obsidian note discovers a better mapping | Treat it as a proposal, then update route index/config through CLI artifacts | Cannot reproduce via JSON route/dry-run |
| Route index regenerated | Compare task/report ids and mark Obsidian companion stale if changed | Changed report id without owner confirmation |

## Error Codes

CLI failures use stable error code prefixes.

| Code | Meaning |
|---|---|
| `auth_error` | Missing credentials or login failure |
| `config_error` | Invalid task/config shape |
| `catalog_error` | Smartbi catalog response is malformed |
| `parameter_error` | Report parameter metadata is missing or malformed |
| `export_error` | Export endpoint did not return an Excel file |
| `network_error` | Request failed after retries |
| `smartbi_rmi_error` | Smartbi RMI call returned non-zero status |
| `smartbi_error` | Generic fallback |

Use `--json` when another runner needs machine-readable failure payloads.

## Probe Helpers

Probe a report by catalog path:

```bash
python3 scripts/probe_smartbi_report.py \
  --path '分析报表/海外直播业务线/海外教务/思维海外满班率' \
  --json
```

Probe a `SIMPLE_REPORT` with row-count protection:

```bash
uv run --with playwright python scripts/probe_smartbi_report.py \
  --path '分析报表/海外直播业务线/海外前端/海外销售员工架构表' \
  --max-rows 5000 \
  --json
```

Inspect a downloaded workbook:

```bash
uv run --with pandas --with openpyxl python scripts/inspect_smartbi_workbook.py \
  outputs/example.xlsx \
  --json
```

## Current Proof

The current V1 has been verified against the `海外产运/外呼` folder:

- `益智外呼质量监控`
- `益智外呼质量监控_偏移值`
- `益智外呼质量日监控`
- `益智外呼分时段监控`

The last generated catalog draft is:

```text
outputs/bi_catalog_drafts/outbound_catalog_draft_2026-05-16.json
```

## Next Gate

Before adding Feishu, scheduling, or analysis skill chaining, keep hardening this foundation:

1. merge one draft task into `configs/smartbi_tasks.json`
2. run dry-run validation
3. run one real export
4. inspect the workbook and `run.json`
5. before any Feishu write, run `scripts/lark_section_guard.py` against the target doc and planned replacement range
6. after the Feishu write, fetch the doc again and rerun `scripts/lark_section_guard.py`
7. only then promote the task to recurring automation

Feishu section-write guard reference:

```bash
python3 scripts/lark_section_guard.py \
  --doc 'https://my.feishu.cn/docx/D7cxda9mToZd75xcQNnc21ZtnOb' \
  --target-section outbound \
  --start '**2. 外呼**' \
  --end '**其他本地化**' \
  --json
```

Guard details and pressure-test cases are documented in
`docs/lark_doc_section_guard.md`.
