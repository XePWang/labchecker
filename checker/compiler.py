"""
checker.compiler
GCC/G++ 编译引擎与 Windows 环境差异自动化兼容转换模块
"""
import concurrent.futures
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from checker.config import C_STANDARD, CXX_STANDARD, GCC_PATH, GXX_PATH
from checker.models import CompileResult, CompileTask
from checker.unpack import detect_and_decode_source

# 编译器通用参数与链接选项 (确保 -lm 放置于末尾以满足 GCC 链接符号解析规则)
COMPILER_FLAGS = ["-O2", "-Wall"]
LINKER_FLAGS = ["-lm"]

# Windows 特有头文件与替换方案
WINDOWS_HEADERS = ["windows.h", "conio.h", "tchar.h", "stdafx.h", "io.h"]

SCANF_S_SHIM = r"""/* [COMPAT SHIM] MSVC scanf_s implementation for GCC/Linux */
#include <stdio.h>
#include <stdarg.h>
#include <ctype.h>
#include <string.h>

static int _labchecker_scanf_s(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    const char *p = fmt;
    int matched = 0;

    while (*p) {
        if (isspace((unsigned char)*p)) {
            while (isspace((unsigned char)*p)) p++;
            int c;
            while ((c = fgetc(stdin)) != EOF && isspace((unsigned char)c));
            if (c != EOF) ungetc(c, stdin);
            continue;
        }

        if (*p == '%') {
            const char *start = p++;
            if (*p == '%') {
                int c = fgetc(stdin);
                if (c != '%') { if (c != EOF) ungetc(c, stdin); break; }
                p++;
                continue;
            }

            int is_suppress = 0;
            if (*p == '*') { is_suppress = 1; p++; }

            while (isdigit((unsigned char)*p)) p++;
            while (*p == 'h' || *p == 'l' || *p == 'L' || *p == 'z' || *p == 'j' || *p == 't') p++;

            char spec = *p++;
            char sub_fmt[32] = {0};
            int len = (int)(p - start);
            if (len < 31) strncpy(sub_fmt, start, len);

            if (spec == 'c') {
                void *ptr = is_suppress ? NULL : va_arg(ap, void*);
                unsigned sz = is_suppress ? 0 : va_arg(ap, unsigned);
                (void)sz;
                int c = fgetc(stdin);
                if (c == EOF) { if (matched == 0) matched = EOF; break; }
                if (ptr) { *(char*)ptr = (char)c; matched++; }
            } else if (spec == 's') {
                char *ptr = is_suppress ? NULL : va_arg(ap, char*);
                unsigned sz = is_suppress ? 0 : va_arg(ap, unsigned);
                int c;
                while ((c = fgetc(stdin)) != EOF && isspace((unsigned char)c));
                if (c == EOF) { if (matched == 0) matched = EOF; break; }
                unsigned cnt = 0;
                while (c != EOF && !isspace((unsigned char)c)) {
                    if (ptr && (sz == 0 || cnt + 1 < sz)) ptr[cnt++] = (char)c;
                    c = fgetc(stdin);
                }
                if (c != EOF) ungetc(c, stdin);
                if (ptr) { ptr[cnt] = '\0'; matched++; }
            } else {
                void *ptr = is_suppress ? NULL : va_arg(ap, void*);
                if (is_suppress) {
                    #pragma GCC diagnostic push
                    #pragma GCC diagnostic ignored "-Wformat-security"
                    int r = fscanf(stdin, sub_fmt);
                    #pragma GCC diagnostic pop
                    if (r == EOF) { if (matched == 0) matched = EOF; break; }
                } else {
                    #pragma GCC diagnostic push
                    #pragma GCC diagnostic ignored "-Wformat-security"
                    int r = fscanf(stdin, sub_fmt, ptr);
                    #pragma GCC diagnostic pop
                    if (r == 1) matched++;
                    else if (r == EOF) { if (matched == 0) matched = EOF; break; }
                    else break;
                }
            }
        } else {
            int c = fgetc(stdin);
            if (c != (unsigned char)*p) {
                if (c != EOF) ungetc(c, stdin);
                break;
            }
            p++;
        }
    }
    va_end(ap);
    return matched;
}
#define scanf_s _labchecker_scanf_s
"""


