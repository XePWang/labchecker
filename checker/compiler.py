"""
checker.compiler
GCC/G++ 编译引擎与 Windows 环境差异自动化兼容转换模块
"""
import os
import re
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

from checker.config import C_STANDARD, CXX_STANDARD, COMMON_CFLAGS, GCC_PATH, GXX_PATH
from checker.models import CompileResult


# Windows 特有头文件与替换方案
WINDOWS_HEADERS = ["windows.h", "conio.h", "tchar.h", "stdafx.h", "io.h"]


def detect_and_convert_encoding(raw_bytes: bytes) -> Tuple[str, str]:
    """尝试以 UTF-8、GBK、GB18030 等多编码解码源码"""
    for enc in ["utf-8", "gb18030", "gbk", "cp936", "latin-1"]:
        try:
            text = raw_bytes.decode(enc)
            return text, enc
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace"), "utf-8(fallback)"


def generate_compat_source(source_text: str) -> Tuple[str, List[str]]:
    """
    针对 Windows 环境特有语法与库调用进行中立的兼容性转译。
    严禁修改算法逻辑、数学公式或分支判定！
    """
    reasons = []
    lines = source_text.splitlines()
    new_lines = []

    has_conio = False
    has_windows = False

    for line in lines:
        stripped = line.strip()

        # 1. 过滤 Windows 专有头文件
        matched_win_header = False
        for wh in WINDOWS_HEADERS:
            pattern = rf'#\s*include\s*[<"]{re.escape(wh)}[>"]'
            if re.search(pattern, stripped, re.IGNORECASE):
                new_lines.append(f"/* [COMPAT AUTO-REMOVED] {line} */")
                reasons.append(f"注释掉 Windows 特有头文件 <{wh}>")
                matched_win_header = True
                if "conio" in wh.lower():
                    has_conio = True
                if "windows" in wh.lower():
                    has_windows = True
                break

        if matched_win_header:
            continue

        # 2. 替换 system("pause")
        if re.search(r'system\s*\(\s*["\']pause["\']\s*\)', line, re.IGNORECASE):
            sub_line = re.sub(
                r'system\s*\(\s*["\']pause["\']\s*\)',
                '/* system("pause") */ 0',
                line,
                flags=re.IGNORECASE,
            )
            new_lines.append(sub_line)
            reasons.append("替换 Windows 控制台挂起 system(\"pause\")")
            continue

        # 3. 替换 getch() / _getch()
        if re.search(r'\b_?getch\s*\(\s*\)', line):
            sub_line = re.sub(r'\b_?getch\s*\(\s*\)', 'getchar()', line)
            new_lines.append(sub_line)
            reasons.append("替换 conio.h 中的 getch() 为标准 getchar()")
            continue

        # 4. 替换 scanf_s 为 scanf
        if re.search(r'\bscanf_s\b', line):
            # 将常见的基础数据类型 scanf_s 简化为 scanf (对于 %d, %f, %lf 等完全等价)
            sub_line = re.sub(r'\bscanf_s\b', 'scanf', line)
            new_lines.append(sub_line)
            reasons.append("将 MSVC 安全扩展 scanf_s 转译为标准 scanf")
            continue

        # 5. 替换 fflush(stdin) 这一非标准未定义行为
        if re.search(r'fflush\s*\(\s*stdin\s*\)', line):
            sub_line = re.sub(r'fflush\s*\(\s*stdin\s*\)', '/* fflush(stdin) */', line)
            new_lines.append(sub_line)
            reasons.append("注释掉 MSVC 未定义行为 fflush(stdin)")
            continue

        new_lines.append(line)

    compat_code = "\n".join(new_lines)

    # 如果原代码依赖 conio.h 但使用了一些宏定义，可在开头插入兼容存根
    header_stubs = []
    if has_conio:
        header_stubs.append("/* Compat stubs for conio */\n#include <stdio.h>\n")

    return "\n".join(header_stubs) + compat_code, reasons


