# SmartBI Writeback CLI Dry-Run Design

Date: 2026-05-25

## Boundary

The writeback path now has two no-upload slices:

- offline dry-run/diff: no SmartBI login
- HTTP servlet probe / shadow execute: SmartBI login is allowed only to validate
  `openimportconfig.jsp` and template download

For every slice:

- no Excel upload
- no `DataAcquisitionServlet` submit
- no external write
- no database mutation
- no Playwright primary path

The current deliverable validates whether local Excel files and SmartBI servlet
metadata are eligible for a future writeback task, then emits a shadow execution
plan. It is not upload-ready.

## Target Demo

Task id: `course_city_cost_writeback`

SmartBI target alias: `课包城市消耗数据回写`

Target path status: verified through SmartBI catalog inspection on 2026-05-25.

Current configured path:

```text
分析报表/海外直播业务线/填报/海外投放课包城市维度数据填报/课包城市消耗数据回写
```

SmartBI target metadata:

- id: `I2c928087017cd66bd66bdc41017ce91e219f5fe6`
- type: `DAQ_IMPORTCONFIG`

Current input:

```text
/Users/takuya/Desktop/投放账户数据回写填报模板_输出.xlsx
```

## Offline Contract

Source of truth:

- config: `configs/smartbi_writeback_tasks.json`
- validator: `scripts/validate_smartbi_writeback_input.py`
- latest dry-run report:
  `outputs/smartbi_writeback_dry_run/course_city_cost_writeback_dry_run_20260525.json`
- workbook structure inspect:
  `outputs/smartbi_writeback_dry_run/course_city_cost_writeback_input_inspect_20260525.json`

The configured workbook contract is:

- workbook type: `.xlsx`
- sheet: `Sheet1`
- instruction row: `1`
- header row: `4`
- data start row: `5`
- expected header count: `31`
- max rows for demo: `5000`
- allowed input dirs:
  - `/Users/takuya/Desktop`
  - `outputs/smartbi_writeback_inputs`

Required non-empty columns:

```text
日期, 主投学科, 平台, 区域细分, 投放账户, 广告计划id, 广告计划名称,
广告组id, 广告组名称, 广告id, 广告名称
```

ID columns may use `0` when upstream has no id:

```text
广告计划id, 广告组id, 广告id, 广告素材id, 笔记ID
```

## Dry-Run Command

```bash
python3 scripts/validate_smartbi_writeback_input.py \
  --task course_city_cost_writeback \
  --file /Users/takuya/Desktop/投放账户数据回写填报模板_输出.xlsx \
  --out outputs/smartbi_writeback_dry_run/course_city_cost_writeback_dry_run_20260525.json \
  --json
```

Pass condition:

- `status == "ok"`
- `boundary.no_smartbi_login == true`
- `boundary.no_upload == true`
- `schema.headers_match == true`
- required non-empty columns have no missing values
- date columns parse
- numeric columns parse

## Current Dry-Run Result

Current result: pass.

Observed input structure:

- sheet: `Sheet1`
- workbook rows: `1120`
- workbook columns: `31`
- header row: `4`
- data start row: `5`
- data rows: `1116`
- field headers matched configured template

Observed date ranges:

| Column | Min | Max |
|---|---:|---:|
| 日期 | 2026-05-22 | 2026-05-22 |
| 开始投放日期 | 2026-04-30 | 2026-05-22 |
| 上传日期 | 2026-05-23 | 2026-05-23 |

Observed top-level totals:

| Metric | Sum |
|---|---:|
| 曝光 | 385302 |
| 点击 | 8914 |
| 覆盖人数 | 345344 |
| 链接点击量 | 6819 |
| 购物 | 306 |
| 潜在客户数 | 9 |
| 消息发起次数 | 51 |
| 消耗 | 40873.217208 |

Observed platform split:

| 平台 | Rows |
|---|---:|
| 直购（FB） | 849 |
| KOLHK | 194 |
| KOLTW | 40 |
| KOL本地 | 21 |
| SEOTW | 12 |

## Target Probe Result

Probe date: 2026-05-25

Probe boundary:

