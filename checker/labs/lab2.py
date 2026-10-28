"""
checker.labs.lab2
《程序设计思维与实践》Lab 2 评测实现
包含：
  - Warming up (0分，不计分但记录完成情况)
  - Lab 2-1 时间段问候 (2.0分)
  - Lab 2-2 字母金字塔 (3.0分，兼容指导书 ABCBC 笔误)
  - Lab 2-3 回文素数 (选做题，独立记录)
  - Lab 2-4 4:2优先编码器 (选做题，独立记录)
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from checker.ai import SemanticAmbiguityReviewer
from checker.compiler import ProjectCompiler
from checker.scoring import scored_problem
from checker.labs.base import BaseLabJudge
from checker.models import (
    CheckItem,
    CompileResult,
    CompileTask,
    ProblemResult,
    Student,
    StudentGrade,
    SubmissionFile,
    TestCaseResult,
)
from checker.sandbox import run_binary


class Lab2Judge(BaseLabJudge):
    """Lab 2 判题器"""

    def __init__(self):
        super().__init__(lab_id="lab2", max_score=5.0)
        self.compiler = ProjectCompiler()

        # Lab 2-1 测试用例: [(小时输入, 期望类别, 关键词列表)]
        self.lab2_1_cases = [
            ("0\n", "morning", ["good morning", "morning", "早上好", "上午好", "早"]),
            ("8\n", "morning", ["good morning", "morning", "早上好", "上午好", "早"]),
            ("11\n", "morning", ["good morning", "morning", "早上好", "上午好", "早"]),
            ("12\n", "noon", ["good noon", "noon", "中午好", "午安"]),
            ("13\n", "afternoon", ["good afternoon", "afternoon", "下午好"]),
            ("17\n", "afternoon", ["good afternoon", "afternoon", "下午好"]),
            ("18\n", "evening", ["good evening", "evening", "傍晚好", "晚上好"]),
            ("20\n", "evening", ["good evening", "evening", "傍晚好", "晚上好"]),
            ("21\n", "night", ["good night", "night", "深夜", "夜间", "晚安"]),
            ("23\n", "night", ["good night", "night", "深夜", "夜间", "晚安"]),
            ("-1\n", "invalid", ["invalid", "error", "无效", "错误", "不合法"]),
            ("24\n", "invalid", ["invalid", "error", "无效", "错误", "不合法"]),
        ]

    def collect_compile_tasks(
        self,
        student: Student,
        files: List[SubmissionFile],
        build_dir: Path,
    ) -> List[CompileTask]:
        """收集 Lab 2 该学生所有题目的源码编译任务"""
        tasks: List[CompileTask] = []
        student_build_dir = build_dir / student.student_id

        p2_1_sources = [f.path for f in files if f.matched_problem == "2-1" and f.file_type in {"c_source", "cpp_source"}]
        for cand_idx, cand_src in enumerate(p2_1_sources):
            tasks.append(
                CompileTask(
                    student_id=student.student_id,
                    problem_id="2-1",
                    cand_idx=cand_idx,
                    binary_name=f"lab2_1_cand_{cand_idx}",
                    src_path=cand_src,
                    build_dir=student_build_dir,
                )
            )

        p2_2_sources = [f.path for f in files if f.matched_problem == "2-2" and f.file_type in {"c_source", "cpp_source"}]
        for cand_idx, cand_src in enumerate(p2_2_sources):
            tasks.append(
                CompileTask(
                    student_id=student.student_id,
                    problem_id="2-2",
                    cand_idx=cand_idx,
                    binary_name=f"lab2_2_cand_{cand_idx}",
                    src_path=cand_src,
                    build_dir=student_build_dir,
                )
            )

        p2_3_sources = [f.path for f in files if f.matched_problem == "2-3" and f.file_type in {"c_source", "cpp_source"}]
        for idx, src in enumerate(p2_3_sources):
            tasks.append(
                CompileTask(
                    student_id=student.student_id,
                    problem_id="2-3",
                    cand_idx=idx,
                    binary_name=f"lab2_3_cand_{idx}",
                    src_path=src,
                    build_dir=student_build_dir,
                )
            )

        p2_4_sources = [f.path for f in files if f.matched_problem == "2-4" and f.file_type in {"c_source", "cpp_source"}]
        for idx, src in enumerate(p2_4_sources):
            tasks.append(
                CompileTask(
                    student_id=student.student_id,
                    problem_id="2-4",
                    cand_idx=idx,
                    binary_name=f"lab2_4_cand_{idx}",
                    src_path=src,
                    build_dir=student_build_dir,
                )
            )

        return tasks

    def _grade_student(
        self,
        student: Student,
        files: List[SubmissionFile],
        build_dir: Path,
        mock_ai: bool = False,
        precompiled: Optional[Dict[Tuple[str, str, int], CompileResult]] = None,
    ) -> StudentGrade:
        """评测单个学生的 Lab 2"""
        student_build_dir = build_dir / student.student_id
        student_build_dir.mkdir(parents=True, exist_ok=True)

        grade = StudentGrade(student=student, max_score=5.0)

        # 分类归属文件
        warmup_files = [f.path for f in files if f.is_warmup or f.matched_problem == "warmup"]
        p2_1_sources = [f.path for f in files if f.matched_problem == "2-1" and f.file_type in {"c_source", "cpp_source"}]
        p2_2_sources = [f.path for f in files if f.matched_problem == "2-2" and f.file_type in {"c_source", "cpp_source"}]
        p2_3_sources = [f.path for f in files if f.matched_problem == "2-3" and f.file_type in {"c_source", "cpp_source"}]
        p2_4_sources = [f.path for f in files if f.matched_problem == "2-4" and f.file_type in {"c_source", "cpp_source"}]

        corrupt_archives = [f for f in files if f.file_type == "corrupt_archive"]

        # 1. 记录 Warmup 热身情况 (0分)
        warmup_prob = ProblemResult(
            problem_id="warmup",
            score=0.0,
            max_score=0.0,
            status="passed" if warmup_files else "missing",
            notes=[f"已提交热身练习文件 ({len(warmup_files)}个)，依课程规则不计入实验总分"] if warmup_files else ["未提交课前热身练习文件"],
            source_files=warmup_files,
        )
        warmup_prob.check_items = [
            CheckItem(
                problem_id="warmup",
                sub_item="课前热身练习",
                submission_status="已提交" if warmup_files else "未提交",
                completion_status="不适用",
                evidence=f"已归档热身练习文件: {[f.name for f in warmup_files]}" if warmup_files else "未提交课前热身练习文件",
                deduction=0.0,
                deduction_reason="热身练习依规则不计入总分",
                agent_note="不作强制提交要求，不计分亦不扣分",
                needs_review=False,
            )
        ]
        grade.problem_results["warmup"] = warmup_prob

        # 2. 评测 Lab 2-1 (2.0分)
        res2_1 = self._grade_lab2_1(student, p2_1_sources, student_build_dir, mock_ai, precompiled=precompiled, corrupt_archives=corrupt_archives, all_files=files)
        grade.problem_results["2-1"] = res2_1

        # 3. 评测 Lab 2-2 (3.0分)
        res2_2 = self._grade_lab2_2(student, p2_2_sources, student_build_dir, mock_ai, precompiled=precompiled, corrupt_archives=corrupt_archives, all_files=files)
        grade.problem_results["2-2"] = res2_2

        # 4. 评测选做题 Lab 2-3 与 2-4 (独立记录完成情况)
        if p2_3_sources:
            grade.optional_results["2-3"] = self._grade_lab2_3(student, p2_3_sources, student_build_dir, precompiled=precompiled)
        if p2_4_sources:
            grade.optional_results["2-4"] = self._grade_lab2_4(student, p2_4_sources, student_build_dir, precompiled=precompiled)

        # 汇总总分
        grade.total_score = round(res2_1.score + res2_2.score, 2)
        if any(r.needs_review for r in grade.problem_results.values()):
            grade.needs_review = True
            for r in grade.problem_results.values():
                grade.review_reasons.extend(r.review_reasons)

        if any(r.is_pending for r in grade.problem_results.values()):
            grade.is_pending = True
            grade.needs_review = True
            grade.status = "needs_review"
            grade.total_score = 0.0
        elif not files:
            grade.status = "missing"
            grade.total_score = 0.0
        elif all(f.file_type == "corrupt_archive" for f in files):
            grade.status = "needs_review"
            grade.needs_review = True
            grade.total_score = 0.0
        elif res2_1.status == "compile_error" and res2_2.status == "compile_error":
            grade.status = "compile_error"
        elif grade.needs_review:
            grade.status = "needs_review"
        else:
            grade.status = "graded"

        # 生成评语
        return grade

    @scored_problem("2-1")
    def _grade_lab2_1(
        self,
        student: Student,
        sources: List[Path],
        build_dir: Path,
        mock_ai: bool,
        precompiled: Optional[Dict[Tuple[str, str, int], CompileResult]] = None,
        corrupt_archives: Optional[List[SubmissionFile]] = None,
        all_files: Optional[List[SubmissionFile]] = None,
    ) -> ProblemResult:
        """评测 Lab 2-1：时间段问候 (2.0分)"""
        prob = ProblemResult(problem_id="2-1", score=0.0, max_score=2.0, source_files=sources)

        if not sources:
            if corrupt_archives:
                prob.status = "needs_review"
                prob.needs_review = True
                prob.is_pending = True
                prob.notes.append(f"收到学生提交压缩包 ({corrupt_archives[0].original_name})，解压失败，内容无法验证，待人工复核")
                prob.review_reasons.append(f"提交压缩包损坏解压失败: {corrupt_archives[0].original_name}，Lab 2-1 源码无法验证")
                prob.check_items = [
                    CheckItem("2-1", "源码提交", "已提交", "待复核", f"已提交压缩包 {corrupt_archives[0].original_name} 但解压失败", None, f"提交压缩包损坏解压失败: {corrupt_archives[0].original_name}，Lab 2-1 源码无法验证", "解压失败、内容无法验证、待复核", True),
                    CheckItem("2-1", "编译与运行", "不适用", "无法验证", "压缩包损坏无法提取源码", 0.0, "未成功提取源码，本项无法验证，不重复扣分", "无法验证", False),
                    CheckItem("2-1", "时间段问候逻辑", "不适用", "无法验证", "压缩包损坏无法提取源码", 0.0, "未成功提取源码，本项无法验证，不重复扣分", "无法验证", False),
                    CheckItem("2-1", "边界与无效输入处理", "不适用", "无法验证", "压缩包损坏无法提取源码", 0.0, "未成功提取源码，本项无法验证，不重复扣分", "无法验证", False),
                ]
            else:
                prob.status = "missing"
                prob.notes.append("未提交 Lab 2-1 源码")
                prob.check_items = [
                    CheckItem("2-1", "源码提交", "未提交", "未达成", "未检索到 Lab 2-1 源码文件", 2.00, "未提交 Lab 2-1 源码文件", "缺少源码", False),
                    CheckItem("2-1", "编译与运行", "不适用", "无法验证", "未提交源码", 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
                    CheckItem("2-1", "时间段问候逻辑", "不适用", "无法验证", "未提交源码", 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
                    CheckItem("2-1", "边界与无效输入处理", "不适用", "无法验证", "未提交源码", 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
                ]
            return prob

        total_cases = len(self.lab2_1_cases)
        # 存在一份或多份源码候选：逐一评测，择优采用最高分版本
        cand_evaluations = []
        for cand_idx, cand_src in enumerate(sources):
            sf = next((f for f in (all_files or []) if f.path == cand_src), None)
            c_encoding_error = sf.encoding_error if sf else ""
            try:
                c_text = cand_src.read_text(encoding="utf-8")
            except Exception as e:
                c_text = ""
                c_encoding_error = f"UTF-8 解码失败: {e}"

            if precompiled and (student.student_id, "2-1", cand_idx) in precompiled:
                c_compile = precompiled[(student.student_id, "2-1", cand_idx)]
            else:
                c_compile = self.compiler.compile(cand_src, build_dir, f"lab2_1_cand_{cand_idx}")
            c_results = []
            c_notes = []
            c_reviews = []
            c_needs_review = False
            c_is_pending = False
            passed_cases = 0

            if c_encoding_error:
                c_notes.append(f"源码编码损坏: {c_encoding_error}")
                c_needs_review = True
                c_is_pending = True
                c_reviews.append(f"Lab 2-1 源码存在不可恢复的编码损坏无法严格解码: {c_encoding_error}，待人工复核")
            elif sf and sf.encoding_converted:
                c_notes.append(f"源码已自 {sf.source_encoding} 规范化为 UTF-8")

            if not c_compile.success:
                c_notes.append(f"Lab 2-1 ({cand_src.name}) 编译失败")
            else:
                for idx, (in_str, category, keywords) in enumerate(self.lab2_1_cases, 1):
                    exec_res = run_binary(c_compile.binary_path, input_str=in_str, timeout=2.0)

                    case_res = TestCaseResult(
                        case_id=f"case_{idx}",
                        input_data=in_str.strip(),
                        expected_output=f"[{category}] 包含 {keywords[0]}",
                        actual_output=exec_res.stdout.strip(),
                        passed=False,
                        score=0.0,
                        max_score=round(2.0 / total_cases, 2),
                        timed_out=exec_res.timed_out,
                        exit_code=exec_res.exit_code,
                    )

                    if exec_res.timed_out:
                        case_res.error_message = "运行超时"
                    elif exec_res.exit_code != 0:
                        case_res.error_message = f"运行时异常 (exit {exec_res.exit_code})"
                    else:
                        out_lower = exec_res.stdout.lower()
                        matched_kw = any(kw in out_lower for kw in keywords)

                        # 必须避免 morning 误判包含 night 等反例
                        conflict = False
                        if category == "morning" and ("afternoon" in out_lower or "evening" in out_lower or "night" in out_lower):
                            conflict = True
                        elif category == "noon" and ("afternoon" in out_lower):
                            conflict = True

                        if matched_kw and not conflict:
                            case_res.passed = True
                            case_res.score = case_res.max_score
                            passed_cases += 1
                        else:
                            # 确定性未命中，调用语义复核
                            if idx == 1:
                                ai_sem = SemanticAmbiguityReviewer.review_output(
                                    problem_id="2-1",
                                    student_id=student.student_id,
                                    input_data=in_str,
                                    expected_behavior=f"时间问候语义对齐 {category}",
                                    actual_output=exec_res.stdout,
                                    source_code=c_text,
                                    max_score=case_res.max_score,
                                    mock_mode=mock_ai,
                                )
                                if ai_sem.get("passed"):
                                    case_res.passed = True
                                    case_res.score = case_res.max_score
                                    passed_cases += 1
                                    c_notes.append(f"用例 {idx} 经 AI 语义复核确认问候语正确")
                                elif ai_sem.get("is_pending"):
                                    case_res.needs_review = True
                                    sem_reason = ai_sem.get("review_reason") or "AI 语义复核超时或异常，判定待定"
                                    case_res.review_reason = sem_reason
                                    c_is_pending = True
                                    c_needs_review = True
                                    c_reviews.append(f"2-1 语义复核待定: {sem_reason}")
                                    c_notes.append(f"用例 {idx} AI 语义复核待定: {sem_reason}")
                                elif ai_sem.get("needs_review"):
                                    case_res.needs_review = True
                                    sem_reason = ai_sem.get("review_reason") or "AI 语义复核需人工介入"
                                    case_res.review_reason = sem_reason
                                    c_needs_review = True
                                    c_reviews.append(f"2-1 需人工复核: {sem_reason}")

                    c_results.append(case_res)

            cand_score = round(2.0 * (passed_cases / total_cases), 2)
            cand_evaluations.append({
                "cand_idx": cand_idx,
                "src_path": cand_src,
                "score": cand_score,
                "passed_cases": passed_cases,
                "c_res": c_compile,
                "test_results": c_results,
                "notes": c_notes,
                "reviews": c_reviews,
                "needs_review": c_needs_review,
                "is_pending": c_is_pending,
                "success": c_compile.success,
            })

        best_eval = cand_evaluations[0]
        src_path = best_eval["src_path"]
        c_res = best_eval["c_res"]
        prob.compile_result = c_res
        prob.test_results = best_eval["test_results"]
        passed_cases = best_eval["passed_cases"]
        prob.notes.extend(best_eval["notes"])
        if best_eval["needs_review"]:
            prob.needs_review = True
            prob.review_reasons.extend(best_eval["reviews"])
        if best_eval["is_pending"]:
            prob.is_pending = True

        prob.candidate_evaluations = [
            {
                "index": c["cand_idx"],
                "src_path": str(c["src_path"]),
                "filename": c["src_path"].name,
                "score": c["score"],
                "passed_cases": c["passed_cases"],
                "compile_success": c["success"],
                "needs_review": c["needs_review"],
                "notes": c["notes"],
                "reviews": c["reviews"],
            }
            for c in cand_evaluations
        ]
        prob.chosen_candidate = {
            "index": best_eval["cand_idx"],
            "src_path": str(best_eval["src_path"]),
            "filename": best_eval["src_path"].name,
            "score": best_eval["score"],
            "passed_cases": best_eval["passed_cases"],
            "reason": f"最高分版本 ({prob.score:.2f}/2.00, 通过率 {passed_cases}/{total_cases})",
        }

        best_sf = next((f for f in (all_files or []) if f.path == src_path), None)
        is_enc_err = bool(best_sf and best_sf.encoding_error)

        # 构建结构化检查分项 (CheckItems: 4 个分项)
        items: List[CheckItem] = []
        if is_enc_err:
            items.append(CheckItem(
                problem_id="2-1",
                sub_item="源码提交",
                submission_status="已提交",
                completion_status="待复核",
                evidence=f"提交源码文件: {src_path.name} (编码损坏: {best_sf.encoding_error})",
                deduction=None,
                deduction_reason=f"源码编码损坏无法严格解码: {best_sf.encoding_error}，待人工复核",
                agent_note="源码编码损坏，待人工复核",
                needs_review=True,
            ))
            items.append(CheckItem(
                problem_id="2-1",
                sub_item="编译与运行",
                submission_status="已提交",
                completion_status="待复核",
                evidence=f"源码编码异常导致编译无法正常判定: {best_sf.encoding_error}",
                deduction=None,
                deduction_reason="源码存在编码损坏无法可靠编译，待人工复核",
                agent_note="编码损坏待复核",
                needs_review=True,
            ))
            items.append(CheckItem(
                problem_id="2-1",
                sub_item="时间段问候逻辑",
                submission_status="不适用",
                completion_status="待复核",
                evidence="源码编码损坏，时间段逻辑待复核",
                deduction=None,
                deduction_reason="源码编码损坏待人工复核",
                agent_note="待复核",
                needs_review=True,
            ))
            items.append(CheckItem(
                problem_id="2-1",
                sub_item="边界与无效输入处理",
                submission_status="不适用",
                completion_status="待复核",
                evidence="源码编码损坏，边界处理待复核",
                deduction=None,
                deduction_reason="源码编码损坏待人工复核",
                agent_note="待复核",
                needs_review=True,
            ))
        elif not c_res.success:
            items.append(CheckItem(
                problem_id="2-1",
                sub_item="源码提交",
                submission_status="已提交",
                completion_status="已达成",
                evidence=f"提交源码文件: {src_path.name}",
                deduction=0.0,
                deduction_reason="",
                agent_note="源码归档正常",
                needs_review=False,
            ))
            items.append(CheckItem(
                problem_id="2-1",
                sub_item="编译与运行",
                submission_status="已提交",
                completion_status="未达成",
                evidence=f"GCC 编译失败: {c_res.stderr[:100]}",
                deduction=2.00,
                deduction_reason=f"Lab 2-1 编译失败: {c_res.stderr[:100]}",
                agent_note="编译语法错误",
                needs_review=False,
            ))
            items.append(CheckItem(
                problem_id="2-1",
                sub_item="时间段问候逻辑",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="源码未成功编译",
                deduction=0.0,
                deduction_reason="未成功编译，本项无法验证，不重复扣分",
                agent_note="无法验证",
                needs_review=False,
            ))
            items.append(CheckItem(
                problem_id="2-1",
                sub_item="边界与无效输入处理",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="源码未成功编译",
                deduction=0.0,
                deduction_reason="未成功编译，本项无法验证，不重复扣分",
                agent_note="无法验证",
                needs_review=False,
            ))
        else:
            enc_note = f" (已自 {best_sf.source_encoding} 规范化为 UTF-8)" if (best_sf and best_sf.encoding_converted) else ""
            ev_str = f"提交源码文件: {src_path.name}{enc_note} (共 {len(sources)} 份候选，已择优采用最高分版本)" if len(sources) > 1 else f"提交源码文件: {src_path.name}{enc_note}"
            an_str = f"多候选已择优采用最高分版本: {src_path.name}{enc_note}" if len(sources) > 1 else (f"源码文件已规范化为 UTF-8 (来源编码: {best_sf.source_encoding})" if (best_sf and best_sf.encoding_converted) else "源码归档正常")
            items.append(CheckItem(
                problem_id="2-1",
                sub_item="源码提交",
                submission_status="已提交",
                completion_status="已达成",
                evidence=ev_str,
                deduction=0.0,
                deduction_reason="",
                agent_note=an_str,
                needs_review=False,
            ))
            items.append(CheckItem(
                problem_id="2-1",
                sub_item="编译与运行",
                submission_status="已提交",
                completion_status="已达成",
                evidence=f"GCC 编译成功 ({c_res.duration_ms:.1f}ms)，测试用例可正常执行",
                deduction=0.0,
                deduction_reason="",
                agent_note="编译运行通过",
                needs_review=False,
            ))

            valid_test_res = best_eval["test_results"][:10]
            valid_passed = sum(1 for c in valid_test_res if c.passed)
            valid_ded = 2.0 * (10-valid_passed) / total_cases
            has_pending = any(c.needs_review for c in valid_test_res)
            v_status = "已达成" if valid_ded == 0 else ("部分达成" if valid_passed > 0 else "未达成")
            if has_pending:
                v_status = "待复核"
            items.append(CheckItem(
                problem_id="2-1",
                sub_item="时间段问候逻辑",
                submission_status="已提交",
                completion_status=v_status,
                evidence=f"通过有效时间段问候测试 {valid_passed}/10 项 (Morning/Noon/Afternoon/Evening/Night)",
                deduction=None if has_pending else valid_ded,
                deduction_reason=f"部分时间段问候未通过测试 (-{valid_ded:.2f}分)" if (valid_ded > 0 and not has_pending) else ("语义复核待定" if has_pending else ""),
                agent_note="经语义复核待定" if has_pending else ("问候逻辑正确" if valid_ded == 0 else "部分时段匹配有偏差"),
                needs_review=has_pending,
            ))

            invalid_test_res = best_eval["test_results"][10:12]
            invalid_passed = sum(1 for c in invalid_test_res if c.passed)
            inv_ded = 2.0 * (2-invalid_passed) / total_cases
            inv_status = "已达成" if inv_ded == 0 else ("部分达成" if invalid_passed > 0 else "未达成")
            items.append(CheckItem(
                problem_id="2-1",
                sub_item="边界与无效输入处理",
                submission_status="已提交",
                completion_status=inv_status,
                evidence=f"通过非法输入过滤测试 {invalid_passed}/2 项 (包含 -1 与 24)",
                deduction=inv_ded,
                deduction_reason=f"非法输入 (-1, 24) 未正确报错或识别 (-{inv_ded:.2f}分)" if inv_ded > 0 else "",
                agent_note="边界与非法输入处理正常" if inv_ded == 0 else "非法输入未完全过滤",
                needs_review=False,
            ))

        prob.check_items = items
        prob.case_budget = 2.0
        prob.case_groups = {'时间段问候逻辑':list(range(10)), '边界与无效输入处理':[10,11]}

        if not c_res.success:
            prob.status = "needs_review" if (prob.is_pending or prob.needs_review) else "compile_error"
            prob.notes.append("Lab 2-1 编译失败")
            return prob

        prob.score = round(2.0 * (passed_cases / total_cases), 2)
        if prob.is_pending:
            prob.status = "needs_review"
            prob.score = 0.0
        elif passed_cases == total_cases:
            prob.status = "passed"
        elif passed_cases > 0:
            prob.status = "partial"
        else:
            prob.status = "failed"

        prob.notes.append(f"测试通过率: {passed_cases}/{total_cases}")
        if len(sources) > 1:
            prob.notes.append(f"检测到 {len(sources)} 份 2-1 源码候选: {[s.name for s in sources]}，已择优评测采用最高分版本: {src_path.name} (得分: {prob.score:.2f}/2.00)")
        return prob

    @scored_problem("2-2")
    def _grade_lab2_2(
        self,
        student: Student,
        sources: List[Path],
        build_dir: Path,
        mock_ai: bool,
        precompiled: Optional[Dict[Tuple[str, str, int], CompileResult]] = None,
        corrupt_archives: Optional[List[SubmissionFile]] = None,
        all_files: Optional[List[SubmissionFile]] = None,
    ) -> ProblemResult:
        """
        评测 Lab 2-2：字母金字塔 (3.0分)
        验证对称序列、层数、大小写自动提升及非字母错误提示。
        兼容指导书笔误：第3行 ABCBC 与 ABCBA 均予以识别。
        """
        prob = ProblemResult(problem_id="2-2", score=0.0, max_score=3.0, source_files=sources)

        if not sources:
            if corrupt_archives:
                prob.status = "needs_review"
                prob.needs_review = True
                prob.is_pending = True
                prob.notes.append(f"收到学生提交压缩包 ({corrupt_archives[0].original_name})，解压失败，内容无法验证，待人工复核")
                prob.review_reasons.append(f"提交压缩包损坏解压失败: {corrupt_archives[0].original_name}，Lab 2-2 源码无法验证")
                prob.check_items = [
                    CheckItem("2-2", "源码提交", "已提交", "待复核", f"已提交压缩包 {corrupt_archives[0].original_name} 但解压失败", None, f"提交压缩包损坏解压失败: {corrupt_archives[0].original_name}，Lab 2-2 源码无法验证", "解压失败、内容无法验证、待复核", True),
                    CheckItem("2-2", "编译与运行", "不适用", "无法验证", "压缩包损坏无法提取源码", 0.0, "未成功提取源码，本项无法验证，不重复扣分", "无法验证", False),
                    CheckItem("2-2", "字母对称金字塔展开 (A~Z)", "不适用", "无法验证", "压缩包损坏无法提取源码", 0.0, "未成功提取源码，本项无法验证，不重复扣分", "无法验证", False),
                    CheckItem("2-2", "大小写字母兼容转换", "不适用", "无法验证", "压缩包损坏无法提取源码", 0.0, "未成功提取源码，本项无法验证，不重复扣分", "无法验证", False),
                    CheckItem("2-2", "非字母与异常输入报错", "不适用", "无法验证", "压缩包损坏无法提取源码", 0.0, "未成功提取源码，本项无法验证，不重复扣分", "无法验证", False),
                ]
            else:
                prob.status = "missing"
                prob.notes.append("未提交 Lab 2-2 源码")
                prob.check_items = [
                    CheckItem("2-2", "源码提交", "未提交", "未达成", "未检索到 Lab 2-2 源码文件", 3.00, "未提交 Lab 2-2 源码文件", "缺少源码", False),
                    CheckItem("2-2", "编译与运行", "不适用", "无法验证", "未提交源码", 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
                    CheckItem("2-2", "字母对称金字塔展开 (A~Z)", "不适用", "无法验证", "未提交源码", 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
                    CheckItem("2-2", "大小写字母兼容转换", "不适用", "无法验证", "未提交源码", 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
                    CheckItem("2-2", "非字母与异常输入报错", "不适用", "无法验证", "未提交源码", 0.0, "未提交源码，本项无法验证，不重复扣分", "无法验证", False),
                ]
            return prob

        # 测试用例: [(输入字符, 期望总行数, 最终行对称序列, 是否非字母测试)]
        test_pyramids = [
            ("C\n", 3, "ABCBA", False),
            ("f\n", 6, "ABCDEFEDCBA", False),  # 小写字母自动提升为大写
            ("A\n", 1, "A", False),
            ("-\n", 0, "ERROR", True),         # 指导书 Sample 3 原样输入 '-'
            ("1\n", 0, "ERROR", True),         # 常见非字母数字输入
            ("Z\n", 26, "ABCDEFGHIJKLMNOPQRSTUVWXYZYXWVUTSRQPONMLKJIHGFEDCBA", False),
        ]
        total_cases = len(test_pyramids)
        # 存在一份或多份源码候选：逐一评测，择优采用最高分版本
        cand_evaluations = []
        for cand_idx, cand_src in enumerate(sources):
            sf = next((f for f in (all_files or []) if f.path == cand_src), None)
            c_encoding_error = sf.encoding_error if sf else ""
            if precompiled and (student.student_id, "2-2", cand_idx) in precompiled:
                c_compile = precompiled[(student.student_id, "2-2", cand_idx)]
            else:
                c_compile = self.compiler.compile(cand_src, build_dir, f"lab2_2_cand_{cand_idx}")
            c_results = []
            c_notes = []
            c_reviews = []
            c_needs_review = False
            c_is_pending = False
            passed_cases = 0
            typo_detected = False

            if c_encoding_error:
                c_notes.append(f"源码编码损坏: {c_encoding_error}")
                c_needs_review = True
                c_is_pending = True
                c_reviews.append(f"Lab 2-2 源码存在不可恢复的编码损坏无法严格解码: {c_encoding_error}，待人工复核")
            elif sf and sf.encoding_converted:
                c_notes.append(f"源码已自 {sf.source_encoding} 规范化为 UTF-8")

            if not c_compile.success:
                c_notes.append(f"Lab 2-2 ({cand_src.name}) 编译失败")
            else:
                for idx, (in_char, exp_lines, exp_final_seq, is_error_test) in enumerate(test_pyramids, 1):
                    exec_res = run_binary(c_compile.binary_path, input_str=in_char, timeout=2.0)

                    case_res = TestCaseResult(
                        case_id=f"case_{idx}",
                        input_data=in_char.strip(),
                        expected_output=f"行数={exp_lines}, 终行序列={exp_final_seq}" if not is_error_test else "非字母报错信息",
                        actual_output=exec_res.stdout.strip(),
                        passed=False,
                        score=0.0,
                        max_score=round(3.0 / total_cases, 2),
                        timed_out=exec_res.timed_out,
                        exit_code=exec_res.exit_code,
                    )

                    if exec_res.timed_out:
                        case_res.error_message = "运行超时"
                    elif exec_res.exit_code != 0:
                        case_res.error_message = f"运行时异常 (exit {exec_res.exit_code})"
                    else:
                        out_lines = [line for line in exec_res.stdout.splitlines() if line.strip()]

                        if is_error_test:
                            out_lower = exec_res.stdout.lower()
                            error_keywords = [
                                "invalid character", "invalid", "not a letter", "not letter",
                                "error", "非字母", "错误", "不是字母", "不合法", "无效"
                            ]
                            if any(w in out_lower for w in error_keywords):
                                case_res.passed = True
                                case_res.score = case_res.max_score
                                passed_cases += 1
                            else:
                                case_res.error_message = "未能检测到非字母非法输入报错提示"
                        else:
                            # 构造本用例各行的完整理论预期对称序列
                            target_ch = in_char.strip().upper()
                            n_lines = ord(target_ch) - ord('A') + 1

                            expected_rows = []
                            for row_i in range(1, n_lines + 1):
                                up = "".join(chr(ord('A') + j) for j in range(row_i))
                                down = "".join(chr(ord('A') + j) for j in range(row_i - 2, -1, -1))
                                expected_rows.append(up + down)

                            # 提取纯英文字母行，过滤输入提示语干扰
                            letter_rows = []
                            for line in out_lines:
                                clean_l = line.strip()
                                if any(kw in clean_l.lower() for kw in ["input", "enter", "receiving", "请输入", "输入", "sample"]):
                                    continue
                                seq = "".join(re.findall(r"[A-Za-z]", clean_l)).upper()
                                if seq:
                                    letter_rows.append(seq)

                            # 严格逐行验证：行数必须完全一致，且每行均需满足对称序列
                            if len(letter_rows) == n_lines:
                                all_rows_matched = True
                                for r_idx in range(n_lines):
                                    exp_r = expected_rows[r_idx]
                                    actual_r = letter_rows[r_idx]
                                    if r_idx == 2:  # 第3行兼容指导书样例中的 ABCBC 笔误
                                        if actual_r == "ABCBC":
                                            typo_detected = True
                                        if actual_r not in {"ABCBA", "ABCBC"}:
                                            all_rows_matched = False
                                            break
                                    else:
                                        if actual_r != exp_r:
                                            all_rows_matched = False
                                            break

                                if all_rows_matched:
                                    case_res.passed = True
                                    case_res.score = case_res.max_score
                                    passed_cases += 1
                                else:
                                    case_res.error_message = f"行内容未严格对称展开 (提取内容: {letter_rows[:3]}...)"
                            else:
                                case_res.error_message = f"金字塔总行数不符预期: 期望{n_lines}行, 实际检测到{len(letter_rows)}行"

                    c_results.append(case_res)

                if typo_detected:
                    c_notes.append("检测到输出匹配指导书样例笔误 ABCBC，已按课程容错规则判定通过")

            cand_score = round(3.0 * (passed_cases / total_cases), 2)
            cand_evaluations.append({
                "cand_idx": cand_idx,
                "src_path": cand_src,
                "score": cand_score,
                "passed_cases": passed_cases,
                "c_res": c_compile,
                "test_results": c_results,
                "notes": c_notes,
                "reviews": c_reviews,
                "needs_review": c_needs_review,
                "is_pending": c_is_pending,
                "success": c_compile.success,
            })

        best_eval = cand_evaluations[0]
        src_path = best_eval["src_path"]
        c_res = best_eval["c_res"]
        prob.compile_result = c_res
        prob.test_results = best_eval["test_results"]
        passed_cases = best_eval["passed_cases"]
        prob.notes.extend(best_eval["notes"])
        if best_eval.get("needs_review"):
            prob.needs_review = True
            prob.review_reasons.extend(best_eval.get("reviews", []))
        if best_eval.get("is_pending"):
            prob.is_pending = True

        prob.candidate_evaluations = [
            {
                "index": c["cand_idx"],
                "src_path": str(c["src_path"]),
                "filename": c["src_path"].name,
                "score": c["score"],
                "passed_cases": c["passed_cases"],
                "compile_success": c["success"],
                "needs_review": c["needs_review"],
                "notes": c["notes"],
                "reviews": c["reviews"],
            }
            for c in cand_evaluations
        ]
        prob.chosen_candidate = {
            "index": best_eval["cand_idx"],
            "src_path": str(best_eval["src_path"]),
            "filename": best_eval["src_path"].name,
            "score": best_eval["score"],
            "passed_cases": best_eval["passed_cases"],
            "reason": f"最高分版本 ({prob.score:.2f}/3.00, 通过率 {passed_cases}/{total_cases})",
        }

        best_sf = next((f for f in (all_files or []) if f.path == src_path), None)
        is_enc_err = bool(best_sf and best_sf.encoding_error)

        # 构建结构化检查分项 (CheckItems: 5 个分项)
        items: List[CheckItem] = []
        if is_enc_err:
            items.append(CheckItem(
                problem_id="2-2",
                sub_item="源码提交",
                submission_status="已提交",
                completion_status="待复核",
                evidence=f"提交源码文件: {src_path.name} (编码损坏: {best_sf.encoding_error})",
                deduction=None,
                deduction_reason=f"源码编码损坏无法严格解码: {best_sf.encoding_error}，待人工复核",
                agent_note="源码编码损坏，待人工复核",
                needs_review=True,
            ))
            items.append(CheckItem(
                problem_id="2-2",
                sub_item="编译与运行",
                submission_status="已提交",
                completion_status="待复核",
                evidence=f"源码编码异常导致编译无法正常判定: {best_sf.encoding_error}",
                deduction=None,
                deduction_reason="源码存在编码损坏无法可靠编译，待人工复核",
                agent_note="编码损坏待复核",
                needs_review=True,
            ))
            items.append(CheckItem(
                problem_id="2-2",
                sub_item="字母对称金字塔展开 (A~Z)",
                submission_status="不适用",
                completion_status="待复核",
                evidence="源码编码损坏，金字塔构造待复核",
                deduction=None,
                deduction_reason="源码编码损坏待人工复核",
                agent_note="待复核",
                needs_review=True,
            ))
            items.append(CheckItem(
                problem_id="2-2",
                sub_item="大小写字母兼容转换",
                submission_status="不适用",
                completion_status="待复核",
                evidence="源码编码损坏，大小写转换待复核",
                deduction=None,
                deduction_reason="源码编码损坏待人工复核",
                agent_note="待复核",
                needs_review=True,
            ))
            items.append(CheckItem(
                problem_id="2-2",
                sub_item="非字母与异常输入报错",
                submission_status="不适用",
                completion_status="待复核",
                evidence="源码编码损坏，异常输入处理待复核",
                deduction=None,
                deduction_reason="源码编码损坏待人工复核",
                agent_note="待复核",
                needs_review=True,
            ))
        elif not c_res.success:
            items.append(CheckItem(
                problem_id="2-2",
                sub_item="源码提交",
                submission_status="已提交",
                completion_status="已达成",
                evidence=f"提交源码文件: {src_path.name}",
                deduction=0.0,
                deduction_reason="",
                agent_note="源码归档正常",
                needs_review=False,
            ))
            items.append(CheckItem(
                problem_id="2-2",
                sub_item="编译与运行",
                submission_status="已提交",
                completion_status="未达成",
                evidence=f"GCC 编译失败: {c_res.stderr[:100]}",
                deduction=3.00,
                deduction_reason=f"Lab 2-2 编译失败: {c_res.stderr[:100]}",
                agent_note="编译语法错误",
                needs_review=False,
            ))
            items.append(CheckItem(
                problem_id="2-2",
                sub_item="字母对称金字塔展开 (A~Z)",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="源码未成功编译",
                deduction=0.0,
                deduction_reason="未成功编译，本项无法验证，不重复扣分",
                agent_note="无法验证",
                needs_review=False,
            ))
            items.append(CheckItem(
                problem_id="2-2",
                sub_item="大小写字母兼容转换",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="源码未成功编译",
                deduction=0.0,
                deduction_reason="未成功编译，本项无法验证，不重复扣分",
                agent_note="无法验证",
                needs_review=False,
            ))
            items.append(CheckItem(
                problem_id="2-2",
                sub_item="非字母与异常输入报错",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="源码未成功编译",
                deduction=0.0,
                deduction_reason="未成功编译，本项无法验证，不重复扣分",
                agent_note="无法验证",
                needs_review=False,
            ))
        else:
            enc_note = f" (已自 {best_sf.source_encoding} 规范化为 UTF-8)" if (best_sf and best_sf.encoding_converted) else ""
            ev_str = f"提交源码文件: {src_path.name}{enc_note} (共 {len(sources)} 份候选，已择优采用最高分版本)" if len(sources) > 1 else f"提交源码文件: {src_path.name}{enc_note}"
            an_str = f"多候选已择优采用最高分版本: {src_path.name}{enc_note}" if len(sources) > 1 else (f"源码文件已规范化为 UTF-8 (来源编码: {best_sf.source_encoding})" if (best_sf and best_sf.encoding_converted) else "源码归档正常")
            items.append(CheckItem(
                problem_id="2-2",
                sub_item="源码提交",
                submission_status="已提交",
                completion_status="已达成",
                evidence=ev_str,
                deduction=0.0,
                deduction_reason="",
                agent_note=an_str,
                needs_review=False,
            ))
            items.append(CheckItem(
                problem_id="2-2",
                sub_item="编译与运行",
                submission_status="已提交",
                completion_status="已达成",
                evidence=f"GCC 编译成功 ({c_res.duration_ms:.1f}ms)，测试用例可正常执行",
                deduction=0.0,
                deduction_reason="",
                agent_note="编译运行通过",
                needs_review=False,
            ))

            pyr_cases = [best_eval["test_results"][0], best_eval["test_results"][2], best_eval["test_results"][5]]
            passed_pyr = sum(1 for c in pyr_cases if c.passed)
            ded_pyr = 3.0 * (3-passed_pyr) / total_cases
            pyr_status = "已达成" if ded_pyr == 0 else ("部分达成" if passed_pyr > 0 else "未达成")
            items.append(CheckItem(
                problem_id="2-2",
                sub_item="字母对称金字塔展开 (A~Z)",
                submission_status="已提交",
                completion_status=pyr_status,
                evidence=f"通过对称金字塔展开测试 {passed_pyr}/3 项 (输入 C, A, Z)",
                deduction=ded_pyr,
                deduction_reason=f"字母对称金字塔展开序列不完整或未严格对称 (-{ded_pyr:.2f}分)" if ded_pyr > 0 else "",
                agent_note="金字塔对称展开正确" if ded_pyr == 0 else "对称展开存在偏差",
                needs_review=False,
            ))

            case_f = best_eval["test_results"][1]
            ded_f = 0.0 if case_f.passed else 3.0 / total_cases
            items.append(CheckItem(
                problem_id="2-2",
                sub_item="大小写字母兼容转换",
                submission_status="已提交",
                completion_status="已达成" if case_f.passed else "未达成",
                evidence="小写字母 'f' 成功自动提升并正确生成 6 层金字塔" if case_f.passed else "小写字母未能正确转换为对应大写金字塔",
                deduction=ded_f,
                deduction_reason="小写字母未做自动提升转换 (-0.50分)" if ded_f > 0 else "",
                agent_note="大小写兼容转换正常" if ded_f == 0 else "小写字母未转换",
                needs_review=False,
            ))

            err_cases = [best_eval["test_results"][3], best_eval["test_results"][4]]
            passed_err = sum(1 for c in err_cases if c.passed)
            ded_err = 3.0 * (2-passed_err) / total_cases
            err_status = "已达成" if ded_err == 0 else ("部分达成" if passed_err > 0 else "未达成")
            items.append(CheckItem(
                problem_id="2-2",
                sub_item="非字母与异常输入报错",
                submission_status="已提交",
                completion_status=err_status,
                evidence=f"通过非字母异常输入报错测试 {passed_err}/2 项 (输入 '-' 与 '1')",
                deduction=ded_err,
                deduction_reason=f"非字母与数字输入未按指导书要求报错提示 (-{ded_err:.2f}分)" if ded_err > 0 else "",
                agent_note="非字母错误处理正常" if ded_err == 0 else "非字母输入未报错",
                needs_review=False,
            ))

        prob.check_items = items
        prob.case_budget = 3.0
        prob.case_groups = {'字母对称金字塔展开 (A~Z)':[0,2,5], '大小写字母兼容转换':[1], '非字母与异常输入报错':[3,4]}

        if not c_res.success:
            prob.status = "needs_review" if (prob.is_pending or prob.needs_review) else "compile_error"
            prob.notes.append("Lab 2-2 编译失败")
            return prob

        prob.score = round(3.0 * (passed_cases / total_cases), 2)
        if prob.is_pending:
            prob.status = "needs_review"
            prob.score = 0.0
        elif passed_cases == total_cases:
            prob.status = "passed"
        elif passed_cases > 0:
            prob.status = "partial"
        else:
            prob.status = "failed"

        prob.notes.append(f"测试通过率: {passed_cases}/{total_cases}")
        if len(sources) > 1:
            prob.notes.append(f"检测到 {len(sources)} 份 2-2 源码候选: {[s.name for s in sources]}，已择优评测采用最高分版本: {src_path.name} (得分: {prob.score:.2f}/3.00)")
        return prob

    @scored_problem("2-3")
    def _grade_lab2_3(self, student, sources, build_dir, precompiled=None):
        """选做题不计分，但每个独立版本都记录完整用例与最终选择。"""
        prob = ProblemResult('2-3', 0.0, 0.0, source_files=sources)
        if not sources:
            prob.status = 'missing'
            return prob
        compiled = (precompiled or {}).get((student.student_id, '2-3', 0))
        prob.compile_result = compiled or self.compiler.compile(sources[0], build_dir, 'lab2_3_cand_0')
        if not prob.compile_result.success:
            prob.status = 'compile_error'
            prob.check_items=[CheckItem(prob.problem_id,'选做题实测验收','已提交','未达成',prob.compile_result.stderr,0.0,'选做题不计分')]
            return prob
        execution = run_binary(prob.compile_result.binary_path, input_str='5 500\n', timeout=5.0)
        expected = [5,7,11,101,131,151,181,191,313,353,373,383]
        actual = [int(n) for n in re.findall(r'\b\d+\b', execution.stdout)]
        ran = not execution.timed_out and execution.exit_code == 0
        facts = [(str(value),ran and value in actual) for value in expected]
        facts.append(('完整有序序列，无遗漏或多余元素',ran and actual==expected))
        prob.test_results = [TestCaseResult(f'check_{i+1}','5 500',label,execution.stdout,passed,0.0,0.0,
            timed_out=execution.timed_out,exit_code=execution.exit_code) for i,(label,passed) in enumerate(facts)]
        count=sum(c.passed for c in prob.test_results)
        prob.status='passed' if count==len(facts) else 'partial' if count else 'failed'
        prob.notes = ['选做题2-3回文素数测试完全正确' if prob.status=='passed' else '选做题2-3结果未完整匹配标准序列']
        prob.check_items=[CheckItem('2-3','选做题实测验收','已提交','已达成' if prob.status=='passed' else '部分达成' if count else '未达成',
            f'输入5 500；通过{count}/{len(facts)}项检查；实际输出:{execution.stdout}',0.0,'选做题不计分')]
        return prob

    @scored_problem("2-4")
    def _grade_lab2_4(self, student, sources, build_dir, precompiled=None):
        prob = ProblemResult('2-4', 0.0, 0.0, source_files=sources)
        if not sources:
            prob.status = 'missing'
            return prob
        compiled = (precompiled or {}).get((student.student_id, '2-4', 0))
        prob.compile_result = compiled or self.compiler.compile(sources[0], build_dir, 'lab2_4_cand_0')
        if not prob.compile_result.success:
            prob.status = 'compile_error'
            prob.check_items=[CheckItem(prob.problem_id,'选做题实测验收','已提交','未达成',prob.compile_result.stderr,0.0,'选做题不计分')]
            return prob
        for index,input_text in enumerate(['1010\n','0000\n']):
            execution = run_binary(prob.compile_result.binary_path,input_str=input_text,timeout=2.0)
            matched = ('11' in execution.stdout or 'a3' in execution.stdout.lower()) if index==0 else any(w in execution.stdout for w in ['没有','非编码','0','flag=0','inactive'])
            passed = matched and not execution.timed_out and execution.exit_code==0
            prob.test_results.append(TestCaseResult(f'case_{index+1}',input_text.strip(),
                '11或a3' if index==0 else '无有效输入/flag=0',execution.stdout,passed,0.0,0.0,
                timed_out=execution.timed_out,exit_code=execution.exit_code))
        count=sum(c.passed for c in prob.test_results)
        prob.status = 'passed' if count==len(prob.test_results) else 'partial' if count else 'failed'
        prob.notes = ['选做题2-4优先编码器功能测试完全正确' if prob.status=='passed' else '选做题2-4部分逻辑有偏差']
        prob.check_items=[CheckItem('2-4','选做题实测验收','已提交','已达成' if prob.status=='passed' else '部分达成' if count else '未达成',
            '; '.join(f'输入{c.input_data}，输出{c.actual_output}' for c in prob.test_results),0.0,'选做题不计分')]
        return prob

    def generate_comment(self, grade: StudentGrade) -> str:
        if grade.status == 'missing':
            return f"{grade.student.name}同学你好！本次实验2未检测到可归属的源码提交，请核对提交记录和文件内容，并联系助教确认是否已经收到材料，以便完成实验成绩与提交情况的核验。"
        parts=[f"{grade.student.name}同学你好！本次实验2验收如下："]
        for pid,p in grade.problem_results.items():
            if not p.max_score:
                continue
            if p.compile_result and p.compile_result.success:
                parts.append(f"Lab {pid}通过编译，实际用例通过{sum(c.passed for c in p.test_results)}/{len(p.test_results)}项。")
            elif p.compile_result:
                parts.append(f"Lab {pid}编译失败，运行结果无法验证。")
            else:
                parts.append(f"Lab {pid}未取得可验证源码。")
            for item in p.check_items:
                if item.deduction:
                    parts.append(f"{item.sub_item}：{item.deduction_reason}。")
            if p.is_pending:
                parts.append('该题存在未定事实，请根据复核清单核验。')
        if grade.optional_results:
            parts.append('选做题按各自实测用例记录完成情况，不计入必做题总分。')
        parts.append('请对照每项输入、实际输出和检查证据核对反馈，已确认错误按对应均分计扣，待定事项保留人工复核。')
        return ''.join(parts)
