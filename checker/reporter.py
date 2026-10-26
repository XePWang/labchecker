"""
checker.reporter
多维度判题报告与成绩单生成器：
  1. labX结果.csv (逐人逐题评测明细)
  2. labX报告.md (批次统计、规则说明、复核清单)
  3. labX实验成绩单.csv (完整点名册、得分、>=50字定制评语)
  4. labX实验成绩单.xlsx (如果存在模板文件，同步填充 Excel 工作表)
"""
import csv
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from checker.models import Student, StudentGrade


class LabReporter:
    """负责将评测结果汇总并输出三份交付报表"""

    def __init__(self, lab_id: str, output_dir: Path):
        self.lab_id = lab_id.lower()
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_all_reports(
        self,
        roster_students: List[Student],
        grades: Dict[str, StudentGrade],
        excel_template_path: Optional[Path] = None,
    ) -> Dict[str, Path]:
        """生成全部三份报表并返回文件路径字典"""
        csv_detail_path = self.generate_detail_csv(roster_students, grades)
        md_summary_path = self.generate_summary_markdown(roster_students, grades)
        csv_roster_path = self.generate_roster_grade_csv(roster_students, grades)

        result_paths = {
            "detail_csv": csv_detail_path,
            "summary_md": md_summary_path,
            "roster_csv": csv_roster_path,
        }

        if excel_template_path and Path(excel_template_path).exists():
            xlsx_path = self.generate_roster_grade_xlsx(roster_students, grades, excel_template_path)
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
                        "实验总分": 0.0,
                        "提交状态": "未交",
                        "待人工复核": "否",
                        "复核原因": "",
                        "题号": "全",
                        "题目满分": 5.0,
                        "题目得分": 0.0,
                        "子项得分": "",
                        "编译状态": "-",
                        "兼容处理": "-",
                        "测试通过情况": "-",
                        "AI评审/备注": "未检测到有效提交",
                    })
                    continue

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
                        notes_str += f" | AI建议: {prob.ai_review.get('suggested_score')}分, {prob.ai_review.get('reasoning')}"

                    writer.writerow({
                        "序号": student.seq,
                        "学号": student.student_id,
                        "姓名": student.name,
                        "班级": student.class_id,
                        "实验总分": grade.total_score,
                        "提交状态": grade.status,
                        "待人工复核": "是" if prob.needs_review or grade.needs_review else "否",
                        "复核原因": "; ".join(prob.review_reasons) or "; ".join(grade.review_reasons),
                        "题号": pid,
                        "题目满分": prob.max_score,
                        "题目得分": prob.score,
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
                        "实验总分": grade.total_score,
                        "提交状态": grade.status,
                        "待人工复核": "否",
                        "复核原因": "",
                        "题号": f"{opid}(选做)",
                        "题目满分": 0.0,
                        "题目得分": 0.0,
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
    ) -> Path:
        """导出 labX报告.md"""
        file_path = self.output_dir / f"{self.lab_id}报告.md"

        total_roster = len(roster_students)
        submitted_count = sum(1 for s in roster_students if s.student_id in grades and grades[s.student_id].status != "missing")
        missing_count = total_roster - submitted_count

        total_scores = [grades[s.student_id].total_score for s in roster_students if s.student_id in grades and grades[s.student_id].status != "missing"]
        avg_score = round(sum(total_scores) / len(total_scores), 2) if total_scores else 0.0
        max_score = max(total_scores) if total_scores else 0.0
        min_score = min(total_scores) if total_scores else 0.0

        full_score_count = sum(1 for sc in total_scores if sc >= 4.99)
        needs_review_students = [
            (s, grades[s.student_id])
            for s in roster_students
            if s.student_id in grades and grades[s.student_id].needs_review
        ]

        sub_pct = round(submitted_count / total_roster * 100, 1) if total_roster > 0 else 0.0
        lines = [
            f"# 《程序设计思维与实践》{self.lab_id.upper()} 批量评测报告\n",
            "## 一、 整体评测概况",
            f"- **点名册应交人数**: {total_roster} 人",
            f"- **实际提交人数**: {submitted_count} 人 ({sub_pct}%)",
            f"- **未提交/缺考人数**: {missing_count} 人",
            f"- **满分 (5.0分) 人数**: {full_score_count} 人",
            f"- **提交有效平均分**: {avg_score} 分 (最高分: {max_score}, 最低分: {min_score})",
            f"- **需人工复核人次**: {len(needs_review_students)} 人\n",
            "## 二、 实验评测规则与基准说明",
        ]

        if self.lab_id == "lab1":
            lines.extend([
                "- **Lab 1-2 进制与逻辑 (满分 3.0分)**：",
                "  - 代码执行 (1.5分)：核对 $x$ 为学号末两位，$y$ 对齐手机号末两位；严格校验逻辑运算与位运算共 9 项输出，静态核验操作符存在性。",
                "  - 手写验算 (1.5分草案)：通过 Antigravity 多模态视觉模型批改演草纸照片，核实姓名学号手机号及 6 种操作符二进制列竖式推导。",
                "- **Lab 1-3 温度转换 (满分 2.0分)**：",
                "  - 覆盖双向转换、零度、负温及浮点小数边界，容忍合理中英文交互提示语，浮点容差 $\\pm 0.08$；自动捕获 5/9 整型除法陷阱。\n",
            ])
        elif self.lab_id == "lab2":
            lines.extend([
                "- **Warming up (0分)**：热身练习自动识别并记录完成情况，不计入总分。",
                "- **Lab 2-1 时间段问候 (满分 2.0分)**：",
                "  - 覆盖 [0,12) 晨、12 午、[13,18) 下午、[18,21) 傍晚、[21,24) 夜间全边界及 -1、24 等非法值；宽容支持中英文语义等价表达。",
                "- **Lab 2-2 字母金字塔 (满分 3.0分)**：",
                "  - 校验金字塔层数、字符镜像对称序列、大小写自动提升及非字母错误提示。按教学研讨记录指导书笔误：第3行 ABCBC 与对称序列 ABCBA 均判正确。",
                "- **Lab 2-3 / Lab 2-4 (选做题)**：独立记录测试结果，不额外改动必做题 5 分上限。\n",
            ])

        lines.extend([
            "## 三、 待人工复核清单 (共 {} 项)".format(len(needs_review_students)),
        ])

        if not needs_review_students:
            lines.append("当前批次未发现疑难争议样本，全部用例已由确定性沙箱及 AI 视觉复核自动定级。\n")
        else:
            lines.append("| 学号 | 姓名 | 班级 | 当前建议得分 | 待复核疑点 / 证据说明 |")
            lines.append("| :--- | :--- | :--- | :---: | :--- |")
            for std, gr in needs_review_students:
                reasons = "<br>".join(set(gr.review_reasons))
                lines.append(f"| {std.student_id} | {std.name} | {std.class_id} | {gr.total_score} | {reasons} |")
            lines.append("")

        lines.extend([
            "## 四、 编译与兼容性环境处理说明",
            "- 对标 Code::Blocks 25.03 GCC 14 标准体系，在 Linux 下启用 GCC `-std=c11` / G++ `-std=c++17`。",
            "- 针对 Windows 平台特有的 `<windows.h>`、`<conio.h>`、`system(\"pause\")`、`scanf_s` 及 GBK 编码源码，已全自动生成 `_compat` 编译副本并保存审计日志，未改变学生核心算法与数学公式。",
            "- 所有程序均在资源隔离沙箱下运行，进程组级超时强杀防范死循环与内存泄露。\n",
        ])

        file_path.write_text("\n".join(lines), encoding="utf-8")
        return file_path

    def generate_roster_grade_csv(
        self,
        roster_students: List[Student],
        grades: Dict[str, StudentGrade],
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
                score = grade.total_score if grade and grade.status != "missing" else 0.0
                comment = grade.comment if grade else (
                    f"{student.name}同学你好！系统未检测到你在本实验中的代码提交，请核查是否提交逾期或命名格式存在偏差。请尽快联系助教补交，以便及时核对实验成绩。"
                )

                writer.writerow({
                    "序号": student.seq,
                    "学生学号": student.student_id,
                    "学生姓名": student.name,
                    "分数(5)": f"{score:.2f}",
                    "实验评语（不少于50字）": comment,
                })

        return file_path

    def generate_roster_grade_xlsx(
        self,
        roster_students: List[Student],
        grades: Dict[str, StudentGrade],
        template_path: Path,
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

            # 模板格式从第 3 行开始填入数据
            # 列 A: 序号, 列 B: 学生学号, 列 C: 学生姓名, 列 D: 分数(5), 列 E: 评语
            for idx, student in enumerate(roster_students, start=3):
                grade = grades.get(student.student_id)
                score = grade.total_score if grade and grade.status != "missing" else 0.0
                comment = grade.comment if grade else (
                    f"{student.name}同学你好！系统未检测到你在本实验中的代码提交，请核查是否提交逾期或命名格式存在偏差。请尽快联系助教补交，以便及时核对实验成绩。"
                )

                ws.cell(row=idx, column=1, value=student.seq)
                ws.cell(row=idx, column=2, value=student.student_id)
                ws.cell(row=idx, column=3, value=student.name)
                ws.cell(row=idx, column=4, value=round(score, 2))
                ws.cell(row=idx, column=5, value=comment)

            wb.save(str(dest_path))
            return dest_path
        except Exception:
            return None
