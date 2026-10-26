#!/usr/bin/env python3
"""
lab1 独立运行入口
"""
import argparse
import sys
from pathlib import Path

# 添加项目根目录至 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from checker.cli import run_lab
from checker.config import DEFAULT_ROSTER_PATH, DEFAULT_TEMPLATE_PATH

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lab 1 独立判题脚本")
    parser.add_argument("--clean", action="store_true", help="评测前先清空 src/, build/, output/ 缓存")
    parser.add_argument("--mock-ai", action="store_true", help="使用 Mock 模式模拟 AI")
    parser.add_argument("--student-id", type=str, default="", help="仅针对单个学号评测")
    args = parser.parse_args()

    ret = run_lab(
        lab_id="lab1",
        roster_path=DEFAULT_ROSTER_PATH,
        template_path=DEFAULT_TEMPLATE_PATH,
        mock_ai=args.mock_ai,
        single_student_id=args.student_id,
        clean=args.clean,
    )
    sys.exit(ret)
