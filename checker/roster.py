"""
checker.roster
点名册解析与学生身份匹配模块
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from checker.models import Student


class RosterManager:
    """管理课程点名册数据并提供学生身份对齐服务"""

    def __init__(self, roster_path: Optional[Path] = None):
        self.roster_path = roster_path
        self.students: List[Student] = []
        self.by_id: Dict[str, Student] = {}
        self.by_name: Dict[str, List[Student]] = {}

        if self.roster_path and Path(self.roster_path).exists():
            self.load_roster(Path(self.roster_path))

    def load_roster(self, path: Path) -> List[Student]:
        """支持加载 .xls 与 .xlsx 格式点名册"""
        self.roster_path = path
        self.students.clear()
        self.by_id.clear()
        self.by_name.clear()

        suffix = path.suffix.lower()
        if suffix == ".xls":
            self._load_xls(path)
        elif suffix == ".xlsx":
            self._load_xlsx(path)
        else:
            raise ValueError(f"不支持的点名册文件格式: {suffix}，仅支持 .xls 与 .xlsx")

        for s in self.students:
            self.by_id[s.student_id] = s
            self.by_name.setdefault(s.name, []).append(s)

        return self.students

    def _load_xls(self, path: Path):
        import xlrd
        workbook = xlrd.open_workbook(str(path))
        sheet = workbook.sheet_by_index(0)

        header_row = -1
        id_col = -1
        name_col = -1
        seq_col = 0
        gender_col = -1
        college_col = -1
        major_col = -1
        class_col = -1

        for r in range(sheet.nrows):
            row = [str(sheet.cell_value(r, c)).strip() for c in range(sheet.ncols)]
            for c, val in enumerate(row):
                if "学号" in val:
                    header_row = r
                    id_col = c
                elif "姓名" in val:
                    name_col = c
                elif "序号" in val:
                    seq_col = c
                elif "性别" in val:
                    gender_col = c
                elif "学院" in val:
                    college_col = c
                elif "专业" in val:
                    major_col = c
                elif "班级" in val:
                    class_col = c
            if header_row != -1 and id_col != -1 and name_col != -1:
                break

        if header_row == -1:
            raise ValueError(f"点名册 {path.name} 中未找到包含'学号'与'姓名'的表头行")

        for r in range(header_row + 1, sheet.nrows):
            raw_id = str(sheet.cell_value(r, id_col)).strip()
            # 兼容数字浮点转字符串
            if raw_id.endswith(".0"):
                raw_id = raw_id[:-2]
            if not raw_id:
                continue

            raw_name = str(sheet.cell_value(r, name_col)).strip()
            seq_val = sheet.cell_value(r, seq_col) if seq_col >= 0 else len(self.students) + 1
            try:
                seq = int(float(seq_val))
            except (ValueError, TypeError):
                seq = len(self.students) + 1

            gender = str(sheet.cell_value(r, gender_col)).strip() if gender_col >= 0 else ""
            college = str(sheet.cell_value(r, college_col)).strip() if college_col >= 0 else ""
            major = str(sheet.cell_value(r, major_col)).strip() if major_col >= 0 else ""
            class_id = str(sheet.cell_value(r, class_col)).strip() if class_col >= 0 else ""
            if class_id.endswith(".0"):
                class_id = class_id[:-2]

            student = Student(
                seq=seq,
                student_id=raw_id,
                name=raw_name,
                gender=gender,
                college=college,
                major=major,
                class_id=class_id,
            )
            self.students.append(student)

    def _load_xlsx(self, path: Path):
        import openpyxl
        wb = openpyxl.load_workbook(str(path), data_only=True)
        sheet = wb.active

        header_row = -1
        id_col = -1
        name_col = -1
        seq_col = 1
        gender_col = -1
        college_col = -1
        major_col = -1
        class_col = -1

        for r in range(1, sheet.max_row + 1):
            row = [str(sheet.cell(r, c).value or "").strip() for c in range(1, sheet.max_column + 1)]
            for c_idx, val in enumerate(row, start=1):
                if "学号" in val:
                    header_row = r
                    id_col = c_idx
                elif "姓名" in val:
                    name_col = c_idx
                elif "序号" in val:
                    seq_col = c_idx
                elif "性别" in val:
                    gender_col = c_idx
                elif "学院" in val:
                    college_col = c_idx
                elif "专业" in val:
                    major_col = c_idx
                elif "班级" in val:
                    class_col = c_idx
            if header_row != -1 and id_col != -1 and name_col != -1:
                break

        if header_row == -1:
            raise ValueError(f"点名册 {path.name} 中未找到包含'学号'与'姓名'的表头行")

        for r in range(header_row + 1, sheet.max_row + 1):
            raw_id = str(sheet.cell(r, id_col).value or "").strip()
            if raw_id.endswith(".0"):
                raw_id = raw_id[:-2]
            if not raw_id:
                continue

            raw_name = str(sheet.cell(r, name_col).value or "").strip()
            seq_val = sheet.cell(r, seq_col).value if seq_col > 0 else len(self.students) + 1
            try:
                seq = int(float(seq_val))
            except (ValueError, TypeError):
                seq = len(self.students) + 1

            gender = str(sheet.cell(r, gender_col).value or "").strip() if gender_col > 0 else ""
            college = str(sheet.cell(r, college_col).value or "").strip() if college_col > 0 else ""
            major = str(sheet.cell(r, major_col).value or "").strip() if major_col > 0 else ""
            class_id = str(sheet.cell(r, class_col).value or "").strip() if class_col > 0 else ""
            if class_id.endswith(".0"):
                class_id = class_id[:-2]

            self.students.append(
                Student(
                    seq=seq,
                    student_id=raw_id,
                    name=raw_name,
                    gender=gender,
                    college=college,
                    major=major,
                    class_id=class_id,
                )
            )

    def find_student_by_id(self, student_id: str) -> Optional[Student]:
        """精确学号查询"""
        return self.by_id.get(student_id)

    def match_student_from_text(self, text: str) -> Tuple[Optional[Student], List[Student], str]:
        """
        从文件名、目录名或压缩包名中匹配学生身份
        返回 (唯一匹配学生, 候选冲突列表, 匹配依据描述)
        """
        clean_text = text.replace(" ", "").replace("_", "").replace("-", "")

        # 1. 优先在文本中查找完整的已知花名册学号（按长度从长到短匹配）
        matched_ids = []
        for sid, student in sorted(self.by_id.items(), key=lambda x: len(x[0]), reverse=True):
            if sid in text or sid in clean_text:
                matched_ids.append(student)

        if len(matched_ids) == 1:
            return matched_ids[0], [], f"精确匹配花名册学号 {matched_ids[0].student_id}"
        elif len(matched_ids) > 1:
            # 多个学号命中
            return None, matched_ids, f"多个学号冲突: {[s.student_id for s in matched_ids]}"

        # 2. 匹配姓名（先按名字长度从长到短，防止包含短名误判）
        matched_names = []
        for name, std_list in sorted(self.by_name.items(), key=lambda x: len(x[0]), reverse=True):
            if len(name) >= 2 and (name in text or name in clean_text):
                matched_names.extend(std_list)

        if len(matched_names) == 1:
            return matched_names[0], [], f"精确匹配花名册姓名 {matched_names[0].name}"
        elif len(matched_names) > 1:
            # 同名或多个姓名冲突
            return None, matched_names, f"同名或多姓名冲突: {[s.name + '(' + s.student_id + ')' for s in matched_names]}"

        # 3. 正则提取 8~12 位连续数字作为疑似学号
        digits = re.findall(r"\b(\d{8,12})\b", text)
        for d in digits:
            if d in self.by_id:
                return self.by_id[d], [], f"正则识别并匹配学号 {d}"

        return None, [], "未匹配到任何已知学号或姓名"