def detect_and_convert_encoding(raw_bytes: bytes) -> Tuple[str, str]:
    """严格识别并转换源码编码，严禁使用 latin-1 或 errors='replace' 掩盖乱码"""
    ok, enc, text, _, err = detect_and_decode_source(raw_bytes)
    if ok:
        return text, enc
    raise UnicodeDecodeError(enc, raw_bytes, 0, len(raw_bytes), err or "无法可靠解码")


def generate_compat_source(source_text: str) -> Tuple[str, List[str]]:
    """
    针对 Windows 环境特有语法与库调用进行中立的兼容性转译。
    严禁修改算法逻辑、数学公式或分支判定！
    """
    reasons = []
    lines = source_text.splitlines()
    new_lines = []

    has_conio = False
    has_scanf_s = False

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
            reasons.append('替换 Windows 控制台挂起 system("pause")')
            continue

        # 3. 替换 getch() / _getch()
        if re.search(r'\b_?getch\s*\(\s*\)', line):
            sub_line = re.sub(r'\b_?getch\s*\(\s*\)', 'getchar()', line)
            new_lines.append(sub_line)
            reasons.append('替换 conio.h 中的 getch() 为标准 getchar()')
            continue

        # 4. 检测 scanf_s (使用专用 shim 替代简单字符串替换)
        if re.search(r'\bscanf_s\b', line):
            has_scanf_s = True
            # 保留原代码中的 scanf_s 调用，由前置 shim 处理
            new_lines.append(line)
            continue

        # 5. 替换 fflush(stdin) 这一非标准未定义行为
        if re.search(r'fflush\s*\(\s*stdin\s*\)', line):
            sub_line = re.sub(r'fflush\s*\(\s*stdin\s*\)', '/* fflush(stdin) */', line)
            new_lines.append(sub_line)
            reasons.append('注释掉 MSVC 未定义行为 fflush(stdin)')
            continue

        new_lines.append(line)

    header_stubs = []
    if has_conio:
        header_stubs.append("/* Compat stubs for conio */\n#include <stdio.h>\n")
    if has_scanf_s:
        header_stubs.append(SCANF_S_SHIM + "\n")
        reasons.append('注入 MSVC 兼容的 scanf_s 存根函数 (安全处理 %s/%c 缓冲区尺寸参数)')

    return "\n".join(header_stubs) + "\n".join(new_lines), reasons


