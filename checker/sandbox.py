"""
checker.sandbox
安全运行沙箱：网络隔离、文件系统隔离、进程组隔离、超时强杀与严格流式输出截断
"""
import os
import selectors
import shutil
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

        # 最大文件写入尺寸 (512KB) 防学生代码狂写文件
        resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 1024, 512 * 1024))

        # 文件句柄限制
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))

        # 禁用 core dump 防写爆磁盘
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except Exception:
        pass

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


def _is_unshare_supported() -> bool:
    """检测当前内核与用户空间是否支持 unshare --user -m -r -n"""
    try:
        res = subprocess.run(
            ["unshare", "--user", "-m", "-r", "-n", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        return res.returncode == 0
    except Exception:
        return False


CAN_UNSHARE = _is_unshare_supported()


def run_binary(
    bin_path: Path,
    input_str: str = "",
    timeout: float = DEFAULT_EXEC_TIMEOUT,
    cwd: Optional[Path] = None,
) -> ExecutionResult:
    """
    在隔离网络、挂载隔离、独立进程组与严格流式截断下运行二进制程序
    """
    resolved_bin = bin_path.resolve()
    run_cwd = cwd.resolve() if cwd else resolved_bin.parent
    in_bytes = input_str.encode("utf-8")

    start_time = time.time()
    timed_out = False
    truncated = False
    exit_code = 0

    stdout_buf = bytearray()
    stderr_buf = bytearray()

    # 构造隔离命令
    use_isolation = CAN_UNSHARE
    sb_tmp_dir = None

    if use_isolation:
        # 为本次运行在 /dev/shm 或 /tmp 分配临时沙箱目录
        shm_root = Path("/dev/shm") if Path("/dev/shm").exists() else Path("/tmp")
        sb_name = f"sb_{os.getpid()}_{int(time.time()*1000)}"
        sb_tmp_dir = shm_root / sb_name
        sb_tmp_dir.mkdir(parents=True, exist_ok=True)

        target_bin_in_sb = sb_tmp_dir / resolved_bin.name
        shutil.copy2(resolved_bin, target_bin_in_sb)

        # 构造 unshare 命令：隔离网络(-n)、私有化挂载(-m)、在容器中挂载 tmpfs 遮蔽 /home 与 /tmp
        # 从而使沙箱内程序无法窃取宿主机标记文件，也无法连接宿主机本地端口
        wrapper_sh = (
            "mount --make-rprivate / && "
            "mount -t tmpfs none /home && "
            "mount -t tmpfs none /tmp && "
            f"cd {sb_tmp_dir} && ./{resolved_bin.name}"
        )
        cmd = ["unshare", "--user", "-m", "-r", "-n", "bash", "-c", wrapper_sh]
    else:
        cmd = [str(resolved_bin)]

    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(run_cwd if not use_isolation else sb_tmp_dir),
            preexec_fn=_set_resource_limits,
        )

        # 写入标准输入后关闭 stdin
        if in_bytes:
            try:
                proc.stdin.write(in_bytes)
                proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
        try:
            proc.stdin.close()
        except Exception:
            pass

        # 流式读取 stdout 与 stderr，严格限制内存缓冲不得超过 MAX_OUTPUT_BYTES
        os.set_blocking(proc.stdout.fileno(), False)
        os.set_blocking(proc.stderr.fileno(), False)

        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ, data="stdout")
        sel.register(proc.stderr, selectors.EVENT_READ, data="stderr")

        while True:
            # 超时检测
            elapsed = time.time() - start_time
            if elapsed > timeout:
                timed_out = True
                break

            events = sel.select(timeout=min(0.05, max(0.001, timeout - elapsed)))
            for key, _ in events:
                try:
                    chunk = os.read(key.fd, 4096)
                except (OSError, ValueError):
                    chunk = b""

                if not chunk:
                    try:
                        sel.unregister(key.fileobj)
                    except Exception:
                        pass
                    continue

                if key.data == "stdout":
                    avail = MAX_OUTPUT_BYTES - len(stdout_buf)
                    if avail > 0:
                        stdout_buf.extend(chunk[:avail])
                    if len(stdout_buf) >= MAX_OUTPUT_BYTES:
                        truncated = True
                else:
                    avail = MAX_OUTPUT_BYTES - len(stderr_buf)
                    if avail > 0:
                        stderr_buf.extend(chunk[:avail])
                    if len(stderr_buf) >= MAX_OUTPUT_BYTES:
                        truncated = True

                # 若输出超出上限，立即强杀整组进程防刷屏与内存消耗
                if truncated:
                    break

            if truncated or not sel.get_map():
                break

            # 进程已自行结束
            if proc.poll() is not None:
                # 读完管道剩余字节
                for fd, buf, name in [(proc.stdout.fileno(), stdout_buf, "stdout"), (proc.stderr.fileno(), stderr_buf, "stderr")]:
                    try:
                        rem = os.read(fd, 4096)
                        if rem and len(buf) < MAX_OUTPUT_BYTES:
                            buf.extend(rem[:MAX_OUTPUT_BYTES - len(buf)])
                    except Exception:
                        pass
                break

    except Exception as e:
        exit_code = -2
        stderr_buf.extend(f"Execution Exception: {str(e)}".encode("utf-8"))

    finally:
        # 清理进程组
        if proc:
            if timed_out or truncated or proc.poll() is None:
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGKILL)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            try:
                proc.wait(timeout=0.5)
            except Exception:
                pass
            if proc.stdout: proc.stdout.close()
            if proc.stderr: proc.stderr.close()

        if sb_tmp_dir and sb_tmp_dir.exists():
            shutil.rmtree(sb_tmp_dir, ignore_errors=True)

    duration_ms = (time.time() - start_time) * 1000
    if timed_out:
        exit_code = -1
        stderr_buf.extend(b"\n[Execution Timed Out (SIGKILL)]")
    elif proc and proc.returncode is not None:
        exit_code = proc.returncode

    if truncated:
        stdout_buf.extend(b"\n...[OUTPUT TRUNCATED DUE TO SIZE LIMIT]...")

    stdout_str, out_enc = decode_bytes(bytes(stdout_buf))
    stderr_str, _ = decode_bytes(bytes(stderr_buf))

    return ExecutionResult(
        stdout=stdout_str,
        stderr=stderr_str,
        exit_code=exit_code,
        timed_out=timed_out,
        duration_ms=duration_ms,
        truncated=truncated,
        encoding=out_enc,
    )
