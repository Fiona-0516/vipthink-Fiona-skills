# Package Manifest

## Package

- name: `smartbi-data-cli-internal-20260526`
- audience: trusted internal operators
- boundary: internal package, no credentials, no exported workbooks, no run logs

## Included

- `scripts/`
  - SmartBI CLI
  - browser-backed `SIMPLE_REPORT` helper
  - report probe helper
  - batch runner
  - config validators
  - writeback validation/diff/probe helpers
  - BI profile query and route matrix helpers
  - report ID registry and route index builders
- `configs/`
  - maintained read-only export configs
  - maintained chain configs
  - writeback task config
  - route matrix config
- `docs/`
  - CLI V1 docs
  - production runbook
  - writeback DevKit operator guide
  - error codes
  - security boundary
- `recipes/`
  - new report onboarding
  - read-only export chain
  - writeback shadow validation
- `inputs/bi_knowledge_maps/current/`
  - refreshed report profiles
  - refreshed BI business data map
  - refreshed filter learning inventory
  - source note
- `outputs/bi_catalog_registry/`
  - current and dated SmartBI report ID registry
  - current and dated BI route index
  - join report and route reference notes

## Excluded

- SmartBI credentials
- cookies/session files
- exported Excel/CSV files
- runtime `run.json` logs
- screenshots
- `__pycache__`
- historical matrix run outputs
- historical dry-run packet outputs

