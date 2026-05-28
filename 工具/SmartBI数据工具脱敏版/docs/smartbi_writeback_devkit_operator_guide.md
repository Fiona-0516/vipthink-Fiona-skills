# SmartBI Writeback DevKit Operator Guide

## Current Status

`course_city_cost_writeback` has passed one CLI real-upload acceptance run:

- run id: `cli-single-upload-20260526-parameter-panel-v1`
- path: `SmartbiClient` login, RMI upload-context initialization, `DataAcquisitionServlet` multipart upload, callback parsing, post-verify export, candidate subset compare
- browser used: `false`
- Playwright primary path: `false`
- upload request count: `1`
- no auto retry
- no auto rollback
- callback `success=true`
- `sheetResults[0].successCount=36`
- `sheetResults[0].totalCount=36`
- post-verify candidate subset compare: `ok`

Acceptance artifacts:

- `outputs/smartbi_writeback_cli/course_city_cost_writeback/cli-single-upload-20260526-parameter-panel-v1/cli_real_upload_acceptance_report.json`
- `outputs/smartbi_writeback_cli/course_city_cost_writeback/cli-single-upload-20260526-parameter-panel-v1/single_upload_response_reparsed.json`
- `outputs/smartbi_writeback_cli/course_city_cost_writeback/cli-single-upload-20260526-parameter-panel-v1/post_verify_compare_summary.json`

## Operator Model

投放师/业务开发者被视为 CLI developer/operator。当前 DevKit MVP 不做 UI、不做权限系统、不做投放师和 owner 分层。

每次上传仍然是生产写入动作。`writeback-upload --confirm` 会发送一次 `DataAcquisitionServlet` 请求。失败时不要自动重试，不要自动 rollback；先运行 `writeback-diagnose` 读取回执 artifact。

## Daily Upload Flow

1. 本地检查 Excel：

```bash
python3 scripts/smartbi_cli.py writeback-check \
  --task course_city_cost_writeback \
  --file /path/to/writeback.xlsx \
  --json
```

2. 确认上传：

```bash
python3 scripts/smartbi_cli.py writeback-upload \
  --task course_city_cost_writeback \
  --file /path/to/writeback.xlsx \
  --operator <operator-name> \
  --confirm \
  --json
```

3. 失败诊断：

```bash
python3 scripts/smartbi_cli.py writeback-diagnose \
  --run-dir outputs/smartbi_writeback_cli/course_city_cost_writeback/<run-id> \
  --json
```

`writeback-upload` 默认不自动 retry、不自动 rollback。未知响应、空响应、异常数据提示、post-verify mismatch 都应 fail closed。

## Post-Verify Rule

验收口径是 candidate subset，不是全表行数相等。

SmartBI post-verify 报表可能包含同一天其他投放师、其他渠道、其他批次的数据。因此验收只要求：

- candidate key 全部出现在 post-verify export 中
- candidate compare columns 的值与 export 中同 key 聚合值一致
- `candidate_keys_missing_in_export_count=0`
- `value_mismatch_count=0`

## New Table Onboarding

新回写表接入时，投放师/业务开发者需要提供：

- SmartBI 回写表 URL 或路径
- 一份预计正确的 sample Excel
- post-verify 报表 URL 或路径
- key columns / compare columns；如果没有提供，CLI 先给建议

生成草稿：

```bash
python3 scripts/smartbi_cli.py writeback-onboard \
  --offline \
  --task <new_writeback_task> \
  --target-url "<openimportconfig.jsp?resid=...>" \
  --sample-file /path/to/sample.xlsx \
  --post-verify-path "<post verify report path>" \
  --json
```

在线只读探测版本可去掉 `--offline` 并提供 SmartBI 凭据；它只做目标探测、模板下载和 RMI upload-context probe，不上传。

Onboarding 产物：

- `writeback_task_config_draft.json`
- `writeback_onboarding_report.json`
- `shadow_upload_plan.json`

状态流：

- `discovered`
- `configured`
- `validated`
- `approved_for_developer_use`

未经过小样本真实上传和 post-verify 验收的新表不得标记为 `approved_for_developer_use`。

## Second Table Acceptance

第二张表应按以下顺序接入：

1. `writeback-onboard` 生成配置草稿和 shadow upload plan。
2. 人工确认 post-verify 报表、key columns、compare columns。
3. `writeback-check` 本地校验 sample Excel。
4. shadow/preflight 复核 multipart fields 和 upload context。
5. owner/operator 小样本真实上传一次。
6. 上传后立即 post-verify candidate subset compare。
7. 只有验收通过后，才把该 task 标记为 `approved_for_developer_use`。

## Failure Policy

- no auto retry
- no auto rollback
- no Playwright primary path
- no secret logging
- no binary workbook logging
- ambiguous upload result must stop
- exception data detected must stop and diagnose
- rollback 只在确认已有成功写入且业务需要撤回时由真人触发