class ProjectCompiler:
    """负责将学生源码编译为可执行文件，并提供自动兼容重试机制与网络隔离"""

    def __init__(self):
        self.gcc = GCC_PATH
        self.gxx = GXX_PATH

    def compile(
        self,
        src_path: Path,
        build_dir: Path,
        problem_id: str,
        extra_sources: Optional[List[Path]] = None,
        include_dirs: Optional[List[Path]] = None,
    ) -> CompileResult:
        """
        编译单个题目代码
        1. 确保 -lm 位于链接库末尾
        2. 保留相对目录结构与 include 路径
        3. 若因 Windows 专有库失败，生成 _compat 副本
        """
        build_dir.mkdir(parents=True, exist_ok=True)
        is_cpp = src_path.suffix.lower() in {".cpp", ".cc", ".cxx"}
        compiler = self.gxx if is_cpp else self.gcc
        std_flag = f"-std={CXX_STANDARD}" if is_cpp else f"-std={C_STANDARD}"

        bin_name = f"{problem_id}.bin"
        bin_path = build_dir / bin_name
        log_path = build_dir / f"{problem_id}_compile.log"

        inc_args = []
        if include_dirs:
            for inc in include_dirs:
                inc_args.extend(["-I", str(inc.resolve())])
        inc_args.extend(["-I", str(src_path.parent.resolve())])
        if (src_path.parent / "inc").is_dir():
            inc_args.extend(["-I", str((src_path.parent / "inc").resolve())])
        if (src_path.parent / "include").is_dir():
            inc_args.extend(["-I", str((src_path.parent / "include").resolve())])

        sources = [src_path] + (extra_sources or [])
        # 链接库 LINKER_FLAGS (如 -lm) 必须放在 sources 之后
        cmd = [compiler, std_flag] + COMPILER_FLAGS + inc_args + [str(s.resolve()) for s in sources] + ["-o", str(bin_path)] + LINKER_FLAGS

        # 使用 unshare --user -n 隔离编译过程中的外部网络访问
        wrapped_cmd = cmd
        try:
            if shutil.which("unshare"):
                wrapped_cmd = ["unshare", "--user", "-n"] + cmd
        except Exception:
            pass

        start_time = time.time()
        try:
            res = subprocess.run(
                wrapped_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                timeout=20,
            )
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
            self._write_log(log_path, cmd, "", "编译进程超时 (20s)", -1, duration_ms, False, [])
            return CompileResult(
                success=False,
                command=cmd,
                stderr="编译超时 (20s)",
                exit_code=-1,
                duration_ms=duration_ms,
            )

        # 编译失败，分析是否属于 Windows 兼容性问题
        first_err = res.stderr
        raw_bytes = src_path.read_bytes()
        try:
            decoded_text, src_enc = detect_and_convert_encoding(raw_bytes)
        except Exception:
            decoded_text, src_enc = "", "unknown"

        needs_compat = False
        compat_reasons = []

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

            # 兼容性副本命名: 使用 problem_id 前缀确保独立，防止多候选或不同题目 main.c 互相覆盖
            compat_src_path = build_dir / f"{problem_id}_{src_path.stem}_compat{src_path.suffix}"
            compat_src_path.write_text(compat_code, encoding="utf-8")

            compat_sources = [compat_src_path] + (extra_sources or [])
            compat_cmd = [compiler, std_flag] + COMPILER_FLAGS + inc_args + [str(s.resolve()) for s in compat_sources] + ["-o", str(bin_path)] + LINKER_FLAGS

            wrapped_compat_cmd = compat_cmd
            try:
                if shutil.which("unshare"):
                    wrapped_compat_cmd = ["unshare", "--user", "-n"] + compat_cmd
            except Exception:
                pass

            start_time = time.time()
            try:
                compat_res = subprocess.run(
                    wrapped_compat_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    errors="replace",
                    timeout=20,
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
                    stderr="兼容重编译超时 (20s)",
                    exit_code=-1,
                    duration_ms=duration_ms,
                    compat_applied=True,
                    compat_reasons=compat_reasons,
                )

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

    def compile_batch(
        self,
        tasks: List[CompileTask],
        max_workers: int = 32,
    ) -> Dict[Tuple[str, str, int], CompileResult]:
        """
        公共批量并发编译执行器。
        使用有并发上限的任务池调用现有编译器。
        保留原有编译参数、Windows 兼容处理、超时和日志机制。
        每个“学生 × 题号 × 源码候选”产物与临时文件独立，避免 main.c 互相覆盖。
        单个候选编译失败或超时，不影响其他候选和学生继续处理。
        """
        results: Dict[Tuple[str, str, int], CompileResult] = {}
        if not tasks:
            return results

        def _execute_task(task: CompileTask) -> Tuple[CompileTask, CompileResult]:
            try:
                res = self.compile(
                    src_path=task.src_path,
                    build_dir=task.build_dir,
                    problem_id=task.binary_name,
                    extra_sources=task.extra_sources,
                    include_dirs=task.include_dirs,
                )
                return task, res
            except Exception as e:
                err_res = CompileResult(
                    success=False,
                    command=[],
                    stderr=f"编译调度异常: {str(e)}",
                    exit_code=-1,
                    duration_ms=0.0,
                )
                return task, err_res

        workers = max(1, max_workers)
        if workers == 1:
            for task in tasks:
                _, res = _execute_task(task)
                results[(task.student_id, task.problem_id, task.cand_idx)] = res
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_task = {executor.submit(_execute_task, t): t for t in tasks}
                for future in concurrent.futures.as_completed(future_to_task):
                    task, res = future.result()
                    results[(task.student_id, task.problem_id, task.cand_idx)] = res

        return results
