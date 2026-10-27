"""
checker.cli
判题系统命令行交互入口
"""
import argparse
import shutil
import sys
import time
from pathlib import Path
from typing import Dict

from checker.config import DEFAULT_ROSTER_PATH, DEFAULT_TEMPLATE_PATH, PROJECT_ROOT, WORK_DIR
from checker.labs.lab1 import Lab1Judge
from checker.labs.lab2 import Lab2Judge
from checker.models import StudentGrade
from checker.reporter import LabReporter
from checker.roster import RosterManager
from checker.unpack import SubmissionNormalizer


def run_lab(
    lab_id: str,
    roster_path: Path,
    template_path: Path,
    mock_ai: bool = False,
    single_student_id: str = "",
    clean: bool = False,
    compile_workers: int = 32,
) -> int:
    """运行指定实验的完整判题流水线"""
    pipeline_start_time = time.time()
    lab_name = lab_id.lower()
    lab_root = PROJECT_ROOT / lab_name

    print(f"\n==========================================")
    print(f"🚀 开始执行《程序设计思维与实践》{lab_name.upper()} 批量判题流水线")
    print(f"==========================================")

    # 1. 目录初始化与可选清理
    submit_dir = lab_root / "submit"
    src_dir = lab_root / "src"
    build_dir = lab_root / "build"
    output_dir = lab_root / "output"

    if clean:
        print(f"[*] 正在执行前置清理: 清空 {lab_name} 下的 src/, build/, output/ 缓存...")
        for d in [src_dir, build_dir, output_dir]:
            if d.exists():
                for item in d.iterdir():
                    if item.name.lower() in {"readme.md", ".gitkeep"}:
                        continue
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)

    submit_dir.mkdir(parents=True, exist_ok=True)
    src_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 2. 加载花名册
    print(f"[*] 正在加载点名册: {roster_path}...")
    roster_mgr = RosterManager(roster_path)
    total_students = len(roster_mgr.students)
    print(f"[+] 成功加载点名册学生: {total_students} 人")

    # 3. 识别、解压并规范化提交文件
    print(f"[*] 正在从 {submit_dir} 识别并规范化学生提交...")
    normalizer = SubmissionNormalizer(roster_mgr, lab_name, lab_root)
    student_files_map = normalizer.process_all_submissions()
    print(f"[+] 规范化完成，已归属学生数: {len(student_files_map)}")

    if normalizer.unmatched_items:
        print(f"[!] 警告: 发现 {len(normalizer.unmatched_items)} 个未匹配提交项，将记录在审计清单")
    if normalizer.ambiguous_items:
        print(f"[!] 警告: 发现 {len(normalizer.ambiguous_items)} 个多候选冲突项，将标记人工复核")

    # 3. 实例化对应实验评测器
    if lab_name == "lab1":
        judge = Lab1Judge()
    elif lab_name == "lab2":
        judge = Lab2Judge()
    else:
        print(f"[-] 错误: 暂未实现该实验的评测规则 ({lab_name})")
        return 1

    # 4. 执行逐人评测
    grades: Dict[str, StudentGrade] = {}
    students_to_grade = roster_mgr.students
    if single_student_id:
        target = roster_mgr.find_student_by_id(single_student_id)
        if not target:
            print(f"[-] 错误: 点名册中未找到学号为 {single_student_id} 的学生")
            return 1
        students_to_grade = [target]

    # 若为真实 Lab 1 批次评测，启用 AI4study 手写验算多线程并发预热加速
    if not mock_ai and lab_name == "lab1":
        from checker.ai import HandwrittenReviewer
        ai_tasks = []
        for s in students_to_grade:
            s_files = student_files_map.get(s.student_id, [])
            imgs = [f.path for f in s_files if f.file_type == "image"]
            if imgs:
                try:
                    exp_x = int(s.student_id[-2:])
                except Exception:
                    exp_x = 0
                ai_tasks.append((s.student_id, s.name, exp_x, imgs))
        if ai_tasks:
            HandwrittenReviewer.precompute_reviews(ai_tasks, max_workers=4)

    # 4.1 公共并行编译阶段 (Parallel Compilation)
    print(f"[*] 正在收集待编译源码候选并启动公共编译阶段 (并发 workers: {compile_workers})...")
    batch_compile_start = time.time()
    compile_tasks = []
    for s in students_to_grade:
        if s.student_id in normalizer.conflict_students:
            continue
        s_files = student_files_map.get(s.student_id, [])
        compile_tasks.extend(judge.collect_compile_tasks(s, s_files, build_dir))

    precompiled_results = judge.compiler.compile_batch(compile_tasks, max_workers=compile_workers)
    batch_compile_duration = time.time() - batch_compile_start
    print(f"[+] 编译阶段完成: 共完成 {len(compile_tasks)} 个源码候选编译，耗时 {batch_compile_duration:.2f} 秒")

    # 4.2 串行运行判分阶段 (Serial Grading & Deductions & Comments)
    grade_start_time = time.time()
    print(f"[*] 开始自动化评测 (共 {len(students_to_grade)} 人, Mock AI: {mock_ai})...")
    for idx, student in enumerate(students_to_grade, 1):
        if student.student_id in normalizer.conflict_students:
            conflict_reason = normalizer.conflict_students[student.student_id]
            grade = StudentGrade(
                student=student,
                max_score=5.0,
                total_score=0.0,
                status="ambiguous",
                needs_review=True,
                is_pending=True,
                review_reasons=[f"归属冲突: {conflict_reason}"],
                comment=(
                    f"{student.name}同学你好！系统检测到提交文件中存在多学号匹配冲突（{conflict_reason}），"
                    f"无法自动确定作业归属。该情况已转入助教人工复核清单，成绩暂时待定，请主动联系助教澄清。"
                ),
            )
            grades[student.student_id] = grade
        else:
            files = student_files_map.get(student.student_id, [])
            grade = judge.grade_student(student, files, build_dir, mock_ai=mock_ai, precompiled=precompiled_results)
            if student.student_id in getattr(normalizer, "inferred_students", {}):
                inf_reason = normalizer.inferred_students[student.student_id]
                grade.needs_review = True
                grade.review_reasons.append(inf_reason)
                if grade.status == "graded":
                    grade.status = "needs_review"
            grades[student.student_id] = grade

        status_flag = "✓" if grade.status == "graded" else ("!" if grade.needs_review else "✗")
        review_flag = " [需复核]" if grade.needs_review else ""
        print(
            f"  [{idx:2d}/{len(students_to_grade):2d}] {status_flag} {student.student_id} {student.name:6s} "
            f"总分: {grade.total_score:4.2f}/5.00 ({grade.status}){review_flag}"
        )

    # 5. 导出报表
    print(f"[*] 正在导出判题报表与成绩单至 {output_dir}...")
    reporter = LabReporter(lab_name, output_dir)

    if single_student_id:
        # 单人重判模式：生成独立单人报表，并在历史全班成绩存在时安全合并更新，严防全班 0 分覆盖
        target_student = students_to_grade[0]
        target_grade = grades[target_student.student_id]
        single_paths = reporter.generate_single_student_report(target_student, target_grade, mock_mode=mock_ai)
        print(f"[+] 单人独立报表生成完毕:")
        print(f"  - 单人详细记录: {single_paths['detail_csv']}")
        print(f"  - 单人总结报告: {single_paths['summary_md']}")

        detail_batch = output_dir / f"{lab_name}结果.csv"
        if not detail_batch.exists() and mock_ai:
            detail_batch = output_dir / f"mock_{lab_name}结果.csv"
        if detail_batch.exists():
            print(f"[*] 检测到历史批次成绩文件，正在安全合并单人结果并更新全班成绩单...")
            merged_grades = reporter.load_existing_grades_from_files(roster_mgr.students)
            merged_grades[target_student.student_id] = target_grade
            report_paths = reporter.generate_all_reports(
                roster_students=roster_mgr.students,
                grades=merged_grades,
                ambiguous_items=normalizer.ambiguous_items,
                unmatched_items=normalizer.unmatched_items,
                excel_template_path=template_path if template_path.exists() else None,
                mock_mode=mock_ai,
            )
            print(f"[+] 全班报表合并更新完毕: {report_paths['roster_csv']}")
        else:
            print(f"[*] 全班历史批次成绩文件不存在，仅保留单人独立报表，未覆盖全班花名册。")
    else:
        # 全量批次模式
        encoding_stats = {
            "converted_count": normalizer.converted_encoding_count,
            "unknown_count": len(normalizer.unknown_encoding_files),
        }
        report_paths = reporter.generate_all_reports(
            roster_students=roster_mgr.students,
            grades=grades,
            ambiguous_items=normalizer.ambiguous_items,
            unmatched_items=normalizer.unmatched_items,
            excel_template_path=template_path if template_path.exists() else None,
            mock_mode=mock_ai,
            encoding_stats=encoding_stats,
        )

        print(f"[+] 报表生成完毕:")
        print(f"  - 详细评测记录: {report_paths['detail_csv']}")
        print(f"  - 批次总结报告: {report_paths['summary_md']}")
        print(f"  - 花名册成绩单: {report_paths['roster_csv']}")
        if "roster_xlsx" in report_paths:
            print(f"  - 官方模板Excel: {report_paths['roster_xlsx']}")

    grade_duration = time.time() - grade_start_time
    total_pipeline_duration = time.time() - pipeline_start_time
    print(f"\n[*] 运行阶段耗时汇总:")
    print(f"  - 编译阶段耗时: {batch_compile_duration:.2f} 秒 (并发 workers: {compile_workers}, 源码任务数: {len(compile_tasks)})")
    print(f"  - 串行评测耗时: {grade_duration:.2f} 秒")
    print(f"  - 全批流水线总耗时: {total_pipeline_duration:.2f} 秒")
    print(f"==========================================")
    print(f"🎉 {lab_name.upper()} 评测完成！\n")
    return 0


