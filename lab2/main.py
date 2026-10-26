#!/usr/bin/env python3
"""
lab2 独立运行入口
"""
import sys
from pathlib import Path

# 添加项目根目录至 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from checker.cli import run_lab
from checker.config import DEFAULT_ROSTER_PATH, DEFAULT_TEMPLATE_PATH

if __name__ == "__main__":
    ret = run_lab(
        lab_id="lab2",
        roster_path=DEFAULT_ROSTER_PATH,
        template_path=DEFAULT_TEMPLATE_PATH,
        mock_ai=False,
    )
    sys.exit(ret)
