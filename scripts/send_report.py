#!/usr/bin/env python
"""Send a pytest result summary to a Feishu/Lark group bot.

Usage:
    python -m pytest tests -q --junitxml=reports/junit.xml
    python scripts/send_report.py

Webhook comes from FEISHU_WEBHOOK (never hardcode it). Optional:
    --junit reports/junit.xml
    --report reports/report.html        (pytest-html 报告文件，默认自动取该路径)
    --bug-xlsx reports/bugs/xxx.xlsx    (缺陷表，默认自动取 bugs 目录最新 xlsx)
    --report-url https://...            (CI artifact or Pages link)
    --dry-run                           (print the message instead of sending)

注意：群自定义机器人 webhook 只能发文本/富文本，无法上传附件。这里改用
post 富文本推送，把 report.html 与缺陷 Excel 渲染成可点击的超链接：
CI 中优先用 --report-url 的 artifact 链接，本地则用 file:/// 绝对路径。
"""

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is optional
    load_dotenv = None

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if load_dotenv is not None:
    load_dotenv(ROOT / ".env")
DEFAULT_JUNIT = ROOT / "reports" / "junit.xml"
DEFAULT_REPORT = ROOT / "reports" / "report.html"
DEFAULT_BUG_DIR = ROOT / "reports" / "bugs"


def summarize(junit: Path) -> dict:
    """Return passed/failed/skipped cases and counters from a junit xml."""
    if not junit.is_file():
        raise SystemExit(f"未找到 junit 报告：{junit}，请先执行 pytest --junitxml=...")

    cases = list(ET.parse(junit).getroot().iter("testcase"))
    failed: list[str] = []
    skipped = passed = 0

    for case in cases:
        name = case.get("name", "unknown")
        classname = case.get("classname", "").split(".")[-1]
        label = f"{classname}::{name}" if classname else name
        if case.find("failure") is not None or case.find("error") is not None:
            failed.append(label)
        elif case.find("skipped") is not None:
            skipped += 1
        else:
            passed += 1

    duration = sum(float(case.get("time") or 0) for case in cases)
    executed = passed + len(failed)
    return {
        "total": len(cases),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "duration": duration,
        "effective_rate": executed / len(cases) * 100 if cases else 0.0,
        "pass_rate": passed / executed * 100 if executed else 0.0,
    }


def resolve_report(path: Path) -> Path:
    """校验 pytest-html 报告文件存在。"""
    if not path.is_file():
        raise SystemExit(
            f"未找到测试报告：{path}，请先执行 pytest --html=reports/report.html"
        )
    return path


def collect_bug_xlsx(explicit: str, bug_dir: Path) -> list[Path]:
    """返回需要推送的缺陷表：显式指定优先，否则取 bugs 目录全部 xlsx（新→旧）。"""
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"未找到缺陷表：{path}")
        return [path]
    if not bug_dir.is_dir():
        return []
    return sorted(
        bug_dir.glob("*.xlsx"), key=lambda item: item.stat().st_mtime, reverse=True
    )


def file_href(path: Path) -> str:
    """本地文件转 file:/// URI，便于在飞书消息里点击打开。"""
    return path.resolve().as_uri()


