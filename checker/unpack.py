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

    def _discover_submission_items(self) -> List[Path]:
        """
        发现待评测的提交项。
        支持：
        1. 直接散落在 labX/submit/ 下的学生提交；
        2. 平台导出的总包文件夹 (如 labX/submit/实验一/)；
        3. 平台导出的总包压缩包 (如 labX/submit/实验一.zip)，解压至 .work/labX_container/ 后处理。
        """
        if not self.submit_dir.exists():
            return []

        entries = sorted(list(self.submit_dir.iterdir()))
        items: List[Path] = []

        # 1. 查找是否存在已解压的整批容器目录 (例如 实验一/ 或 lab1/)
        batch_dirs = []
        for e in entries:
            if e.is_dir() and e.name not in IGNORED_PATTERNS and not e.name.startswith("."):
                std, cands, _ = self.roster.match_student_from_text(e.name)
                clean_stem = re.sub(r"[\s_\-]", "", e.name)
                is_batch_name = bool(re.search(rf"^({self.lab_name}|实验[一二三四五六七八九十0-9]+|batch|container|总包)$", clean_stem, re.IGNORECASE))
                if not std and not cands and is_batch_name:
                    batch_dirs.append(e)

        # 2. 查找整批容器压缩包 (例如 实验一.zip)
        batch_zips = []
        for e in entries:
            if e.is_file() and e.suffix.lower() in KNOWN_ARCHIVE_EXTS:
                std, cands, _ = self.roster.match_student_from_text(e.name)
                clean_stem = re.sub(r"[\s_\-]", "", e.stem)
                is_batch_name = bool(re.search(rf"^({self.lab_name}|实验[一二三四五六七八九十0-9]+|batch|container|总包)$", clean_stem, re.IGNORECASE))
                if not std and not cands and is_batch_name:
                    batch_zips.append(e)

        if batch_dirs:
            # 优先使用已存在的解压容器目录
            for bdir in batch_dirs:
                for sub_item in sorted(list(bdir.iterdir())):
                    if sub_item.name not in IGNORED_PATTERNS and not sub_item.name.startswith("."):
                        items.append(sub_item)
        elif batch_zips:
            # 安全解压总包容器至 .work/
            for bzip in batch_zips:
                container_dest = WORK_DIR / f"{self.lab_name}_container" / bzip.stem
                container_dest.mkdir(parents=True, exist_ok=True)
                existing = [p for p in container_dest.iterdir() if p.name not in IGNORED_PATTERNS]
                if not existing:
                    ok, msg, files = self.extractor.extract_container(bzip, container_dest)
                    if not ok:
                        self.unmatched_items.append({"path": str(bzip), "reason": f"总包容器解压失败: {msg}"})
                        continue
                for sub_item in sorted(list(container_dest.iterdir())):
                    if sub_item.name not in IGNORED_PATTERNS and not sub_item.name.startswith("."):
                        items.append(sub_item)
        else:
            # 常规模式：散放于 submit_dir 下的学生文件
            for e in entries:
                if e.name not in IGNORED_PATTERNS and not e.name.startswith("."):
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
                        item_record = self._archive_unattributed_item(entry, reason=f"解压失败: {msg}", candidates=[sid])
                        self.unmatched_items.append(item_record)
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

        if entry.is_file() and entry.suffix.lower() in KNOWN_ARCHIVE_EXTS:
            # 压缩包：建立独立子目录 others/<archive_stem>/，保留原压缩包并解压全部内容
            target_sub_dir = self.others_dir / entry.stem
            if target_sub_dir.exists() and not any(target_sub_dir.iterdir()):
                pass
            elif target_sub_dir.exists():
                source_tag = re.sub(r"[^\w\-.]", "_", entry.parent.name)
                target_sub_dir = self.others_dir / f"{entry.stem}_{source_tag}"

            target_sub_dir.mkdir(parents=True, exist_ok=True)

            # 1. 保存原始压缩包副本，确保来源可完整追溯
            dest_archive = target_sub_dir / entry.name
            try:
                if not dest_archive.exists() or dest_archive.stat().st_size != entry.stat().st_size:
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
            target_sub_dir = self.others_dir / entry.name
            if target_sub_dir.exists():
                source_tag = re.sub(r"[^\w\-.]", "_", entry.parent.name)
                target_sub_dir = self.others_dir / f"{entry.name}_{source_tag}"
            shutil.copytree(entry, target_sub_dir, dirs_exist_ok=True)
            archive_dest_str = f"{self.lab_name}/src/others/{target_sub_dir.name}/"
            for p in target_sub_dir.rglob("*"):
                if p.is_file():
                    archived_files.append(str(p.relative_to(target_sub_dir)))
        else:
            # 独立单文件 (如散放的照片、源码或未识别文件)
            target_file = self.others_dir / entry.name
            if target_file.exists() and target_file.stat().st_size != entry.stat().st_size:
                source_tag = re.sub(r"[^\w\-.]", "_", entry.parent.name)
                target_file = self.others_dir / f"{entry.stem}_{source_tag}{entry.suffix}"
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
        if ext in ALLOWED_SOURCE_EXTS:
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
                try:
                    content = raw_file.read_text(errors="ignore")
                    if any(op in content for op in ["!x", "x||y", "x&&y", "~x", "x|y", "x&y"]):
                        matched_problem = "1-2"
                    elif any(kw in content.lower() for kw in ["32", "celsius", "fahrenheit", "centigrade", "华氏", "摄氏"]):
                        matched_problem = "1-3"
                except Exception:
                    pass
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

        if target_file_path.exists() and target_file_path.is_file():
            if target_file_path.read_bytes() == raw_file.read_bytes():
                # 完全相同内容，去重跳过，避免生成冗余副本
                existing = self.student_files.get(student.student_id, [])
                if any(sf.path == target_file_path for sf in existing):
                    return None
            else:
                stem = target_file_path.stem
                target_file_path = target_file_path.parent / f"{stem}_alt{ext}"

        shutil.copy2(raw_file, target_file_path)

        return SubmissionFile(
            path=target_file_path,
            original_name=raw_file.name,
            file_type=ftype,
            matched_problem=matched_problem,
            is_warmup=is_warmup,
        )
