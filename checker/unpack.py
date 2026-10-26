"""
checker.unpack
提交识别、安全解压、编码兼容与规范化归档模块
"""
import os
import re
import shutil
import zipfile
import tarfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from checker.config import WORK_DIR
from checker.models import Student, SubmissionFile
from checker.roster import RosterManager


# 允许纳入评测的安全文件扩展名
ALLOWED_SOURCE_EXTS = {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"}
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
ALLOWED_DOC_EXTS = {".docx", ".doc", ".pdf", ".txt", ".md"}
KNOWN_ARCHIVE_EXTS = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".rar", ".7z"}

# 忽略的垃圾文件与系统隐藏目录
IGNORED_PATTERNS = {
    "__MACOSX", ".DS_Store", "Thumbs.db", "desktop.ini",
    ".git", ".vs", ".vscode", "Debug", "Release", "x64", "x86"
}


def sanitize_filename(filename: str) -> str:
    """解决 Windows 压缩包在 Linux 下提取可能产生的文件名乱码问题"""
    # 尝试 cp437 转 gbk
    try:
        decoded = filename.encode("cp437").decode("gbk")
        return decoded
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    # 尝试 utf-8
    try:
        decoded = filename.encode("cp437").decode("utf-8")
        return decoded
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    return filename


def is_safe_extract_path(base_dir: Path, target_path: Path) -> bool:
    """
    实际防范 Zip Slip 路径穿越与链接逃逸
    """
    try:
        resolved_base = base_dir.resolve()
        resolved_target = target_path.resolve()
        return str(resolved_target).startswith(str(resolved_base))
    except Exception:
        return False


