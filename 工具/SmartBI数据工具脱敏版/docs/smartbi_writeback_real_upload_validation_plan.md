# SmartBI Writeback Real Upload Validation Plan

Date: 2026-05-25

## Non-Negotiable Boundary

Do not run real upload from Codex until the owner explicitly confirms the final
upload window.

Current CLI state:

- `writeback --dry-run`: enabled
- `writeback --probe`: enabled
- `writeback --http-probe`: enabled
- `writeback --diff`: enabled
- `writeback --shadow-execute`: enabled, no upload
- `writeback --execute`: blocked by code

The execute path must remain blocked until this runbook is accepted and the
owner provides a prepared test workbook plus rollback workbook.

## Target

Writeback target:

- alias: `课包城市消耗数据回写`
- type: `DAQ_IMPORTCONFIG`
- id: `I2c928087017cd66bd66bdc41017ce91e219f5fe6`

Post-verify report:

- alias: `课包城市消耗周报填报数据`
- type: `SPREADSHEET_REPORT`
- id: `I2c928087017cd66bd66bdc41017ce9117774567b`
- inspect status: verified on 2026-05-25
- visible sheet: `Sheet1`
- parameters:
  - `开始日期`
  - `结束日期`
  - `消耗数据投放平台`
  - `消耗课包`

## Human Validation Method

The owner will manually alter a few values in the writeback workbook, then
verify the changed values in the real BI table/report after upload.

Recommended test edits:

- Change only 2 to 3 rows.
- Change only one low-risk numeric metric per row, preferably `消耗`.
- Use rows with stable keys:
  - `日期`
  - `平台`
  - `区域细分`
  - `投放账户`
  - `广告计划id`
  - `广告组id`
  - `广告id`
- Do not change dimensions or id fields for the test.
- Keep the original workbook untouched as rollback source.

## Required Artifacts Before Execute Is Enabled

1. Original rollback workbook.
2. Human-edited test workbook.
3. Dry-run report for original workbook.
4. Dry-run report for test workbook.
5. Cell-level diff manifest between original and test workbook.
6. Target probe report showing the upload form is still `DataAcquisitionServlet`.
7. Post-verify plan tied to `课包城市消耗周报填报数据`.

## Real Upload Sequence

### Phase 1: Preflight

Run dry-run on original:

```bash
python3 scripts/smartbi_cli.py writeback \
  --task course_city_cost_writeback \
  --file /path/to/original.xlsx \
  --dry-run \
  --run-id real-preflight-original-YYYYMMDD-HHMMSS \
  --json
```

Run dry-run on edited test file:

```bash
python3 scripts/smartbi_cli.py writeback \
  --task course_city_cost_writeback \
  --file /path/to/edited-test.xlsx \
  --dry-run \
  --run-id real-preflight-edited-YYYYMMDD-HHMMSS \
  --json
```

Run target probe:

```bash
python3 scripts/smartbi_cli.py writeback \
  --task course_city_cost_writeback \
  --probe \
  --run-id real-preflight-probe-YYYYMMDD-HHMMSS \
  --json
```

Stop if any preflight status is not `ok`.

Build diff manifest between rollback original and human-edited test file:

```bash
python3 scripts/smartbi_cli.py writeback \
  --task course_city_cost_writeback \
  --diff \
  --original-file /path/to/original.xlsx \
  --candidate-file /path/to/edited-test.xlsx \
  --max-changed-rows 3 \
  --run-id real-preflight-diff-YYYYMMDD-HHMMSS \
  --json
```

Pass condition:

- `status == "ok"`
- `changed_row_count <= 3`
- changed columns are numeric value columns, preferably only `消耗`
- dimensions and id fields are unchanged

### Phase 2: Upload Edited Test Workbook

This is not currently enabled.

The current implementation stops at shadow execute:

```bash
python3 scripts/smartbi_cli.py writeback \
  --task course_city_cost_writeback \
  --shadow-execute \
  --candidate-file /path/to/edited-test.xlsx \
  --rollback-file /path/to/original.xlsx \
  --expected-diff /path/to/writeback_diff.json \
  --json
```

Shadow execute performs:

- candidate workbook dry-run
- rollback workbook dry-run
- current diff rebuild
- `expected-diff` match check
- `openimportconfig.jsp` target validation
- `ExcelTemplateDownloadServlet` template validation
- `DataAcquisitionServlet` multipart preview generation
- response parser fixture simulation
- post-verify plan generation

Shadow execute explicitly records:

- `request_sent=false`
- `upload_submitted=false`
- `external_write=false`

It does not send a `DataAcquisitionServlet` request.

When enabled later, the command must require all of:

- `--execute`
- `--confirm-writeback`
- `--rollback-file /path/to/original.xlsx`
- `--expected-diff /path/to/diff.json`
- owner-provided confirmation in the current thread

