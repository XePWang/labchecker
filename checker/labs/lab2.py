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
from checker.labs.base import BaseLabJudge
from checker.models import (
    CompileResult,
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

    def grade_student(
        self,
        student: Student,
        files: List[SubmissionFile],
        build_dir: Path,
        mock_ai: bool = False,
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

        # 1. 记录 Warmup 热身情况 (0分)
        if warmup_files:
            grade.problem_results["warmup"] = ProblemResult(
                problem_id="warmup",
                score=0.0,
                max_score=0.0,
                status="passed",
                notes=[f"已提交热身练习文件 ({len(warmup_files)}个)，依课程规则不计入实验总分"],
                source_files=warmup_files,
            )

        # 2. 评测 Lab 2-1 (2.0分)
        res2_1 = self._grade_lab2_1(student, p2_1_sources, student_build_dir, mock_ai)
        grade.problem_results["2-1"] = res2_1

        # 3. 评测 Lab 2-2 (3.0分)
        res2_2 = self._grade_lab2_2(student, p2_2_sources, student_build_dir, mock_ai)
        grade.problem_results["2-2"] = res2_2

        # 4. 评测选做题 Lab 2-3 与 2-4 (独立记录完成情况)
        if p2_3_sources:
            grade.optional_results["2-3"] = self._grade_lab2_3(student, p2_3_sources, student_build_dir)
        if p2_4_sources:
            grade.optional_results["2-4"] = self._grade_lab2_4(student, p2_4_sources, student_build_dir)

        # 汇总总分
        grade.total_score = round(res2_1.score + res2_2.score, 2)
        if any(r.needs_review for r in grade.problem_results.values()):
            grade.needs_review = True
            for r in grade.problem_results.values():
                grade.review_reasons.extend(r.review_reasons)

        if any(r.is_pending for r in grade.problem_results.values()):
            grade.is_pending = True

        if not files:
            grade.status = "missing"
            grade.total_score = 0.0
        elif res2_1.status == "compile_error" and res2_2.status == "compile_error":
            grade.status = "compile_error"
        elif grade.needs_review:
            grade.status = "needs_review"
        else:
            grade.status = "graded"

        # 生成评语
        grade.comment = self.generate_comment(grade)
        return grade

    def _grade_lab2_1(
        self,
        student: Student,
        sources: List[Path],
        build_dir: Path,
        mock_ai: bool,
    ) -> ProblemResult:
        """评测 Lab 2-1：时间段问候 (2.0分)"""
        prob = ProblemResult(problem_id="2-1", score=0.0, max_score=2.0, source_files=sources)

        if not sources:
            prob.status = "missing"
            prob.notes.append("未提交 Lab 2-1 源码")
            return prob

        src_path = sources[0]
        if len(sources) > 1:
            prob.notes.append(f"发现多份 2-1 源码候选，默认评测: {src_path.name}")
            prob.needs_review = True
            prob.review_reasons.append(f"同题多候选: {[s.name for s in sources]}")

        src_text = src_path.read_text(encoding="utf-8", errors="ignore")
        c_res = self.compiler.compile(src_path, build_dir, "lab2_1")
        prob.compile_result = c_res

        if not c_res.success:
            prob.status = "compile_error"
            prob.notes.append("Lab 2-1 编译失败")
            return prob

        passed_cases = 0
        total_cases = len(self.lab2_1_cases)

        for idx, (in_str, category, keywords) in enumerate(self.lab2_1_cases, 1):
            exec_res = run_binary(c_res.binary_path, input_str=in_str, timeout=2.0)

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
                # 语义关键词匹配
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
                    if not mock_ai and idx == 1:
                        ai_sem = SemanticAmbiguityReviewer.review_output(
                            problem_id="2-1",
                            student_id=student.student_id,
                            input_data=in_str,
                            expected_behavior=f"时间问候语义对齐 {category}",
                            actual_output=exec_res.stdout,
                            source_code=src_text,
                            max_score=case_res.max_score,
                            mock_mode=mock_ai,
                        )
                        if ai_sem.get("passed"):
                            case_res.passed = True
                            case_res.score = case_res.max_score
                            passed_cases += 1
                            prob.notes.append(f"用例 {idx} 经 AI 语义复核确认问候语正确")

            prob.test_results.append(case_res)

        prob.score = round(2.0 * (passed_cases / total_cases), 2)
        if passed_cases == total_cases:
            prob.status = "passed"
        elif passed_cases > 0:
            prob.status = "partial"
        else:
            prob.status = "failed"

        prob.notes.append(f"测试通过率: {passed_cases}/{total_cases}")
        return prob

    def _grade_lab2_2(
        self,
        student: Student,
        sources: List[Path],
        build_dir: Path,
        mock_ai: bool,
    ) -> ProblemResult:
        """
        评测 Lab 2-2：字母金字塔 (3.0分)
        验证对称序列、层数、大小写自动提升及非字母错误提示。
        兼容指导书笔误：第3行 ABCBC 与 ABCBA 均予以识别。
        """
        prob = ProblemResult(problem_id="2-2", score=0.0, max_score=3.0, source_files=sources)

        if not sources:
            prob.status = "missing"
            prob.notes.append("未提交 Lab 2-2 源码")
            return prob

        src_path = sources[0]
        if len(sources) > 1:
            prob.notes.append(f"发现多份 2-2 源码候选，默认评测: {src_path.name}")
            prob.needs_review = True
            prob.review_reasons.append(f"同题多候选: {[s.name for s in sources]}")

        c_res = self.compiler.compile(src_path, build_dir, "lab2_2")
        prob.compile_result = c_res

        if not c_res.success:
            prob.status = "compile_error"
            prob.notes.append("Lab 2-2 编译失败")
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

        passed_cases = 0
        total_cases = len(test_pyramids)
        typo_detected = False

        for idx, (in_char, exp_lines, exp_final_seq, is_error_test) in enumerate(test_pyramids, 1):
            exec_res = run_binary(c_res.binary_path, input_str=in_char, timeout=2.0)

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

            prob.test_results.append(case_res)

        if typo_detected:
            prob.notes.append("检测到输出匹配指导书样例笔误 ABCBC，已按课程容错规则判定通过")

        prob.score = round(3.0 * (passed_cases / total_cases), 2)
        if passed_cases == total_cases:
            prob.status = "passed"
        elif passed_cases > 0:
            prob.status = "partial"
        else:
            prob.status = "failed"

        prob.notes.append(f"测试通过率: {passed_cases}/{total_cases}")
        return prob

    def _grade_lab2_3(self, student: Student, sources: List[Path], build_dir: Path) -> ProblemResult:
        """选做题 Lab 2-3：回文素数"""
        prob = ProblemResult(problem_id="2-3", score=0.0, max_score=0.0, source_files=sources)
        c_res = self.compiler.compile(sources[0], build_dir, "lab2_3")
        prob.compile_result = c_res
        if c_res.success:
            exec_res = run_binary(c_res.binary_path, input_str="5 500\n", timeout=5.0)
            nums = [int(n) for n in re.findall(r"\b\d+\b", exec_res.stdout)]
            expected = [5, 7, 11, 101, 131, 151, 181, 191, 313, 353, 373, 383]
            if nums == expected:
                prob.status = "passed"
                prob.notes.append("选做题2-3回文素数测试完全正确")
            else:
                prob.status = "partial"
                prob.notes.append(f"选做题2-3结果部分匹配 (输出 {len(nums)} 个回文素数)")
        else:
            prob.status = "compile_error"
        return prob

    def _grade_lab2_4(self, student: Student, sources: List[Path], build_dir: Path) -> ProblemResult:
        """选做题 Lab 2-4：4:2 优先编码器"""
        prob = ProblemResult(problem_id="2-4", score=0.0, max_score=0.0, source_files=sources)
        c_res = self.compiler.compile(sources[0], build_dir, "lab2_4")
        prob.compile_result = c_res
        if c_res.success:
            # 测试 1010 -> 11, 0000 -> 非编码状态
            res1 = run_binary(c_res.binary_path, input_str="1010\n", timeout=2.0)
            res2 = run_binary(c_res.binary_path, input_str="0000\n", timeout=2.0)
            ok1 = "11" in res1.stdout or "a3" in res1.stdout.lower()
            ok2 = any(w in res2.stdout for w in ["没有", "非编码", "0", "flag=0", "inactive"])
            if ok1 and ok2:
                prob.status = "passed"
                prob.notes.append("选做题2-4优先编码器功能测试完全正确")
            else:
                prob.status = "partial"
                prob.notes.append("选做题2-4部分逻辑有偏差")
        else:
            prob.status = "compile_error"
        return prob

    def generate_comment(self, grade: StudentGrade) -> str:
        """生成不少于 50 字的定制评语"""
        student = grade.student
        r2_1 = grade.problem_results.get("2-1")
        r2_2 = grade.problem_results.get("2-2")
        has_warmup = "warmup" in grade.problem_results
        has_optional = bool(grade.optional_results)

        parts = [f"{student.name}同学你好！本次实验2重点考核分支判断、循环嵌套与字符处理逻辑。"]

        if grade.status == "missing":
            return f"{student.name}同学你好！系统未检测到你在实验2提交的有效源程序，请及时排查是否压缩包命名规范或未在截止时间前上传。请尽快联系助教补交，以确保本次实验平时成绩的有效录入。"

        if has_warmup:
            parts.append("积极完成了热身练习，编程态度值得表扬；")

        # 2-1 评述
        if r2_1:
            if r2_1.status == "passed":
                parts.append("Lab 2-1时间问候程序逻辑清晰，精确覆盖了各时段分界点与非法输入测试；")
            elif r2_1.status == "partial":
                parts.append("Lab 2-1基本实现了时间分支，但在边界条件或非法值判断上存在疏漏，需细化if分支；")
            elif r2_1.status == "compile_error":
                parts.append("Lab 2-1程序编译异常，请注意检查基础语法与变量定义；")
            else:
                parts.append("Lab 2-1未能通过基础问候语测试，请强化条件分支训练；")

        # 2-2 评述
        if r2_2:
            if r2_2.status == "passed":
                parts.append("Lab 2-2字母金字塔算法功底扎实，循环控制与字母镜像对称逻辑构建得非常漂亮！")
            elif r2_2.status == "partial":
                parts.append("Lab 2-2生成了字母金字塔，但在大小写转换或非字母错误处理上尚有优化空间。")
            elif r2_2.status == "compile_error":
                parts.append("Lab 2-2未能编译成功，建议在本地集成环境中单步调试循环。")
            else:
                parts.append("Lab 2-2字符循环逻辑有误，需深入理解嵌套循环索引变量的变化规律。")

        if has_optional:
            parts.append("同时探索并提交了选做拓展题，体现了优秀的自主学习探究能力。")

        comment = "".join(parts)
        if len(comment) < 50:
            comment += "整体实验表现良好，望在后续大作业中继续保持严谨求实的编程习惯！"

        return comment
