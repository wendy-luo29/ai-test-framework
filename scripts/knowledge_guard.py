#!/usr/bin/env python3
"""知识库一致性校验入口。

知识库（it-nas）以 submodule 挂在 `knowledge/`，校验实现随知识库走：
`knowledge/tools/knowledge_guard.py`。本文件只做转发，保持
`python scripts/knowledge_guard.py [--strict]` 的既有调用方式不变。
"""

import runpy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_REPO = REPO_ROOT / "knowledge"
KNOWLEDGE_PROJECT = KNOWLEDGE_REPO / "Project-LspQuote"
TOOL = KNOWLEDGE_REPO / "tools" / "knowledge_guard.py"


def main() -> int:
    if not TOOL.is_file():
        print(f"未找到知识库校验器：{TOOL}")
        print("请先执行：git submodule update --init --recursive")
        return 1

    argv = sys.argv[1:]
    if "--project-root" not in argv:
        argv = ["--project-root", str(REPO_ROOT), *argv]
    if "--knowledge-root" not in argv:
        argv = ["--knowledge-root", str(KNOWLEDGE_PROJECT), *argv]

    sys.argv = [str(TOOL), *argv]
    runpy.run_path(str(TOOL), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
