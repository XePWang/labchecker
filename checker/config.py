"""
checker.config
全局配置与参数定义
"""
import os
import shutil
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 临时工作目录：所有临时输出、构建缓存和沙箱执行目录均位于 .work
WORK_DIR = PROJECT_ROOT / ".work"
WORK_DIR.mkdir(parents=True, exist_ok=True)

# 默认参考文件与点名册路径 (兼容 "参考文件" 或 "refs")
REF_DIR = PROJECT_ROOT / "参考文件"
if not REF_DIR.exists() and (PROJECT_ROOT / "refs").exists():
    REF_DIR = PROJECT_ROOT / "refs"

DEFAULT_ROSTER_PATH = REF_DIR / "郝萌(2026-2027-1-22CS14003-003-A)点名册.xls"
DEFAULT_TEMPLATE_PATH = REF_DIR / "实验成绩单_组号_任课老师姓名.xlsx"

# 编译器配置
GCC_PATH = shutil.which("gcc") or "/usr/bin/gcc"
GXX_PATH = shutil.which("g++") or "/usr/bin/g++"
C_STANDARD = "c11"
CXX_STANDARD = "c++17"
COMMON_CFLAGS = ["-O2", "-Wall", "-lm"]

# 运行与沙箱限制
DEFAULT_EXEC_TIMEOUT = 2.0  # 单个用例运行超时时间 (秒)
MAX_OUTPUT_BYTES = 64 * 1024  # 单次运行最大捕获输出字节数 (64 KB)，防止死循环刷屏导致 OOM
MAX_MEMORY_MB = 128  # 虚拟内存上限 (MB)

# Antigravity CLI 配置
AGY_CLI_PATH = shutil.which("agy") or "/home/user/.local/bin/agy"
AGY_MODEL = os.environ.get("AGY_MODEL", "gemini-3.8-flash-low")
AGY_TIMEOUT_SECONDS = 90  # AI 推理与多模态解析超时时间