- SmartBI login: yes
- target page open: yes
- file selected: no
- upload submitted: no
- external write: no

Latest target probe artifacts:

- result:
  `outputs/smartbi_writeback_target_probe/course_city_cost_writeback/20260525-165003/target_probe.json`
- screenshot:
  `outputs/smartbi_writeback_target_probe/course_city_cost_writeback/20260525-165003/target-page.png`

Verified page:

- document title: `课包城市消耗数据回写`
- page URL after load: `https://bi.61info.cn/smartbi/vision/openimportconfig.jsp`
- visible controls:
  - `下载补录模板`
  - `浏览`
  - `导入`
  - `下载异常数据`

Upload form shape:

- action: `DataAcquisitionServlet`
- method: `post`
- enctype: `multipart/form-data`
- file input: `input[type=file][name=file]`
- hidden field: `type=excelimport`

Template download form shape:

- action: `ExcelTemplateDownloadServlet`
- method: `post`

Implication:

The first real implementation should target a direct HTTP servlet flow, not
browser automation:

- open target config through `openimportconfig.jsp`
- validate the generated/import config metadata
- construct an audited multipart request preview for `DataAcquisitionServlet`
- keep actual multipart submit behind a later hard-gated execute slice
- keep browser probe only as a fallback diagnostic path

A strict RMI-only writeback path is not proven from this probe. SmartBI uses RMI
to load UI/config state, while the actual Excel import surface is servlet-based.

## Proposed CLI Upgrade Shape

Keep writeback separate from the existing read-only export flow.

Future command shape:

```bash
python3 scripts/smartbi_cli.py writeback \
  --config configs/smartbi_writeback_tasks.json \
  --task course_city_cost_writeback \
  --file /Users/takuya/Desktop/投放账户数据回写填报模板_输出.xlsx \
  --dry-run \
  --json
```

Current probe command shape:

```bash
python3 scripts/smartbi_cli.py writeback \
  --config configs/smartbi_writeback_tasks.json \
  --task course_city_cost_writeback \
  --probe \
  --json
```

Current HTTP servlet probe command shape:

```bash
python3 scripts/smartbi_cli.py writeback \
  --config configs/smartbi_writeback_tasks.json \
  --task course_city_cost_writeback \
  --http-probe \
  --file /Users/takuya/Desktop/投放账户数据回写填报模板_输出.xlsx \
  --json
```

HTTP servlet probe pass condition:

- browser is not used
- SmartBI login succeeds through `SmartbiClient`
- `openimportconfig.jsp` returns the expected `resId` and resource name
- `ExcelImportExecutorView` / `OPEN_EXCEL_IMPORT` / `DAQ_IMPORTCONFIG` are present
- `ExcelTemplateDownloadServlet` returns a valid xlsx zip
- `future_upload_request.will_submit_in_http_probe == false`

Current diff command shape:

```bash
python3 scripts/smartbi_cli.py writeback \
  --config configs/smartbi_writeback_tasks.json \
  --task course_city_cost_writeback \
  --diff \
  --original-file /path/to/original.xlsx \
  --candidate-file /path/to/edited-test.xlsx \
  --max-changed-rows 3 \
  --json
```

Real writeback remains blocked in the current CLI slice. Passing the future
flags now returns `writeback_execute_blocked` with process return code `2`.
Diff failures also return process code `2`.

## Shadow Execute Build

`writeback --shadow-execute` builds an auditable execution plan but does not
submit the multipart request.

Required inputs:

```bash
python3 scripts/smartbi_cli.py writeback \
  --config configs/smartbi_writeback_tasks.json \
  --task course_city_cost_writeback \
  --shadow-execute \
  --candidate-file outputs/smartbi_writeback_inputs/投放账户数据回写填报模板_输出.xlsx \
  --rollback-file /Users/takuya/Desktop/投放账户数据回写填报模板_输出.xlsx \
  --expected-diff outputs/smartbi_writeback_cli/course_city_cost_writeback/shadow-expected-diff-20260525/writeback_diff.json \
  --run-id shadow-execute-20260525 \
  --json
```

Shadow preflight gates:

- candidate workbook dry-run must pass
- rollback workbook dry-run must pass
- current rollback/candidate diff must have `status=ok`
- `--expected-diff` must exist, have `status=ok`, and match the current diff
- HTTP servlet probe must pass through `SmartbiClient`

Shadow plan artifact:

```text
outputs/smartbi_writeback_cli/course_city_cost_writeback/shadow-execute-20260525/writeback_shadow_execution_plan.json
```

The plan includes:

- target `DAQ_IMPORTCONFIG` id
- candidate workbook path, byte size, and SHA-256
- rollback workbook path, byte size, and SHA-256
- expected diff path and match result
- `DataAcquisitionServlet` multipart field preview:
  - `type=excelimport`
  - `id=<target report_id>`
  - `parameterPanelBOId`
  - `selectedRuleIds`
  - `file=<xlsx binary omitted>`
- response parser fixture results for success HTML, failure HTML, and empty
  response
- post-verify report plan from `post_verify.report`
- `upload_submitted=false`

Hard block remains:

```bash
python3 scripts/smartbi_cli.py writeback \
  --task course_city_cost_writeback \
  --execute \
  --confirm-writeback \
  --json
```

Expected result: `writeback_execute_blocked` with process code `2`.

## GAO Hardening Harness

The local fixture harness is:

```bash
python3 scripts/test_smartbi_writeback_shadow.py
```

It is local-only:

- SmartBI login: false
- DataAcquisitionServlet request sent: false
- upload_submitted=false
- external write: false

Coverage:

- multipart preview fields and no-submit flags
- expected-diff valid / invalid / mismatch checks
- response parser fixtures for success HTML, failure HTML with `下载异常数据`,
  and empty response
- missing `--rollback-file`
- missing `--expected-diff`
- key/id field mutation diff failure
- `writeback_execute_blocked`

Generated artifacts:

```text
outputs/smartbi_writeback_cli/course_city_cost_writeback/gao-hardening-20260525/post_verify_dry_run_plan.json
outputs/smartbi_writeback_cli/course_city_cost_writeback/gao-hardening-20260525/real_upload_readiness_packet.json
outputs/smartbi_writeback_cli/course_city_cost_writeback/gao-hardening-20260525/fixture_test_summary.json
```

The readiness packet decision is `shadow_ready_not_upload_ready`. It is not
owner approval, not upload approval, and not execute enablement.

## Upload Readiness Planning

The upload-readiness planning packet is now available under:

```text
outputs/smartbi_writeback_cli/course_city_cost_writeback/upload-readiness/
```

Artifacts:

- `real_upload_implementation_plan.json`
- `real_upload_safety_gate.json`
- `owner_approval_packet.md`

Current implementation readiness decision:

```text
ready_for_separate_real_upload_implementation_goal_after_owner_decision_not_upload_ready
```

Boundary:

- current readiness remains `shadow_ready_not_upload_ready`
- this is not owner approval
- this is not upload approval
- this is not execute enablement
- `writeback_execute_blocked` remains active
- DataAcquisitionServlet request sent=false
- upload_submitted=false

The next step, if the owner chooses to continue, must be a separate
implementation goal with explicit owner approval. This document does not enable
real multipart submit.

## Owner Manual Test Command

The guarded real upload execution path is implemented behind owner-token,
SHA-256, run-id, and upload-window gates. The default unguarded command still
returns `writeback_execute_blocked`.

Owner-test artifacts:

```text
outputs/smartbi_writeback_cli/course_city_cost_writeback/owner-test/owner_test_command.md
outputs/smartbi_writeback_cli/course_city_cost_writeback/owner-test/owner_test_token.json
outputs/smartbi_writeback_cli/course_city_cost_writeback/owner-test/guarded_execute_test_summary.json
```

Boundary for artifact generation:

- DataAcquisitionServlet request sent=false
- upload_submitted=false
- SmartBI login=false
- SmartBI production data unchanged

Only manually running the real upload command in `owner_test_command.md` will
submit to `DataAcquisitionServlet` and change SmartBI production data.

## First Owner Upload Failure

The first owner manual upload test returned a SmartBI business failure:

```text
upload_result=failed
success=false
```

