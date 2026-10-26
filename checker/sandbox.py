"""
checker.sandbox
安全运行沙箱：进程组隔离、资源限制、超时强杀与输出截断
"""
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

from checker.config import DEFAULT_EXEC_TIMEOUT, MAX_MEMORY_MB, MAX_OUTPUT_BYTES


class ExecutionResult:
    """进程执行结果"""

    def __init__(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        timed_out: bool,
        duration_ms: float,
        truncated: bool = False,
        encoding: str = "utf-8",
    ):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.duration_ms = duration_ms
        self.truncated = truncated
        self.encoding = encoding


def _set_resource_limits():
    """在子进程启动前施加资源限额 (Linux rlimit)"""
    try:
        import resource

        # 虚拟内存上限 (默认 128MB)
        mem_bytes = MAX_MEMORY_MB * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))

        # 最大文件写入尺寸 (10MB)
        resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 1024 * 1024, 10 * 1024 * 1024))

        # 文件句柄限制
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))

        # 禁用 core dump 防写爆磁盘
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except Exception:
        pass

    # 创建独立进程组
    try:
        os.setsid()
    except Exception:
        pass


def decode_bytes(raw: bytes) -> Tuple[str, str]:
    """保留原始字节语义，宽容解码多编码输出"""
    for enc in ["utf-8", "gb18030", "gbk", "cp936", "latin-1"]:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(lossy)"


def run_binary(
    bin_path: Path,
    input_str: str = "",
    timeout: float = DEFAULT_EXEC_TIMEOUT,
    cwd: Optional[Path] = None,
) -> ExecutionResult:
    """
    在隔离进程组与资源限额下运行学生二进制程序
    """
    run_cwd = cwd or bin_path.parent
    in_bytes = input_str.encode("utf-8")

    start_time = time.time()
    proc = None
    timed_out = False
    truncated = False

    try:
        proc = subprocess.Popen(
            [str(bin_path.resolve())],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(run_cwd),
            preexec_fn=_set_resource_limits,
        )

        raw_out, raw_err = proc.communicate(input=in_bytes, timeout=timeout)
        duration_ms = (time.time() - start_time) * 1000
        exit_code = proc.returncode

    except subprocess.TimeoutExpired:
        timed_out = True
        duration_ms = (time.time() - start_time) * 1000
        exit_code = -1
        raw_out = b""
        raw_err = b"Execution Timed Out"

        # 彻底清理整个进程组，防止孤儿进程刷 CPU
        if proc:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                proc.wait(timeout=1.0)
            except Exception:
                pass
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()
            if proc.stdin:
                proc.stdin.close()

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        exit_code = -2
        raw_out = b""
        raw_err = f"Execution Exception: {str(e)}".encode("utf-8")

    # 截断过长输出防 OOM
    if len(raw_out) > MAX_OUTPUT_BYTES:
        raw_out = raw_out[:MAX_OUTPUT_BYTES] + b"\n...[OUTPUT TRUNCATED DUE TO SIZE LIMIT]..."
        truncated = True

    if len(raw_err) > MAX_OUTPUT_BYTES:
        raw_err = raw_err[:MAX_OUTPUT_BYTES]
        truncated = True

    stdout_str, out_enc = decode_bytes(raw_out)
    stderr_str, _ = decode_bytes(raw_err)

    return ExecutionResult(
        stdout=stdout_str,
        stderr=stderr_str,
        exit_code=exit_code,
        timed_out=timed_out,
        duration_ms=duration_ms,
        truncated=truncated,
        encoding=out_enc,
    )