def build_blocks(
    stats: dict,
    report: Path,
    bug_files: list[Path],
    report_url: str,
    env_name: str,
    api_path: str,
) -> list[list[dict]]:
    """构造飞书 post 富文本段落，文件项为可点击的 a 标签。"""
    branch = os.getenv("GITHUB_REF_NAME", "")
    sha = os.getenv("GITHUB_SHA", "")[:7]
    blocks: list[list[dict]] = [
        [{"tag": "text", "text": f"环境：{env_name}"}],
        [{"tag": "text", "text": f"接口地址：{api_path or '未配置'}"}],
        [{"tag": "text", "text": f"分支：{branch or '-'}  提交：{sha or '-'}"}],
        [
            {
                "tag": "text",
                "text": (
                    f"结果：总计 {stats['total']} ｜ 通过 {stats['passed']} ｜ "
                    f"失败 {len(stats['failed'])} ｜ 跳过 {stats['skipped']} ｜ "
                    f"耗时 {stats['duration']:.2f}s"
                ),
            }
        ],
        [
            {
                "tag": "text",
                "text": (
                    f"有效执行率：{stats['effective_rate']:.1f}%（skip 不计入通过）"
                    f"，非跳过通过率：{stats['pass_rate']:.1f}%"
                ),
            }
        ],
    ]
    if stats["failed"]:
        blocks.append([{"tag": "text", "text": "失败用例："}])
        blocks += [
            [{"tag": "text", "text": f"{index}. {name}"}]
            for index, name in enumerate(stats["failed"][:5], 1)
        ]
        if len(stats["failed"]) > 5:
            blocks.append(
                [{"tag": "text", "text": f"... 其余 {len(stats['failed']) - 5} 条见报告"}]
            )
    blocks.append(
        [
            {"tag": "text", "text": "测试报告："},
            {"tag": "a", "text": str(report), "href": report_url or file_href(report)},
        ]
    )
    if bug_files:
        blocks.append([{"tag": "text", "text": "缺陷明细："}])
        blocks += [
            [
                {"tag": "text", "text": f"{index}. "},
                {"tag": "a", "text": str(path), "href": file_href(path)},
            ]
            for index, path in enumerate(bug_files, 1)
        ]
    else:
        blocks.append([{"tag": "text", "text": "缺陷明细：无（未生成缺陷 Excel）"}])
    blocks.append([{"tag": "text", "text": f"时间：{datetime.now():%Y-%m-%d %H:%M:%S}"}])
    return blocks


def render_text(blocks: list[list[dict]]) -> str:
    """把富文本段落转成纯文本，供 --dry-run 预览。"""
    lines = []
    for block in blocks:
        parts = [
            f"{item['text']}（{item['href']}）" if item["tag"] == "a" else item["text"]
            for item in block
        ]
        lines.append("".join(parts))
    return "\n".join(lines)


def build_payload(blocks: list[list[dict]]) -> dict:
    return {
        "msg_type": "post",
        "content": {"post": {"zh_cn": {"title": "自动化测试报告", "content": blocks}}},
    }


def send(webhook: str, payload: dict) -> None:
    try:
        response = requests.post(webhook, json=payload, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SystemExit(f"飞书消息发送失败：{exc}") from exc

    body = response.json()
    code = body.get("code", body.get("StatusCode", -1))
    if code != 0:
        raise SystemExit(f"飞书返回错误：code={code}, msg={body.get('msg', body)}")


def resolve_env_name() -> str:
    if os.getenv("TEST_ENV"):
        return os.environ["TEST_ENV"]
    try:
        from config.config_loader import get_value

        return str(get_value("env_name") or get_value("api_base_url") or "本地（未配置 api_base_url）")
    except Exception:
        return "未知环境"


def resolve_api_path() -> str:
    """接口地址只取接口路径（去掉服务地址），如 /address/validate。"""
    try:
        from config.config_loader import get_value

        return str(get_value("address_validation.path") or "")
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="发送 pytest 结果到飞书群机器人")
    parser.add_argument("--junit", default=str(DEFAULT_JUNIT), help="junit xml 路径")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="pytest-html 报告路径")
    parser.add_argument(
        "--bug-xlsx",
        default="",
        help="缺陷 Excel 路径，默认自动取 reports/bugs 下最新 xlsx",
    )
    parser.add_argument("--report-url", default=os.getenv("REPORT_URL", ""), help="报告链接")
    parser.add_argument("--webhook", default=os.getenv("FEISHU_WEBHOOK", ""), help="覆盖 FEISHU_WEBHOOK")
    parser.add_argument("--dry-run", action="store_true", help="只打印不发送")
    args = parser.parse_args()

    stats = summarize(Path(args.junit))
    report = resolve_report(Path(args.report).expanduser().resolve())
    bug_files = collect_bug_xlsx(args.bug_xlsx, DEFAULT_BUG_DIR)
    blocks = build_blocks(
        stats,
        report,
        bug_files,
        args.report_url,
        resolve_env_name(),
        resolve_api_path(),
    )

    if args.dry_run:
        print(render_text(blocks))
        return 0

    if not args.webhook:
        raise SystemExit("未设置 FEISHU_WEBHOOK，无法发送（可先用 --dry-run 预览）")

    send(args.webhook, build_payload(blocks))
    print(f"已发送飞书通知：通过 {stats['passed']} / 失败 {len(stats['failed'])} / 跳过 {stats['skipped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