Artifacts:

```text
outputs/smartbi_writeback_cli/course_city_cost_writeback/owner-test-20260525/guarded_execute_response.json
outputs/smartbi_writeback_cli/course_city_cost_writeback/owner-test-20260525/upload_failure_diagnosis.json
```

The response preview contained `doImportFormSubmitCallback` and `sheetResults`,
but the old response artifact kept only a short preview, so the detailed row or
column reason is currently `insufficient_response_capture`.

Policy after this failure:

- no automatic retry
- no rollback unless a successful write is confirmed
- no post-verify command after this failed upload
- next step is failure diagnosis / exception data review

Future real writeback shape, after separate owner approval:

```bash
python3 scripts/smartbi_cli.py writeback \
  --config configs/smartbi_writeback_tasks.json \
  --task course_city_cost_writeback \
  --file /Users/takuya/Desktop/投放账户数据回写填报模板_输出.xlsx \
  --execute \
  --confirm-writeback \
  --json
```

Real writeback must require:

- explicit `--execute`
- explicit `--confirm-writeback`
- credentials from `SMARTBI_USERNAME` and `SMARTBI_PASSWORD`
- one configured target task
- one configured input file
- a saved run artifact
- a post-writeback verification plan

Related runbook:

- `docs/smartbi_writeback_real_upload_validation_plan.md`

## Technical Feasibility

Feasible, but first real implementation should be HTTP-servlet-backed rather
than browser-backed or strict RMI-only.

Reasoning:

- current `scripts/smartbi_cli.py` is an export-oriented CLI
- current export path uses `RMIServlet` and `ssreportServlet`
- the upload endpoint is visible as `DataAcquisitionServlet`
- direct template download through `ExcelTemplateDownloadServlet` has been
  verified without browser automation
- the user-facing SmartBI operation is a page upload button, but the underlying
  operation is a multipart servlet request

The implemented safe path now has two layers:

1. `shadow-execute`: log in, validate target, validate candidate/rollback/diff,
   and construct but do not submit the `DataAcquisitionServlet` multipart
   payload.
2. guarded `execute`: only after owner-token, SHA-256 locks, upload window, and
   preflight checks pass, submit exactly one `DataAcquisitionServlet` request.

The guarded execute code path is implemented, but it is not run by tests or by
artifact generation. Only the owner manually running the command artifact will
perform the upload.

## Demo Test Ladder

1. `offline dry-run`
   Validate local Excel only. This is now done.

2. `target probe`
   Login and open the SmartBI target page. Identify upload control and endpoint.
   Do not upload. This is now done.

3. `http servlet probe`
   Login without browser, open import config, and download the template through
   servlet endpoints. This is now partially done: direct template download
   passed.

4. `single-file execute`
   Guarded code path is implemented. Owner manual test command is available at
   `outputs/smartbi_writeback_cli/course_city_cost_writeback/owner-test/owner_test_command.md`.
   Running that command uploads exactly one approved file to exactly one
   approved target and writes preflight/response artifacts.

5. `post-verify`
   Re-open or export the corresponding result view and compare row count,
   date range, platform split, and spend sum against the dry-run report.

## Manual UI Success And Post-Verify

On `2026-05-26`, the owner manually uploaded the corrected workbook through the
SmartBI UI. The SmartBI UI displayed `sheet1导入规则1` with `成功:36列;失败:0列`.

This was not a CLI upload. During the follow-up, the CLI only performed
read-only post-verify actions:

- `inspect-report` against `课包城市消耗周报填报数据`
- read-only export filtered to `2026-05-25`
- local subset compare of the 36 candidate rows against the exported report

Artifacts:

- post-verify export config:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/manual-success-20260526/post_verify_export_config.json`
- post-verify export:
  `outputs/bi_exports/course_city_cost_post_verify_20260525/2026-05-26/20260526-114718/课包城市消耗周报填报数据.xlsx`
- post-verify compare:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/manual-success-20260526/post_verify_compare_summary.json`

Result:

- compare status: `ok`
- candidate row count: `36`
- post-verify export row count: `107`
- candidate keys missing in export: `0`
- value mismatch count: `0`
- candidate spend sum: `41204.726709`