class ProjectCompiler:
    """负责将学生源码编译为可执行文件，并提供自动兼容重试机制"""

    def __init__(self):
        self.gcc = GCC_PATH
        self.gxx = GXX_PATH

    def compile(
        self,
        src_path: Path,
        build_dir: Path,
        problem_id: str,
        extra_sources: Optional[List[Path]] = None,
    ) -> CompileResult:
        """
        编译单个题目代码
        1. 首先尝试直接编译原始文件
        2. 若因 Windows 头文件/语法失败，生成 compat 副本并重试
        3. 记录完整的命令、耗时、标准输出与错误
        """
        build_dir.mkdir(parents=True, exist_ok=True)
        is_cpp = src_path.suffix.lower() in {".cpp", ".cc", ".cxx"}
        compiler = self.gxx if is_cpp else self.gcc
        std_flag = f"-std={CXX_STANDARD}" if is_cpp else f"-std={C_STANDARD}"

        bin_name = f"{problem_id}.bin"
        bin_path = build_dir / bin_name
        log_path = build_dir / f"{problem_id}_compile.log"

        sources = [src_path] + (extra_sources or [])
        cmd = [compiler, std_flag] + COMMON_CFLAGS + [str(s) for s in sources] + ["-o", str(bin_path)]

        start_time = time.time()
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            duration_ms = (time.time() - start_time) * 1000

            if res.returncode == 0 and bin_path.exists():
                self._write_log(log_path, cmd, res.stdout, res.stderr, res.returncode, duration_ms, False, [])
                return CompileResult(
                    success=True,
                    command=cmd,
                    binary_path=bin_path,
                    stdout=res.stdout,
                    stderr=res.stderr,
                    exit_code=0,
                    duration_ms=duration_ms,
                    compat_applied=False,
                )
        except subprocess.TimeoutExpired:
            duration_ms = (time.time() - start_time) * 1000
            self._write_log(log_path, cmd, "", "编译进程超时 (30s)", -1, duration_ms, False, [])
            return CompileResult(
                success=False,
                command=cmd,
                stderr="编译超时 (30s)",
                exit_code=-1,
                duration_ms=duration_ms,
            )

        # 编译失败，分析错误信息是否属于 Windows 兼容性问题
        first_err = res.stderr
        raw_bytes = src_path.read_bytes()
        decoded_text, src_enc = detect_and_convert_encoding(raw_bytes)

        needs_compat = False
        compat_reasons = []

        # 检查是否包含 Windows 专有标识
        if any(wh in first_err for wh in WINDOWS_HEADERS) or any(
            k in decoded_text for k in ["windows.h", "conio.h", "system(\"pause\")", "system(\"PAUSE\")", "scanf_s"]
        ):
            needs_compat = True

        if src_enc != "utf-8":
            needs_compat = True
            compat_reasons.append(f"将源文件编码从 {src_enc} 规范化转换为 UTF-8")

        if needs_compat:
            compat_code, syntax_reasons = generate_compat_source(decoded_text)
            compat_reasons.extend(syntax_reasons)

            compat_src_path = build_dir / f"{src_path.stem}_compat{src_path.suffix}"
            compat_src_path.write_text(compat_code, encoding="utf-8")

            compat_sources = [compat_src_path] + (extra_sources or [])
            compat_cmd = [compiler, std_flag] + COMMON_CFLAGS + [str(s) for s in compat_sources] + ["-o", str(bin_path)]

            start_time = time.time()
            try:
                compat_res = subprocess.run(
                    compat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30
                )
                duration_ms = (time.time() - start_time) * 1000
                success = compat_res.returncode == 0 and bin_path.exists()

                self._write_log(
                    log_path,
                    compat_cmd,
                    compat_res.stdout,
                    compat_res.stderr,
                    compat_res.returncode,
                    duration_ms,
                    True,
                    compat_reasons,
                )

                return CompileResult(
                    success=success,
                    command=compat_cmd,
                    binary_path=bin_path if success else None,
                    stdout=compat_res.stdout,
                    stderr=compat_res.stderr if not success else first_err + "\n--- 兼容转换后编译通过 ---",
                    exit_code=compat_res.returncode,
                    duration_ms=duration_ms,
                    compat_applied=True,
                    compat_reasons=compat_reasons,
                )
            except subprocess.TimeoutExpired:
                duration_ms = (time.time() - start_time) * 1000
                return CompileResult(
                    success=False,
                    command=compat_cmd,
                    stderr="兼容重编译超时 (30s)",
                    exit_code=-1,
                    duration_ms=duration_ms,
                    compat_applied=True,
                    compat_reasons=compat_reasons,
                )

        # 非环境兼容问题，确属语法或程序错误
        duration_ms = (time.time() - start_time) * 1000
        self._write_log(log_path, cmd, res.stdout, res.stderr, res.returncode, duration_ms, False, [])
        return CompileResult(
            success=False,
            command=cmd,
            stdout=res.stdout,
            stderr=res.stderr,
            exit_code=res.returncode,
            duration_ms=duration_ms,
            compat_applied=False,
        )

    def _write_log(
        self,
        log_path: Path,
        cmd: List[str],
        stdout: str,
        stderr: str,
        exit_code: int,
        duration_ms: float,
        compat_applied: bool,
        compat_reasons: List[str],
    ):
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"=== 编译命令 ===\n{' '.join(cmd)}\n\n")
            f.write(f"=== 退出码 ===\n{exit_code} (耗时: {duration_ms:.2f}ms)\n\n")
            if compat_applied:
                f.write(f"=== 兼容性转换介入 ===\n" + "\n".join(compat_reasons) + "\n\n")
            if stdout:
                f.write(f"=== 标准输出 ===\n{stdout}\n\n")
            if stderr:
                f.write(f"=== 标准错误 ===\n{stderr}\n\n")