The implementation must:

- log in through `SmartbiClient`
- open `openimportconfig.jsp` and verify the target id/name
- dry-run the candidate workbook
- dry-run the rollback workbook
- verify the expected diff against the current rollback/candidate pair
- construct the `DataAcquisitionServlet` multipart request from the audited
  field preview
- capture response metadata after upload
- write a run artifact

### Phase 3: Human Verify

The owner checks whether the edited values are visible in the real BI table or
post-verify report.

Pass condition:

- all edited keys show the edited values
- no unexpected row count or date range drift is observed
- no SmartBI exception report is generated

### Phase 4: Immediate Rollback

Upload the original rollback workbook through the same controlled execute path.

After rollback, verify:

- edited keys return to original values
- aggregate `消耗` returns to the original dry-run value
- report remains usable by other users

## Stop Conditions

Stop and do not execute upload if:

- original workbook dry-run fails
- edited workbook dry-run fails
- diff contains dimensions or id fields
- diff touches more than 3 rows
- target probe does not find `DataAcquisitionServlet`
- SmartBI page no longer has `input[type=file][name=file]`
- owner cannot monitor the BI page during the test
- rollback workbook is missing
- post-verify route cannot be opened

## Current Status

No-upload shadow engineering hardening is in place. This is a shadow build, not
an upload-ready build.

Current verified commands:

```bash
python3 scripts/smartbi_cli.py writeback \
  --task course_city_cost_writeback \
  --file /Users/takuya/Desktop/投放账户数据回写填报模板_输出.xlsx \
  --dry-run \
  --run-id cli-dry-run-20260525 \
  --json

python3 scripts/smartbi_cli.py writeback \
  --task course_city_cost_writeback \
  --probe \
  --run-id cli-probe-20260525 \
  --json

python3 scripts/smartbi_cli.py writeback \
  --task course_city_cost_writeback \
  --http-probe \
  --file /Users/takuya/Desktop/投放账户数据回写填报模板_输出.xlsx \
  --run-id cli-http-probe-20260525 \
  --json

python3 scripts/smartbi_cli.py writeback \
  --task course_city_cost_writeback \
  --diff \
  --original-file /Users/takuya/Desktop/投放账户数据回写填报模板_输出.xlsx \
  --candidate-file outputs/smartbi_writeback_test_inputs/投放账户数据回写填报模板_输出_diff_probe.xlsx \
  --run-id cli-diff-one-change-20260525 \
  --json

python3 scripts/smartbi_cli.py writeback \
  --task course_city_cost_writeback \
  --shadow-execute \
  --candidate-file outputs/smartbi_writeback_inputs/投放账户数据回写填报模板_输出.xlsx \
  --rollback-file /Users/takuya/Desktop/投放账户数据回写填报模板_输出.xlsx \
  --expected-diff outputs/smartbi_writeback_cli/course_city_cost_writeback/shadow-expected-diff-20260525/writeback_diff.json \
  --run-id shadow-execute-20260525 \
  --json
```

Negative gates verified:

- changing a key/id field makes `--diff` return `status=error` and process code `2`
- missing `--rollback-file` makes `--shadow-execute` return process code `2`
- missing `--expected-diff` makes `--shadow-execute` return process code `2`
- mismatched `--expected-diff` makes `--shadow-execute` return process code `2`
- candidate dry-run failure makes `--shadow-execute` return process code `2`
- rollback dry-run failure makes `--shadow-execute` return process code `2`
- passing `--execute --confirm-writeback` returns `writeback_execute_blocked`
  and process code `2`

GAO hardening artifacts:

- post-verify dry-run plan:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/gao-hardening-20260525/post_verify_dry_run_plan.json`
- real upload readiness packet:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/gao-hardening-20260525/real_upload_readiness_packet.json`
- fixture test summary:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/gao-hardening-20260525/fixture_test_summary.json`

Current readiness decision:

- `shadow_ready_not_upload_ready`
- `post_verify_executed=false`
- `upload_submitted=false`
- DataAcquisitionServlet request sent: false
- owner approval absent
- real upload still blocked

Upload-readiness planning artifacts:

- implementation plan:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/upload-readiness/real_upload_implementation_plan.json`
- safety gate:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/upload-readiness/real_upload_safety_gate.json`
- owner approval packet:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/upload-readiness/owner_approval_packet.md`

Implementation readiness decision:

- `ready_for_separate_real_upload_implementation_goal_after_owner_decision_not_upload_ready`

The owner approval packet is not owner approval, not upload approval, and not
execute enablement. The guarded execute implementation is now present, but no
upload has been run. The next step is owner manual execution of the command
artifact during the approved window; this implementation stage did not send any
DataAcquisitionServlet request.