class SafeExtractor:
    """负责将学生提交的各类型文件安全解压至工作区"""

    def __init__(self, work_root: Optional[Path] = None):
        self.work_root = work_root or (WORK_DIR / "unpack_scratch")
        self.work_root.mkdir(parents=True, exist_ok=True)

    def extract_archive(self, archive_path: Path, dest_dir: Path) -> Tuple[bool, str, List[Path]]:
        """
        安全解压压缩文件，返回 (是否成功, 状态信息, 提取出的文件列表)
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        suffix = archive_path.suffix.lower()

        extracted_files: List[Path] = []
        max_total_bytes = 100 * 1024 * 1024  # 单包最大解压 100MB 防炸弹
        total_extracted_bytes = 0
        max_files_count = 200

        if suffix == ".zip":
            try:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    for info in zf.infolist():
                        if any(ign in info.filename for ign in IGNORED_PATTERNS):
                            continue

                        raw_name = sanitize_filename(info.filename)
                        # 过滤目录或符号链接
                        if info.is_dir() or raw_name.endswith("/"):
                            continue

                        out_path = dest_dir / raw_name
                        if not is_safe_extract_path(dest_dir, out_path):
                            return False, f"检测到 Zip Slip 恶意路径穿越: {raw_name}", []

                        total_extracted_bytes += info.file_size
                        if total_extracted_bytes > max_total_bytes:
                            return False, "解压体积超过限制 (100MB 限制)，疑似解压炸弹", []

                        if len(extracted_files) >= max_files_count:
                            return False, "解压文件数量过多 (> 200)，中止解压", []

                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, open(out_path, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        extracted_files.append(out_path)

                return True, "解压成功", extracted_files
            except zipfile.BadZipFile:
                return False, "损坏的 ZIP 压缩包", []
            except Exception as e:
                return False, f"ZIP 解压异常: {str(e)}", []

        elif suffix in {".tar", ".gz", ".tgz", ".bz2"}:
            try:
                mode = "r:*"
                with tarfile.open(archive_path, mode) as tf:
                    for member in tf.getmembers():
                        if any(ign in member.name for ign in IGNORED_PATTERNS):
                            continue
                        if member.islnk() or member.issym():
                            continue  # 忽略软硬链接防逃逸
                        if not member.isfile():
                            continue

                        raw_name = sanitize_filename(member.name)
                        out_path = dest_dir / raw_name
                        if not is_safe_extract_path(dest_dir, out_path):
                            return False, f"检测到 Tar 路径穿越: {raw_name}", []

                        total_extracted_bytes += member.size
                        if total_extracted_bytes > max_total_bytes:
                            return False, "Tar 解压体积超限", []

                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        f = tf.extractfile(member)
                        if f:
                            with open(out_path, "wb") as dst:
                                shutil.copyfileobj(f, dst)
                            extracted_files.append(out_path)

                return True, "Tar 解压成功", extracted_files
            except Exception as e:
                return False, f"Tar 解压异常: {str(e)}", []

        elif suffix in {".rar", ".7z"}:
            return False, f"当前环境暂不支持 {suffix} 格式，需学生按规定提交 .zip 格式或手动辅助解压", []
        else:
            return False, f"未知或非压缩包格式: {suffix}", []


class SubmissionNormalizer:
    """
    负责从 labX/submit 读取原始文件，归属到对应学生，并规格化到 labX/src/<student_id>/
    """

    def __init__(self, roster_manager: RosterManager, lab_name: str, lab_root: Path):
        self.roster = roster_manager
        self.lab_name = lab_name.lower()  # e.g. "lab1", "lab2"
        self.lab_root = lab_root
        self.submit_dir = lab_root / "submit"
        self.src_dir = lab_root / "src"
        self.extractor = SafeExtractor(WORK_DIR / f"{self.lab_name}_unpack")

        # 归属与冲突追踪
        self.student_files: Dict[str, List[SubmissionFile]] = {}
        self.unmatched_items: List[Dict[str, str]] = []
        self.ambiguous_items: List[Dict[str, str]] = []

    def process_all_submissions(self) -> Dict[str, List[SubmissionFile]]:
        """执行全量处理流水线"""
        self.src_dir.mkdir(parents=True, exist_ok=True)
        if not self.submit_dir.exists():
            return {}

        # 遍历 submit 目录下所有直接条目（可以是 zip、目录、或散放代码文件）
        entries = sorted(list(self.submit_dir.iterdir()))

        for entry in entries:
            if entry.name.startswith(".") or entry.name in IGNORED_PATTERNS:
                continue

            # 1. 尝试从最外层提交项匹配学生身份
            student, candidates, reason = self.roster.match_student_from_text(entry.name)

            if len(candidates) > 1:
                self.ambiguous_items.append({
                    "path": str(entry),
                    "candidates": [c.student_id for c in candidates],
                    "reason": reason
                })
                continue

            extracted_items: List[Path] = []
            if entry.is_file() and entry.suffix.lower() in KNOWN_ARCHIVE_EXTS:
                # 压缩包，解压到临时工作区
                unpack_dest = WORK_DIR / f"{self.lab_name}_unpack" / entry.stem
                shutil.rmtree(unpack_dest, ignore_errors=True)
                success, msg, files = self.extractor.extract_archive(entry, unpack_dest)
                if not success:
                    self.unmatched_items.append({
                        "path": str(entry),
                        "reason": f"解压失败: {msg}"
                    })
                    continue
                extracted_items = files
            elif entry.is_dir():
                # 已经是目录
                for root, _, fs in os.walk(entry):
                    for f in fs:
                        extracted_items.append(Path(root) / f)
            elif entry.is_file():
                # 单个散放文件
                extracted_items = [entry]

            # 2. 遍历提取到的文件
            for file_path in extracted_items:
                if any(ign in file_path.name for ign in IGNORED_PATTERNS):
                    continue

                # 若外层未匹配到学生，尝试从内层文件路径识别
                cur_student = student
                if not cur_student:
                    cur_student, file_cands, f_reason = self.roster.match_student_from_text(
                        f"{file_path.parent.name}_{file_path.name}"
                    )
                    if len(file_cands) > 1:
                        self.ambiguous_items.append({
                            "path": str(file_path),
                            "candidates": [c.student_id for c in file_cands],
                            "reason": f_reason
                        })
                        continue

                if not cur_student:
                    self.unmatched_items.append({
                        "path": str(file_path),
                        "reason": "文件及外层均未匹配到点名册中的学号或姓名"
                    })
                    continue

                # 分类与题目识别
                sub_file = self._classify_and_stage_file(cur_student, file_path)
                if sub_file:
                    self.student_files.setdefault(cur_student.student_id, []).append(sub_file)

        return self.student_files

    def _classify_and_stage_file(self, student: Student, raw_file: Path) -> Optional[SubmissionFile]:
        """识别文件题号、过滤二进制与危险后缀，安全拷贝至 labX/src/<student_id>/"""
        ext = raw_file.suffix.lower()
        if ext in ALLOWED_SOURCE_EXTS:
            ftype = "c_source" if ext in {".c", ".h"} else "cpp_source"
        elif ext in ALLOWED_IMAGE_EXTS:
            ftype = "image"
        elif ext in ALLOWED_DOC_EXTS:
            ftype = "document"
        else:
            # 忽略所有可执行文件 (.exe, .o, .out) 与其他无关格式
            return None

        name_lower = raw_file.name.lower()

        # 判断是否为 warmup
        is_warmup = bool(re.search(r"warm\s*up|热身", name_lower))

        # 识别题号
        matched_problem = None
        if self.lab_name == "lab1":
            if "1-2" in name_lower or "1_2" in name_lower or "1.2" in name_lower:
                matched_problem = "1-2"
            elif "1-3" in name_lower or "1_3" in name_lower or "1.3" in name_lower:
                matched_problem = "1-3"
            elif ftype == "image":
                # Lab 1 中图片通常为 1-2 验算截图
                matched_problem = "1-2"
        elif self.lab_name == "lab2":
            if is_warmup:
                matched_problem = "warmup"
            elif "2-1" in name_lower or "2_1" in name_lower or "2.1" in name_lower:
                matched_problem = "2-1"
            elif "2-2" in name_lower or "2_2" in name_lower or "2.2" in name_lower:
                matched_problem = "2-2"
            elif "2-3" in name_lower or "2_3" in name_lower or "2.3" in name_lower:
                matched_problem = "2-3"
            elif "2-4" in name_lower or "2_4" in name_lower or "2.4" in name_lower:
                matched_problem = "2-4"

        # 规范化目标目录
        target_student_dir = self.src_dir / student.student_id
        target_student_dir.mkdir(parents=True, exist_ok=True)

        target_file_path = target_student_dir / raw_file.name
        # 避免同名覆盖，若内容不同则增加区分编号
        if target_file_path.exists():
            if target_file_path.read_bytes() != raw_file.read_bytes():
                stem = raw_file.stem
                target_file_path = target_student_dir / f"{stem}_alt{ext}"

        shutil.copy2(raw_file, target_file_path)

        return SubmissionFile(
            path=target_file_path,
            original_name=raw_file.name,
            file_type=ftype,
            matched_problem=matched_problem,
            is_warmup=is_warmup,
        )
