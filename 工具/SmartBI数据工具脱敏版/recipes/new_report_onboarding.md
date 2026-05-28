# New SmartBI Report Onboarding Recipe

Use this when adding a new read-only SmartBI report source for teammate or agent
use. This recipe does not write to SmartBI and does not create automation.

## Preconditions

- You are in the project root.
- SmartBI credentials are available only through `SMARTBI_USERNAME` and
  `SMARTBI_PASSWORD`.
- You know the nearest SmartBI catalog path from the UI.
- The owner has confirmed that read-only catalog inspection is allowed.

## Steps

1. Run teammate preflight checks without logging into SmartBI:

   ```bash
   python3 scripts/smartbi_cli.py doctor --json
   ```

2. Validate the current CLI surface without logging into SmartBI:

   ```bash
   python3 scripts/smoke_smartbi_cli.py --json
   ```

3. After credentials are injected, run online doctor:

   ```bash
   python3 scripts/smartbi_cli.py doctor --online --json
   ```

4. List the nearest catalog folder:

   ```bash
   python3 scripts/smartbi_cli.py catalog-list \
     --path "<catalog path>" \
     --json
   ```

5. If the target report path or type is uncertain, probe the report first:

   ```bash
   python3 scripts/probe_smartbi_report.py \
     --path "<full report path>" \
     --json
   ```

6. For `SPREADSHEET_REPORT`, inspect parameters:

   ```bash
   python3 scripts/smartbi_cli.py inspect-report \
     --report-id "<report id>" \
     --report-path "<full report path>" \
     --json
   ```

7. Generate a draft config from the catalog folder:

   ```bash
   python3 scripts/smartbi_cli.py catalog-draft \
     --path "<catalog path>" \
     --out "outputs/bi_catalog_drafts/<draft-name>.json" \
     --json
   ```

8. Copy only the selected task into the maintained config after review. Prefer
   business-facing filter aliases when they are stable.

9. Dry-run the selected task:

   ```bash
   python3 scripts/smartbi_cli.py run \
     --config configs/smartbi_tasks.json \
     --task "<task id>" \
     --dry-run \
     --json
   ```

10. If a workbook is exported later, inspect workbook shape before writing a
   downstream parser:

   ```bash
   uv run --with pandas --with openpyxl python scripts/inspect_smartbi_workbook.py \
     --file "<exported workbook>" \
     --json
   ```

## Pass Conditions

- Doctor and smoke checks pass.
- Catalog path resolves through the current account.
- Report type is known.
- Required parameters are visible.
- Dry-run produces the expected report id, path, filters, and output plan.
- No credentials are written to files.

## Stop Conditions

- Catalog path differs from the current SmartBI UI path.
- Report type is `SIMPLE_REPORT` and row count/filter guard is not understood.
- `inspect-report` cannot see expected parameters.
- Dry-run plan uses wrong filters, date window, or output path.
- Any artifact contains credentials, cookies, tokens, or private session data.
