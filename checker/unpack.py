"""
checker.unpack
提交识别、安全解压、编码兼容与规范化归档模块
"""
import os
import re
import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from checker.ai import HandwrittenReviewer
from checker.config import WORK_DIR
from checker.models import Student, SubmissionFile
from checker.roster import RosterManager

# 允许纳入评测的安全文件扩展名
ALLOWED_SOURCE_EXTS = {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"}
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
ALLOWED_DOC_EXTS = {".docx", ".doc", ".pdf", ".txt", ".md"}
ALLOWED_PROJECT_EXTS = {".cbp"}
ALLOWED_LINK_EXTS = {".lnk"}
KNOWN_ARCHIVE_EXTS = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".rar", ".7z"}

# 忽略的垃圾文件、说明文件与系统隐藏目录
IGNORED_PATTERNS = {
    "__MACOSX", ".DS_Store", "Thumbs.db", "desktop.ini",
    ".git", ".vs", ".vscode", "Debug", "Release", "x64", "x86",
    "README.md", "readme.md", ".gitkeep"
}

# 保留目录 (不能将它们识别为学生目录或参与编译)
RESERVED_DIRS = {"others", "__MACOSX"}

# 手动确认归属清单 (例如教师或助教与学生核验澄清后的散放文件直接确认归属)
MANUAL_ATTRIBUTIONS: Dict[str, str] = {
    "68cbd4b92caa5a802f170c2c28b6fcb1.jpg": "2026110214",  # 胡杨树 (手机号末位26，纸面演算x=14,y=26已人工核验确认)
}


def sanitize_filename(filename: str) -> str:
    """解决 Windows 压缩包在 Linux 下提取可能产生的文件名乱码问题"""
    try:
        decoded = filename.encode("cp437").decode("gbk")
        return decoded
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    try:
        decoded = filename.encode("cp437").decode("utf-8")
        return decoded
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    return filename


def is_valid_source_text_char(ch: str) -> bool:
    """
    检查单个非 ASCII 字符是否属于合法源程序/注释字符。
    包括 CJK 统一汉字、扩展区汉字、常用标点、全半角符号、数学符号、箭头、
    温度与度量衡符号 (℃, ℉, °)、带音调拼音、希腊字母及制表符等。
    绝不能将汉字比例作为硬性通过条件。
    """
    cp = ord(ch)
    return (
        (0x4E00 <= cp <= 0x9FFF)       # CJK Unified Ideographs
        or (0x3400 <= cp <= 0x4DBF)   # CJK Extension A
        or (0x20000 <= cp <= 0x2A6DF) # CJK Extension B
        or (0xF900 <= cp <= 0xFAFF)   # CJK Compatibility Ideographs
        or (0x3000 <= cp <= 0x312F)   # CJK Symbols and Punctuation, Bopomofo
        or (0x3200 <= cp <= 0x33FF)   # Enclosed CJK, CJK Compatibility
        or (0x2000 <= cp <= 0x27FF)   # General Punctuation, Letterlike (℃ 0x2103, ℉ 0x2109), Number Forms, Arrows, Math, Box, Geometric
        or (0xFF00 <= cp <= 0xFFEE)   # Halfwidth and Fullwidth Forms
        or (0x00A0 <= cp <= 0x024F)   # Latin-1 Supplement (如 ° 0x00B0 摄氏度符号等), Latin Extended-A/B
        or (0x0370 <= cp <= 0x04FF)   # Greek and Cyrillic
    )


# 保留别名兼容
is_valid_cjk_or_punct = is_valid_source_text_char


def has_binary_controls(text: str) -> bool:
    """检测文本是否包含二进制文件特有的非打印控制字符 (除常见空白符 \\t, \\n, \\r 外的 0x00-0x08, 0x0B, 0x0E-0x1F)"""
    for ch in text:
        cp = ord(ch)
        if (0 <= cp <= 8) or (cp == 11) or (14 <= cp <= 31):
            return True
    return False


