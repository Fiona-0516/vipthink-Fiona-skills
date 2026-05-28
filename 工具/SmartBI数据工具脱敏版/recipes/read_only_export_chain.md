# Read-Only Export Chain Recipe

Use this when a teammate needs to run a maintained SmartBI read-only export or a
reporting chain. This recipe does not write to SmartBI.

## Preconditions

- The task already exists in the maintained config.
- The owner has confirmed the task id, date window, filters, and whether real
  export is allowed.
- Credentials are available through `SMARTBI_USERNAME` and
  `SMARTBI_PASSWORD` only when real export is approved.

## Steps

1. Run teammate preflight checks:

   ```bash
   python3 scripts/smartbi_cli.py doctor --json
   ```

2. Run online preflight only after credentials are injected:

   ```bash
   python3 scripts/smartbi_cli.py doctor --online --json
   ```

3. Run offline smoke:

   ```bash
   python3 scripts/smoke_smartbi_cli.py --json
   ```

4. Validate the maintained config:

   ```bash
   python3 scripts/validate_smartbi_config.py configs/smartbi_tasks.json --json
   ```

5. Dry-run the selected task:

   ```bash
   python3 scripts/smartbi_cli.py run \
     --config configs/smartbi_tasks.json \
     --task "<task id>" \
     --dry-run \
     --json
   ```

6. For multiple tasks, dry-run the batch first:

   ```bash
   python3 scripts/run_smartbi_batch.py \
     --config configs/smartbi_tasks.json \
     --task "<task id 1>" \
     --task "<task id 2>" \
     --max-workers 3 \
     --json
   ```

7. Run real export only after owner approval:

   ```bash
   python3 scripts/smartbi_cli.py run \
     --config configs/smartbi_tasks.json \
     --task "<task id>" \
     --overwrite \
     --json
   ```

8. For an approved real batch export:

   ```bash
   python3 scripts/run_smartbi_batch.py \
     --config configs/smartbi_tasks.json \
     --task "<task id 1>" \
     --task "<task id 2>" \
     --max-workers 3 \
     --execute \
     --json
   ```

9. Inspect the generated run artifacts:

   - task `run.json`;
   - workbook path;
   - batch `batch-summary.json`;
   - batch `batch-summary.md`;
   - downstream chain `publish_guard` when a business report is generated.

## Pass Conditions

- Doctor, offline smoke, and config validation pass.
- Dry-run plan matches the approved task, filters, and output path.
- Real export writes a valid workbook and `run.json`.
- Batch summary has no failed task for required outputs.
- Downstream chain publish guard passes before any published workbook is used.

## Stop Conditions

- Dry-run is skipped.
- Credentials are passed in command text or written to a file.
- `--execute` is used without owner approval.
- `--max-workers` is raised above the approved value.
- Output workbook is missing, empty, invalid, or fails assertions.
- Downstream `publish_guard.allowed` is false.
