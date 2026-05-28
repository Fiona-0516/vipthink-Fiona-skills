# SmartBI Data CLI Security Boundary

This document defines what teammates may run, share, and change when using
SmartBI Data CLI.

## Default Safe Mode

The default safe mode is local, read-only, and dry-run first:

- no SmartBI writeback;
- no external system writes;
- no Feishu, GitHub, Obsidian, or automation mutation;
- credentials supplied only through the local runtime;
- outputs kept under local `outputs/` run directories.

Start with:

```bash
python3 scripts/smartbi_cli.py doctor --json
```

`doctor` is offline by default. `doctor --online --json` may login and read the
SmartBI catalog root, but it must not export Excel, upload files, or write to
external systems.

## Credential Rules

- Do not write SmartBI usernames, passwords, cookies, tokens, or session values
  into configs, docs, recipes, automation prompts, logs, screenshots, or handoff
  notes.
- Use `SMARTBI_USERNAME` and `SMARTBI_PASSWORD` in the local shell or private
  automation runtime.
- Do not pass passwords through teammate chat, issue comments, public README
  files, or shared screenshots.
- If a run output contains credentials or session material, stop and treat the
  artifact as non-shareable.

## Read-Only Export Boundary

Read-only export is allowed only after dry-run or smoke validation:

1. validate config and command shape;
2. run dry-run where available;
3. run a bounded real export only when the owner has approved the selected
   task, date window, filters, and concurrency;
4. inspect `run.json`, workbook validity, and downstream chain guards before
   treating the output as usable.

The batch runner defaults to dry-run. Real export requires explicit
`--execute`.

## Writeback Boundary

Writeback is not a normal export. It can change SmartBI production data.

Allowed teammate steps without separate upload approval:

- `writeback-check` local workbook inspection;
- local workbook validation;
- local candidate/rollback diff;
- HTTP probe that does not select or upload a file;
- shadow execution plan that does not submit `DataAcquisitionServlet`.

Allowed only for approved operator runs:

- `writeback-upload --confirm` for one confirmed upload;
- post-verify candidate subset comparison;
- `writeback-diagnose` after failure.

Blocked unless explicitly approved by the owner/operator:

- real upload;
- `DataAcquisitionServlet` submit;
- changing candidate/rollback files after approval;
- extending upload windows locally;
- bypassing approval token or SHA-256 locks.

If a writeback command asks for `--execute`, `--single-upload`,
`--confirm-writeback`, `--confirm`, `--owner-approval-token`, upload windows, or
SHA-256 locks, stop and confirm the current approved run packet.

## Shareable Package Rules

Internal teammate package may include:

- CLI scripts;
- example configs or owner-approved internal configs;
- recipes;
- error-code and security-boundary docs;
- operator guide for approved writeback users;
- smoke and replay commands;
- local verification instructions.

External or public package must remove:

- real BI hostnames and paths;
- report IDs;
- business-specific structure;
- fixed export entrypoints tied to internal data;
- credentials, tokens, cookies, and private automation details.

When in doubt, publish README-only and share the real package out of band.

## Stop Conditions

Stop the run and preserve evidence when:

- credentials are missing or appear in an artifact;
- SmartBI login or catalog access fails unexpectedly;
- a report type or workbook shape does not match the documented contract;
- a dry-run fails;
- a writeback preflight, diff, HTTP probe, or shadow step fails;
- a real upload path appears without owner approval;
- the same failure repeats after one clean rerun.