def detect_and_decode_source(raw_bytes: bytes) -> Tuple[bool, str, str, bool, Optional[str]]:
    """
    对源文件/头文件字节流执行严格编码识别与解码。
    返回: (ok: bool, encoding_name: str, decoded_text: str, converted: bool, error_msg: Optional[str])
    严格规则:
    1. 严禁使用 errors='ignore'、errors='replace' 或 Latin-1 无条件兜底。
    2. 支持 UTF-8、UTF-8 BOM、GBK/GB18030、以及有明确依据的 UTF-16 (BOM 或交替 ASCII 结构)。
    3. 识别出非 ASCII 字符必须有充分的 CJK 或合法文本特征，二进制/损坏文件拒绝转码并返回 False。
    """
    if not raw_bytes:
        return True, "utf-8", "", False, None

    # 1. 检查已知 BOM 标识
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        try:
            text = raw_bytes[3:].decode("utf-8")
            if not has_binary_controls(text):
                return True, "utf-8-sig", text, True, None
            return False, "binary", "", False, "文件包含二进制非打印控制字符"
        except UnicodeDecodeError as e:
            return False, "utf-8-sig", "", False, f"UTF-8 BOM 内容损坏: {e}"

    if raw_bytes.startswith(b"\xff\xfe"):
        try:
            text = raw_bytes[2:].decode("utf-16-le")
            if not has_binary_controls(text):
                return True, "utf-16-le", text, True, None
            return False, "binary", "", False, "文件包含二进制非打印控制字符"
        except UnicodeDecodeError as e:
            return False, "utf-16-le", "", False, f"UTF-16LE BOM 内容损坏: {e}"

    if raw_bytes.startswith(b"\xfe\xff"):
        try:
            text = raw_bytes[2:].decode("utf-16-be")
            if not has_binary_controls(text):
                return True, "utf-16-be", text, True, None
            return False, "binary", "", False, "文件包含二进制非打印控制字符"
        except UnicodeDecodeError as e:
            return False, "utf-16-be", "", False, f"UTF-16BE BOM 内容损坏: {e}"

    # 2. 检查无 BOM 的 UTF-16 (必须具备极高置信度的交替高/低位 0x00 特征)
    if len(raw_bytes) >= 4 and len(raw_bytes) % 2 == 0:
        null_high = sum(1 for i in range(1, len(raw_bytes), 2) if raw_bytes[i] == 0)
        if null_high / (len(raw_bytes) // 2) > 0.6:
            try:
                text = raw_bytes.decode("utf-16-le")
                if not has_binary_controls(text):
                    return True, "utf-16-le", text, True, None
            except UnicodeDecodeError:
                pass
        null_low = sum(1 for i in range(0, len(raw_bytes), 2) if raw_bytes[i] == 0)
        if null_low / (len(raw_bytes) // 2) > 0.6:
            try:
                text = raw_bytes.decode("utf-16-be")
                if not has_binary_controls(text):
                    return True, "utf-16-be", text, True, None
            except UnicodeDecodeError:
                pass

    # 3. 严格尝试 UTF-8 解码
    try:
        text = raw_bytes.decode("utf-8")
        if not has_binary_controls(text):
            return True, "utf-8", text, False, None
        return False, "binary", "", False, "文件包含二进制非打印控制字符"
    except UnicodeDecodeError:
        pass

    # 4. 尝试 GBK / GB18030 解码 (校验有效字符特征，支持 ℃、℉ 等温度符号，杜绝二进制误判)
    for enc in ["gb18030", "gbk"]:
        try:
            text = raw_bytes.decode(enc)
            if not has_binary_controls(text):
                non_ascii = [c for c in text if ord(c) > 127]
                if non_ascii:
                    # 允许任意合法文本字符 (包括 ℃, ℉, 汉字, 标点等)，绝不能将汉字比例作为硬性通过条件
                    valid_chars = sum(1 for c in non_ascii if is_valid_source_text_char(c))
                    if valid_chars / len(non_ascii) >= 0.7:
                        return True, "gb18030", text, True, None
                else:
                    return True, "gb18030", text, False, None
        except UnicodeDecodeError:
            pass

    return False, "unknown", "", False, "严格多编码解码均失败 (不支持或损坏编码)"


def is_safe_extract_path(base_dir: Path, target_path: Path) -> bool:
    """
    实际防范 Zip Slip 路径穿越与链接逃逸 (通过 relative_to 严格校验归属性，杜绝同名前缀绕过)
    """
    try:
        resolved_base = base_dir.resolve()
        resolved_target = target_path.resolve()
        # 必须是 resolved_base 的严格子路径
        resolved_target.relative_to(resolved_base)
        return resolved_target != resolved_base
    except (ValueError, Exception):
        return False


class SafeExtractor:
    """负责将学生提交的各类型文件安全解压至工作区"""

    def __init__(self, work_root: Optional[Path] = None):
        self.work_root = work_root or (WORK_DIR / "unpack_scratch")
        self.work_root.mkdir(parents=True, exist_ok=True)

    def extract_archive(
        self,
        archive_path: Path,
        dest_dir: Path,
        max_total_bytes: int = 100 * 1024 * 1024,
        max_files_count: int = 300,
        recursive: bool = True,
        depth: int = 0,
        max_depth: int = 3,
    ) -> Tuple[bool, str, List[Path]]:
        """
        安全解压压缩文件，返回 (是否成功, 状态信息, 提取出的文件列表)
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        suffix = archive_path.suffix.lower()

        extracted_files: List[Path] = []
        total_extracted_bytes = 0

        if suffix == ".zip":
            try:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    for info in zf.infolist():
                        if any(ign in info.filename for ign in IGNORED_PATTERNS):
                            continue

                        raw_name = sanitize_filename(info.filename)
                        if info.is_dir() or raw_name.endswith("/"):
                            continue

                        out_path = dest_dir / raw_name
                        if not is_safe_extract_path(dest_dir, out_path):
                            return False, f"检测到 Zip Slip 恶意路径穿越: {raw_name}", []

                        total_extracted_bytes += info.file_size
                        if total_extracted_bytes > max_total_bytes:
                            return False, "解压体积超过限制 (100MB 限制)，疑似解压炸弹", []

                        if len(extracted_files) >= max_files_count:
                            return False, "解压文件数量过多 (> 300)，中止解压", []

                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, open(out_path, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        extracted_files.append(out_path)

                # 嵌套压缩包递归展开 (处理学生在 zip 内嵌套提交了子 zip 的情况)
                if recursive and depth < max_depth:
                    final_files: List[Path] = []
                    for f in extracted_files:
                        if f.is_file() and f.suffix.lower() in KNOWN_ARCHIVE_EXTS:
                            nested_dest = dest_dir / f"nested_{f.stem}"
                            nested_dest.mkdir(parents=True, exist_ok=True)
                            ok, msg, sub_files = self.extract_archive(
                                archive_path=f,
                                dest_dir=nested_dest,
                                max_total_bytes=max_total_bytes,
                                max_files_count=max_files_count,
                                recursive=True,
                                depth=depth + 1,
                                max_depth=max_depth,
                            )
                            if ok:
                                final_files.extend(sub_files)
                            else:
                                final_files.append(f)
                        else:
                            final_files.append(f)
                    extracted_files = final_files

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
                            continue
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

    def extract_container(self, archive_path: Path, dest_dir: Path) -> Tuple[bool, str, List[Path]]:
        """安全解压整批平台容器包，如 实验一.zip (支持 500MB, 5000文件，不自动递归以便保留每位学生独立zip)"""
        return self.extract_archive(
            archive_path=archive_path,
            dest_dir=dest_dir,
            max_total_bytes=500 * 1024 * 1024,
            max_files_count=5000,
            recursive=False,
        )


class SubmissionNormalizer:
    """
    负责从 labX/submit 读取原始文件，归属到对应学生，并规格化到 labX/src/<student_id>/
    保留学生多级相对目录上下文（如 #include "inc/helper.h"），记录归属冲突。
    """

    def __init__(self, roster_manager: RosterManager, lab_name: str, lab_root: Path):
        self.roster = roster_manager
        self.lab_name = lab_name.lower()  # e.g. "lab1", "lab2"
        self.lab_root = lab_root
        self.submit_dir = lab_root / "submit"
        self.src_dir = lab_root / "src"
        self.others_dir = self.src_dir / "others"
        self.extractor = SafeExtractor(WORK_DIR / f"{self.lab_name}_unpack")

        self.student_files: Dict[str, List[SubmissionFile]] = {}
        self.unmatched_items: List[Dict[str, Any]] = []
        self.ambiguous_items: List[Dict[str, Any]] = []
        # 学号到冲突描述的映射 (供 reporter 查询)
        self.conflict_students: Dict[str, str] = {}
        # 学号到视觉推断审计原因的映射
        self.inferred_students: Dict[str, str] = {}
        # 源码编码转换统计
        self.converted_encoding_count: int = 0
        self.unknown_encoding_files: List[Dict[str, str]] = []

    @property
    def encoding_stats(self) -> Dict[str, Any]:
        """源码编码识别与转码统计"""
        return {
            "converted_count": self.converted_encoding_count,
            "unknown_count": len(self.unknown_encoding_files),
        }

    def _is_container_dir(self, d: Path) -> bool:
        """检查目录是否为包裹了学生提交的容器目录"""
        if d.name in IGNORED_PATTERNS or d.name.startswith("."):
            return False
        # 如果目录名本身直接精确匹配唯一学生，则优先视为该学生的独立提交目录
        std, cands, _ = self.roster.match_student_from_text(d.name)
        if std and len(cands) == 1:
            return False

        # 目录名符合明显批次特征 (实验一, lab1, batch, etc.)
        clean_stem = re.sub(r"[\s_\-]", "", d.name)
        if re.search(rf"^({self.lab_name}|实验[一二三四五六七八九十0-9]+|batch|container|总包)$", clean_stem, re.IGNORECASE):
            return True

        # 检查内部是否包含可归属的学生提交 (扫描子文件/子目录)
        try:
            for p in d.rglob("*"):
                if p.name.startswith(".") or p.name in IGNORED_PATTERNS:
                    continue
                child_std, child_cands, _ = self.roster.match_student_from_text(p.name)
                if child_std or child_cands:
                    return True
                if p.is_file() and p.suffix.lower() in KNOWN_ARCHIVE_EXTS:
                    if self.roster.match_student_from_text(p.stem)[0]:
                        return True
        except Exception:
            pass
        return False

    def _is_container_archive(self, archive_path: Path) -> bool:
        """检查压缩包是否为总包容器"""
        std, cands, _ = self.roster.match_student_from_text(archive_path.name)
        if std and len(cands) == 1:
            return False

        clean_stem = re.sub(r"[\s_\-]", "", archive_path.stem)
        if re.search(rf"^({self.lab_name}|实验[一二三四五六七八九十0-9]+|batch|container|总包)$", clean_stem, re.IGNORECASE):
            return True

        # 检查压缩包内文件名列表是否包含可归属学生
        try:
            if zipfile.is_zipfile(archive_path):
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    for name in zf.namelist():
                        fname = Path(name).name
                        if fname and not fname.startswith(".") and fname not in IGNORED_PATTERNS:
                            c_std, c_cands, _ = self.roster.match_student_from_text(fname)
                            if c_std or c_cands:
                                return True
            elif tarfile.is_tarfile(archive_path):
                with tarfile.open(archive_path, 'r:*') as tf:
                    for name in tf.getnames():
                        fname = Path(name).name
                        if fname and not fname.startswith(".") and fname not in IGNORED_PATTERNS:
                            c_std, c_cands, _ = self.roster.match_student_from_text(fname)
                            if c_std or c_cands:
                                return True
        except Exception:
            pass
        return False

    def _discover_submission_items(self) -> List[Path]:
        """
        发现待评测的提交项。
        支持：
        1. 直接散落在 labX/submit/ 下的学生提交；
        2. 包含学生提交的各级总包/批次文件夹 (如 实验一/、学生作业/)；
        3. 平台导出的总包压缩包 (如 实验一.zip)，解压至 .work/labX_container/ 后展开。
        """
        if not self.submit_dir.exists():
            return []

        entries = sorted(list(self.submit_dir.iterdir()))
        items: List[Path] = []
        handled_container_stems: Set[str] = set()

        def collect_from_dir(d: Path):
            for sub_item in sorted(list(d.iterdir())):
                if sub_item.name.startswith(".") or sub_item.name in IGNORED_PATTERNS:
                    continue
                if sub_item.is_dir() and self._is_container_dir(sub_item):
                    collect_from_dir(sub_item)
                else:
                    items.append(sub_item)

        # 1. 优先扫描并展开容器目录
        container_dirs = []
        regular_entries = []
        for e in entries:
            if e.name.startswith(".") or e.name in IGNORED_PATTERNS:
                continue
            if e.is_dir() and self._is_container_dir(e):
                container_dirs.append(e)
                clean_tag = re.sub(r"[\s_\-]", "", e.name).lower()
                handled_container_stems.add(clean_tag)
            else:
                regular_entries.append(e)

        for cdir in container_dirs:
            collect_from_dir(cdir)

        # 2. 查找并解压总包容器压缩包 (未解压为同名容器目录的)
        remaining_entries = []
        for e in regular_entries:
            clean_stem = re.sub(r"[\s_\-]", "", e.stem).lower()
            if e.is_file() and e.suffix.lower() in KNOWN_ARCHIVE_EXTS and self._is_container_archive(e):
                if clean_stem not in handled_container_stems:
                    container_dest = WORK_DIR / f"{self.lab_name}_container" / e.stem
                    container_dest.mkdir(parents=True, exist_ok=True)
                    existing = [p for p in container_dest.iterdir() if p.name not in IGNORED_PATTERNS]
                    if not existing:
                        ok, msg, files = self.extractor.extract_container(e, container_dest)
                        if not ok:
                            self.unmatched_items.append({"path": str(e), "reason": f"总包容器解压失败: {msg}"})
                            continue
                    collect_from_dir(container_dest)
                    handled_container_stems.add(clean_stem)
            else:
                remaining_entries.append(e)

        # 3. 散放于 submit_dir 下的学生提交文件或未识别项
        for e in remaining_entries:
            items.append(e)

        return items

    def process_all_submissions(self) -> Dict[str, List[SubmissionFile]]:
        """执行全量处理流水线"""
        self.src_dir.mkdir(parents=True, exist_ok=True)
        self.others_dir.mkdir(parents=True, exist_ok=True)
        readme_path = self.others_dir / "README.md"
        if not readme_path.exists():
            readme_path.write_text(
                "# 无法归属文件归档目录 (others)\n\n"
                "本目录用于统一保存按学号分类时无法确定学生归属的提交文件与异常数据包，便于后续联系学生核实。\n"
                "判题机在扫描与评测时将忽略此目录。\n",
                encoding="utf-8"
            )

        items = self._discover_submission_items()
        if not items:
            return {}

        matched_items_by_student: Dict[str, List[Path]] = {}
        unmatched_candidate_items: List[Path] = []

        # 第一阶段：按文件名对点名册进行第一轮身份匹配
        for entry in items:
            if entry.name.startswith(".") or entry.name in IGNORED_PATTERNS or entry.name.lower() in {"readme.md", ".gitkeep"}:
                continue

            student, candidates, reason = self.roster.match_student_from_text(entry.name)

            # 检查手动人工核验清单
            if not student and entry.name in MANUAL_ATTRIBUTIONS:
                manual_sid = MANUAL_ATTRIBUTIONS[entry.name]
                student = self.roster.find_student_by_id(manual_sid)
                if student:
                    candidates = [student]
                    reason = f"人工核验确认归属: {manual_sid}"

            if len(candidates) > 1:
                conflict_ids = [c.student_id for c in candidates]
                conflict_msg = f"提交包同时包含多个候选学号: {conflict_ids} (原因: {reason})"
                item_record = self._archive_unattributed_item(entry, reason=conflict_msg, candidates=conflict_ids)
                self.ambiguous_items.append(item_record)
                for cid in conflict_ids:
                    self.conflict_students[cid] = conflict_msg
                continue

            if student:
                matched_items_by_student.setdefault(student.student_id, []).append(entry)
            else:
                unmatched_candidate_items.append(entry)

        # 解压并规范化已匹配学生的提交文件
        for sid, entry_list in matched_items_by_student.items():
            student = self.roster.find_student_by_id(sid)
            if not student:
                continue

            for entry in entry_list:
                extracted_items: List[Path] = []
                root_dir: Optional[Path] = None

                if entry.is_file() and entry.suffix.lower() in KNOWN_ARCHIVE_EXTS:
                    unpack_dest = WORK_DIR / f"{self.lab_name}_unpack" / f"{sid}_{entry.stem}"
                    unpack_dest.mkdir(parents=True, exist_ok=True)
                    success, msg, files = self.extractor.extract_archive(entry, unpack_dest, recursive=True)
                    if not success:
                        # 记录已收到该学生压缩包，但文件损坏无法解压，保留在学生目录中
                        student_src_dir = self.src_dir / sid
                        student_src_dir.mkdir(parents=True, exist_ok=True)
                        dest_archive = student_src_dir / entry.name
                        try:
                            if not dest_archive.exists() or dest_archive.resolve() != entry.resolve():
                                shutil.copy2(entry, dest_archive)
                        except Exception:
                            dest_archive = entry

                        corrupt_file = SubmissionFile(
                            path=dest_archive,
                            original_name=entry.name,
                            file_type="corrupt_archive",
                            note=f"解压失败: {msg}",
                        )
                        self.student_files.setdefault(sid, []).append(corrupt_file)
                        continue
                    extracted_items = files
                    root_dir = unpack_dest
                elif entry.is_dir():
                    for root, _, fs in os.walk(entry):
                        for f in fs:
                            extracted_items.append(Path(root) / f)
                    root_dir = entry
                elif entry.is_file():
                    extracted_items = [entry]
                    root_dir = entry.parent

                # 若解压包内只有一个顶层包裹文件夹，去除该单层包裹以获得真实代码根目录
                effective_root = root_dir
                if root_dir and root_dir.exists():
                    top_items = [p for p in root_dir.iterdir() if p.name not in IGNORED_PATTERNS]
                    if len(top_items) == 1 and top_items[0].is_dir():
                        effective_root = top_items[0]

                for file_path in extracted_items:
                    if any(ign in file_path.name for ign in IGNORED_PATTERNS):
                        continue

                    rel_path = file_path.name
                    if effective_root and file_path.is_relative_to(effective_root):
                        rel_path = str(file_path.relative_to(effective_root))

                    sub_file = self._classify_and_stage_file(student, file_path, rel_path)
                    if sub_file:
                        self.student_files.setdefault(student.student_id, []).append(sub_file)

        # 第二阶段：对无法通过文件名识别的独立文件（如照片或测试包）进行多模态视觉核验与内容检查
        # 收集当前尚未归属照片的学生池，用于推断候选过滤
        students_without_image = [
            s for s in self.roster.students
            if not any(f.file_type == "image" for f in self.student_files.get(s.student_id, []))
        ]

        for entry in unmatched_candidate_items:
            ext = entry.suffix.lower()
            if ext in ALLOWED_IMAGE_EXTS:
                # 视觉模型识别演草纸照片
                matched_std, ident_info = HandwrittenReviewer.identify_student_from_image(
                    entry, self.roster, candidate_students=students_without_image
                )
                if matched_std:
                    method = ident_info.get("method", "param_x")
                    if method == "param_x":
                        reason = f"演草纸未写学号姓名，根据推导参数 x={ident_info.get('x')} 视觉识别推断归属，需人工复核确认"
                    else:
                        reason = f"演草纸通过视觉提取身份信息（{method}）归属，需人工复核确认"
                    self.inferred_students[matched_std.student_id] = reason
                    sub_file = self._classify_and_stage_file(matched_std, entry, entry.name)
                    if sub_file:
                        self.student_files.setdefault(matched_std.student_id, []).append(sub_file)
                        # 更新已拥有照片的学生池
                        if matched_std in students_without_image:
                            students_without_image.remove(matched_std)
                else:
                    item_record = self._archive_unattributed_item(
                        entry,
                        reason=f"手写照片视觉识别未能唯一定位点名册学生: {ident_info.get('reason', '')}",
                        candidates=[s.student_id for s in students_without_image] if len(students_without_image) <= 3 else []
                    )
                    self.unmatched_items.append(item_record)
            elif ext in KNOWN_ARCHIVE_EXTS:
                # 检查是否为测试包
                test_unpack = WORK_DIR / "test_inspect" / entry.stem
                test_unpack.mkdir(parents=True, exist_ok=True)
                ok, msg, test_files = self.extractor.extract_archive(entry, test_unpack, recursive=False)
                c_files = [f for f in test_files if f.suffix.lower() in ALLOWED_SOURCE_EXTS]
                if not c_files:
                    item_record = self._archive_unattributed_item(
                        entry,
                        reason="测试数据包 (仅含 penguins-selected.csv，无学号且无 C 源码)",
                    )
                    self.unmatched_items.append(item_record)
                else:
                    item_record = self._archive_unattributed_item(
                        entry,
                        reason=f"未匹配学生但含源程序: {[f.name for f in c_files]}",
                    )
                    self.unmatched_items.append(item_record)
            else:
                item_record = self._archive_unattributed_item(
                    entry,
                    reason=f"未匹配点名册学生的文件: {entry.name}",
                )
                self.unmatched_items.append(item_record)

        return self.student_files

    def _archive_unattributed_item(
        self,
        entry: Path,
        reason: str,
        candidates: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        将无法确定学生归属的提交文件统一归档至 labX/src/others/。
        保持原始 submit 目录内容只读不变，保留原文件名及必要的相对目录；同名文件不覆盖，完整记录来源。
        """
        self.others_dir.mkdir(parents=True, exist_ok=True)
        candidates = candidates or []
        archived_files: List[str] = []

        # 来源标识：如果父目录不是 submit 根目录或保留目录，则记录父目录名作为来源标识
        source_tag = ""
        if entry.parent.resolve() != self.submit_dir.resolve() and entry.parent.name not in {"submit", "", self.lab_name}:
            source_tag = re.sub(r"[^\w\-.]", "_", entry.parent.name)

        if entry.is_file() and entry.suffix.lower() in KNOWN_ARCHIVE_EXTS:
            # 压缩包：建立独立子目录 others/<archive_stem>/，保留原压缩包并解压全部内容
            base_dir_name = f"{entry.stem}_{source_tag}" if source_tag else entry.stem
            target_sub_dir = self.others_dir / base_dir_name
            idx = 2
            while target_sub_dir.exists():
                target_sub_dir = self.others_dir / f"{base_dir_name}_{idx}"
                idx += 1

            target_sub_dir.mkdir(parents=True, exist_ok=True)

            # 1. 保存原始压缩包副本，确保来源可完整追溯
            dest_archive = target_sub_dir / entry.name
            try:
                shutil.copy2(entry, dest_archive)
                archived_files.append(dest_archive.name)
            except Exception:
                pass

            # 2. 安全解压内部全部文件，保持相对路径
            success, msg, files = self.extractor.extract_archive(entry, target_sub_dir, recursive=True)
            if success:
                for f in files:
                    try:
                        rel = str(f.relative_to(target_sub_dir))
                        archived_files.append(rel)
                    except Exception:
                        archived_files.append(f.name)

            archive_dest_str = f"{self.lab_name}/src/others/{target_sub_dir.name}/"
        elif entry.is_dir():
            base_dir_name = f"{entry.name}_{source_tag}" if source_tag else entry.name
            target_sub_dir = self.others_dir / base_dir_name
            idx = 2
            while target_sub_dir.exists():
                target_sub_dir = self.others_dir / f"{base_dir_name}_{idx}"
                idx += 1

            shutil.copytree(entry, target_sub_dir)
            archive_dest_str = f"{self.lab_name}/src/others/{target_sub_dir.name}/"
            for p in target_sub_dir.rglob("*"):
                if p.is_file():
                    archived_files.append(str(p.relative_to(target_sub_dir)))
        else:
            # 独立单文件 (如散放的照片、源码或未识别文件)
            base_filename = f"{entry.stem}_{source_tag}{entry.suffix}" if source_tag else entry.name
            target_file = self.others_dir / base_filename
            idx = 2
            while target_file.exists():
                if source_tag:
                    target_file = self.others_dir / f"{entry.stem}_{source_tag}_{idx}{entry.suffix}"
                else:
                    target_file = self.others_dir / f"{entry.stem}_{idx}{entry.suffix}"
                idx += 1

            try:
                shutil.copy2(entry, target_file)
                archived_files.append(target_file.name)
            except Exception:
                pass
            archive_dest_str = f"{self.lab_name}/src/others/{target_file.name}"

        return {
            "path": str(entry),
            "archive_dest": archive_dest_str,
            "source_archive": entry.name,
            "reason": reason,
            "candidates": candidates,
            "status": "无法归属、待复核",
            "archived_files": archived_files,
        }

    def _classify_and_stage_file(
        self,
        student: Student,
        raw_file: Path,
        rel_path_str: str,
    ) -> Optional[SubmissionFile]:
        """识别文件题号、保留相对子目录结构，安全拷贝至 labX/src/<student_id>/"""
        ext = raw_file.suffix.lower()
        is_source = ext in ALLOWED_SOURCE_EXTS
        if is_source:
            ftype = "c_source" if ext in {".c", ".h"} else "cpp_source"
        elif ext in ALLOWED_IMAGE_EXTS:
            ftype = "image"
        elif ext in ALLOWED_DOC_EXTS:
            ftype = "document"
        elif ext in ALLOWED_PROJECT_EXTS:
            ftype = "project"
        elif ext in ALLOWED_LINK_EXTS:
            ftype = "link"
        elif ext in {".exe", ".bin", ".out"}:
            ftype = "executable"
        else:
            return None

        # 源文件编码识别与 UTF-8 规范化
        source_encoding = "binary"
        encoding_converted = False
        encoding_error = ""
        content_for_matching = ""

        raw_bytes = raw_file.read_bytes()
        if is_source:
            ok, enc, text, conv, err = detect_and_decode_source(raw_bytes)
            source_encoding = enc
            encoding_converted = conv
            if ok:
                final_bytes = text.encode("utf-8")
                content_for_matching = text
                if conv:
                    self.converted_encoding_count += 1
            else:
                final_bytes = raw_bytes
                encoding_error = err or "未知或损坏编码"
                self.unknown_encoding_files.append({
                    "path": str(raw_file),
                    "student_id": student.student_id,
                    "error": encoding_error,
                })
        else:
            final_bytes = raw_bytes

        name_lower = raw_file.name.lower()
        search_target = f"{rel_path_str} {raw_file.name}".lower()
        is_warmup = bool(re.search(r"warm\s*up|热身", search_target))

        matched_problem = None
        if self.lab_name == "lab1":
            # 严格边界匹配 1-3 与 1-2，避免学号中包含 "12"（如 20261112xx）或 "13" 导致误判
            is_p13 = bool(re.search(r"lab\s*1\s*[-_.]?\s*3(?!\d)|(?<!\d)1\s*[-_.]\s*3(?!\d)|(?<!\d)13(?!\d)|温度", search_target))
            is_p12 = bool(re.search(r"lab\s*1\s*[-_.]?\s*2(?!\d)|(?<!\d)1\s*[-_.]\s*2(?!\d)|(?<!\d)12(?!\d)|逻辑|验算|草稿|演草", search_target))
            if is_p13 and not is_p12:
                matched_problem = "1-3"
            elif is_p12 and not is_p13:
                matched_problem = "1-2"
            elif is_p13 and is_p12:
                if "1-3" in search_target or "1_3" in search_target or "1.3" in search_target:
                    matched_problem = "1-3"
                else:
                    matched_problem = "1-2"
            elif ftype == "image":
                matched_problem = "1-2"
            elif ftype in ("c_source", "cpp_source"):
                # 内容兜底分析（针对如张辰越将 Lab 1-2 源码误命名为 Lab 1-1 等情况）
                # 统一使用严格解码规范化后的文本，严禁使用 errors="ignore" 掩盖乱码
                if content_for_matching:
                    if any(op in content_for_matching for op in ["!x", "x||y", "x&&y", "~x", "x|y", "x&y"]):
                        matched_problem = "1-2"
                    elif any(kw in content_for_matching.lower() for kw in ["32", "celsius", "fahrenheit", "centigrade", "华氏", "摄氏"]):
                        matched_problem = "1-3"
        elif self.lab_name == "lab2":
            if is_warmup:
                matched_problem = "warmup"
            elif re.search(r"lab\s*2\s*[-_.]?\s*1(?!\d)|(?<!\d)2\s*[-_.]\s*1(?!\d)|(?<!\d)21(?!\d)|问候", search_target):
                matched_problem = "2-1"
            elif re.search(r"lab\s*2\s*[-_.]?\s*2(?!\d)|(?<!\d)2\s*[-_.]\s*2(?!\d)|(?<!\d)22(?!\d)|金字塔", search_target):
                matched_problem = "2-2"
            elif re.search(r"lab\s*2\s*[-_.]?\s*3(?!\d)|(?<!\d)2\s*[-_.]\s*3(?!\d)|(?<!\d)23(?!\d)|回文", search_target):
                matched_problem = "2-3"
            elif re.search(r"lab\s*2\s*[-_.]?\s*4(?!\d)|(?<!\d)2\s*[-_.]\s*4(?!\d)|(?<!\d)24(?!\d)|编码器", search_target):
                matched_problem = "2-4"

        target_student_dir = self.src_dir / student.student_id
        target_student_dir.mkdir(parents=True, exist_ok=True)

        target_file_path = target_student_dir / rel_path_str
        target_file_path.parent.mkdir(parents=True, exist_ok=True)

        existing_files = self.student_files.get(student.student_id, [])

        stem = target_file_path.stem
        matched_target_path: Optional[Path] = None
        write_needed = True

        # 检查候选路径族 [target, target_alt, target_alt2, ...]
        # 优先复用或去重完全相同内容的文件，避免同一路径多次提交相同内容生成 _alt2、_alt3 导致重复编译
        curr_alt_idx = 1
        check_path = target_file_path
        while True:
            if check_path.exists() and check_path.is_file():
                check_bytes = check_path.read_bytes()
                if check_bytes == final_bytes:
                    if any(sf.path == check_path for sf in existing_files):
                        # 本批次中已登记过该完全相同内容候选（如 A, B, B 中的第二个 B），直接去重跳过
                        return None
                    matched_target_path = check_path
                    write_needed = False
                    break
                elif is_source and check_bytes == raw_bytes:
                    # 磁盘文件为历史未转码的原始字节，就地规范化覆盖
                    matched_target_path = check_path
                    write_needed = True
                    break
                else:
                    curr_alt_idx += 1
                    alt_name = f"{stem}_alt{ext}" if curr_alt_idx == 2 else f"{stem}_alt{curr_alt_idx - 1}{ext}"
                    check_path = target_file_path.parent / alt_name
            else:
                matched_target_path = check_path
                write_needed = True
                break

        target_file_path = matched_target_path

        if write_needed:
            if is_source:
                target_file_path.write_bytes(final_bytes)
            else:
                shutil.copy2(raw_file, target_file_path)

        return SubmissionFile(
            path=target_file_path,
            original_name=raw_file.name,
            file_type=ftype,
            matched_problem=matched_problem,
            is_warmup=is_warmup,
            source_encoding=source_encoding,
            encoding_converted=encoding_converted,
            encoding_error=encoding_error,
        )