def main():
    parser = argparse.ArgumentParser(description="《程序设计思维与实践》批量自动化判题机")
    parser.add_argument(
        "--lab",
        type=str,
        default="lab1",
        choices=["lab1", "lab2", "all"],
        help="待评测的实验编号 (lab1, lab2, 或 all)",
    )
    parser.add_argument(
        "--roster",
        type=Path,
        default=DEFAULT_ROSTER_PATH,
        help="点名册文件路径 (.xls 或 .xlsx)",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=DEFAULT_TEMPLATE_PATH,
        help="成绩单模板路径 (.xlsx)",
    )
    parser.add_argument(
        "--mock-ai",
        action="store_true",
        help="使用 Mock 模式模拟 AI4study 多模态批改与语义复核（适合离线快速测试）",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="评测前先清空旧的 src/, build/, output/ 缓存目录",
    )
    parser.add_argument(
        "--student-id",
        type=str,
        default="",
        help="仅针对单个学号执行判题",
    )
    parser.add_argument(
        "--compile-workers",
        type=int,
        default=32,
        help="公共编译阶段的并发工作线程数 (默认 32，设为 1 为串行编译)",
    )

    args = parser.parse_args()

    if args.lab == "all":
        labs = ["lab1", "lab2"]
    else:
        labs = [args.lab]

    exit_code = 0
    for l_id in labs:
        ret = run_lab(
            lab_id=l_id,
            roster_path=args.roster,
            template_path=args.template,
            mock_ai=args.mock_ai,
            single_student_id=args.student_id,
            clean=args.clean,
            compile_workers=args.compile_workers,
        )
        if ret != 0:
            exit_code = ret

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
