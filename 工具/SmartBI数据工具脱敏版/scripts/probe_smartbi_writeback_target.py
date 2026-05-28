#!/usr/bin/env python3
"""Probe a SmartBI writeback target page without uploading files."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/smartbi_writeback_tasks.json"
DEFAULT_OUT_ROOT = ROOT / "outputs/smartbi_writeback_target_probe"
BASE_URL = "https://bi.61info.cn/smartbi/vision"


class ProbeError(RuntimeError):
    pass


def load_task(config_path: Path, task_name: str) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    task = (config.get("tasks") or {}).get(task_name)
    if not isinstance(task, dict):
        raise ProbeError(f"unknown task: {task_name}")
    return task


def require_credentials() -> tuple[str, str]:
    username = os.environ.get("SMARTBI_USERNAME")
    password = os.environ.get("SMARTBI_PASSWORD")
    if not username or not password:
        raise ProbeError("SMARTBI_USERNAME and SMARTBI_PASSWORD are required")
    return username, password


def safe_headers(headers: dict[str, str]) -> dict[str, str]:
    allowed = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in {"content-type", "content-length", "location"}:
            allowed[key] = value
    return allowed


async def run_probe(
    *,
    config_path: Path,
    task_name: str,
    out_root: Path,
    headless: bool,
    browser_channel: str,
) -> dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as error:
        raise ProbeError("playwright is required for SmartBI target probe") from error

    username, password = require_credentials()
    task = load_task(config_path, task_name)
    target = task.get("target") or {}
    target_id = target.get("report_id")
    if not isinstance(target_id, str) or not target_id:
        raise ProbeError("task target.report_id is required for target probe")

    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = out_root / task_name / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    network_events: list[dict[str, Any]] = []
    console_events: list[dict[str, str]] = []

    async with async_playwright() as playwright:
        launch_kwargs: dict[str, Any] = {"headless": headless}
        if browser_channel:
            launch_kwargs["channel"] = browser_channel
        browser = await playwright.chromium.launch(**launch_kwargs)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})

        def on_response(response: Any) -> None:
            url = response.url
            if "bi.61info.cn/smartbi" not in url:
                return
            network_events.append(
                {
                    "url": url.split("?", 1)[0],
                    "method": response.request.method,
                    "status": response.status,
                    "headers": safe_headers(dict(response.headers)),
                }
            )

        page.on("response", on_response)
        page.on("console", lambda msg: console_events.append({"type": msg.type, "text": msg.text[:500]}))

        try:
            await page.goto(f"{BASE_URL}/index.jsp?time=1778858593300", wait_until="domcontentloaded", timeout=60000)
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
                raise ProbeError(f"SmartBI login failed: {login_payload.get('retCode')}")

            target_url = f"{BASE_URL}/openresource.jsp?isBrowse=true&showLeftTree=default&resid={target_id}"
            await page.goto(target_url, wait_until="domcontentloaded", timeout=120000)
            await page.wait_for_timeout(8000)

            screenshot_path = out_dir / "target-page.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)

            dom_summary = await page.evaluate(
                """({targetAlias}) => {
                  const textOf = (node) => (node && (node.innerText || node.value || node.textContent) || '').trim();
                  const visibleText = document.body ? document.body.innerText.slice(0, 5000) : '';
                  const buttons = Array.from(document.querySelectorAll('button,input[type=button],input[type=submit],a'))
                    .map((el) => ({
                      tag: el.tagName,
                      type: el.getAttribute('type') || '',
                      text: textOf(el).slice(0, 120),
                      id: el.id || '',
                      name: el.getAttribute('name') || '',
                      className: el.className || ''
                    }))
                    .filter((item) => /上传|导入|Excel|模板|下载|提交|确定|保存/.test(item.text + item.id + item.name + item.className))
                    .slice(0, 80);
                  const fileInputs = Array.from(document.querySelectorAll('input[type=file]'))
                    .map((el) => ({
                      id: el.id || '',
                      name: el.getAttribute('name') || '',
                      accept: el.getAttribute('accept') || '',
                      disabled: Boolean(el.disabled),
                      hidden: Boolean(el.hidden) || getComputedStyle(el).display === 'none'
                    }));
                  const forms = Array.from(document.querySelectorAll('form'))
                    .map((form) => ({
                      id: form.id || '',
                      name: form.getAttribute('name') || '',
                      action: form.getAttribute('action') || '',
                      method: form.getAttribute('method') || '',
                      enctype: form.getAttribute('enctype') || '',
                      controls: Array.from(form.querySelectorAll('input,select,textarea'))
                        .map((control) => ({
                          tag: control.tagName,
                          type: control.getAttribute('type') || '',
                          name: control.getAttribute('name') || '',
                          id: control.id || '',
                          value: (control.getAttribute('type') || '').toLowerCase() === 'password'
                            ? '[redacted]'
                            : String(control.value || '').slice(0, 200)
                        }))
                    }));
                  return {
                    title: document.title,
                    url: location.href,
                    containsTargetAlias: visibleText.includes(targetAlias),
                    visibleTextSample: visibleText,
                    buttons,
                    fileInputs,
                    forms
                  };
                }""",
                {"targetAlias": str(target.get("alias") or "")},
            )
        finally:
            await browser.close()

    result = {
        "status": "ok",
        "mode": "smartbi_target_probe_no_upload",
        "boundary": {
            "smartbi_login": True,
            "page_open": True,
            "file_selected": False,
            "upload_submitted": False,
            "external_write": False,
        },
        "task": task_name,
        "target": target,
        "run_id": run_id,
        "artifacts": {
            "directory": str(out_dir),
            "screenshot": str(out_dir / "target-page.png"),
        },
        "dom": dom_summary,
        "network": network_events[-120:],
        "console": console_events[-80:],
    }
    result_path = out_dir / "target_probe.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["artifacts"]["result"] = str(result_path)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--task", required=True)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--browser-channel", default="chrome")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(
            run_probe(
                config_path=args.config.expanduser(),
                task_name=args.task,
                out_root=args.out_root.expanduser(),
                headless=not args.headed,
                browser_channel=args.browser_channel,
            )
        )
    except Exception as error:
        result = {
            "status": "error",
            "mode": "smartbi_target_probe_no_upload",
            "boundary": {
                "smartbi_login": True,
                "page_open": False,
                "file_selected": False,
                "upload_submitted": False,
                "external_write": False,
            },
            "errors": [str(error)],
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        else:
            print(f"target probe failed: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Status: {result['status']}")
        print(f"Result: {result['artifacts']['result']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
