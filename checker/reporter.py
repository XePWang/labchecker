"""
checker.reporter
多维度判题报告与成绩单生成器：
  1. labX结果.csv (逐人逐题评测明细)
  2. labX报告.md (批次统计、规则说明、复核清单)
  3. labX实验成绩单.csv (完整点名册、得分、>=50字定制评语)
  4. labX实验成绩单.xlsx (如果存在模板文件，同步填充 Excel 工作表)
  5. 单人重判独立导出与批次安全合并
"""
import csv
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from checker.models import Student, StudentGrade, ProblemResult


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
    ) -> Dict[str, Path]:
        """生成全套标准报表并返回文件路径字典"""
        csv_detail_path = self.generate_detail_csv(roster_students, grades)
        md_summary_path = self.generate_summary_markdown(
            roster_students,
            grades,
            ambiguous_items=ambiguous_items,
            unmatched_items=unmatched_items,
            mock_mode=mock_mode,
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
    ) -> Path:
        """导出 labX结果.csv"""
        file_path = self.output_dir / f"{self.lab_id}结果.csv"

        fieldnames = [
            "序号", "学号", "姓名", "班级", "实验总分", "提交状态",
            "待人工复核", "复核原因", "题号", "题目满分", "题目得分",
            "子项得分", "编译状态", "兼容处理", "测试通过情况", "AI评审/备注"
        ]

        with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for student in roster_students:
                grade = grades.get(student.student_id)
                if not grade or grade.status == "missing":
                    writer.writerow({
                        "序号": student.seq,
                        "学号": student.student_id,
                        "姓名": student.name,
                        "班级": student.class_id,
                        "实验总分": "0.00",
                        "提交状态": "未交",
                        "待人工复核": "否",
                        "复核原因": "",
                        "题号": "全",
                        "题目满分": "5.00",
                        "题目得分": "0.00",
                        "子项得分": "",
                        "编译状态": "-",
                        "兼容处理": "-",
                        "测试通过情况": "-",
                        "AI评审/备注": "未检测到有效提交",
                    })
                    continue

                if grade.status in {"ambiguous", "conflict"}:
                    reasons_str = "; ".join(grade.review_reasons) or "多学号匹配冲突"
                    writer.writerow({
                        "序号": student.seq,
                        "学号": student.student_id,
                        "姓名": student.name,
                        "班级": student.class_id,
                        "实验总分": "待定",
                        "提交状态": "冲突待复核",
                        "待人工复核": "是",
                        "复核原因": reasons_str,
                        "题号": "全",
                        "题目满分": "5.00",
                        "题目得分": "待定",
                        "子项得分": "",
                        "编译状态": "-",
                        "兼容处理": "-",
                        "测试通过情况": "-",
                        "AI评审/备注": f"提交包存在归属争议: {reasons_str}",
                    })
                    continue

                total_sc_display = "待定" if grade.is_pending else f"{grade.total_score:.2f}"

                if not grade.problem_results:
                    writer.writerow({
                        "序号": student.seq,
                        "学号": student.student_id,
                        "姓名": student.name,
                        "班级": student.class_id,
                        "实验总分": total_sc_display,
                        "提交状态": grade.status,
                        "待人工复核": "是" if grade.needs_review else "否",
                        "复核原因": "; ".join(grade.review_reasons),
                        "题号": "全",
                        "题目满分": f"{grade.max_score:.2f}",
                        "题目得分": total_sc_display,
                        "子项得分": "",
                        "编译状态": "-",
                        "兼容处理": "-",
                        "测试通过情况": "-",
                        "AI评审/备注": grade.comment or "已评测",
                    })
                else:
                    for pid, prob in grade.problem_results.items():
                        c_status = "-"
                    compat_str = "无"
                    if prob.compile_result:
                        c_status = "成功" if prob.compile_result.success else "失败"
                        if prob.compile_result.compat_applied:
                            compat_str = "; ".join(prob.compile_result.compat_reasons)

                    sub_str = ", ".join([f"{k}:{v}" for k, v in prob.sub_scores.items()])
                    pass_rate = ""
                    if prob.test_results:
                        p_cnt = sum(1 for t in prob.test_results if t.passed)
                        pass_rate = f"{p_cnt}/{len(prob.test_results)}"

                    notes_str = "; ".join(prob.notes)
                    if prob.ai_review:
                        ai_sc = prob.ai_review.get("suggested_score")
                        ai_sc_str = "待定" if prob.ai_review.get("is_pending") or ai_sc is None else f"{ai_sc}分"
                        mock_tag = "[模拟/Mock] " if prob.ai_review.get("is_mock") else ""
                        notes_str += f" | {mock_tag}AI建议: {ai_sc_str}, {prob.ai_review.get('reasoning')}"

                    prob_sc_display = "待定" if prob.is_pending else f"{prob.score:.2f}"

                    writer.writerow({
                        "序号": student.seq,
                        "学号": student.student_id,
                        "姓名": student.name,
                        "班级": student.class_id,
                        "实验总分": total_sc_display,
                        "提交状态": grade.status,
                        "待人工复核": "是" if prob.needs_review or grade.needs_review else "否",
                        "复核原因": "; ".join(prob.review_reasons) or "; ".join(grade.review_reasons),
                        "题号": pid,
                        "题目满分": f"{prob.max_score:.2f}",
                        "题目得分": prob_sc_display,
                        "子项得分": sub_str,
                        "编译状态": c_status,
                        "兼容处理": compat_str,
                        "测试通过情况": pass_rate,
                        "AI评审/备注": notes_str,
                    })

                # 记录选做题
                for opid, oprob in grade.optional_results.items():
                    writer.writerow({
                        "序号": student.seq,
                        "学号": student.student_id,
                        "姓名": student.name,
                        "班级": student.class_id,
                        "实验总分": total_sc_display,
                        "提交状态": grade.status,
                        "待人工复核": "否",
                        "复核原因": "",
                        "题号": f"{opid}(选做)",
                        "题目满分": "0.00",
                        "题目得分": "0.00",
                        "子项得分": "",
                        "编译状态": "成功" if oprob.compile_result and oprob.compile_result.success else "失败",
                        "兼容处理": "-",
                        "测试通过情况": oprob.status,
                        "AI评审/备注": "; ".join(oprob.notes),
                    })

        return file_path

    def generate_summary_markdown(
        self,
        roster_students: List[Student],
        grades: Dict[str, StudentGrade],
        ambiguous_items: Optional[List[Dict[str, Any]]] = None,
        unmatched_items: Optional[List[Dict[str, Any]]] = None,
        mock_mode: bool = False,
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

        # 仅对已定级学生统计均分
        graded_scores = [
            grades[s.student_id].total_score
            for s in submitted_students
            if not grades[s.student_id].is_pending and grades[s.student_id].status not in {"ambiguous", "conflict"}
        ]
        avg_score = round(sum(graded_scores) / len(graded_scores), 2) if graded_scores else 0.0
        max_score = max(graded_scores) if graded_scores else 0.0
        min_score = min(graded_scores) if graded_scores else 0.0
        full_score_count = sum(1 for sc in graded_scores if sc >= 4.99)

        needs_review_students = [
            (s, grades[s.student_id])
            for s in roster_students
            if s.student_id in grades and (grades[s.student_id].needs_review or grades[s.student_id].is_pending or grades[s.student_id].status in {"ambiguous", "conflict"})
        ]

        sub_pct = round(submitted_count / total_roster * 100, 1) if total_roster > 0 else 0.0
        lines = [
            f"# 《程序设计思维与实践》{self.lab_id.upper()} 批量评测报告\n",
        ]

        if mock_mode:
            lines.extend([
                "> [!WARNING]",
                "> **当前报告由模拟评测模式 (Mock AI) 生成**。手写演草纸与语义复核未调用真实大模型推理，分值仅供流水线与测试基准调试，**严禁作为最终正式成绩单使用**。\n",
            ])

        lines.extend([
            "## 一、 整体评测概况",
            f"- **点名册应交人数**: {total_roster} 人",
            f"- **实际提交人次**: {submitted_count} 人 ({sub_pct}%)",
            f"- **归属争议/多学号冲突**: {conflict_count} 人",
            f"- **未提交/缺考人数**: {missing_count} 人",
            f"- **满分 (5.0分) 人数**: {full_score_count} 人",
            f"- **已定级有效平均分**: {avg_score} 分 (最高分: {max_score}, 最低分: {min_score})",
            f"- **待人工复核总人次**: {len(needs_review_students)} 人\n",
            "## 二、 实验评测规则与基准说明",
        ])

        if self.lab_id == "lab1":
            lines.extend([
                "- **Lab 1-2 进制与逻辑 (满分 3.0分)**：",
                "  - 代码执行 (1.5分)：逐项核验 $!x, x||y, x&&y, ~x, x|y, x&y$ 等全部 9 个整数输出项；关联学号末两位 $x$ 与推导参数 $y$；静态审查运算符，严禁直接输出常数欺骗。",
                "  - 手写验算 (1.5分草案)：多模态视觉核对手写学号、姓名、手机号及 6 种操作符二进制竖式推导；字迹不清或模型异常时保持成绩待定，绝不随意赋分。",
                "- **Lab 1-3 温度转换 (满分 2.0分)**：",
                "  - 覆盖双向转换、零度、负温及浮点小数边界，并引入金丝雀用例防范硬编码全部样例；严格识别本次输入对应的运算结果，拦截倾倒多答案作弊；自动捕获 5/9 整型除法陷阱。\n",
            ])
        elif self.lab_id == "lab2":
            lines.extend([
                "- **Warming up (0分)**：热身练习自动识别并记录完成情况，不计入总分。",
                "- **Lab 2-1 时间段问候 (满分 2.0分)**：",
                "  - 覆盖 [0,12) 晨、12 午、[13,18) 下午、[18,21) 傍晚、[21,24) 夜间全边界及 -1、24 等非法值；宽容支持中英文语义等价表达。",
                "- **Lab 2-2 字母金字塔 (满分 3.0分)**：",
                "  - 严格校验金字塔总行数与逐行对称展开序列，拦截只打最后一行的作弊程序；兼容指导书 Sample 2 第3行 ABCBC 笔误；接受 Sample 3 的 `Invalid character!` 规范非字母提示。",
                "- **Lab 2-3 / Lab 2-4 (选做题)**：独立记录测试结果，不额外改动必做题 5 分上限。\n",
            ])

        lines.extend([
            f"## 三、 待人工复核清单 (共 {len(needs_review_students)} 项)",
        ])

        if not needs_review_students:
            lines.append("当前批次未发现疑难争议样本，全部用例已由确定性沙箱及视觉复核自动定级。\n")
        else:
            lines.append("| 学号 | 姓名 | 班级 | 当前状态/分值 | 待复核疑点 / 证据说明 |")
            lines.append("| :--- | :--- | :--- | :---: | :--- |")
            for std, gr in needs_review_students:
                reasons = "<br>".join(set(gr.review_reasons)) if gr.review_reasons else "待人工复核"
                sc_str = "成绩待定" if (gr.is_pending or gr.status in {"ambiguous", "conflict"}) else f"{gr.total_score:.2f}分"
                lines.append(f"| {std.student_id} | {std.name} | {std.class_id} | {sc_str} | {reasons} |")
            lines.append("")

        if ambiguous_items or unmatched_items:
            lines.append("### 3.1 提交文件归属异常清单")
            if ambiguous_items:
                lines.append("**多学号冲突提交件**：")
                for item in ambiguous_items:
                    lines.append(f"- 路径: `{item.get('path', '')}` | 候选学号: `{item.get('candidates', [])}` | 说明: {item.get('reason', '')}")
            if unmatched_items:
                lines.append("\n**未识别点名册提交件**：")
                for uitem in unmatched_items:
                    lines.append(f"- 路径: `{uitem.get('path', '')}` | 原因: {uitem.get('reason', '')}")
            lines.append("")

        lines.extend([
            "## 四、 编译与兼容性环境处理说明",
            "- 对标 Code::Blocks 25.03 GCC 14 标准体系，在 Linux 下启用 GCC `-std=c11` / G++ `-std=c++17`，数学库 `-lm` 严格位于命令尾部确保符号解析。",
            "- 针对 Windows 平台特有的 `<windows.h>`、`<conio.h>`、`system(\"pause\")`、`scanf_s` 及 GBK 编码源码，已全自动生成 `_compat` 编译副本并保存审计日志，未改变学生核心算法与数学公式。",
            "- 所有程序均在资源隔离沙箱下运行，隔离网络并以 tmpfs 阴影隔离宿主关键目录，进程组级流式超时强杀防范死循环与内存泄露。\n",
        ])

        file_path.write_text("\n".join(lines), encoding="utf-8")
        return file_path

    def generate_roster_grade_csv(
        self,
        roster_students: List[Student],
        grades: Dict[str, StudentGrade],
        mock_mode: bool = False,
    ) -> Path:
        """
        导出 labX实验成绩单.csv
        格式完全对齐官方模板：
        序号,学生学号,学生姓名,分数(5),实验评语（不少于50字）
        """
        file_path = self.output_dir / f"{self.lab_id}实验成绩单.csv"
        fieldnames = ["序号", "学生学号", "学生姓名", "分数(5)", "实验评语（不少于50字）"]

        with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for student in roster_students:
                grade = grades.get(student.student_id)
                if not grade or grade.status == "missing":
                    score_str = "0.00"
                    comment = (
                        f"{student.name}同学你好！系统未检测到你在本实验中的代码提交，请核查是否提交逾期或命名格式存在偏差。"
                        f"按教学大纲要求，请尽快联系助教补交并进行复核，以便及时核对并确认实验平时成绩。"
                    )
                elif grade.is_pending or grade.status in {"ambiguous", "conflict"}:
                    score_str = "待定"
                    comment = grade.comment or (
                        f"{student.name}同学你好！本次实验提交材料存在待人工复核事项（如归属多学号冲突或材料字迹待定），"
                        f"系统暂未直接给出最终分数。请主动联系助教进行现场核实与登记，确保成绩准确无误。"
                    )
                else:
                    score_str = f"{grade.total_score:.2f}"
                    comment = grade.comment

                writer.writerow({
                    "序号": student.seq,
                    "学生学号": student.student_id,
                    "学生姓名": student.name,
                    "分数(5)": score_str,
                    "实验评语（不少于50字）": comment,
                })

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
            dest_path = self.output_dir / f"{self.lab_id}实验成绩单.xlsx"
            shutil.copy2(template_path, dest_path)

            wb = openpyxl.load_workbook(str(dest_path))
            sheet_title = "Lab 1" if self.lab_id == "lab1" else "Lab 2"
            if sheet_title not in wb.sheetnames:
                sheet_title = wb.sheetnames[0]

            ws = wb[sheet_title]

            for idx, student in enumerate(roster_students, start=3):
                grade = grades.get(student.student_id)
                if not grade or grade.status == "missing":
                    val_score = 0.0
                    comment = (
                        f"{student.name}同学你好！系统未检测到你在本实验中的代码提交，请核查是否提交逾期或命名格式存在偏差。"
                        f"按教学大纲要求，请尽快联系助教补交并进行复核，以便及时核对并确认实验平时成绩。"
                    )
                elif grade.is_pending or grade.status in {"ambiguous", "conflict"}:
                    val_score = "待定"
                    comment = grade.comment or (
                        f"{student.name}同学你好！本次实验提交材料存在待人工复核事项，成绩暂保持待定状态，请联系助教核实。"
                    )
                else:
                    val_score = round(grade.total_score, 2)
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
    ) -> Dict[str, Path]:
        """为单人重判导出专用的独立报表，避免覆盖其他学生成绩"""
        detail_path = self.output_dir / f"single_{student.student_id}_{self.lab_id}结果.csv"
        fieldnames = [
            "序号", "学号", "姓名", "班级", "实验总分", "提交状态",
            "待人工复核", "复核原因", "题号", "题目满分", "题目得分",
            "子项得分", "编译状态", "兼容处理", "测试通过情况", "AI评审/备注"
        ]

        total_sc_str = "待定" if grade.is_pending else f"{grade.total_score:.2f}"

        with open(detail_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            if not grade.problem_results:
                writer.writerow({
                    "序号": student.seq,
                    "学号": student.student_id,
                    "姓名": student.name,
                    "班级": student.class_id,
                    "实验总分": total_sc_str,
                    "提交状态": grade.status,
                    "待人工复核": "是" if grade.needs_review else "否",
                    "复核原因": "; ".join(grade.review_reasons),
                    "题号": "全",
                    "题目满分": f"{grade.max_score:.2f}",
                    "题目得分": total_sc_str,
                    "子项得分": "",
                    "编译状态": "-",
                    "兼容处理": "-",
                    "测试通过情况": "-",
                    "AI评审/备注": grade.comment or "单人重评记录",
                })
            else:
                for pid, prob in grade.problem_results.items():
                    c_status = "-"
                compat_str = "无"
                if prob.compile_result:
                    c_status = "成功" if prob.compile_result.success else "失败"
                    if prob.compile_result.compat_applied:
                        compat_str = "; ".join(prob.compile_result.compat_reasons)

                sub_str = ", ".join([f"{k}:{v}" for k, v in prob.sub_scores.items()])
                pass_rate = ""
                if prob.test_results:
                    p_cnt = sum(1 for t in prob.test_results if t.passed)
                    pass_rate = f"{p_cnt}/{len(prob.test_results)}"

                notes_str = "; ".join(prob.notes)
                if prob.ai_review:
                    ai_sc = prob.ai_review.get("suggested_score")
                    ai_sc_str = "待定" if prob.ai_review.get("is_pending") or ai_sc is None else f"{ai_sc}分"
                    notes_str += f" | AI建议: {ai_sc_str}, {prob.ai_review.get('reasoning')}"

                prob_sc_str = "待定" if prob.is_pending else f"{prob.score:.2f}"

                writer.writerow({
                    "序号": student.seq,
                    "学号": student.student_id,
                    "姓名": student.name,
                    "班级": student.class_id,
                    "实验总分": total_sc_str,
                    "提交状态": grade.status,
                    "待人工复核": "是" if prob.needs_review or grade.needs_review else "否",
                    "复核原因": "; ".join(prob.review_reasons) or "; ".join(grade.review_reasons),
                    "题号": pid,
                    "题目满分": f"{prob.max_score:.2f}",
                    "题目得分": prob_sc_str,
                    "子项得分": sub_str,
                    "编译状态": c_status,
                    "兼容处理": compat_str,
                    "测试通过情况": pass_rate,
                    "AI评审/备注": notes_str,
                })

        md_path = self.output_dir / f"single_{student.student_id}_{self.lab_id}报告.md"
        md_content = f"""# 《程序设计思维与实践》{self.lab_id.upper()} 单人评测报告 ({student.student_id} {student.name})

- **学号**: {student.student_id}
- **姓名**: {student.name}
- **班级**: {student.class_id}
- **最终总分**: {total_sc_str} / {grade.max_score:.2f}
- **评测状态**: {grade.status}
- **待人工复核**: {"是" if grade.needs_review else "否"}
- **复核原因**: {"; ".join(grade.review_reasons) if grade.review_reasons else "无"}

## 评语（>= 50字）
{grade.comment}
"""
        md_path.write_text(md_content, encoding="utf-8")
        return {"detail_csv": detail_path, "summary_md": md_path}

    def load_existing_grades_from_files(
        self,
        roster_students: List[Student],
    ) -> Dict[str, StudentGrade]:
        """从历史保存的 labX结果.csv 与 labX实验成绩单.csv 恢复已评测学生记录"""
        detail_path = self.output_dir / f"{self.lab_id}结果.csv"
        roster_csv_path = self.output_dir / f"{self.lab_id}实验成绩单.csv"

        recovered: Dict[str, StudentGrade] = {}
        roster_map = {s.student_id: s for s in roster_students}

        # 1. 恢复评语
        comments: Dict[str, str] = {}
        if roster_csv_path.exists():
            try:
                with open(roster_csv_path, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        sid = row.get("学生学号", "").strip()
                        if sid:
                            comments[sid] = row.get("实验评语（不少于50字）", "").strip()
            except Exception:
                pass

        # 2. 恢复细分成绩
        if detail_path.exists():
            try:
                with open(detail_path, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        sid = row.get("学号", "").strip()
                        if not sid or sid not in roster_map:
                            continue

                        std = roster_map[sid]
                        if sid not in recovered:
                            tot_sc_str = row.get("实验总分", "0.00").strip()
                            try:
                                tot_sc = float(tot_sc_str) if tot_sc_str != "待定" else 0.0
                            except ValueError:
                                tot_sc = 0.0

                            st = row.get("提交状态", "missing").strip()
                            nr = (row.get("待人工复核", "否").strip() == "是")
                            is_pend = (tot_sc_str == "待定")

                            reasons = [r.strip() for r in row.get("复核原因", "").split(";") if r.strip()]
                            g = StudentGrade(
                                student=std,
                                total_score=tot_sc,
                                status=st,
                                needs_review=nr,
                                review_reasons=reasons,
                                is_pending=is_pend,
                                comment=comments.get(sid, ""),
                            )
                            recovered[sid] = g

                        pid = row.get("题号", "").strip()
                        if pid and pid != "全":
                            prob_sc_str = row.get("题目得分", "0.00").strip()
                            try:
                                p_sc = float(prob_sc_str) if prob_sc_str != "待定" else 0.0
                            except ValueError:
                                p_sc = 0.0
                            prob_res = ProblemResult(
                                problem_id=pid,
                                score=p_sc,
                                max_score=float(row.get("题目满分", 0.0) or 0.0),
                                status="passed" if p_sc > 0 else "failed",
                                is_pending=(prob_sc_str == "待定"),
                                notes=[row.get("AI评审/备注", "")],
                            )
                            recovered[sid].problem_results[pid] = prob_res
            except Exception:
                pass

        return recovered
