#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 pytest 执行结果导出为 Excel 测试报告，并把结果回写到用例 Excel。

替代原飞书群机器人推送：不再读取 FEISHU_WEBHOOK，不发送任何网络请求。

用法：
    python -m pytest tests -q --junitxml=reports/junit.xml
    python scripts/export_test_report.py

产物：
    1. reports/test-results_YYYYMMDD_HHMMSS.xlsx
       - 执行摘要 / 模块统计 / 用例执行明细 / 测试实例明细
       - 失败明细 / 跳过与需复核 / 未登记用例（如有） / 回写记录
    2. 用例 Excel 回写（默认原地更新，保留原样式）
       - 实际结果 / 是否通过 / 执行时间(年月日) 三列
       - 目标解析优先级：--testcase-xlsx > config.report.excel.testcase_xlsx
         > testcases/**/*.xlsx 中按 case_id 命中率 + 修改时间自动选择
       - 未提供 --testcase-xlsx 且自动匹配不到时，只生成报告，不修改任何用例文件

可选参数：
    --junit reports/junit.xml
    --html reports/report.html
    --output reports/test-results_xxx.xlsx
    --testcase-xlsx testcases/REQ-xxx/output/api_testcases_xxx.xlsx
    --requirement REQ-xxx          （限制自动发现的用例目录）
    --no-writeback                 （只出报告，不回写用例）
    --env-url / --api-path         （覆盖自动解析的环境与接口路径）
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_JUNIT = ROOT / "reports" / "junit.xml"
DEFAULT_HTML = ROOT / "reports" / "report.html"
DEFAULT_OUTPUT_DIR = ROOT / "reports"
DEFAULT_BUG_DIR = ROOT / "reports" / "bugs"
CASE_ID_RE = re.compile(r"case_id\s*:\s*([A-Za-z0-9][A-Za-z0-9_\-]*)")

# ── 用例 Excel 标准表头（按列名定位，不依赖列序号） ──
H_CASE_ID = "用例编号"
H_TITLE = "用例标题"
H_AC = "关联原子能力"
H_PRIORITY = "用例优先级"
H_REQUIREMENT = "关联需求ID"
H_ACTUAL = "实际结果"
H_PASSED = "是否通过"
H_EXEC_TIME = "执行时间(年月日)"

OUTCOME_LABELS = {
    "PASS": "通过",
    "FAIL": "失败",
    "SKIP": "跳过",
    "XFAIL": "已知缺陷(XFAIL)",
    "XPASS": "XPASS（需复核）",
}

# ── 样式 ──
FONT_NAME = "微软雅黑"
HEADER_FONT = Font(name=FONT_NAME, size=11, bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="2E75B6")
SECTION_FONT = Font(name=FONT_NAME, size=11, bold=True, color="1F4E78")
SECTION_FILL = PatternFill("solid", fgColor="D9E1F2")
BODY_FONT = Font(name=FONT_NAME, size=10)
TITLE_FONT = Font(name=FONT_NAME, size=16, bold=True, color="1F4E78")
NOTE_FONT = Font(name=FONT_NAME, size=9, color="808080")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top", horizontal="left")
CENTER = Alignment(wrap_text=True, vertical="center", horizontal="center")

RESULT_FILLS = {
    "PASS": PatternFill("solid", fgColor="C6EFCE"),
    "FAIL": PatternFill("solid", fgColor="FFC7CE"),
    "SKIP": PatternFill("solid", fgColor="FFF2CC"),
    "XFAIL": PatternFill("solid", fgColor="FCE4D6"),
    "XPASS": PatternFill("solid", fgColor="DDEBF7"),
}


# ══════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════

@dataclass
class TestDefinition:
    scope: str
    function: str
    case_id: str
    xfail: bool
    source: Path


@dataclass
class InstanceResult:
    classname: str
    name: str
    base_name: str
    case_id: str
    outcome: str
    duration: float
    message: str = ""
    detail: str = ""
    source: str = ""

    @property
    def label(self) -> str:
        return f"{self.classname}::{self.name}" if self.classname else self.name


@dataclass
class CaseResult:
    case_id: str
    outcome: str
    instances: list[InstanceResult] = field(default_factory=list)
    title: str = ""
    ac: str = ""
    priority: str = ""
    requirement: str = ""

    @property
    def counts(self) -> Counter:
        return Counter(instance.outcome for instance in self.instances)

    @property
    def duration(self) -> float:
        return sum(instance.duration for instance in self.instances)


@dataclass
class CaseMeta:
    title: str = ""
    ac: str = ""
    priority: str = ""
    requirement: str = ""


@dataclass
class WritebackInfo:
    target: str = ""
    sheet: str = ""
    updated: int = 0
    missing: list[str] = field(default_factory=list)
    unexecuted: int = 0
    fallback: str = ""
    error: str = ""


# ══════════════════════════════════════════════════════════════
# 基础工具
# ══════════════════════════════════════════════════════════════

def clean_cell(value: Any, limit: int = 32000) -> str:
    """去掉 Excel 不支持的控制字符，并限制单元格长度。"""
    if value is None:
        return ""
    text = str(value)
    text = "".join(
        ch for ch in text
        if ch in ("\n", "\t") or ord(ch) >= 32
    )
    return text[:limit]


def one_line(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def config_value(path: str, default: Any = None) -> Any:
    """读取 config/*.yaml；配置层异常时回退默认值，报告生成不因此中断。"""
    try:
        from config.config_loader import get_value

        return get_value(path, default)
    except Exception:
        return default


def git_info() -> tuple[str, str]:
    def run(args: list[str]) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
            )
        except Exception:
            return ""
        return result.stdout.strip() if result.returncode == 0 else ""

    branch = os.getenv("GITHUB_REF_NAME") or run(["branch", "--show-current"])
    sha = os.getenv("GITHUB_SHA", "")[:7] or run(["rev-parse", "--short", "HEAD"])
    return branch or "-", sha or "-"


def parse_timestamp(value: str | None) -> datetime:
    if value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now()


# ══════════════════════════════════════════════════════════════
# 脚本 case_id 索引
# ══════════════════════════════════════════════════════════════

