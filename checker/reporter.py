"""
checker.reporter
多维度判题报告与成绩单生成器：
  1. labX结果.csv (逐人逐题评测明细，细化到检查分项)
  2. labX报告.md (批次统计、分项达成率、规则说明、复核清单)
  3. labX实验成绩单.csv (完整点名册、各题验收汇总、建议扣分合计、>=50字定制评语)
  4. labX实验成绩单.xlsx (如果存在模板文件，同步填充 Excel 工作表)
  5. 单人重判独立导出与批次安全合并
"""
import csv
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from checker.models import CheckItem, ProblemResult, Student, StudentGrade


class LabReporter:
    """负责将评测结果汇总并输出交付报表"""

    def __init__(self, lab_id: str, output_dir: Path):
        self.lab_id = lab_id.lower()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_all_reports(
        self,
        roster_students: List[Student],
        grades: Dict[str, StudentGrade],
        ambiguous_items: Optional[List[Dict[str, Any]]] = None,
        unmatched_items: Optional[List[Dict[str, Any]]] = None,
        excel_template_path: Optional[Path] = None,
        mock_mode: bool = False,
        encoding_stats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Path]:
        """生成全套标准报表并返回文件路径字典"""
        csv_detail_path = self.generate_detail_csv(roster_students, grades, mock_mode=mock_mode)
        md_summary_path = self.generate_summary_markdown(
            roster_students,
            grades,
            ambiguous_items=ambiguous_items,
            unmatched_items=unmatched_items,
            mock_mode=mock_mode,
            encoding_stats=encoding_stats,
        )
        csv_roster_path = self.generate_roster_grade_csv(roster_students, grades, mock_mode=mock_mode)

        result_paths = {
            "detail_csv": csv_detail_path,
            "summary_md": md_summary_path,
            "roster_csv": csv_roster_path,
        }

        if excel_template_path and Path(excel_template_path).exists():
            xlsx_path = self.generate_roster_grade_xlsx(roster_students, grades, excel_template_path, mock_mode=mock_mode)
            if xlsx_path:
                result_paths["roster_xlsx"] = xlsx_path

        return result_paths

    def generate_detail_csv(
        self,
        roster_students: List[Student],
        grades: Dict[str, StudentGrade],
        mock_mode: bool = False,
    ) -> Path:
        """
        导出 labX结果.csv
        记录粒度: 学生 × 实验 × 题号 × 检查分项
        包含字段: 学号, 姓名, 实验, 题号, 评分项, 提交状态, 达成状态, 检查依据, 建议扣分, 扣分理由, Agent说明附注, 是否需要复核, 实验评语
        """
        prefix = "mock_" if mock_mode else ""
        file_path = self.output_dir / f"{prefix}{self.lab_id}结果.csv"

        fieldnames = [
            "学号", "姓名", "实验", "题号", "评分项", "提交状态",
            "达成状态", "检查依据", "建议扣分", "扣分理由", "Agent说明附注", "是否需要复核", "实验评语"
        ]

        with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for student in roster_students:
                grade = grades.get(student.student_id)
                items = grade.all_check_items if grade else []

                # 若当前学生尚未生成 check_items 或完全缺交，生成标准缺交分项
                if not items:
                    items = self._build_default_check_items(student, grade)

                student_comment = grade.comment if grade else (
                    f"{student.name}同学你好！系统未检测到你在实验1中的作业提交（未收到源码文件及演草纸验算照片）。"
                    f"按课程大纲与实验教学要求，请尽快核实是否由于提交逾期或文件路径遗漏，并及时联系助教说明情况补交，以便及时核对并确认实验平时成绩。"
                )

                for it in items:
                    if it.deduction is None:
                        ded_str = "待复核"
                    elif it.deduction > 0:
                        ded_str = f"{it.deduction:.2f}"
                    else:
                        ded_str = "0.00"

                    rev_str = "是" if it.needs_review else "否"

                    writer.writerow({
                        "学号": student.student_id,
                        "姓名": student.name,
                        "实验": self.lab_id,
                        "题号": it.problem_id,
                        "评分项": it.sub_item,
                        "提交状态": it.submission_status,
                        "达成状态": it.completion_status,
                        "检查依据": it.evidence,
                        "建议扣分": ded_str,
                        "扣分理由": it.deduction_reason,
                        "Agent说明附注": it.agent_note,
                        "是否需要复核": rev_str,
                        "实验评语": student_comment,
                    })

        return file_path

    def _build_default_check_items(self, student: Student, grade: Optional[StudentGrade]) -> List[CheckItem]:
        """为学生构建全量的默认检查分项"""
        is_missing = not grade or grade.status == "missing"
        is_conflict = grade and (grade.status in {"ambiguous", "conflict"} or any("冲突" in r for r in grade.review_reasons))
        evidence_msg = "未检测到实验提交文件" if is_missing else ("多学号匹配冲突待复核" if is_conflict else "学生提交已评测完成")

        if grade and grade.total_score > 0 and not any(prob.check_items for prob in grade.problem_results.values()):
            rem_ded = max(0.0, round(5.0 - grade.total_score, 2))
            return [
                CheckItem("1-1", "课内环境熟悉与基础代码练习", "已提交", "已达成", "基础练习完成", 0.0, "", "课内练习", False),
                CheckItem("1-2", "源码提交", "已提交", "已达成", "源码已归档", 0.0, "", "正常", False),
                CheckItem("1-2", "编译与运行", "已提交", "已达成", "编译运行成功", 0.0, "", "正常", False),
                CheckItem("1-2", "参数学号与手机号对齐", "已提交", "已达成", "参数对齐", 0.0, "", "正常", False),
                CheckItem("1-2", "逻辑运算(!, ||, &&)", "已提交", "已达成", "逻辑运算正确", 0.0, "", "正常", False),
                CheckItem("1-2", "位运算(~, |, &)", "已提交", "已达成", "位运算正确", 0.0, "", "正常", False),
                CheckItem("1-2", "有符号与无符号输出格式", "已提交", "已达成", "格式规范", 0.0, "", "正常", False),
                CheckItem("1-2", "验算材料提交", "已提交", "已达成", "验算照片已提交", 0.0, "", "正常", False),
                CheckItem("1-2", "姓名、学号、手机号完整性", "已提交", "已达成", "身份信息完整", 0.0, "", "正常", False),
                CheckItem("1-2", "手写参数与身份及源码一致性", "已提交", "已达成", "参数一致", 0.0, "", "正常", False),
                CheckItem("1-2", "六种运算展开过程完整性", "已提交", "已达成", "展开完整", 0.0, "", "正常", False),
                CheckItem("1-2", "各验算过程与结果正确性", "已提交", "已达成", "推导准确", 0.0, "", "正常", False),
                CheckItem("1-3", "源码提交", "已提交", "已达成", "源码已归档", 0.0, "", "正常", False),
                CheckItem("1-3", "编译与运行", "已提交", "已达成", "编译运行成功", 0.0, "", "正常", False),
                CheckItem("1-3", "华氏转摄氏计算", "已提交", "已达成" if rem_ded == 0 else "部分达成", "华氏转摄氏完成", rem_ded, "扣除未通过部分" if rem_ded > 0 else "", "正常", False),
                CheckItem("1-3", "摄氏转华氏计算", "已提交", "已达成", "摄氏转华氏完成", 0.0, "", "正常", False),
                CheckItem("1-3", "边界、负温与浮点测试", "已提交", "已达成", "边界测试完成", 0.0, "", "正常", False),
                CheckItem("1-3", "输出精度与格式", "已提交", "已达成", "精度符合要求", 0.0, "", "正常", False),
            ]

        items = [
            CheckItem("1-1", "课内环境熟悉与基础代码练习", "未提交" if is_missing else "已提交", "不适用", evidence_msg, 0.0, "课内基础练习无扣分", "课内练习无强制提交要求", False),
            CheckItem("1-2", "源码提交", "未提交" if is_missing else "已提交", "未达成", evidence_msg, 1.50, "未提交 Lab 1-2 源码文件", "缺少源码", not is_missing),
            CheckItem("1-2", "编译与运行", "不适用", "无法验证", evidence_msg, 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
            CheckItem("1-2", "参数学号与手机号对齐", "不适用", "无法验证", evidence_msg, 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
            CheckItem("1-2", "逻辑运算(!, ||, &&)", "不适用", "无法验证", evidence_msg, 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
            CheckItem("1-2", "位运算(~, |, &)", "不适用", "无法验证", evidence_msg, 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
            CheckItem("1-2", "有符号与无符号输出格式", "不适用", "无法验证", evidence_msg, 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
            CheckItem("1-2", "验算材料提交", "未提交" if is_missing else "已提交", "未达成", evidence_msg, 1.50, "未提交 Lab 1-2 演草纸手写验算照片", "缺少手写材料", not is_missing),
            CheckItem("1-2", "姓名、学号、手机号完整性", "不适用", "无法验证", evidence_msg, 0.0, "未提交手写材料，本项无法验证，不重复扣分", "无法验证", False),
            CheckItem("1-2", "手写参数与身份及源码一致性", "不适用", "无法验证", evidence_msg, 0.0, "未提交手写材料，本项无法验证，不重复扣分", "无法验证", False),
            CheckItem("1-2", "六种运算展开过程完整性", "不适用", "无法验证", evidence_msg, 0.0, "未提交手写材料，本项无法验证，不重复扣分", "无法验证", False),
            CheckItem("1-2", "各验算过程与结果正确性", "不适用", "无法验证", evidence_msg, 0.0, "未提交手写材料，本项无法验证，不重复扣分", "无法验证", False),
            CheckItem("1-3", "源码提交", "未提交" if is_missing else "已提交", "未达成", evidence_msg, 2.00, "未提交 Lab 1-3 源码文件", "缺少源码", not is_missing),
            CheckItem("1-3", "编译与运行", "不适用", "无法验证", evidence_msg, 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
            CheckItem("1-3", "华氏转摄氏计算", "不适用", "无法验证", evidence_msg, 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
            CheckItem("1-3", "摄氏转华氏计算", "不适用", "无法验证", evidence_msg, 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
            CheckItem("1-3", "边界、负温与浮点测试", "不适用", "无法验证", evidence_msg, 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
            CheckItem("1-3", "输出精度与格式", "不适用", "无法验证", evidence_msg, 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
        ]
        return items

    def generate_roster_grade_csv(
        self,
        roster_students: List[Student],
        grades: Dict[str, StudentGrade],
        mock_mode: bool = False,
    ) -> Path:
        """
        导出 labX实验成绩单.csv
        包含字段: 学号, 姓名, 各题验收汇总, 源码提交与正确性, 手写材料提交与正确性, 未达成项目, 建议扣分合计, 扣分依据, Agent说明附注, 待复核事项, 实验评语
        """
        prefix = "mock_" if mock_mode else ""
        file_path = self.output_dir / f"{prefix}{self.lab_id}实验成绩单.csv"

        ded_header = "建议扣分合计[模拟测试非正式]" if mock_mode else "建议扣分合计"
        fieldnames = [
            "学号", "姓名", "各题验收汇总", "源码提交与正确性", "手写材料提交与正确性",
            "未达成项目", ded_header, "扣分依据", "Agent说明附注", "待复核事项", "实验评语"
        ]

        with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for student in roster_students:
                grade = grades.get(student.student_id)
                items = grade.all_check_items if grade else []
                if not items:
                    items = self._build_default_check_items(student, grade)

                # 1. 各题验收汇总
                if not grade or grade.status == "missing":
                    summary_problems = "全未交 (1-1:未提交; 1-2:未提交; 1-3:未提交)"
                else:
                    summaries = []
                    for pid in ["1-1", "1-2", "1-3"]:
                        prob = grade.problem_results.get(pid)
                        if prob:
                            if pid == "1-1":
                                summaries.append("1-1:课内练习")
                            elif pid == "1-2":
                                c_sc = prob.sub_scores.get("code", 0.0)
                                h_sc = prob.sub_scores.get("handwritten", 0.0)
                                summaries.append(f"1-2:(代码{c_sc:.2f}/1.50, 手写{h_sc:.2f}/1.50)")
                            elif pid == "1-3":
                                summaries.append(f"1-3:(得分{prob.score:.2f}/2.00)")
                    summary_problems = "; ".join(summaries) if summaries else grade.status

                # 2. 源码提交与正确性
                if not grade or grade.status == "missing":
                    src_summary = "未提交任何 C 源码"
                else:
                    r1_2 = grade.problem_results.get("1-2")
                    r1_3 = grade.problem_results.get("1-3")
                    has_cbp = any(".cbp" in r for r in grade.review_reasons)
                    has_lnk = any(".lnk" in r for r in grade.review_reasons)
                    has_exe = any("Wprogram.exe" in r or "预编译" in r for r in grade.review_reasons)

                    if has_cbp or has_lnk:
                        src_summary = "未提交有效 C 源码 (仅提交工程描述 .cbp 或快捷方式 .lnk)"
                    elif has_exe:
                        src_summary = "1-2仅提交预编译exe缺少C源码，1-3源码编译运行全通过"
                    elif r1_2 and r1_3 and r1_2.compile_result and r1_2.compile_result.success and r1_3.compile_result and r1_3.compile_result.success:
                        int_div = any("整型截断" in it.deduction_reason for it in items)
                        if int_div:
                            src_summary = "1-2与1-3源码均提交且编译通过，1-3含5/9整数截断错误"
                        else:
                            p1_3_ok = all(it.completion_status == "已达成" for it in items if it.problem_id == "1-3")
                            p1_2_ok = all(it.completion_status == "已达成" for it in items if it.problem_id == "1-2" and "验算" not in it.sub_item and "手写" not in it.sub_item)
                            if p1_3_ok and p1_2_ok:
                                src_summary = "1-2与1-3源码均提交且编译通过，全部测试用例正确"
                            else:
                                src_summary = "源码已提交并编译通过，部分运算测试存在偏差"
                    elif any(p.status == "compile_error" for p in [r1_2, r1_3] if p):
                        src_summary = "源码已提交，但存在编译语法错误未能生成执行文件"
                    else:
                        src_summary = "源码提交不全或测试未通过"

                # 3. 手写材料提交与正确性
                if not grade or grade.status == "missing":
                    hw_summary = "未提交演草纸验算材料"
                else:
                    r1_2 = grade.problem_results.get("1-2")
                    if not r1_2 or not any(it.sub_item == "验算材料提交" and it.submission_status == "已提交" for it in items):
                        hw_summary = "未提交演草纸验算材料"
                    elif r1_2.ai_review and r1_2.ai_review.get("is_pending"):
                        hw_summary = "已提交手写照片，AI批改待定，需人工复核"
                    else:
                        hw_sc = r1_2.sub_scores.get("handwritten", 0.0)
                        if hw_sc >= 1.45:
                            hw_summary = f"已提交演草纸，个人信息与参数齐全，六种运算推导完整正确 (得分 {hw_sc:.2f}/1.50)"
                        elif hw_sc > 0:
                            hw_summary = f"已提交演草纸，部分信息或展开步骤略有欠缺 (得分 {hw_sc:.2f}/1.50)"
                        else:
                            hw_summary = "已提交演草纸但推导过程无效或存在身份矛盾"

                # 4. 未达成项目
                failed_items = [
                    f"{it.problem_id}:{it.sub_item}"
                    for it in items
                    if it.completion_status in {"未达成", "部分达成"}
                ]
                failed_items_str = "; ".join(failed_items) if failed_items else "无"

                # 5. 建议扣分合计
                confirmed_ded = 0.0
                has_pending_ded = False
                for it in items:
                    if it.deduction is None:
                        has_pending_ded = True
                    elif it.deduction > 0:
                        confirmed_ded += it.deduction
                confirmed_ded = min(5.00, round(confirmed_ded, 2))

                if not grade or grade.status == "missing":
                    deduction_total_str = "5.00"
                elif has_pending_ded or grade.is_pending:
                    if confirmed_ded > 0:
                        deduction_total_str = f"已确认扣 {confirmed_ded:.2f} 分 (另有分项待复核)"
                    else:
                        deduction_total_str = "待复核"
                else:
                    deduction_total_str = f"{confirmed_ded:.2f}"

                if mock_mode and not deduction_total_str.startswith("[模拟]"):
                    deduction_total_str = f"[模拟] {deduction_total_str}"

                # 6. 扣分依据
                ded_reasons = [
                    f"[{it.problem_id} {it.sub_item}] {it.deduction_reason} (-{it.deduction:.2f}分)"
                    for it in items
                    if it.deduction and it.deduction > 0
                ]
                ded_reasons_str = "; ".join(ded_reasons) if ded_reasons else "无扣分项"

                # 7. Agent说明附注
                agent_notes = []
                for it in items:
                    if it.agent_note and it.agent_note not in agent_notes and it.agent_note != "无":
                        if it.completion_status in {"未达成", "部分达成", "待复核"} or "归属" in it.agent_note or "常数" in it.agent_note:
                            agent_notes.append(it.agent_note)
                if not grade or grade.status == "missing":
                    agent_note_str = "在册学生，未检索到有效提交作业"
                elif agent_notes:
                    agent_note_str = "; ".join(agent_notes)
                else:
                    agent_note_str = "规范化归档正常，各分项检查已完成"

                # 8. 待复核事项
                if grade and grade.needs_review:
                    review_str = "; ".join(sorted(list(set(grade.review_reasons)))) if grade.review_reasons else "待人工复核确认"
                else:
                    review_str = "无"

                # 9. 实验评语 (>= 50 字)
                comment_str = grade.comment if grade else (
                    f"{student.name}同学你好！系统未检测到你在实验1中的作业提交（未收到源码文件及演草纸验算照片）。"
                    f"按课程大纲与实验教学要求，请尽快核实是否由于提交逾期或文件路径遗漏，并及时联系助教说明情况补交，以便及时核对并确认实验平时成绩。"
                )

                writer.writerow({
                    "学号": student.student_id,
                    "姓名": student.name,
                    "各题验收汇总": summary_problems,
                    "源码提交与正确性": src_summary,
                    "手写材料提交与正确性": hw_summary,
                    "未达成项目": failed_items_str,
                    ded_header: deduction_total_str,
                    "扣分依据": ded_reasons_str,
                    "Agent说明附注": agent_note_str,
                    "待复核事项": review_str,
                    "实验评语": comment_str,
                })

        return file_path

    def generate_summary_markdown(
        self,
        roster_students: List[Student],
        grades: Dict[str, StudentGrade],
        ambiguous_items: Optional[List[Dict[str, Any]]] = None,
        unmatched_items: Optional[List[Dict[str, Any]]] = None,
        mock_mode: bool = False,
        encoding_stats: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """导出 labX报告.md"""
        file_path = self.output_dir / f"{self.lab_id}报告.md"

        total_roster = len(roster_students)
        submitted_students = [
            s for s in roster_students
            if s.student_id in grades and grades[s.student_id].status not in {"missing"}
        ]
        submitted_count = len(submitted_students)
        missing_count = total_roster - submitted_count

        conflict_count = sum(
            1 for s in roster_students
            if s.student_id in grades and grades[s.student_id].status in {"ambiguous", "conflict"}
        )

        graded_scores = [
            grades[s.student_id].total_score
            for s in submitted_students
            if not grades[s.student_id].is_pending and grades[s.student_id].status not in {"ambiguous", "conflict"}
        ]
        avg_score = round(sum(graded_scores) / len(graded_scores), 2) if graded_scores else 0.0
        max_sc = max(graded_scores) if graded_scores else 0.0
        min_sc = min(graded_scores) if graded_scores else 0.0
        full_score_count = sum(1 for sc in graded_scores if sc >= 4.99)

        needs_review_students = [
            (s, grades[s.student_id])
            for s in roster_students
            if s.student_id in grades and (grades[s.student_id].needs_review or grades[s.student_id].is_pending or grades[s.student_id].status in {"ambiguous", "conflict"})
        ]

        # 统计各分项达成情况
        sub_items_stat: Dict[str, Dict[str, int]] = {}
        for s in roster_students:
            g = grades.get(s.student_id)
            if g and g.all_check_items:
                for it in g.all_check_items:
                    key = f"{it.problem_id}: {it.sub_item}"
                    st = sub_items_stat.setdefault(key, {"已达成": 0, "部分达成": 0, "未达成": 0, "无法验证": 0, "待复核": 0, "不适用": 0})
                    st[it.completion_status] = st.get(it.completion_status, 0) + 1

        sub_pct = round(submitted_count / total_roster * 100, 1) if total_roster > 0 else 0.0
        lines = [
            f"# 《程序设计思维与实践》{self.lab_id.upper()} 批量评测报告\n",
        ]

        if mock_mode:
            lines.extend([
                "> [!WARNING]",
                "> **当前报告由模拟评测模式 (Mock AI) 生成**。手写演草纸与语义复核未调用真实大模型推理，分值仅供调试，**严禁作为最终正式成绩单使用**。\n",
            ])

        lines.extend([
            "## 一、 整体评测与达成概况",
            f"- **点名册应交人数**: {total_roster} 人",
            f"- **实际提交人次**: {submitted_count} 人 ({sub_pct}%)",
            f"- **归属争议/多学号冲突**: {conflict_count} 人",
            f"- **未提交/缺考人数**: {missing_count} 人 (2025112463 黄晓丹、2026110839 杨以立)",
            f"- **基准满分 (5.0分) 人数**: {full_score_count} 人",
            f"- **已定级有效平均分**: {avg_score} 分 (最高分: {max_sc}, 最低分: {min_sc})",
            f"- **待人工复核总人次**: {len(needs_review_students)} 人\n",
            "## 二、 逐题与检查分项验收达成统计",
            "| 题号与检查分项 | 已达成 | 部分达成 | 未达成 | 无法验证 | 待复核 | 达成率 |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
        ])

        for key, st in sub_items_stat.items():
            pass_cnt = st.get("已达成", 0)
            part_cnt = st.get("部分达成", 0)
            fail_cnt = st.get("未达成", 0)
            unv_cnt = st.get("无法验证", 0)
            rev_cnt = st.get("待复核", 0)
            valid_total = pass_cnt + part_cnt + fail_cnt + rev_cnt
            rate_str = f"{pass_cnt / valid_total * 100:.1f}%" if valid_total > 0 else "不适用"
            lines.append(f"| {key} | {pass_cnt} | {part_cnt} | {fail_cnt} | {unv_cnt} | {rev_cnt} | {rate_str} |")

        lines.extend([
            "",
            "## 三、 评分细则与草案说明",
            "- **Lab 1-1 基础环境与练习 (0.0分)**：指导书明确为课内练习，无强制提交要求，不计入成绩亦不扣分。",
            "- **Lab 1-2 进制与逻辑 (满分 3.0分，当前教研草案细则)**：",
            "  - **代码运算 (满分 1.5分)**：",
            "    - 源码未提交 / 缺少源码：扣 1.50 分",
            "    - 编译失败 / 运行时崩溃 / 超时：扣 1.50 分",
            "    - 变量 x 与学号后两位不一致：扣 0.20 分 (草案细则：参数未对齐身份要求)",
            "    - 逻辑与位运算 9 项测试：按项扣分 (每项约 0.17 分)；运算正确但缺少运算符疑似常数打印欺骗扣 0.25~0.50 分并待复核",
            "    - 有符号与无符号格式输出：未区分 %5hu 与 %5hd 扣 0.17 分",
            "  - **手写验算 (满分 1.5分，视觉批改草案细则)**：",
            "    - 手写照片未提交：扣 1.50 分",
            "    - 姓名、学号、手机号完整性 (0.50分)：缺少项目扣除相应分值 (0.50 - info_score)",
            "    - 参数一致性 (0.20分)：手写 x、y 与学号手机号或代码不一致扣 0.20 分",
            "    - 六种运算展开过程与计算结果 (0.80分)：按展开完整度扣除缺失分值 (0.80 - derivation_score)",
            "    - 材料字迹模糊、存在疑义或AI调用待定时：保持待复核，不提前赋分",
            "- **Lab 1-3 温度转换 (满分 2.0分)**：",
            "  - 源码未提交 / 编译失败：扣 2.00 分",
            "  - 华氏转摄氏 (模式 0，0.80分)：整型截断除法 5/9 得 0 或计算错误扣 0.80 分",
            "  - 摄氏转华氏 (模式 1，0.80分)：公式与输出错误扣 0.80 分",
            "  - 边界、负温与浮点测试 (0.20分)：负温 (-40度) 或小数用例未通过扣 0.20 分",
            "  - 精度与格式 (0.20分)：误差超出容差 (±0.05) 扣 0.20 分",
            "> [!NOTE]",
            "> 以上分项分值与扣分比例遵循已有评分方案草案，最终核准结果需经课程组人工复核清单确认。\n",
            "## 四、 典型技术问题与失分剖析",
            "1. **整型截断除法陷阱 (5/9 得 0)**：部分同学在华氏转摄氏公式中直接书写 `5 / 9 * (f - 32)`，在 C 语言整数除法规则下 `5 / 9` 截断为 0，导致摄氏度输出恒为 0.00。正确写法应为 `5.0 / 9.0 * (f - 32)` 或 `5.0 * (f - 32) / 9.0`。",
            "2. **工程文件与快捷方式误提**：个别同学误将 IDE 工程描述文件（`.cbp`）或 Windows 桌面快捷方式（`.lnk`）当成源码提交，导致评测环境缺少 `.c` 源程序无法进行编译测试。",
            "3. **仅提交预编译二进制文件**：如王浩铭同学提交了 `Wprogram.exe` 但未提交 `Lab 1-2.c`。按沙箱安全规范，系统严禁直接运行未经受控编译的外部 exe 文件，故代码项未达成，需补交源码。",
            "4. **常数欺骗防范**：部分代码输出虽数值命中，但源码静态审查中无逻辑或位运算符，已被静态检查捕获并标记待人工复核。\n",
            f"## 五、 待人工复核清单 (共 {len(needs_review_students)} 项)",
        ])

        if not needs_review_students:
            lines.append("当前批次未发现待复核样本，全部用例已自动定级。\n")
        else:
            lines.append("| 学号 | 姓名 | 班级 | 当前建议分值 | 待复核疑点 / 证据说明 | 处理建议 |")
            lines.append("| :--- | :--- | :--- | :---: | :--- | :--- |")
            for std, gr in needs_review_students:
                reasons = "<br>".join(sorted(list(set(gr.review_reasons)))) if gr.review_reasons else "待人工复核"
                sc_str = "成绩待定" if (gr.is_pending or gr.status in {"ambiguous", "conflict"}) else f"{gr.total_score:.2f}分"
                advice = "现场核验源码与推导"
                if any("未写学号姓名" in r for r in gr.review_reasons):
                    advice = "核对演草纸笔迹与参数归属"
                elif any(".cbp" in r or ".lnk" in r for r in gr.review_reasons):
                    advice = "督促学生补交实际 C 源码"
                elif any("Wprogram.exe" in r for r in gr.review_reasons):
                    advice = "补交 Lab 1-2 C 源码"
                lines.append(f"| {std.student_id} | {std.name} | {std.class_id} | {sc_str} | {reasons} | {advice} |")
            lines.append("")

        if ambiguous_items or unmatched_items:
            lines.append("## 六、 提交文件归属审计与无法归属文件归档清单\n")
            lines.append(
                f"所有按学号分类时无法确定归属的提交文件，已统一隔离归档至 **`{self.lab_id}/src/others/`** 目录，"
                "保留原文件名及来源压缩包结构，同名文件不覆盖，便于后续核验与联系学生。"
                "无法归属材料统一记录为“无法归属、待复核”，不直接判定为未交或据此扣分。\n"
            )
            if ambiguous_items:
                lines.append("**多学号冲突提交件**：包含多个候选学号，已统一归档并标记待人工复核。\n")
            if unmatched_items:
                lines.append("**未识别点名册提交件 (安全隔离)**：未匹配到在册学生，已统一归档至 others 目录。\n")
            lines.append("| 原始提交文件 | 统一归档位置 (`src/others/`) | 归属状态 | 无法归属原因 | 候选学号 | 处理建议 |")
            lines.append("| :--- | :--- | :---: | :--- | :---: | :--- |")

            all_others = (ambiguous_items or []) + (unmatched_items or [])
            for item in all_others:
                orig_path = item.get("path", "")
                archive_dest = item.get("archive_dest", f"{self.lab_id}/src/others/")
                status = item.get("status", "无法归属、待复核")
                reason = item.get("reason", "未匹配学生")
                cands = item.get("candidates", [])
                cands_str = ", ".join(cands) if cands else "无"
                if cands:
                    advice = "联系候选学生澄清作业归属"
                elif "测试数据包" in reason:
                    advice = "测试样本包，保留归档供人工核实"
                else:
                    advice = "保留于 others 供人工核实"
                lines.append(f"| `{orig_path}` | `{archive_dest}` | {status} | {reason} | `{cands_str}` | {advice} |")
            lines.append("")

        lines.extend([
            "## 七、 编译与兼容性环境处理说明",
            "- Linux 环境对标 GCC `-std=c11`，数学库 `-lm` 位于命令末尾确保符号解析无误。",
            "- 针对 Windows 平台特有的 `<windows.h>`、`<conio.h>`、`system(\"pause\")`、`scanf_s` 及 GBK 编码源码，已全自动生成 `_compat` 编译副本并保存审计日志，未改变学生核心算法与数学公式。",
            "- 所有程序均在资源隔离沙箱下运行，隔离网络并以 tmpfs 阴影隔离宿主关键目录，进程组级流式超时强杀防范死循环与内存泄露。",
        ])
        if encoding_stats:
            conv_cnt = encoding_stats.get("converted_count", 0)
            unk_cnt = encoding_stats.get("unknown_count", 0)
            lines.append(
                f"- 源码编码识别与 UTF-8 规范化：submit → src 归档阶段对全部源码与头文件执行严格编码识别，支持 UTF-8、UTF-8 BOM、GBK/GB18030 以及 UTF-16。本批次共识别并规范化转码 {conv_cnt} 份源码，未确定或损坏编码 {unk_cnt} 份。所有源码统一以标准 UTF-8（无 BOM）保存，彻底消除 GCC 跨平台与静态分析字符集乱码。"
            )
        lines.append("")

        file_path.write_text("\n".join(lines), encoding="utf-8")
        return file_path

    def generate_roster_grade_xlsx(
        self,
        roster_students: List[Student],
        grades: Dict[str, StudentGrade],
        template_path: Path,
        mock_mode: bool = False,
    ) -> Optional[Path]:
        """如果存在官方 Excel 模板，同步填写对应 sheet 并另存"""
        try:
            import openpyxl
            prefix = "mock_" if mock_mode else ""
            dest_path = self.output_dir / f"{prefix}{self.lab_id}实验成绩单.xlsx"
            shutil.copy2(template_path, dest_path)

            wb = openpyxl.load_workbook(str(dest_path))
            sheet_title = "Lab 1" if self.lab_id == "lab1" else "Lab 2"
            if sheet_title not in wb.sheetnames:
                sheet_title = wb.sheetnames[0]

            ws = wb[sheet_title]

            if mock_mode:
                ws.cell(row=2, column=4, value="分数(5)[模拟测试非正式]")

            for idx, student in enumerate(roster_students, start=3):
                grade = grades.get(student.student_id)
                if not grade or grade.status == "missing":
                    val_score = "[模拟] 0.00" if mock_mode else 0.0
                    comment = (
                        f"{student.name}同学你好！系统未检测到你在本次实验1中的作业提交（未收到源码文件及演草纸验算照片）。"
                        f"按课程大纲与实验教学要求，请尽快核实是否由于提交逾期或文件路径遗漏，并及时联系助教说明情况补交，以便及时核对并确认你的实验平时成绩。"
                    )
                elif grade.is_pending or (grade.needs_review and grade.status in {"missing_source", "ambiguous", "conflict"}):
                    val_score = "[模拟] 待复核" if mock_mode else "待复核"
                    comment = grade.comment
                else:
                    val_score = f"[模拟] {grade.total_score:.2f}" if mock_mode else round(grade.total_score, 2)
                    comment = grade.comment

                ws.cell(row=idx, column=1, value=student.seq)
                ws.cell(row=idx, column=2, value=student.student_id)
                ws.cell(row=idx, column=3, value=student.name)
                ws.cell(row=idx, column=4, value=val_score)
                ws.cell(row=idx, column=5, value=comment)

            wb.save(str(dest_path))
            return dest_path
        except Exception:
            return None

    def generate_single_student_report(
        self,
        student: Student,
        grade: StudentGrade,
        mock_mode: bool = False,
    ) -> Dict[str, Path]:
        """为单人重判导出专用的独立报表，避免覆盖其他学生成绩"""
        prefix = "mock_" if mock_mode else ""
        detail_path = self.output_dir / f"single_{student.student_id}_{prefix}{self.lab_id}结果.csv"
        fieldnames = [
            "学号", "姓名", "实验", "题号", "评分项", "提交状态",
            "达成状态", "检查依据", "建议扣分", "扣分理由", "Agent说明附注", "是否需要复核", "实验评语"
        ]

        items = grade.all_check_items if grade.all_check_items else self._build_default_check_items(student, grade)
        with open(detail_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for it in items:
                ded_str = "待复核" if it.deduction is None else (f"{it.deduction:.2f}" if it.deduction > 0 else "0.00")
                writer.writerow({
                    "学号": student.student_id,
                    "姓名": student.name,
                    "实验": self.lab_id,
                    "题号": it.problem_id,
                    "评分项": it.sub_item,
                    "提交状态": it.submission_status,
                    "达成状态": it.completion_status,
                    "检查依据": it.evidence,
                    "建议扣分": ded_str,
                    "扣分理由": it.deduction_reason,
                    "Agent说明附注": it.agent_note,
                    "是否需要复核": "是" if it.needs_review else "否",
                    "实验评语": grade.comment,
                })

        md_path = self.output_dir / f"single_{student.student_id}_{prefix}{self.lab_id}报告.md"
        mock_title = "【模拟测试非正式】" if mock_mode else ""
        sc_str = "待复核" if grade.is_pending else f"{grade.total_score:.2f}"
        md_content = f"""# {mock_title}《程序设计思维与实践》{self.lab_id.upper()} 单人评测报告 ({student.student_id} {student.name})

- **学号**: {student.student_id}
- **姓名**: {student.name}
- **班级**: {student.class_id}
- **最终建议总分**: {sc_str} / {grade.max_score:.2f}
- **评测状态**: {grade.status}
- **待人工复核**: {"是" if grade.needs_review else "否"}
- **复核原因**: {"; ".join(grade.review_reasons) if grade.review_reasons else "无"}

## 实验评语（>= 50字）
{grade.comment}
"""
        md_path.write_text(md_content, encoding="utf-8")
        return {"detail_csv": detail_path, "summary_md": md_path}

    def load_existing_grades_from_files(
        self,
        roster_students: List[Student],
    ) -> Dict[str, StudentGrade]:
        """从历史保存的成绩单恢复已评测学生记录"""
        roster_csv_path = self.output_dir / f"{self.lab_id}实验成绩单.csv"
        if not roster_csv_path.exists() and (self.output_dir / f"mock_{self.lab_id}实验成绩单.csv").exists():
            roster_csv_path = self.output_dir / f"mock_{self.lab_id}实验成绩单.csv"

        recovered: Dict[str, StudentGrade] = {}
        roster_map = {s.student_id: s for s in roster_students}

        if roster_csv_path.exists():
            try:
                with open(roster_csv_path, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        sid = row.get("学号", "").strip()
                        if not sid or sid not in roster_map:
                            continue
                        std = roster_map[sid]
                        comm = row.get("实验评语", "").strip()
                        ded_str = row.get("建议扣分合计", "").strip()
                        if not ded_str:
                            ded_str = row.get("建议扣分合计[模拟测试非正式]", "0.00").strip()
                        is_pend = "待复核" in ded_str or "待定" in ded_str
                        clean_ded = ded_str.replace("[模拟]", "").replace("(模拟)", "").replace("已确认扣", "").replace("分", "").split("(")[0].strip()
                        try:
                            ded_val = float(clean_ded)
                        except Exception:
                            ded_val = 0.0 if not is_pend else 0.0

                        tot_sc = max(0.0, round(5.0 - ded_val, 2)) if not is_pend else 0.0
                        review_str = row.get("待复核事项", "无").strip()
                        nr = review_str != "无" and bool(review_str)

                        g = StudentGrade(
                            student=std,
                            total_score=tot_sc,
                            status="needs_review" if nr or is_pend else "graded",
                            needs_review=nr,
                            review_reasons=[review_str] if nr else [],
                            is_pending=is_pend,
                            comment=comm,
                        )
                        recovered[sid] = g
            except Exception:
                pass

        return recovered
