# SmartBI DATA CLI Production Candidate Assessment

Date: 2026-05-23

## Decision

Current artifact: SmartBI DATA CLI maturity gate

Maturity: Production Candidate

Gate status: accepted risk

Top blockers: none at P0

SmartBI DATA CLI can enter the production-candidate hardening path as a
generic, read-only data-access capability. It should not be treated as a fully
autonomous production data platform yet.

This decision does not change the data path for the weekly report chains:
SmartBI remains the source, SmartBI DATA CLI remains the collection layer, and
business-specific chain scripts remain responsible for cleaning, analysis,
workbook generation, and optional publishing.

## Evidence Summary

The current implementation has moved beyond demo level because it has:

- config-driven SmartBI task definitions in `configs/smartbi_tasks.json`
- dry-run mode that does not log into SmartBI or export Excel
- real export mode behind explicit execution flags and environment credentials
- per-task `run.json` logs with timing data
- offline route matrix checks for business-question to BI-report routing
- bounded batch runner with worker isolation, timeout support, and partial
  success reporting
- no Feishu writes, GitHub writes, Obsidian writes, or automation mutation in
  the generic CLI
- downstream adoption by maintained report chains

Recent local verification:

| Check | Result | Evidence |
|---|---|---|
| Production candidate replay | pass | `outputs/smartbi_cli_replay/smartbi-cli-prod-replay-20260523/replay-summary.json` |
| Real-export replay | pass, 1/1 | `outputs/smartbi_cli_replay/should-not-run-missing-env/replay-summary.json` |
| Production readiness check | production_candidate | `outputs/smartbi_production_readiness/smartbi-production-readiness-20260523/readiness-summary.json` |
| CLI smoke | pass | `python3 scripts/smoke_smartbi_cli.py --json` |
| Maintained SmartBI automation audit | pass | `python3 scripts/audit_smartbi_automation_readiness.py --json` |
| Batch dry-run | pass, 2/2 | `outputs/smartbi_batch_runs/smartbi-cli-prod-candidate-dry-run-20260523/batch-summary.json` |
| Route matrix | pass, 3/0/0 | `outputs/bi_catalog_registry/matrix_runs/smartbi-cli-prod-candidate-route-matrix-20260523/matrix-summary.json` |
| Real export benchmark | pass, 2/2 | `outputs/smartbi_batch_runs/p1-real-parallel-benchmark-20260523/batch-summary.json` |
| Controlled weekly chain trial | pass | `outputs/smartbi_benchmarks/p1-controlled-closeout-20260523.md` |

## Seven-Dimension Gate

| Dimension | Status | Judgment |
|---|---|---|
| Maintainability | green | Generic CLI, config schema, chain-specific logic kept outside the CLI, and documented source-of-truth boundary. |
| Test Confidence | green | Strong offline smoke, dry-run, route matrix, real benchmark evidence, and a single offline replay wrapper now exist. |
| Observability | green | `run.json`, `batch-summary.json/md`, timings, worker status, and route-matrix summaries make failures traceable without printing credentials. |
| Release Readiness | accepted risk | Explicit execution gates, dry-run default, bounded workers, and publish guards exist. Rollback is mostly operational: keep serial export/default configs and rerun previous known-good commands. |
| Security Baseline | accepted risk | Credentials are environment-only and smoke checks scan scripts/configs/docs for known plaintext tokens. Real export still depends on local SmartBI credential/session availability. |
| Data/API Contract | accepted risk | V1 supports `SPREADSHEET_REPORT` with JSON schema and workbook validation. `SIMPLE_REPORT` remains a chain-level escape hatch and is intentionally not a generic CLI contract yet. |
| Agent/Harness Reliability | green | Commands are machine-readable, resumable through local artifacts, and safe dry-runs are available for Codex before any real export. |

## Accepted Risks

1. SmartBI availability, credentials, and permission state are external
   dependencies. The CLI can fail clearly, but cannot control those systems.
2. V1 generic contract is centered on `SPREADSHEET_REPORT`. `SIMPLE_REPORT`
   browser export is supported only through selected chain-level helpers.
3. CLI validates export shape and configured assertions, but business truth
   still belongs to report-specific chains and human acceptance.
4. Full production still needs recurring-cycle evidence, because one controlled
   real-export replay is not enough to prove unattended weekly stability.

## Non-Goals

Do not use this production-candidate decision to add:

- automatic Feishu writes
- automatic publishing
- recurring automation changes
- Obsidian as runtime source of truth
- business-specific FB QA, growth, or attribution logic inside the generic CLI
- broader `SIMPLE_REPORT` productization before repeated non-AFTEE demand exists

## Next Safe Codex Action

Do not expand the system. The next safe action is a small hardening slice:

1. Keep `scripts/replay_smartbi_cli_production_candidate.py` as the default
   local acceptance command.
2. Keep the wrapper offline by default: no SmartBI login, no Excel export, no
   credentials required, no external writes.
3. Use optional real-export replay only behind explicit flags and human
   confirmation.
4. Keep `SIMPLE_REPORT` outside the generic CLI until at least two more
   non-AFTEE use cases prove repeated demand.

## Production Backsolve

The target is full production, not just production candidate. Functionally, the
CLI is close enough; the remaining gaps are operational.

To upgrade from `Production Candidate` to `Production`, require all of these:

| Gate | Current State | Required To Mark Production |
|---|---|---|
| Offline replay | done | `python3 scripts/replay_smartbi_cli_production_candidate.py --json` passes from a clean local checkout/runtime. |
| Real-export replay | done once | One controlled real-export replay command exists and has passed once, with environment credentials and no external writes. |
| Recurring evidence | blocked for Production | `scripts/check_smartbi_production_readiness.py --json` currently returns `production_candidate`, not `production`. |
| Failure handling | partial | Failures produce replay summaries with failed command and return code; likely-cause classification can still be improved later. |
| Owner runbook | done | `docs/smartbi_data_cli_production_runbook.md` explains normal replay, real-export replay, stop conditions, and rollback/default serial path. |
| Data contract | accepted risk | `SPREADSHEET_REPORT` remains production-supported; `SIMPLE_REPORT` is explicitly chain-owned unless repeated demand justifies promotion. |
| Security boundary | accepted risk | Credentials remain outside configs/docs/logs, and no replay command prints secrets. |

GAO reverse conclusion:

1. Do not add new business functions to SmartBI DATA CLI.
2. Do not promote `SIMPLE_REPORT` generically yet.
3. Do add a production replay/runbook layer, because this turns scattered proof
   into repeatable operating evidence.
4. Full production can be reached after `scripts/check_smartbi_production_readiness.py --json` returns `production`.

Current recurring evidence result:

- 外呼周报: 1 valid cycle; not enough for Production.
- AFTEE 订单/GMV 周报: enough distinct valid artifacts, but consecutive
  scheduled-cycle proof is not established.
- AFTEE 分期退费周报: enough distinct valid artifacts, but consecutive
  scheduled-cycle proof is not established.

## Current Gate Output

Maturity: Production Candidate

Gate status: accepted risk

Top blockers: none at P0

Accepted risks:

1. SmartBI credentials/session/permission dependency
2. `SIMPLE_REPORT` not yet a generic CLI contract
3. Full production still needs recurring cycle evidence

Next safe Codex action: keep the offline production replay wrapper as the
default acceptance command, and use
`python3 scripts/check_smartbi_production_readiness.py --json` after scheduled
cycles before marking the CLI `Production`.

Human confirmation needed: yes, before running any further real-export replay.

Next confirmation gate: whether to let engineering commander implement the
minimum recurring-cycle evidence check needed for full production.