Guarded execute implementation status:

- guarded real upload code path: implemented
- default unguarded execute: still `writeback_execute_blocked`
- owner-token gate: implemented
- candidate/rollback/expected-diff SHA-256 gates: implemented
- upload-window gate: implemented
- automatic retry: disabled
- automatic rollback: disabled

Owner manual test artifacts:

- command:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/owner-test/owner_test_command.md`
- token:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/owner-test/owner_test_token.json`
- test summary:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/owner-test/guarded_execute_test_summary.json`

These artifacts were generated without SmartBI login, without sending a
DataAcquisitionServlet request, and without uploading any workbook. Only the
owner manually running the real upload command will perform the upload.

First owner manual upload result:

- run id: `owner-test-20260525`
- response artifact:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/owner-test-20260525/guarded_execute_response.json`
- diagnosis artifact:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/owner-test-20260525/upload_failure_diagnosis.json`
- `upload_result=failed`
- `success=false`
- HTTP status: `200`
- SmartBI callback preview contains `doImportFormSubmitCallback`
- SmartBI callback preview contains `sheetResults`
- diagnosed failure reason: `insufficient_response_capture`

Current failure policy:

- no automatic retry
- no rollback unless a successful write is confirmed
- no post-verify command after this failed upload
- next step is failure diagnosis / exception data review, not another upload

The improved parser now supports SmartBI `doImportFormSubmitCallback(...)`
callback JSON extraction and future response artifacts can preserve callback
JSON, `sheetResults`, `errorMessage`, and a longer sanitized preview.

Owner manual UI upload success follow-up:

- date observed: `2026-05-26`
- owner manually uploaded corrected workbook through the SmartBI UI
- SmartBI UI message showed `sheet1导入规则1` with `成功:36列;失败:0列`
- CLI did not send this upload request
- CLI post-verify performed read-only login/export only
- post-verify export:
  `outputs/bi_exports/course_city_cost_post_verify_20260525/2026-05-26/20260526-114718/课包城市消耗周报填报数据.xlsx`
- post-verify compare artifact:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/manual-success-20260526/post_verify_compare_summary.json`
- compare result: `status=ok`
- candidate 36 keys are all visible in the post-verify export
- metric mismatch count: `0`
- rollback remains unnecessary unless a later business review finds incorrect
  production data

CLI real upload success follow-up:

- run id: `cli-single-upload-20260526-parameter-panel-v1`
- upload path: no browser, no Playwright primary path
- added pre-upload initialization:
  `DataAcquisitionModule.getImportConfigRules` ->
  `DataAcquisitionModule.getAllParams`
- multipart field `parameterPanelBOId` now comes from `getAllParams.result.clientId`
- endpoint: `DataAcquisitionServlet`
- upload request count: `1`
- automatic retry: `false`
- automatic rollback: `false`
- SmartBI callback: `success=true`
- `sheetResults[0].successCount=36`
- `sheetResults[0].totalCount=36`
- post-verify compare: `status=ok`
- candidate keys missing in export: `0`
- value mismatch count: `0`
- acceptance report:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/cli-single-upload-20260526-parameter-panel-v1/cli_real_upload_acceptance_report.json`

Developer-style Writeback DevKit MVP:

- `course_city_cost_writeback` is the first accepted table for CLI developer
  use.
- `writeback-check` performs local workbook validation and summary only.
- `writeback-upload` maps to the stable no-browser upload path and requires
  `--confirm`; it performs one upload, no auto retry, no auto rollback, then
  post-verify candidate subset compare.
- `writeback-diagnose` reads saved response artifacts without login or upload.
- `writeback-onboard` creates a draft task config and onboarding report for a
  new table. Offline mode generates artifacts only; online mode may perform
  read-only SmartBI target/template/RMI probes but still must not upload.
- New tables move through `discovered`, `configured`, `validated`, and
  `approved_for_developer_use`.
- No unaccepted table may be marked `approved_for_developer_use`.

DevKit documentation:

- operator guide:
  `docs/smartbi_writeback_devkit_operator_guide.md`
- offline onboarding report:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/devkit-mvp-20260526/onboarding/course_city_cost_writeback_devkit_draft/offline-draft/writeback_onboarding_report.json`
- offline task config draft:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/devkit-mvp-20260526/onboarding/course_city_cost_writeback_devkit_draft/offline-draft/writeback_task_config_draft.json`
- offline shadow upload plan:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/devkit-mvp-20260526/onboarding/course_city_cost_writeback_devkit_draft/offline-draft/shadow_upload_plan.json`

Not ready for owner manual upload until:

1. owner reviews the command artifact and accepts the production-data risk
2. candidate, rollback, and expected-diff SHA-256 values still match
3. owner is present to run post-verify and prepare rollback immediately after
   the first upload command
