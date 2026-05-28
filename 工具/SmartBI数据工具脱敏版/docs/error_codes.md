# SmartBI Data CLI Error Codes

This file is the teammate-facing error guide for SmartBI Data CLI runs. It
turns common CLI failures into next actions without requiring teammates to read
the implementation.

## Output Rule

Prefer commands with `--json`. Start teammate handoff checks with:

```bash
python3 scripts/smartbi_cli.py doctor --json
```

Use online SmartBI login/catalog checks only after credentials are injected:

```bash
python3 scripts/smartbi_cli.py doctor --online --json
```

CLI errors use this shape:

```json
{
  "status": "error",
  "error": {
    "code": "auth_error",
    "message": "Smartbi login failed"
  }
}
```

`doctor --json` uses the same `code` vocabulary in its `checks`.

## Codes

| Code | Meaning | Next action |
|---|---|---|
| `credentials_missing` | `SMARTBI_USERNAME` or `SMARTBI_PASSWORD` is not available in the current shell or automation runtime. | Export credentials in the local runtime, then rerun. Do not write credentials into config, docs, recipes, or automation prompts. |
| `dependency_missing` | A required Python dependency is not importable. | Use the project runtime or install the missing dependency locally, then rerun `doctor`. |
| `optional_dependency_missing` | A recommended helper dependency is not available. | Only required for helper flows such as workbook inspection. Install before running those helpers. |
| `plaintext_credentials_found` | Doctor found text that looks like a plaintext password or secret token. | Stop and remove the artifact from shareable packages. Re-run `doctor` after cleanup. |
| `teammate_docs_missing` | Required teammate handoff docs or recipes are missing. | Restore the missing docs before packaging or handing the CLI to a teammate. |
| `auth_error` | SmartBI rejected login or the current account cannot establish a session. | Check credentials, account status, and whether SmartBI requires manual account action. Do not retry in a tight loop. |
| `network_error` | SmartBI endpoint was unreachable, timed out, or the TLS/HTTP request failed after retries. | Check VPN/network, SmartBI availability, and proxy settings. Rerun once after the network is stable. |
| `config_error` | JSON config is missing, invalid, disabled, or refers to an unknown task. | Validate the config path and task id. Use example config shape before editing maintained configs. |
| `catalog_error` | Catalog root/child lookup returned an unexpected shape or the path cannot be resolved. | Confirm the SmartBI UI path and account permissions. Use `catalog-list` on the nearest known parent path. |
| `smartbi_rmi_error` | SmartBI `RMIServlet` returned a non-zero result for a service call. | Treat as a SmartBI-side or permission error unless a config typo is obvious. Preserve the command and response summary. |
| `parameter_error` | The report context did not expose expected parameter metadata. | Run `inspect-report --json` and confirm the report type. Do not force overrides until parameters are visible. |
| `export_error` | Export did not return a valid Excel response or returned an unexpected content type. | Check report type, row limits, filter requirements, and SmartBI UI behavior. Avoid promoting browser fallback until repeated cases justify it. |
| `assertion_error` | Exported workbook exists but failed configured validation assertions. | Inspect the workbook and task assertions. Treat this as a data/shape mismatch, not a successful export. |
| `upload_window_required` | Guarded writeback execute is missing an approved upload window. | Stop. Owner approval and a bounded upload window are required before any real upload. |
| `upload_window_closed` | Current time is outside the approved writeback window. | Stop. Ask the owner for a new window instead of changing the command locally. |
| `owner_approval_required` | Guarded writeback execute lacks the run-scoped approval token. | Stop. Generate or request the owner approval packet; do not bypass. |
| `owner_approval_token_mismatch` | Provided approval token does not match the run artifacts. | Stop. Rebuild the approval packet from current artifacts and get fresh approval. |
| `sha256_lock_required` | Guarded writeback execute lacks a SHA-256 lock for a required artifact. | Stop. Hash the candidate, rollback, and expected-diff files before approval. |
| `sha256_mismatch` | A locked writeback artifact changed after approval. | Stop. Re-run dry-run/diff/shadow and get fresh approval. |
| `writeback_shadow_preflight_failed` | Candidate/rollback/diff/http-probe did not pass before shadow execution. | Inspect the nested step result. Do not proceed to owner approval. |
| `writeback_execute_blocked` | Real writeback was requested without the required hard confirmation. | Stop. This is the intended safe default unless owner-approved real upload is in scope. |
| `writeback_execute_preflight_failed` | Guarded execute preflight failed before upload. | Stop. Preserve artifacts and diagnose from the failed preflight step. |
| `expected_diff_invalid` | Expected diff file is missing, invalid, or does not match current candidate/rollback files. | Regenerate the diff from the current workbook pair. Do not reuse stale expected-diff artifacts. |
| `writeback_upload_context_failed` | SmartBI upload-context initialization failed before multipart upload. | Stop. Diagnose RMI upload-context fields and do not submit upload without a valid context. |
| `upload_window_invalid` | Upload window value is malformed or ends before it starts. | Stop. Regenerate the approved command packet with valid ISO datetimes. |
| `diagnose_artifact_missing` | `writeback-diagnose` could not find known response artifacts in the run directory. | Check the run directory path and preserve the original upload artifacts. |
| `post_verify_mismatch` | Real upload completed but post-verify candidate subset comparison failed. | Treat the run as failed. Do not retry or rollback automatically; inspect `writeback-diagnose` output first. |

## Escalation Rule

Escalate to the CLI owner when:

- a command touches writeback execute or owner approval;
- SmartBI returns a new unknown business error;
- report type or workbook shape differs from the documented contract;
- a teammate sees real credentials, cookies, tokens, or internal-only URLs in a
  shareable artifact;
- the same failure repeats after one clean rerun with unchanged inputs.