The export contains all rows visible for `2026-05-25`, not only the uploaded
candidate batch. Therefore the acceptance check is candidate-as-subset, not
full export row-count equality.

## CLI Real Upload Success

Run `cli-single-upload-20260526-parameter-panel-v1` completed the no-browser CLI
write path:

- SmartBI login through `SmartbiClient`
- target validation through `openimportconfig.jsp`
- upload-context initialization through:
  `DataAcquisitionModule.getImportConfigRules` and
  `DataAcquisitionModule.getAllParams`
- multipart upload through `DataAcquisitionServlet`
- callback parsing from `doImportFormSubmitCallback`
- post-verify export and subset compare

Result:

- browser used: `false`
- Playwright primary path: `false`
- `DataAcquisitionServlet` request sent: `true`
- upload request count: `1`
- automatic retry: `false`
- automatic rollback: `false`
- callback `success=true`
- `sheetResults[0].successCount=36`
- `sheetResults[0].totalCount=36`
- post-verify compare status: `ok`
- candidate keys missing in export: `0`
- value mismatch count: `0`

Artifacts:

- acceptance report:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/cli-single-upload-20260526-parameter-panel-v1/cli_real_upload_acceptance_report.json`
- upload preflight:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/cli-single-upload-20260526-parameter-panel-v1/single_upload_preflight.json`
- reparsed upload response:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/cli-single-upload-20260526-parameter-panel-v1/single_upload_response_reparsed.json`
- post-verify compare:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/cli-single-upload-20260526-parameter-panel-v1/post_verify_compare_summary.json`

## Writeback DevKit MVP

The real upload path is now productized as a developer-style CLI DevKit for
command-line-capable operators. The DevKit does not add a UI, permission system,
or operator/owner role split.

Entrypoints:

- `writeback-check`: local workbook inspection only. It reports row count, date
  range, key count, metric sums, and schema warnings. It does not login and does
  not upload.
- `writeback-upload`: operator alias for one confirmed CLI upload path. It maps
  to the stable `single-upload` implementation, initializes
  `parameterPanelBOId` and `selectedRuleIds`, sends one
  `DataAcquisitionServlet` multipart request only when `--confirm` is present,
  parses the callback, and runs post-verify.
- `writeback-diagnose`: reads saved run artifacts and summarizes
  success/failure, `errorMessage`, `sheetResults`, and exception-data hints. It
  does not login and does not upload.
- `writeback-onboard`: generates a new writeback task config draft,
  onboarding report, and shadow upload plan from a target URL/path plus sample
  workbook. Offline mode does not login; online mode only probes and downloads
  templates read-only.

DevKit fixture artifacts:

- onboarding report:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/devkit-mvp-20260526/onboarding/course_city_cost_writeback_devkit_draft/offline-draft/writeback_onboarding_report.json`
- task config draft:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/devkit-mvp-20260526/onboarding/course_city_cost_writeback_devkit_draft/offline-draft/writeback_task_config_draft.json`
- shadow upload plan:
  `outputs/smartbi_writeback_cli/course_city_cost_writeback/devkit-mvp-20260526/onboarding/course_city_cost_writeback_devkit_draft/offline-draft/shadow_upload_plan.json`

Post-verify remains candidate subset comparison, not full export row-count
equality. Operators must not auto retry and must not auto rollback on failure.
Use `writeback-diagnose` first.

## Stop Conditions

Stop before real upload if any of these occur:

- target path cannot be verified
- target alias does not match `课包城市消耗数据回写`
- upload button or endpoint is ambiguous
- workbook dry-run fails
- required non-empty fields contain blanks
- row count exceeds configured maximum
- SmartBI returns any warning that suggests overwrite or destructive behavior
- post-verify route is unavailable

## Next Confirmation Gate

Proceed only if the owner confirms:

```text
确认进入 SmartBI owner manual upload test：我将手动运行 owner_test_command.md
中的真实上传命令，并确认这会修改 SmartBI 生产数据。我会在上传窗口内监控结果，
并准备按 rollback 模板处理回滚。
```
