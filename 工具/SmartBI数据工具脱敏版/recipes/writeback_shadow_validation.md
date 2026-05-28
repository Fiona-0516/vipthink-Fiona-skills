# Writeback Shadow Validation Recipe

Use this when validating a SmartBI writeback candidate before any real upload.
This recipe stops before real upload. It does not submit
`DataAcquisitionServlet`. Approved operators who need the real upload flow must
use `docs/smartbi_writeback_devkit_operator_guide.md`.

## Preconditions

- The target task exists in `configs/smartbi_writeback_tasks.json`.
- Candidate and rollback workbooks are known.
- The owner has confirmed that no real upload should happen in this pass.
- Credentials are available only if `--http-probe` or `--shadow-execute` needs
  SmartBI login.

## Steps

1. Run teammate preflight checks:

   ```bash
   python3 scripts/smartbi_cli.py doctor --json
   ```

2. Inspect the candidate workbook locally with the operator-facing command:

   ```bash
   python3 scripts/smartbi_cli.py writeback-check \
     --config configs/smartbi_writeback_tasks.json \
     --task "<writeback task id>" \
     --file "<candidate workbook>" \
     --json
   ```

3. Validate the candidate workbook through the legacy no-upload writeback flow:

   ```bash
   python3 scripts/smartbi_cli.py writeback \
     --config configs/smartbi_writeback_tasks.json \
     --task "<writeback task id>" \
     --file "<candidate workbook>" \
     --dry-run \
     --json
   ```

4. Compare rollback and candidate workbooks:

   ```bash
   python3 scripts/smartbi_cli.py writeback \
     --config configs/smartbi_writeback_tasks.json \
     --task "<writeback task id>" \
     --diff \
     --original-file "<rollback workbook>" \
     --candidate-file "<candidate workbook>" \
     --max-changed-rows 3 \
     --json
   ```

5. Probe the SmartBI import target without selecting or uploading a file:

   ```bash
   python3 scripts/smartbi_cli.py writeback \
     --config configs/smartbi_writeback_tasks.json \
     --task "<writeback task id>" \
     --http-probe \
     --json
   ```

6. Build a shadow execution plan without upload:

   ```bash
   python3 scripts/smartbi_cli.py writeback \
     --config configs/smartbi_writeback_tasks.json \
     --task "<writeback task id>" \
     --shadow-execute \
     --candidate-file "<candidate workbook>" \
     --rollback-file "<rollback workbook>" \
     --expected-diff "<expected diff json>" \
     --json
   ```

7. Preserve the generated artifacts for owner/operator review:

   - `writeback-check` JSON output;
   - `writeback_dry_run.json`;
   - `writeback_diff.json`;
   - `writeback_http_probe.json`;
   - `writeback_shadow_execution_plan.json`;
   - any generated approval packet.

## Pass Conditions

- Candidate dry-run status is `ok`.
- `writeback-check` status is acceptable for the configured table.
- Rollback/candidate diff matches the intended small change set.
- HTTP probe confirms target metadata without upload.
- Shadow plan includes candidate, rollback, expected diff, target metadata, and
  post-verify plan.
- No real upload occurs.

## Stop Conditions

- Required workbook headers do not match config.
- Required non-empty fields are missing.
- Diff exceeds the approved row-change limit.
- HTTP probe cannot validate the target import config.
- Shadow preflight fails.
- Any command asks for real execute, `--single-upload`, or `--confirm` before
  owner/operator approval.
- Candidate, rollback, or expected-diff file changes after approval artifacts
  are generated.

## Explicit Non-Goal

Do not run real upload from this recipe. Approved upload is documented in
`docs/smartbi_writeback_devkit_operator_guide.md`; it uses `writeback-upload
--confirm`, performs one upload, runs post-verify candidate subset compare, and
must not auto retry or auto rollback.
