#!/usr/bin/env python3
"""Browser-backed SmartBI SIMPLE_REPORT probe/export helpers.

SmartBI SIMPLE_REPORT exports depend on browser-side QueryView state. Keep this
module small and serial so callers can probe row counts before downloading
large raw tables.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any


BASE_URL = "https://bi.61info.cn/smartbi/vision"


class SmartbiBrowserExportError(RuntimeError):
    pass


def normalize_filters(filters: list[tuple[str, str, str]] | list[list[str]] | None) -> list[list[str]]:
    normalized: list[list[str]] = []
    for item in filters or []:
        if len(item) != 3:
            raise SmartbiBrowserExportError(f"Filter must have alias, value, displayValue: {item}")
        alias, value, display_value = item
        normalized.append([str(alias), str(value), str(display_value)])
    return normalized


async def probe_simple_report_with_browser(
    *,
    username: str,
    password: str,
    report_id: str,
    max_rows: int = 5000,
    browser_channel: str = "chrome",
    headless: bool = True,
    filters: list[tuple[str, str, str]] | list[list[str]] | None = None,
    base_url: str = BASE_URL,
) -> dict[str, Any]:
    return await _simple_report_browser_run(
        username=username,
        password=password,
        report_id=report_id,
        output_path=None,
        max_rows=max_rows,
        browser_channel=browser_channel,
        headless=headless,
        filters=normalize_filters(filters),
        base_url=base_url,
        export=False,
    )


async def export_simple_report_with_browser(
    *,
    username: str,
    password: str,
    report_id: str,
    output_path: Path,
    max_rows: int,
    browser_channel: str = "chrome",
    headless: bool = True,
    filters: list[tuple[str, str, str]] | list[list[str]] | None = None,
    base_url: str = BASE_URL,
) -> dict[str, Any]:
    return await _simple_report_browser_run(
        username=username,
        password=password,
        report_id=report_id,
        output_path=output_path,
        max_rows=max_rows,
        browser_channel=browser_channel,
        headless=headless,
        filters=normalize_filters(filters),
        base_url=base_url,
        export=True,
    )


async def _simple_report_browser_run(
    *,
    username: str,
    password: str,
    report_id: str,
    output_path: Path | None,
    max_rows: int,
    browser_channel: str,
    headless: bool,
    filters: list[list[str]],
    base_url: str,
    export: bool,
) -> dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as error:
        raise SmartbiBrowserExportError(
            "Playwright is required for SmartBI SIMPLE_REPORT export; run with `uv run --with playwright ...`."
        ) from error

    async with async_playwright() as playwright:
        launch_kwargs: dict[str, Any] = {"headless": headless}
        if browser_channel:
            launch_kwargs["channel"] = browser_channel
        browser = await playwright.chromium.launch(**launch_kwargs)
        page = await browser.new_page()
        try:
            await page.goto(f"{base_url}/index.jsp?time=1778858593300", wait_until="domcontentloaded", timeout=60000)
            login_payload = await page.evaluate(
                """async ({username, password}) => {
                  const body = new URLSearchParams({
                    className: 'UserService',
                    methodName: 'clickLogin',
                    params: JSON.stringify([username, password])
                  });
                  const response = await fetch('RMIServlet', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'},
                    body
                  });
                  return await response.json();
                }""",
                {"username": username, "password": password},
            )
            if login_payload.get("result") is not True:
                raise SmartbiBrowserExportError("SmartBI login failed in browser export")

            report_url = f"{base_url}/openresource.jsp?isBrowse=true&showLeftTree=default&resid={report_id}"
            await page.goto(report_url, wait_until="domcontentloaded", timeout=120000)
            await page.wait_for_timeout(8000)
            result = await page.evaluate(
                """async ({filters, maxRows, exportFile}) => {
                  async function rmi(className, methodName, params) {
                    const body = new URLSearchParams({className, methodName, params: JSON.stringify(params)});
                    const response = await fetch('RMIServlet', {
                      method: 'POST',
                      headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'},
                      body
                    });
                    const payload = await response.json();
                    if (payload.retCode !== 0 && payload.retCode !== '0') {
                      throw new Error(JSON.stringify(payload).slice(0, 500));
                    }
                    return payload.result;
                  }
                  const adapter = window.getReportAdapter && window.getReportAdapter();
                  const query =
                    adapter && adapter.queryViewCommand && adapter.queryViewCommand.query ||
                    adapter && adapter.processor && adapter.processor.queryViewCommand && adapter.processor.queryViewCommand.query ||
                    adapter && adapter.processor && adapter.processor.query;
                  if (!query || !query.paramPanelObj || !query.params) {
                    throw new Error('SmartBI QueryView is not ready');
                  }
                  const params = query.params.map((param) => ({
                    id: param.id,
                    alias: param.alias,
                    name: param.name,
                    value: param.value,
                    displayValue: param.displayValue
                  }));
                  const paramIdByAlias = (alias) => {
                    const param = query.params.find((candidate) => candidate.alias === alias || candidate.name === alias);
                    if (!param) throw new Error(`SmartBI parameter not found: ${alias}`);
                    return param.id;
                  };
                  const applied = [];
                  for (const [alias, value, displayValue] of filters) {
                    const paramId = paramIdByAlias(alias);
                    query.paramPanelObj.setParamValue(paramId, value, displayValue, null, null, true);
                    query.setParamValue(paramId, value, displayValue, true);
                    applied.push({alias, value, displayValue});
                  }
                  const panelValues = query.paramPanelObj.getPanelParamValues();
                  await rmi('CompositeService', 'refreshDataWithDefaultEx', [query.clientId, false, false]);
                  const rowCount = await rmi('ClientReportService', 'getTotalRowsCountWithFuture', [query.clientId, 0]);
                  const base = {clientId: query.clientId, params, applied, panelValues, rowCount, maxRows};
                  if (!Number.isInteger(rowCount) || rowCount < 0) {
                    throw new Error(`SmartBI returned invalid row count: ${rowCount}`);
                  }
                  if (rowCount > maxRows) {
                    return {...base, exportSkipped: true, skipReason: `rowCount ${rowCount} exceeds maxRows ${maxRows}`};
                  }
                  if (!exportFile) {
                    return {...base, exportSkipped: true, skipReason: 'probe_only'};
                  }
                  const form = new URLSearchParams({
                    type: 'EXCEL2007',
                    clientId: query.clientId,
                    delimiter: '',
                    maxRow: String(maxRows),
                    mode: '',
                    valueType: '',
                    headerHtml: '',
                    tailHtml: '',
                    result: '',
                    contentType: 'gridOnly',
                    pageId: '',
                    exportHiddenField: '',
                    needHiddenParamIds: '',
                    checkedRows: '',
                    chartAlign: '',
                    codeType: 'UTF-8',
                    isBOM: ''
                  });
                  const response = await fetch('ExportServlet', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'},
                    body: form
                  });
                  const contentType = response.headers.get('content-type') || '';
                  const contentDisposition = response.headers.get('content-disposition') || '';
                  const buffer = await response.arrayBuffer();
                  return {
                    ...base,
                    contentType,
                    contentDisposition,
                    bytes: Array.from(new Uint8Array(buffer))
                  };
                }""",
                {"filters": filters, "maxRows": max_rows, "exportFile": export},
            )
            body_values = result.pop("bytes", None)
            if body_values is None:
                return result
            body = bytes(body_values)
            content_type = result.get("contentType", "")
            if "excel" not in content_type.lower() and not body.startswith(b"PK\x03\x04"):
                preview = body[:300].decode("utf-8", "replace")
                raise SmartbiBrowserExportError(f"SmartBI export did not return Excel: {content_type}: {preview}")
            if output_path is None:
                raise SmartbiBrowserExportError("output_path is required when export=True")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(body)
            result["output"] = str(output_path)
            result["bytes"] = len(body)
            return result
        finally:
            await browser.close()


def parse_filter_json(value: str | None) -> list[list[str]]:
    if not value:
        return []
    data = json.loads(value)
    if not isinstance(data, list):
        raise SmartbiBrowserExportError("--filters-json must be a list")
    return normalize_filters(data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe or export a SmartBI SIMPLE_REPORT through a browser session.")
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--output")
    parser.add_argument("--max-rows", type=int, default=5000)
    parser.add_argument("--filters-json", help='List of [alias, value, displayValue] filters.')
    parser.add_argument("--browser-channel", default=os.environ.get("SMARTBI_BROWSER_CHANNEL", "chrome"))
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--username", default=os.environ.get("SMARTBI_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("SMARTBI_PASSWORD"))
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.username or not args.password:
        raise SystemExit("SMARTBI_USERNAME/SMARTBI_PASSWORD or --username/--password is required")
    filters = parse_filter_json(args.filters_json)
    if args.output:
        result = asyncio.run(
            export_simple_report_with_browser(
                username=args.username,
                password=args.password,
                report_id=args.report_id,
                output_path=Path(args.output).expanduser(),
                max_rows=args.max_rows,
                browser_channel=args.browser_channel,
                headless=not args.headful,
                filters=filters,
            )
        )
    else:
        result = asyncio.run(
            probe_simple_report_with_browser(
                username=args.username,
                password=args.password,
                report_id=args.report_id,
                max_rows=args.max_rows,
                browser_channel=args.browser_channel,
                headless=not args.headful,
                filters=filters,
            )
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
