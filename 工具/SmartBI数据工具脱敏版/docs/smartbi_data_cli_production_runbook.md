# SmartBI DATA CLI Production Runbook

Date: 2026-05-23

## Default Acceptance Replay

Use this before treating SmartBI DATA CLI changes as production-candidate safe:

```bash
python3 scripts/replay_smartbi_cli_production_candidate.py --json
```

Default boundary:

- no SmartBI login
- no Excel export
- no credentials required
- no Feishu, GitHub, Obsidian, or automation writes
- local evidence only under `outputs/smartbi_cli_replay/`

Pass condition:

- top-level `status` is `ok`
- all checks have `accepted: true`
- batch dry-run has `counts.fail == 0`
- route matrix has `counts.fail == 0`

## Real-Export Replay

Run only after owner approval for a controlled export smoke:

```bash
python3 scripts/replay_smartbi_cli_production_candidate.py \
  --execute-real \
  --confirm-real-export \
  --real-task outbound_quality_hk_nonbulk_previous_week \
  --json
```

Real-export boundary:

- SmartBI login is allowed
- Excel export is allowed
- credentials are read only from `SMARTBI_USERNAME` and `SMARTBI_PASSWORD`
- no credentials should be passed as CLI flags
- no external writes are performed
- output stays local under `outputs/bi_exports/`, `outputs/smartbi_batch_runs/`,
  and `outputs/smartbi_cli_replay/`

Pass condition:

- top-level `status` is `ok`
- `mode` is `real_export_replay`
- `boundary.credentials_from_environment` is `true`
- `smartbi_real_export_replay.accepted` is `true`
- nested batch result has `counts.fail == 0`

## Stop Conditions

Stop and do not treat the CLI as production-ready if any of these occur:

- offline replay fails
- real-export replay fails
- SmartBI login or export returns unstable errors across repeated runs
- output workbook is missing or invalid
- any replay output prints credential values
- a downstream chain fails its workbook or publish guard validation

## Rollback / Safe Default

The safe default is offline replay plus serial export in the business chain.

If parallel or real-export replay becomes unstable:

1. use `python3 scripts/replay_smartbi_cli_production_candidate.py --json`
2. keep `scripts/run_smartbi_batch.py` in dry-run mode
3. use chain-level serial export or known-good prior commands
4. do not promote new `SIMPLE_REPORT` behavior into the generic CLI

## Production Marking Rule

Mark SmartBI DATA CLI as `Production` only after:

1. offline replay passes
2. one owner-approved real-export replay passes
3. production readiness check passes:

```bash
python3 scripts/check_smartbi_production_readiness.py --json
```

The readiness check requires two consecutive scheduled report cycles to produce
valid local run artifacts without manual repair.

4. the credential boundary remains clean: no credentials in configs, docs, or
   logs

Until then, keep the maturity label as `Production Candidate / accepted risk`.

Current readiness evidence:

- `outputs/smartbi_production_readiness/smartbi-production-readiness-20260523/readiness-summary.json`
- status: `production_candidate`
- reason: recurring cycle evidence is not yet sufficient across all maintained
  weekly chains