def scan_test_definitions(tests_dir: Path) -> dict[tuple[str, str], TestDefinition]:
    """扫描 tests/**/*.py，建立 (测试类, 函数名) → case_id / xfail 索引。

    case_id 取自函数体内的 `# case_id: XXX` 注释；参数化实例共享同一 case_id。
    """
    defs: dict[tuple[str, str], TestDefinition] = {}
    if not tests_dir.is_dir():
        return defs

    for path in sorted(tests_dir.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue

        lines = source.splitlines()
        module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        module_xfail = False
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                try:
                    text = ast.unparse(node)
                except Exception:
                    continue
                if "pytestmark" in text and "xfail" in text:
                    module_xfail = True

        def walk(body: Iterable[ast.stmt], prefix: str = "") -> None:
            for node in body:
                if isinstance(node, ast.ClassDef):
                    walk(node.body, prefix + node.name + ".")
                    continue
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not node.name.startswith("test_"):
                    continue

                scope = f"{module}.{prefix[:-1]}" if prefix else module
                end = node.end_lineno or node.lineno
                segment = "\n".join(lines[node.lineno - 1:end])
                match = CASE_ID_RE.search(segment)
                case_id = match.group(1) if match else ""

                try:
                    xfail = module_xfail or any(
                        "xfail" in ast.unparse(decorator)
                        for decorator in node.decorator_list
                    )
                except Exception:
                    xfail = module_xfail

                defs[(scope, node.name)] = TestDefinition(
                    scope=scope,
                    function=node.name,
                    case_id=case_id,
                    xfail=xfail,
                    source=path,
                )

        walk(tree.body)

    return defs


def lookup_definition(
    classname: str,
    base_name: str,
    defs: dict[tuple[str, str], TestDefinition],
) -> TestDefinition | None:
    definition = defs.get((classname, base_name))
    if definition is not None:
        return definition

    # 类路径可能多/少一层（如 classname=tests.api.test_x.Class）
    for (scope, function), candidate in defs.items():
        if function == base_name and classname.endswith(scope):
            return candidate

    # 全仓库同名函数唯一时兜底
    same_name = [item for (_, function), item in defs.items() if function == base_name]
    return same_name[0] if len(same_name) == 1 else None


# ══════════════════════════════════════════════════════════════
# JUnit 解析与聚合
# ══════════════════════════════════════════════════════════════

def parse_junit(
    junit: Path,
    defs: dict[tuple[str, str], TestDefinition],
) -> tuple[list[InstanceResult], datetime, str]:
    """返回 (测试实例列表, 执行时间, junit 根节点名称)。"""
    if not junit.is_file():
        raise SystemExit(f"未找到 junit 报告：{junit}，请先执行 pytest --junitxml=...")

    try:
        root = ET.parse(junit).getroot()
    except ET.ParseError as exc:
        raise SystemExit(f"junit 报告解析失败：{junit}（{exc}）") from exc

    suite = root.find("testsuite")
    timestamp_attr = suite.get("timestamp") if suite is not None else None
    executed_at = parse_timestamp(timestamp_attr)
    root_name = root.get("name") or (suite.get("name") if suite is not None else "") or "pytest"

    instances: list[InstanceResult] = []
    for case in root.iter("testcase"):
        classname = case.get("classname") or ""
        name = case.get("name") or "unknown"
        base_name = name.split("[")[0]
        if "::" in base_name:
            base_name = base_name.split("::")[-1]

        definition = lookup_definition(classname, base_name, defs)
        case_id = definition.case_id if definition else ""

        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")

        message = ""
        detail = ""
        if failure is not None or error is not None:
            element = failure if failure is not None else error
            outcome = "FAIL"
            message = element.get("message") or ""
            detail = element.text or ""
        elif skipped is not None:
            skip_type = skipped.get("type") or ""
            outcome = "XFAIL" if skip_type == "pytest.xfail" else "SKIP"
            message = skipped.get("message") or ""
            detail = skipped.text or ""
        elif definition is not None and definition.xfail:
            outcome = "XPASS"
        else:
            outcome = "PASS"

        try:
            duration = float(case.get("time") or 0)
        except ValueError:
            duration = 0.0

        instances.append(
            InstanceResult(
                classname=classname,
                name=name,
                base_name=base_name,
                case_id=case_id,
                outcome=outcome,
                duration=duration,
                message=message,
                detail=detail,
                source=rel(definition.source) if definition else "",
            )
        )

    return instances, executed_at, root_name


def summarize_case_outcome(instances: list[InstanceResult]) -> str:
    counts = Counter(instance.outcome for instance in instances)
    if counts["FAIL"]:
        return "FAIL"
    if counts["XPASS"]:
        return "XPASS"
    if counts["XFAIL"]:
        return "XFAIL"
    if counts["PASS"] == 0 and counts["SKIP"]:
        return "SKIP"
    return "PASS"


def aggregate_cases(
    instances: list[InstanceResult],
) -> tuple[dict[str, CaseResult], list[InstanceResult]]:
    cases: dict[str, CaseResult] = {}
    unregistered: list[InstanceResult] = []

    for instance in instances:
        if not instance.case_id:
            unregistered.append(instance)
            continue
        case = cases.get(instance.case_id)
        if case is None:
            case = CaseResult(case_id=instance.case_id, outcome="")
            cases[instance.case_id] = case
        case.instances.append(instance)

    for case in cases.values():
        case.outcome = summarize_case_outcome(case.instances)

    return cases, unregistered


def case_sort_key(case_id: str) -> tuple[str, int, str]:
    match = re.match(r"^([A-Za-z][A-Za-z0-9_\-]*?)(\d+)$", case_id)
    if match:
        return match.group(1), int(match.group(2)), case_id
    return case_id, 0, case_id


# ══════════════════════════════════════════════════════════════
# 用例 Excel：定位、元数据、回写
# ══════════════════════════════════════════════════════════════

def header_map(ws, header_row: int = 1) -> dict[str, int]:
    """按表头文本定位列号；read_only 与普通工作表都适用。"""
    headers: dict[str, int] = {}
    for row in ws.iter_rows(min_row=header_row, max_row=header_row, values_only=True):
        for index, value in enumerate(row, start=1):
            if value is not None:
                headers[str(value).strip()] = index
        break
    return headers


def find_case_sheet(wb) -> tuple[Any, int, dict[str, int]] | tuple[None, None, None]:
    """找到同时包含「用例编号」与「是否通过」的工作表。"""
    for ws in wb.worksheets:
        for header_row in range(1, 6):
            headers = header_map(ws, header_row)
            if H_CASE_ID in headers and H_PASSED in headers:
                return ws, header_row, headers
    return None, None, None


def read_case_index(
    ws,
    header_row: int,
    headers: dict[str, int],
) -> tuple[dict[str, int], dict[str, CaseMeta]]:
    case_column = headers[H_CASE_ID]
    rows: dict[str, int] = {}
    metas: dict[str, CaseMeta] = {}

    for row in range(header_row + 1, ws.max_row + 1):
        value = ws.cell(row=row, column=case_column).value
        case_id = str(value).strip() if value is not None else ""
        if not case_id:
            continue
        rows[case_id] = row
        metas[case_id] = CaseMeta(
            title=clean_cell(ws.cell(row=row, column=headers[H_TITLE]).value)
            if H_TITLE in headers else "",
            ac=clean_cell(ws.cell(row=row, column=headers[H_AC]).value)
            if H_AC in headers else "",
            priority=clean_cell(ws.cell(row=row, column=headers[H_PRIORITY]).value)
            if H_PRIORITY in headers else "",
            requirement=clean_cell(ws.cell(row=row, column=headers[H_REQUIREMENT]).value)
            if H_REQUIREMENT in headers else "",
        )

    return rows, metas


def load_case_workbook(
    path: Path,
) -> tuple[Any, Any, int, dict[str, int], dict[str, int], dict[str, CaseMeta]] | None:
    try:
        wb = load_workbook(path)
    except Exception as exc:
        print(f"[警告] 用例 Excel 打开失败，跳过回写：{path}（{exc}）")
        return None

    ws, header_row, headers = find_case_sheet(wb)
    if ws is None:
        wb.close()
        print(f"[警告] 未在用例 Excel 中找到「{H_CASE_ID} / {H_PASSED}」表头，跳过回写：{path}")
        return None

    rows, metas = read_case_index(ws, header_row, headers)
    return wb, ws, header_row, headers, rows, metas


def discover_case_workbook(case_ids: set[str], requirement: str = "") -> Path | None:
    """在 testcases/ 下按 case_id 命中数 + 文件修改时间选择用例表。"""
    if not case_ids:
        return None

    testcases_dir = ROOT / "testcases"
    if not testcases_dir.is_dir():
        return None

    scored: list[tuple[int, float, Path]] = []
    for path in sorted(testcases_dir.rglob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        if requirement and requirement.lower() not in str(path).lower():
            continue

        try:
            wb = load_workbook(path, read_only=True, data_only=True)
        except Exception:
            continue

        try:
            ws, header_row, headers = find_case_sheet(wb)
            if ws is None:
                continue
            case_column = headers[H_CASE_ID]
            found_ids: set[str] = set()
            for row in ws.iter_rows(
                min_row=header_row + 1,
                max_col=case_column,
                values_only=True,
            ):
                if len(row) < case_column:
                    continue
                value = row[case_column - 1]
                if value is not None and str(value).strip():
                    found_ids.add(str(value).strip())
            score = len(found_ids & case_ids)
            if score >= max(1, (len(case_ids) + 1) // 2):
                scored.append((score, path.stat().st_mtime, path))
        finally:
            wb.close()

    if not scored:
        return None
    return max(scored, key=lambda item: (item[0], item[1]))[2]


def resolve_case_workbook(
    explicit: str,
    case_ids: set[str],
    requirement: str,
) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            raise SystemExit(f"未找到用例 Excel：{path}")
        return path

    configured = str(config_value("report.excel.testcase_xlsx", "") or "")
    if configured:
        path = ROOT / configured
        if path.is_file():
            return path
        print(f"[警告] config.report.excel.testcase_xlsx 指向的文件不存在：{path}")

    return discover_case_workbook(case_ids, requirement)


def actual_result_text(case: CaseResult, report_name: str) -> str:
    counts = case.counts
    total = len(case.instances)
    duration = case.duration

    if case.outcome == "PASS":
        text = f"PASS｜{counts['PASS']}/{total} 个实例通过"
        if counts["SKIP"]:
            text += f"，{counts['SKIP']} 个实例跳过（未验证）"
    elif case.outcome == "FAIL":
        failures = [
            one_line(item.message or item.detail)
            for item in case.instances
            if item.outcome == "FAIL" and (item.message or item.detail)
        ]
        summary = "；".join(failures)[:400] or "断言失败"
        text = f"FAIL｜失败 {counts['FAIL']}/{total}｜{summary}"
    elif case.outcome == "XPASS":
        text = (
            f"XPASS｜{counts['XPASS']}/{total} 个实例预期失败但实际通过，"
            f"需复核对应 xfail 标记是否已失效"
        )
        if counts["XFAIL"]:
            text += f"；另有 {counts['XFAIL']} 个实例仍为 XFAIL"
        if counts["SKIP"]:
            text += f"；{counts['SKIP']} 个实例跳过（未验证）"
    elif case.outcome == "XFAIL":
        reasons = [
            one_line(item.message)
            for item in case.instances
            if item.outcome == "XFAIL" and item.message
        ]
        summary = "；".join(dict.fromkeys(reasons))[:400] or "已登记缺陷按预期失败"
        text = f"XFAIL（已知缺陷，不计为通过）｜{counts['XFAIL']}/{total} 个实例｜{summary}"
        if counts["SKIP"]:
            text += f"；{counts['SKIP']} 个实例跳过（未验证）"
    else:  # SKIP
        reasons = [
            one_line(item.message)
            for item in case.instances
            if item.outcome == "SKIP" and item.message
        ]
        summary = "；".join(dict.fromkeys(reasons))[:400] or "未说明跳过原因"
        text = f"SKIP（未验证，不计为通过）｜{counts['SKIP']}/{total} 个实例｜{summary}"

    return clean_cell(f"{text}｜耗时 {duration:.2f}s｜详见 {report_name}")


def passed_flag(case: CaseResult) -> str:
    return {
        "PASS": "是",
        "FAIL": "否",
        "XPASS": "是（XPASS，需复核）",
        "XFAIL": "否（已知缺陷）",
        "SKIP": "跳过（未验证）",
    }[case.outcome]


def write_back_results(
    wb,
    ws,
    header_row: int,
    headers: dict[str, int],
    rows: dict[str, int],
    cases: dict[str, CaseResult],
    executed_at: datetime,
    report_name: str,
) -> WritebackInfo:
    """把用例级结果写回「实际结果 / 是否通过 / 执行时间」三列，保留原样式。"""
    info = WritebackInfo(
        target="",
        sheet=ws.title,
        unexecuted=max(len(rows) - len(set(rows) & set(cases)), 0),
    )

    actual_column = headers.get(H_ACTUAL)
    passed_column = headers.get(H_PASSED)
    time_column = headers.get(H_EXEC_TIME)

    if passed_column is None:
        info.error = f"用例表缺少「{H_PASSED}」列，无法回写"
        return info

    time_text = executed_at.strftime("%Y-%m-%d %H:%M:%S")
    for case_id, case in cases.items():
        row = rows.get(case_id)
        if row is None:
            info.missing.append(case_id)
            continue

        if actual_column is not None:
            cell = ws.cell(row=row, column=actual_column)
            cell.value = actual_result_text(case, report_name)
            cell.alignment = WRAP

        cell = ws.cell(row=row, column=passed_column)
        cell.value = passed_flag(case)
        cell.alignment = CENTER

        if time_column is not None:
            cell = ws.cell(row=row, column=time_column)
            cell.value = time_text
            cell.alignment = CENTER

        info.updated += 1

    return info


def save_workbook(wb, path: Path, info: WritebackInfo) -> None:
    """原地保存；文件被 Excel 占用时写入副本，避免丢失本次结果。"""
    try:
        wb.save(path)
        info.target = rel(path)
    except PermissionError:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback = path.with_name(f"{path.stem}-executed-{stamp}{path.suffix}")
        try:
            wb.save(fallback)
        except Exception as exc:
            info.error = f"目标文件被占用，副本保存也失败：{exc}"
            return
        info.target = rel(path)
        info.fallback = rel(fallback)
        info.error = "目标文件被占用，结果已写入副本"
    except Exception as exc:
        info.error = f"保存失败：{exc}"


# ══════════════════════════════════════════════════════════════
# 统计与环境解析
# ══════════════════════════════════════════════════════════════

def instance_stats(instances: list[InstanceResult]) -> dict[str, Any]:
    counts = Counter(instance.outcome for instance in instances)
    display_passed = counts["PASS"] + counts["XPASS"]
    executed = display_passed + counts["FAIL"]
    total = len(instances)
    return {
        "total": total,
        "pass": counts["PASS"],
        "fail": counts["FAIL"],
        "skip": counts["SKIP"],
        "xfail": counts["XFAIL"],
        "xpass": counts["XPASS"],
        "display_passed": display_passed,
        "executed": executed,
        "effective_rate": executed / total * 100 if total else 0.0,
        "pass_rate": display_passed / executed * 100 if executed else 0.0,
        "duration": sum(instance.duration for instance in instances),
    }


def case_stats(cases: dict[str, CaseResult]) -> dict[str, Any]:
    counts = Counter(case.outcome for case in cases.values())
    total = len(cases)
    executed = counts["PASS"] + counts["XPASS"] + counts["FAIL"]
    return {
        "total": total,
        "pass": counts["PASS"],
        "fail": counts["FAIL"],
        "skip": counts["SKIP"],
        "xfail": counts["XFAIL"],
        "xpass": counts["XPASS"],
        "executed": executed,
        "effective_rate": executed / total * 100 if total else 0.0,
        "pass_rate": (counts["PASS"] + counts["XPASS"]) / executed * 100
        if executed else 0.0,
    }


def suite_meta(classname: str) -> tuple[str, str]:
    registry = config_value("report.suites", {}) or {}
    if isinstance(registry, dict):
        for key, meta in registry.items():
            if key in classname and isinstance(meta, dict):
                return str(meta.get("module") or ""), str(meta.get("feature") or "")
    return "", ""


def resolve_target(
    classnames: list[str],
    api_path: str = "",
    env_url: str = "",
) -> tuple[str, str, str, str]:
    """返回 (环境 URL, 接口路径, 模块, 功能)。优先显式参数，其次按类名匹配配置。"""
    module = feature = ""
    for classname in classnames:
        module, feature = suite_meta(classname)
        if module:
            break

    try:
        from config.config_loader import get_module_config, get_service_url, get_value

        is_ui_only = bool(classnames) and all(
            name.startswith("tests.ui") or ".ui." in f".{name}."
            for name in classnames
        )
        if is_ui_only:
            url = env_url or str(get_value("ui_base_url", "") or "")
            return url, api_path or "", module, feature

        if module:
            cfg = get_module_config(module, feature or None)
            path = api_path or str(cfg.get("path") or "")
            url = env_url or get_service_url(module, cfg) or ""
            return url, path, module, feature

        path = api_path or ""
        url = env_url or str(get_value("api_base_url", "") or "")
        return url, path, module, feature
    except Exception:
        return env_url, api_path, module, feature


def conclusion_text(inst: dict[str, Any]) -> str:
    if inst["fail"]:
        return f"不通过（{inst['fail']} 个测试实例失败）"
    if inst["executed"] == 0:
        return "未执行/阻断（全部跳过，不能视为通过）"
    return "通过"


def risk_text(cases: dict[str, CaseResult], inst: dict[str, Any]) -> str:
    items: list[str] = []
    if inst["xfail"]:
        items.append(f"{inst['xfail']} 个已知缺陷实例（XFAIL）不计为通过，需跟踪缺陷")
    if inst["skip"]:
        items.append(f"{inst['skip']} 个跳过实例未验证，需补齐夹具/数据后补测")
    if inst["xpass"]:
        items.append(f"{inst['xpass']} 个 XPASS 实例需复核 xfail 标记是否应移除")
    if not items:
        return "无"
    return "；".join(items)


def next_step_text(inst: dict[str, Any]) -> str:
    if inst["fail"]:
        return "提缺陷 / 修复后回归"
    if inst["xfail"] or inst["skip"]:
        return "修复已知缺陷、补齐夹具后回归；当前结论以已通过范围为准"
    if inst["xpass"]:
        return "复核 XPASS 用例并收紧 xfail 标记后可发布"
    return "可发布（以用例覆盖范围为准）"


def failure_summary(case: CaseResult) -> str:
    messages = [
        one_line(item.message or item.detail)
        for item in case.instances
        if item.outcome == "FAIL" and (item.message or item.detail)
    ]
    return "；".join(messages)[:600] or "断言失败（详见失败明细）"


def skip_summary(case: CaseResult, outcome: str) -> str:
    messages = [
        one_line(item.message)
        for item in case.instances
        if item.outcome == outcome and item.message
    ]
    return "；".join(dict.fromkeys(messages))[:600] or "-"


def case_note(case: CaseResult) -> str:
    """用例明细中的一句话备注：失败/跳过原因，PASS 但部分实例跳过也要提示。"""
    if case.outcome == "FAIL":
        return failure_summary(case)
    if case.outcome == "XFAIL":
        return skip_summary(case, "XFAIL")
    if case.outcome == "XPASS":
        return "预期失败但通过，需复核 xfail 标记"
    if case.outcome == "SKIP":
        return skip_summary(case, "SKIP")
    if case.counts["SKIP"]:
        return f"{case.counts['SKIP']} 个实例跳过（未验证）"
    return ""


def evidence_text(case: CaseResult, junit_name: str, html_name: str) -> str:
    target = ""
    for instance in case.instances:
        if instance.outcome in ("FAIL", "SKIP", "XFAIL", "XPASS"):
            target = instance.name
            break
    if not target and case.instances:
        target = case.instances[0].name
    parts = [f"{junit_name}#{target}" if target else junit_name]
    if html_name:
        parts.append(html_name)
    return "；".join(parts)


# ══════════════════════════════════════════════════════════════
# Excel 输出
# ══════════════════════════════════════════════════════════════

def set_widths(ws, widths: dict[int, float]) -> None:
    for column, width in widths.items():
        ws.column_dimensions[get_column_letter(column)].width = width


def section(ws, row: int, title: str, ncols: int) -> int:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    cell = ws.cell(row=row, column=1, value=title)
    cell.font = SECTION_FONT
    cell.fill = SECTION_FILL
    cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[row].height = 22
    return row + 1


def kv_table(ws, top_row: int, rows: list[tuple[str, str]], ncols: int = 2) -> int:
    for offset, (key, value) in enumerate(rows):
        row = top_row + offset
        left = ws.cell(row=row, column=1, value=clean_cell(key))
        right = ws.cell(row=row, column=2, value=clean_cell(value))
        left.font = Font(name=FONT_NAME, size=10, bold=True, color="1F4E78")
        left.alignment = WRAP
        left.fill = PatternFill("solid", fgColor="F2F7FC")
        right.font = BODY_FONT
        right.alignment = WRAP
        for col in range(1, ncols + 1):
            ws.cell(row=row, column=col).border = BORDER
        if ncols > 2:
            ws.merge_cells(
                start_row=row,
                start_column=2,
                end_row=row,
                end_column=ncols,
            )
    return top_row + len(rows)


def result_table(
    ws,
    top_row: int,
    headers: list[str],
    rows: list[Iterable[Any]],
    widths: dict[int, float] | None = None,
    result_column: int | None = None,
    wrap_columns: Iterable[int] = (),
) -> int:
    """写一张带表头、样式、筛选与冻结的表。"""
    for column, title in enumerate(headers, start=1):
        cell = ws.cell(row=top_row, column=column, value=title)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
        cell.border = BORDER
    ws.row_dimensions[top_row].height = 26

    wrap_set = set(wrap_columns)
    next_row = top_row + 1
    for values in rows:
        for column, value in enumerate(values, start=1):
            cell = ws.cell(row=next_row, column=column)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cell.value = value
            else:
                cell.value = clean_cell(value)
            cell.font = BODY_FONT
            cell.border = BORDER
            cell.alignment = WRAP if column in wrap_set else Alignment(
                wrap_text=True, vertical="top", horizontal="center"
            )
        if result_column is not None:
            result_cell = ws.cell(row=next_row, column=result_column)
            fill = RESULT_FILLS.get(str(result_cell.value).strip())
            if fill is not None:
                result_cell.fill = fill
        next_row += 1

    last_row = max(next_row - 1, top_row)
    last_column = get_column_letter(len(headers))
    ws.auto_filter.ref = f"A{top_row}:{last_column}{last_row}"
    ws.freeze_panes = f"A{top_row + 1}"

    if widths:
        set_widths(ws, widths)
    return next_row


def build_report_workbook(
    *,
    junit: Path,
    html: Path,
    output: Path,
    root_name: str,
    executed_at: datetime,
    instances: list[InstanceResult],
    cases: dict[str, CaseResult],
    unregistered: list[InstanceResult],
    environment: str,
    api_url: str,
    api_path: str,
    module: str,
    feature: str,
    case_workbook: Path | None,
    writeback: WritebackInfo,
    bug_files: list[Path],
) -> Workbook:
    inst = instance_stats(instances)
    cst = case_stats(cases)
    branch, sha = git_info()
    execution_mode = "CI" if (os.getenv("CI") or os.getenv("GITHUB_ACTIONS")) else "本地"
    junit_rel = rel(junit)
    html_rel = rel(html) if html.is_file() else ""
    report_rel = rel(output)
    case_rel = rel(case_workbook) if case_workbook else "未匹配到用例 Excel"
    requirement = Counter(
        case.requirement for case in cases.values() if case.requirement
    ).most_common(1)
    requirement_id = requirement[0][0] if requirement else "-"

    wb = Workbook()
    ws = wb.active
    ws.title = "执行摘要"
    ws.sheet_view.showGridLines = False
    set_widths(ws, {1: 25, 2: 125})

    ws.merge_cells("A1:B1")
    title = f"{requirement_id} 自动化测试执行报告" if requirement_id != "-" else "自动化测试执行报告"
    title_cell = ws["A1"]
    title_cell.value = title
    title_cell.font = TITLE_FONT
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    ws.merge_cells("A2:B2")
    ws["A2"].value = f"生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}"
    ws["A2"].font = NOTE_FONT
    ws["A2"].alignment = Alignment(horizontal="right")

    row = 4
    row = section(ws, row, "一、执行信息", 2)
    row = kv_table(ws, row, [
        ("需求号", requirement_id),
        ("执行时间", f"{executed_at:%Y-%m-%d %H:%M:%S}"),
        ("运行环境", environment),
        ("接口地址", f"{api_url or '未配置'}  {api_path or ''}".strip()),
        ("模块 / 功能", f"{module or '-'} / {feature or '-'}"),
        ("代码版本", f"分支 {branch} ｜ 提交 {sha}"),
        ("执行方式", execution_mode),
        ("执行范围", f"{root_name}（{junit_rel}）"),
    ])
    row += 1

    row = section(ws, row, "二、结果统计", 2)
    row = kv_table(ws, row, [
        (
            "测试实例",
            f"总计 {inst['total']} ｜ PASS {inst['pass']} ｜ XPASS {inst['xpass']} ｜ "
            f"FAIL {inst['fail']} ｜ SKIP {inst['skip']} ｜ XFAIL {inst['xfail']} ｜ "
            f"耗时 {inst['duration']:.2f}s",
        ),
        (
            "测试用例",
            f"总计 {cst['total']} ｜ 通过 {cst['pass']} ｜ 失败 {cst['fail']} ｜ "
            f"跳过 {cst['skip']} ｜ 已知缺陷 {cst['xfail']} ｜ XPASS {cst['xpass']}",
        ),
        (
            "未登记用例",
            f"{len(unregistered)} 个测试实例未关联 case_id，详见「未登记用例」"
            if unregistered else "无",
        ),
        ("有效执行率", f"{inst['effective_rate']:.1f}%（skip / xfail 不计入执行）"),
        (
            "非跳过通过率",
            f"{inst['pass_rate']:.1f}%（(PASS+XPASS) / (PASS+XPASS+FAIL)）",
        ),
    ])
    row += 1

    row = section(ws, row, "三、结论", 2)
    row = kv_table(ws, row, [
        ("结论", conclusion_text(inst)),
        ("风险提示", risk_text(cases, inst)),
        ("下一步", next_step_text(inst)),
    ])
    row += 1

    row = section(ws, row, "四、产物与回写", 2)
    writeback_text = "未执行回写"
    if writeback.fallback:
        writeback_text = f"{writeback.fallback}（副本，更新 {writeback.updated} 行）"
    elif writeback.target:
        writeback_text = f"{writeback.target}（更新 {writeback.updated} 行）"
    if writeback.missing:
        writeback_text += f"｜未匹配 {len(writeback.missing)} 条：{', '.join(writeback.missing[:10])}"
        if len(writeback.missing) > 10:
            writeback_text += " ..."
    if writeback.error:
        writeback_text += f"｜{writeback.error}"

    bug_text = "无（未生成缺陷 Excel）"
    if bug_files:
        bug_text = "、".join(rel(path) for path in bug_files)

    row = kv_table(ws, row, [
        ("Excel 测试报告", report_rel),
        ("JUnit 原始结果", junit_rel),
        ("HTML 报告", html_rel or "缺失（未生成 pytest-html）"),
        ("用例 Excel", case_rel),
        ("结果回写", writeback_text),
        ("缺陷明细", bug_text),
        ("说明", "XFAIL/SKIP 不计为通过；XPASS 单独标注并需复核；用例详情见「用例执行明细」"),
    ])

    # ── 模块统计 ──
    ws = wb.create_sheet("模块统计")
    ws.sheet_view.showGridLines = False
    groups: dict[str, list[InstanceResult]] = {}
    for instance in instances:
        groups.setdefault(instance.classname or "unknown", []).append(instance)

    rows: list[list[Any]] = []
    for classname, group in groups.items():
        group_stats = instance_stats(group)
        mod, feat = suite_meta(classname)
        rows.append([
            classname,
            mod or "-",
            feat or "-",
            group_stats["total"],
            group_stats["pass"],
            group_stats["fail"],
            group_stats["skip"],
            group_stats["xfail"],
            group_stats["xpass"],
            round(group_stats["duration"], 2),
            round(group_stats["pass_rate"], 1),
        ])
    result_table(
        ws,
        1,
        ["测试类", "模块", "功能", "实例数", "PASS", "FAIL", "SKIP",
         "XFAIL", "XPASS", "耗时(s)", "非跳过通过率(%)"],
        rows,
        widths={1: 55, 2: 16, 3: 18, 4: 9, 5: 9, 6: 9, 7: 9, 8: 9, 9: 9, 10: 11, 11: 16},
    )

    # ── 用例执行明细 ──
    ws = wb.create_sheet("用例执行明细")
    ws.sheet_view.showGridLines = False
    ws.merge_cells("A1:N1")
    ws["A1"].value = (
        f"用例明细（按 case_id 聚合参数化实例）：共 {cst['total']} 条 ｜ "
        f"通过 {cst['pass']} ｜ 失败 {cst['fail']} ｜ 跳过 {cst['skip']} ｜ "
        f"已知缺陷 {cst['xfail']} ｜ XPASS {cst['xpass']}"
    )
    ws["A1"].font = SECTION_FONT
    ws["A1"].fill = SECTION_FILL
    ws["A1"].alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 22

    detail_rows: list[list[Any]] = []
    for case_id in sorted(cases, key=case_sort_key):
        case = cases[case_id]
        counts = case.counts
        detail_rows.append([
            case_id,
            case.title,
            case.ac,
            case.priority,
            case.outcome,
            len(case.instances),
            counts["PASS"],
            counts["FAIL"],
            counts["SKIP"],
            counts["XFAIL"],
            counts["XPASS"],
            round(case.duration, 2),
            case_note(case),
            evidence_text(case, junit_rel, html_rel),
        ])
    result_table(
        ws,
        2,
        ["用例编号", "用例标题", "关联AC", "优先级", "执行结果", "实例数",
         "PASS", "FAIL", "SKIP", "XFAIL", "XPASS", "耗时(s)",
         "失败/跳过摘要", "证据"],
        detail_rows,
        widths={1: 14, 2: 45, 3: 18, 4: 8, 5: 12, 6: 8, 7: 8, 8: 8, 9: 8, 10: 9,
                11: 9, 12: 10, 13: 55, 14: 40},
        result_column=5,
        wrap_columns=(2, 3, 13, 14),
    )

    # ── 测试实例明细 ──
    ws = wb.create_sheet("测试实例明细")
    ws.sheet_view.showGridLines = False
    instance_rows = [
        [
            instance.classname,
            instance.name,
            instance.case_id or "未登记",
            instance.outcome,
            round(instance.duration, 3),
            one_line(instance.message or instance.detail, 800),
        ]
        for instance in instances
    ]
    result_table(
        ws,
        1,
        ["测试类", "测试实例", "用例编号", "执行结果", "耗时(s)", "失败/跳过信息"],
        instance_rows,
        widths={1: 45, 2: 45, 3: 14, 4: 12, 5: 10, 6: 80},
        result_column=4,
        wrap_columns=(1, 2, 6),
    )

    # ── 失败明细 ──
    ws = wb.create_sheet("失败明细")
    ws.sheet_view.showGridLines = False
    failure_rows: list[list[Any]] = []
    for case_id in sorted(cases, key=case_sort_key):
        case = cases[case_id]
        for instance in case.instances:
            if instance.outcome != "FAIL":
                continue
            failure_rows.append([
                case_id,
                instance.name,
                round(instance.duration, 3),
                clean_cell(instance.message),
                clean_cell(instance.detail),
                f"{junit_rel}#{instance.name}",
            ])
    for instance in unregistered:
        if instance.outcome != "FAIL":
            continue
        failure_rows.append([
            "未登记",
            instance.name,
            round(instance.duration, 3),
            clean_cell(instance.message),
            clean_cell(instance.detail),
            f"{junit_rel}#{instance.name}",
        ])
    if not failure_rows:
        failure_rows = [["-", "无失败", "-", "本轮无 FAIL 实例", "", junit_rel]]
    result_table(
        ws,
        1,
        ["用例编号", "测试实例", "耗时(s)", "错误信息", "堆栈", "证据"],
        failure_rows,
        widths={1: 14, 2: 45, 3: 10, 4: 60, 5: 80, 6: 40},
        wrap_columns=(2, 4, 5, 6),
    )

    # ── 跳过与需复核 ──
    ws = wb.create_sheet("跳过与需复核")
    ws.sheet_view.showGridLines = False
    pending_rows: list[list[Any]] = []
    for case_id in sorted(cases, key=case_sort_key):
        case = cases[case_id]
        for instance in case.instances:
            if instance.outcome not in ("SKIP", "XFAIL", "XPASS"):
                continue
            if instance.outcome == "XFAIL":
                impact = "已登记缺陷（不计为通过）"
            elif instance.outcome == "XPASS":
                impact = "预期失败但通过，需复核 xfail 标记"
            else:
                impact = "未验证（不计为通过）"
            pending_rows.append([
                case_id,
                instance.name,
                instance.outcome,
                one_line(instance.message, 600) or "-",
                impact,
            ])
    for instance in unregistered:
        if instance.outcome not in ("SKIP", "XFAIL", "XPASS"):
            continue
        if instance.outcome == "XFAIL":
            impact = "已登记缺陷（不计为通过）"
        elif instance.outcome == "XPASS":
            impact = "预期失败但通过，需复核 xfail 标记"
        else:
            impact = "未验证（不计为通过）"
        pending_rows.append([
            "未登记",
            instance.name,
            instance.outcome,
            one_line(instance.message, 600) or "-",
            impact,
        ])
    if not pending_rows:
        pending_rows = [["-", "无", "-", "本轮无 SKIP/XFAIL/XPASS 实例", "-"]]
    result_table(
        ws,
        1,
        ["用例编号", "测试实例", "执行结果", "原因", "影响判断"],
        pending_rows,
        widths={1: 14, 2: 45, 3: 12, 4: 70, 5: 35},
        result_column=3,
        wrap_columns=(2, 4, 5),
    )

    # ── 未登记用例（如有） ──
    if unregistered:
        ws = wb.create_sheet("未登记用例")
        ws.sheet_view.showGridLines = False
        unregistered_rows = [
            [
                instance.classname,
                instance.name,
                instance.outcome,
                round(instance.duration, 3),
                "脚本未声明 case_id，无法回写用例 Excel"
                if instance.outcome == "PASS" else one_line(instance.message, 600),
            ]
            for instance in unregistered
        ]
        result_table(
            ws,
            1,
            ["测试类", "测试实例", "执行结果", "耗时(s)", "说明"],
            unregistered_rows,
            widths={1: 50, 2: 50, 3: 12, 4: 10, 5: 60},
            result_column=3,
            wrap_columns=(1, 2, 5),
        )

    # ── 回写记录 ──
    ws = wb.create_sheet("回写记录")
    ws.sheet_view.showGridLines = False
    missing_text = "无"
    if writeback.missing:
        missing_text = "、".join(writeback.missing)
    notes = [
        ("用例 Excel", case_rel),
        ("工作表", writeback.sheet or "-"),
        ("回写行数", str(writeback.updated)),
        ("用例表中未执行", str(writeback.unexecuted)),
        ("结果表中未匹配", missing_text),
        ("副本", writeback.fallback or "无"),
        ("异常", writeback.error or "无"),
        (
            "回写列",
            f"{H_ACTUAL} / {H_PASSED} / {H_EXEC_TIME}",
        ),
    ]
    kv_table(ws, 1, notes, ncols=2)
    set_widths(ws, {1: 22, 2: 110})

    return wb


# ══════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(
        description="生成 Excel 测试报告并把执行结果回写到用例 Excel（不推送飞书）"
    )
    parser.add_argument("--junit", default=str(DEFAULT_JUNIT), help="junit xml 路径")
    parser.add_argument(
        "--html", "--report",
        dest="html",
        default=str(DEFAULT_HTML),
        help="pytest-html 报告路径（--report 为旧参数别名）",
    )
    parser.add_argument("--output", default="", help="Excel 报告输出路径")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="未指定 --output 时的输出目录",
    )
    parser.add_argument(
        "--testcase-xlsx",
        default="",
        help="要回写的用例 Excel；留空则按配置与 case_id 命中率自动发现",
    )
    parser.add_argument("--requirement", default="", help="限制自动发现的需求目录，如 REQ-xxx")
    parser.add_argument("--no-writeback", action="store_true", help="只生成报告，不回写用例")
    parser.add_argument("--env-url", default=os.getenv("TEST_API_URL", ""), help="覆盖环境地址")
    parser.add_argument("--api-path", default=os.getenv("TEST_API_PATH", ""), help="覆盖接口路径")
    args = parser.parse_args()

    junit = Path(args.junit).expanduser()
    if not junit.is_absolute():
        junit = ROOT / junit
    html = Path(args.html).expanduser()
    if not html.is_absolute():
        html = ROOT / html

    if args.output:
        output = Path(args.output).expanduser()
        if not output.is_absolute():
            output = ROOT / output
    else:
        output_dir = Path(args.output_dir).expanduser()
        if not output_dir.is_absolute():
            output_dir = ROOT / output_dir
        output = output_dir / f"test-results_{datetime.now():%Y%m%d_%H%M%S}.xlsx"

    defs = scan_test_definitions(ROOT / "tests")
    instances, executed_at, root_name = parse_junit(junit, defs)
    cases, unregistered = aggregate_cases(instances)

    case_ids = set(cases)
    case_workbook = resolve_case_workbook(args.testcase_xlsx, case_ids, args.requirement)
    case_meta: dict[str, CaseMeta] = {}
    loaded = None
    if case_workbook is not None:
        loaded = load_case_workbook(case_workbook)
        if loaded is not None:
            _, _, _, _, rows, case_meta = loaded

    for case_id, case in cases.items():
        meta = case_meta.get(case_id)
        if meta:
            case.title = meta.title
            case.ac = meta.ac
            case.priority = meta.priority
            case.requirement = meta.requirement

    environment_name = str(config_value("env", "") or "")
    classnames = sorted({instance.classname for instance in instances if instance.classname})
    api_url, api_path, module, feature = resolve_target(classnames, args.api_path, args.env_url)
    environment = (
        f"{environment_name}（{api_url}）" if environment_name and api_url
        else environment_name or api_url or "未知环境"
    )

    bug_files = (
        sorted(
            (
                path for path in DEFAULT_BUG_DIR.glob("*.xlsx")
                if not path.name.startswith("~$")
            ),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if DEFAULT_BUG_DIR.is_dir() else []
    )

    writeback = WritebackInfo()
    report_name = output.name

    if loaded is not None and not args.no_writeback:
        wb_case, ws_case, header_row, headers, rows, _ = loaded
        lock_file = case_workbook.with_name("~$" + case_workbook.name)
        if lock_file.is_file():
            print(f"[提示] 检测到 Excel 临时锁文件 {lock_file.name}，若保存失败将自动写入副本。")
        writeback = write_back_results(
            wb_case, ws_case, header_row, headers, rows,
            cases, executed_at, report_name,
        )
        if writeback.error and not writeback.updated:
            print(f"[警告] {writeback.error}")
        elif writeback.updated == 0:
            writeback.error = writeback.error or "未在用例表中找到任何匹配的 case_id，未修改用例 Excel"
            print(f"[警告] {writeback.error}")
        else:
            save_workbook(wb_case, case_workbook, writeback)
            if writeback.fallback:
                print(f"[警告] {writeback.error}：{writeback.fallback}")
            elif writeback.error:
                print(f"[警告] {writeback.error}")
        wb_case.close()
    elif case_workbook is None:
        writeback.error = "未找到匹配的用例 Excel，已跳过回写"
        print(f"[警告] {writeback.error}")
    elif loaded is None:
        writeback.error = "用例 Excel 结构校验失败，已跳过回写"
        print(f"[警告] {writeback.error}")
    else:
        writeback.error = "已按 --no-writeback 跳过回写"
        loaded[0].close()

    report_wb = build_report_workbook(
        junit=junit,
        html=html,
        output=output,
        root_name=root_name,
        executed_at=executed_at,
        instances=instances,
        cases=cases,
        unregistered=unregistered,
        environment=environment,
        api_url=api_url,
        api_path=api_path,
        module=module,
        feature=feature,
        case_workbook=case_workbook,
        writeback=writeback,
        bug_files=bug_files,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        report_wb.save(output)
    except PermissionError as exc:
        raise SystemExit(f"Excel 报告保存失败（文件被占用）：{output}（{exc}）") from exc

    inst = instance_stats(instances)
    cst = case_stats(cases)
    print(f"已生成 Excel 测试报告：{rel(output)}")
    print(
        f"测试实例：总计 {inst['total']} ｜ PASS {inst['pass']} ｜ XPASS {inst['xpass']} ｜ "
        f"FAIL {inst['fail']} ｜ SKIP {inst['skip']} ｜ XFAIL {inst['xfail']} ｜ "
        f"耗时 {inst['duration']:.2f}s"
    )
    print(
        f"测试用例：总计 {cst['total']} ｜ 通过 {cst['pass']} ｜ 失败 {cst['fail']} ｜ "
        f"跳过 {cst['skip']} ｜ 已知缺陷 {cst['xfail']} ｜ XPASS {cst['xpass']}"
    )
    if writeback.fallback:
        print(f"目标文件被占用，结果已写入副本：{writeback.fallback}（{writeback.updated} 行）")
        if writeback.missing:
            print(f"未在用例表中找到 {len(writeback.missing)} 条：{', '.join(writeback.missing)}")
    elif writeback.target:
        print(f"已回写用例：{writeback.target}（{writeback.updated} 行）")
        if writeback.missing:
            print(f"未在用例表中找到 {len(writeback.missing)} 条：{', '.join(writeback.missing)}")
    elif not args.no_writeback:
        print(f"未回写用例：{writeback.error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
