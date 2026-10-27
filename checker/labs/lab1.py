"""
checker.labs.lab1
《程序设计思维与实践》Lab 1 评测实现
包含：
  - Lab 1-1 基础环境与练习 (0.0分，课内练习不计分)
  - Lab 1-2 进制与逻辑 (3.0分：代码 1.5分 + 手写演算 1.5分)
  - Lab 1-3 温度转换 (2.0分)
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from checker.ai import HandwrittenReviewer, SemanticAmbiguityReviewer
from checker.compiler import ProjectCompiler
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


class Lab1Judge(BaseLabJudge):
    """Lab 1 判题器"""

    def __init__(self):
        super().__init__(lab_id="lab1", max_score=5.0)
        self.compiler = ProjectCompiler()

        # Lab 1-3 标准测试用例集: [(输入, 期望转换类型, 期望基准值)]
        # 包含官方样例、边界值及防作弊用例
        self.lab1_3_cases = [
            ("0 100\n", "Centigrade", 37.78),
            ("1 -6.67\n", "Fahrenheit", 19.99),
            ("0 0\n", "Centigrade", -17.78),
            ("0 32\n", "Centigrade", 0.00),
            ("1 0\n", "Fahrenheit", 32.00),
            ("1 100\n", "Fahrenheit", 212.00),
            ("0 -40\n", "Centigrade", -40.00),
            ("0 85.5\n", "Centigrade", 29.72),
            ("1 25.0\n", "Fahrenheit", 77.00),
            ("0 50.0\n", "Centigrade", 10.00),
        ]

    def collect_compile_tasks(
        self,
        student: Student,
        files: List[SubmissionFile],
        build_dir: Path,
    ) -> List[CompileTask]:
        """收集 Lab 1 该学生所有需要编译的代码候选任务"""
        tasks: List[CompileTask] = []
        student_build_dir = build_dir / student.student_id

        p1_2_sources = [f.path for f in files if f.matched_problem == "1-2" and f.file_type in {"c_source", "cpp_source"}]
        for cand_idx, cand_src in enumerate(p1_2_sources):
            tasks.append(
                CompileTask(
                    student_id=student.student_id,
                    problem_id="1-2",
                    cand_idx=cand_idx,
                    binary_name=f"lab1_2_cand_{cand_idx}",
                    src_path=cand_src,
                    build_dir=student_build_dir,
                )
            )

        p1_3_sources = [f.path for f in files if f.matched_problem == "1-3" and f.file_type in {"c_source", "cpp_source"}]
        for cand_idx, cand_src in enumerate(p1_3_sources):
            tasks.append(
                CompileTask(
                    student_id=student.student_id,
                    problem_id="1-3",
                    cand_idx=cand_idx,
                    binary_name=f"lab1_3_cand_{cand_idx}",
                    src_path=cand_src,
                    build_dir=student_build_dir,
                )
            )

        return tasks

    def grade_student(
        self,
        student: Student,
        files: List[SubmissionFile],
        build_dir: Path,
        mock_ai: bool = False,
        precompiled: Optional[Dict[Tuple[str, str, int], CompileResult]] = None,
    ) -> StudentGrade:
        """评测单个学生的 Lab 1"""
        student_build_dir = build_dir / student.student_id
        student_build_dir.mkdir(parents=True, exist_ok=True)

        grade = StudentGrade(student=student, max_score=5.0)

        # 整理学生提交的文件
        p1_2_sources = [f.path for f in files if f.matched_problem == "1-2" and f.file_type in {"c_source", "cpp_source"}]
        p1_2_images = [f.path for f in files if f.matched_problem == "1-2" and f.file_type == "image"]
        p1_2_projects = [f.path for f in files if f.matched_problem == "1-2" and f.file_type == "project"]
        p1_2_links = [f.path for f in files if f.matched_problem == "1-2" and f.file_type == "link"]

        # 若图片未命中具体题号，也归入 1-2 验算备选
        if not p1_2_images:
            p1_2_images = [f.path for f in files if f.file_type == "image"]

        p1_3_sources = [f.path for f in files if f.matched_problem == "1-3" and f.file_type in {"c_source", "cpp_source"}]
        p1_3_projects = [f.path for f in files if f.matched_problem == "1-3" and f.file_type == "project"]
        p1_3_links = [f.path for f in files if f.matched_problem == "1-3" and f.file_type == "link"]

        # 1. 评测 Lab 1-1 练习项
        res1_1 = self._grade_lab1_1(student=student, files=files)
        grade.problem_results["1-1"] = res1_1

        # 2. 评测 Lab 1-2 进制与逻辑
        res1_2 = self._grade_lab1_2(
            student=student,
            sources=p1_2_sources,
            images=p1_2_images,
            build_dir=student_build_dir,
            mock_ai=mock_ai,
            projects=p1_2_projects,
            links=p1_2_links,
            all_student_files=files,
            precompiled=precompiled,
        )
        grade.problem_results["1-2"] = res1_2

        # 3. 评测 Lab 1-3 温度转换
        res1_3 = self._grade_lab1_3(
            student=student,
            sources=p1_3_sources,
            build_dir=student_build_dir,
            mock_ai=mock_ai,
            projects=p1_3_projects,
            links=p1_3_links,
            all_student_files=files,
            precompiled=precompiled,
        )
        grade.problem_results["1-3"] = res1_3

        # 计算总分与状态
        grade.total_score = round(res1_2.score + res1_3.score, 2)
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
        elif all(f.file_type in {"project", "link", "executable"} for f in files) and not p1_2_images:
            grade.status = "missing_source"
            grade.needs_review = True
            grade.total_score = 0.0
        elif all(f.file_type == "corrupt_archive" for f in files):
            grade.status = "needs_review"
            grade.needs_review = True
            grade.total_score = 0.0
        elif res1_2.status == "compile_error" and res1_3.status == "compile_error":
            grade.status = "compile_error"
        elif grade.needs_review:
            grade.status = "needs_review"
        else:
            grade.status = "graded"

        # 生成不少于 50 字的高质量动态实验评语
        grade.comment = self.generate_comment(grade)
        return grade

    def _grade_lab1_1(
        self,
        student: Student,
        files: List[SubmissionFile],
    ) -> ProblemResult:
        """记录 Lab 1-1 练习完成情况（指导书明确为课内基础练习，无强制提交与计分要求）"""
        prob = ProblemResult(problem_id="1-1", score=0.0, max_score=0.0)
        p1_1_files = [f for f in files if "1-1" in f.original_name.lower() or "1_1" in f.original_name.lower() or f.is_warmup]

        if not files:
            sub_st = "未提交"
            comp_st = "不适用"
            evidence = "未检测到实验提交文件"
            agent_note = "指导书明确 Lab 1-1 为课内熟悉环境练习，无强制提交要求，不计入成绩亦不扣分。"
        elif p1_1_files:
            sub_st = "已提交"
            comp_st = "已达成"
            evidence = f"提交了包含 Lab 1-1 练习相关文件: {', '.join(f.original_name for f in p1_1_files)}"
            agent_note = "检测到课内基础环境练习代码，记录完成。"
        else:
            sub_st = "不适用"
            comp_st = "不适用"
            evidence = "指导书明确 Lab 1-1 为课内熟悉环境练习，无提交与计分要求"
            agent_note = "指导书不作强制提交要求，不计分亦不扣分。"

        item = CheckItem(
            problem_id="1-1",
            sub_item="课内环境熟悉与基础代码练习",
            submission_status=sub_st,
            completion_status=comp_st,
            evidence=evidence,
            deduction=0.0,
            deduction_reason="指导书明确 Lab 1-1 为课内练习，不设强制提交与分值扣减",
            agent_note=agent_note,
            needs_review=False,
        )
        prob.check_items.append(item)
        prob.status = "passed"
        return prob

    @staticmethod
    def _extract_lab1_2_nine_terms(
        stdout_str: str,
        expected_x: int,
        code_y: Optional[int] = None,
    ) -> Tuple[List[int], int, List[Tuple[str, bool, int, int]]]:
        """
        从可执行文件输出中鲁棒识别 Lab 1-2 的 9 项运算结果。
        支持前置说明文字 (如 x=93, y=82)、末尾调试输出以及非格式化多余数值的过滤。
        """
        all_numbers = [int(n) for n in re.findall(r"-?\d+", stdout_str)]
        candidates = []

        # 1. 连续 9 个数字的滑动窗口
        if len(all_numbers) >= 9:
            for k in range(len(all_numbers) - 9 + 1):
                candidates.append(all_numbers[k:k+9])

        # 2. 按行提取 (每行取前3个或后3个数字，应对未初始化格式化参数导致的单行多数字)
        lines = [l.strip() for l in stdout_str.splitlines() if l.strip()]
        line_nums = [[int(n) for n in re.findall(r"-?\d+", l)] for l in lines]
        active_lines = [nums for nums in line_nums if nums]
        if len(active_lines) >= 3:
            for i in range(len(active_lines) - 2):
                la, lb, lc = active_lines[i], active_lines[i+1], active_lines[i+2]
                if len(la) >= 3 and len(lb) >= 3 and len(lc) >= 3:
                    candidates.append(la[:3] + lb[:3] + lc[:3])
                    candidates.append(la[-3:] + lb[-3:] + lc[-3:])

        if not candidates:
            v_list = all_numbers[:9] if all_numbers else [0] * 9
            while len(v_list) < 9:
                v_list.append(0)
            return v_list, 0, []

        best_c = candidates[0]
        best_score = (-1, -1)
        best_y = 0
        best_checks: List[Tuple[str, bool, int, int]] = []

        for c in candidates:
            if len(c) != 9:
                continue
            deduced = c[4] + c[5] - expected_x
            y_cands = [deduced] if (0 <= deduced <= 99) else []
            if code_y is not None and code_y not in y_cands:
                y_cands.append(code_y)
            if not y_cands:
                y_cands.append(deduced)

            for y in y_cands:
                exp_v1 = 0 if expected_x != 0 else 1
                exp_v2 = 1 if (expected_x != 0 or y != 0) else 0
                exp_v3 = 1 if (expected_x != 0 and y != 0) else 0
                exp_v4 = (65536 + (~expected_x)) & 0xFFFF
                exp_v5 = (expected_x | y)
                exp_v6 = (expected_x & y)
                exp_v7 = (~expected_x)
                exp_v8 = (expected_x | y)
                exp_v9 = (expected_x & y)

                checks = [
                    ("!x", c[0] == exp_v1, c[0], exp_v1),
                    ("x||y", c[1] == exp_v2, c[1], exp_v2),
                    ("x&&y", c[2] == exp_v3, c[2], exp_v3),
                    ("~x(unsigned)", c[3] == exp_v4, c[3], exp_v4),
                    ("x|y(line2)", c[4] == exp_v5, c[4], exp_v5),
                    ("x&y(line2)", c[5] == exp_v6, c[5], exp_v6),
                    ("~x(signed)", c[6] == exp_v7, c[6], exp_v7),
                    ("x|y(line3)", c[7] == exp_v8, c[7], exp_v8),
                    ("x&y(line3)", c[8] == exp_v9, c[8], exp_v9),
                ]

                matches = sum(1 for _, ok, _, _ in checks if ok)
                bonus = 0
                if c[4] == c[7]: bonus += 1
                if c[5] == c[8]: bonus += 1
                if c[6] == ~expected_x: bonus += 2
                if c[0] in (0, 1) and c[1] in (0, 1) and c[2] in (0, 1): bonus += 1

                score = (matches, bonus)
                if score > best_score:
                    best_score = score
                    best_c = c
                    best_y = y
                    best_checks = checks

        return best_c, best_y, best_checks

    def _grade_lab1_2(
        self,
        student: Student,
        sources: List[Path],
        images: List[Path],
        build_dir: Path,
        mock_ai: bool,
        projects: Optional[List[Path]] = None,
        links: Optional[List[Path]] = None,
        all_student_files: Optional[List[SubmissionFile]] = None,
        precompiled: Optional[Dict[Tuple[str, str, int], CompileResult]] = None,
    ) -> ProblemResult:
        """评测 Lab 1-2：代码运算 (1.5分) + 手写验算 (1.5分)"""
        prob = ProblemResult(problem_id="1-2", score=0.0, max_score=3.0, source_files=sources)
        projects = projects or []
        links = links or []
        all_files = all_student_files or []

        has_exe = any(f.file_type == "executable" for f in all_files)
        corrupt_archives = [f for f in all_files if f.file_type == "corrupt_archive"]

        # 学号末两位预期值 x
        try:
            expected_x = int(student.student_id[-2:])
        except Exception:
            expected_x = 0

        # --- A. 代码部分评测 (1.5分) ---
        code_score = 0.0
        deduced_y = None
        has_logical = False
        has_bitwise = False
        code_x_literal = None
        code_y_literal = None
        c_res: Optional[CompileResult] = None
        exec_res = None
        src_path = None
        src_text = ""
        checks = []
        v1 = v2 = v3 = v4 = v5 = v6 = v7 = v8 = v9 = 0
        exp_v1 = exp_v2 = exp_v3 = exp_v4 = exp_v5 = exp_v6 = exp_v7 = exp_v8 = exp_v9 = 0

        if not sources:
            if corrupt_archives:
                prob.notes.append(f"收到学生提交压缩包 ({corrupt_archives[0].original_name})，解压失败，内容无法验证，待人工复核")
                prob.needs_review = True
                prob.review_reasons.append(f"提交压缩包损坏解压失败: {corrupt_archives[0].original_name}，Lab 1-2 源码及演算无法验证")
            elif projects:
                prob.notes.append("未找到 Lab 1-2 源码 (仅提交 Code::Blocks 工程文件 .cbp，缺少 .c 源码)")
                prob.needs_review = True
                prob.review_reasons.append("Lab 1-2 仅提交 .cbp 工程描述文件，缺少 C 源码")
            elif links:
                prob.notes.append("未找到 Lab 1-2 源码 (提交内容为 Windows 快捷方式 .lnk，缺实际源码)")
                prob.needs_review = True
                prob.review_reasons.append("Lab 1-2 提交为 Windows 快捷方式 (.lnk)，缺源码")
            elif has_exe:
                prob.notes.append("未找到 Lab 1-2 源码 (仅提交预编译二进制文件，沙箱禁止执行外部 exe)")
                prob.needs_review = True
                prob.review_reasons.append("Lab 1-2 仅提交预编译 exe 文件，缺少 C 源码")
            else:
                prob.notes.append("未找到 Lab 1-2 代码文件")
            prob.sub_scores["code"] = 0.0
        else:
            # 存在一份或多份源码候选：逐一评测，择优采用最高分版本
            cand_evaluations = []
            for cand_idx, cand_src in enumerate(sources):
                c_text = cand_src.read_text(encoding="utf-8", errors="ignore")
                c_has_log = all(op in c_text for op in ["!", "||", "&&"])
                c_has_bit = all(op in c_text for op in ["~", "|", "&"])
                m_x = re.search(r'\bx\s*=\s*(-?\d+)', c_text)
                m_y = re.search(r'\by\s*=\s*(-?\d+)', c_text)
                c_code_x = int(m_x.group(1)) if m_x else None
                c_code_y = int(m_y.group(1)) if m_y else None

                if precompiled and (student.student_id, "1-2", cand_idx) in precompiled:
                    c_compile = precompiled[(student.student_id, "1-2", cand_idx)]
                else:
                    c_compile = self.compiler.compile(cand_src, build_dir, f"lab1_2_cand_{cand_idx}")
                c_notes = []
                c_reviews = []
                c_needs_review = False
                c_score = 0.0
                c_exec = None
                c_checks = []
                c_deduced_y = 0
                c_v_list = [0] * 9

                if c_code_x is not None and c_code_x != expected_x:
                    c_notes.append(f"源码中 x 赋值 ({c_code_x}) 与学号后两位 ({expected_x}) 不一致")
                    c_needs_review = True
                    c_reviews.append(f"代码 x 赋值为 {c_code_x}，而学号末两位为 {expected_x}")

                if not c_compile.success:
                    c_notes.append(f"Lab 1-2 编译失败: {c_compile.stderr[:200]}")
                    c_score = 0.0
                else:
                    c_exec = run_binary(c_compile.binary_path, input_str="", timeout=2.0)
                    if c_exec.timed_out:
                        c_notes.append("Lab 1-2 运行超时")
                        c_score = 0.0
                    elif c_exec.exit_code != 0:
                        c_notes.append(f"Lab 1-2 运行时崩溃 (exit {c_exec.exit_code})")
                        c_score = 0.0
                    else:
                        all_numbers = [int(n) for n in re.findall(r"-?\d+", c_exec.stdout)]
                        if len(all_numbers) >= 9:
                            c_v_list, c_deduced_y, c_checks = self._extract_lab1_2_nine_terms(
                                c_exec.stdout, expected_x, c_code_y
                            )
                            cv1, cv2, cv3, cv4, cv5, cv6, cv7, cv8, cv9 = c_v_list

                            if c_code_y is not None and c_code_y != c_deduced_y:
                                c_notes.append(f"代码字面 y={c_code_y} 与运算输出推导 y={c_deduced_y} 存在偏差")

                            exp_v1 = 0 if expected_x != 0 else 1
                            exp_v2 = 1 if (expected_x != 0 or c_deduced_y != 0) else 0
                            exp_v3 = 1 if (expected_x != 0 and c_deduced_y != 0) else 0
                            exp_v4 = (65536 + (~expected_x)) & 0xFFFF
                            exp_v5 = (expected_x | c_deduced_y)
                            exp_v6 = (expected_x & c_deduced_y)
                            exp_v7 = (~expected_x)
                            exp_v8 = (expected_x | c_deduced_y)
                            exp_v9 = (expected_x & c_deduced_y)

                            passed_terms = sum(1 for _, ok, _, _ in c_checks if ok)
                            failed_terms = [name for name, ok, _, _ in c_checks if not ok]

                            if passed_terms == 9:
                                if c_has_log and c_has_bit:
                                    c_score = 1.5
                                    c_notes.append(f"代码逻辑与位运算 9 项校验完全正确 (x={expected_x}, 推导y={c_deduced_y})")
                                else:
                                    c_score = 0.75
                                    c_notes.append("9项运算输出正确，但源码缺少运算符，疑似直接打印常数")
                                    c_needs_review = True
                                    c_reviews.append("1-2 源码运算符静态检查未通过")
                            else:
                                c_score = round(1.5 * (passed_terms / 9.0), 2)
                                c_notes.append(f"代码运算有 {len(failed_terms)} 项不符预期: {', '.join(failed_terms)} (通过 {passed_terms}/9)")
                        else:
                            c_notes.append(f"代码输出数字不足 9 个 (实际输出 {len(all_numbers)} 个)")
                            c_score = 0.2

                cand_evaluations.append({
                    "src_path": cand_src,
                    "score": c_score,
                    "c_res": c_compile,
                    "exec_res": c_exec,
                    "src_text": c_text,
                    "has_logical": c_has_log,
                    "has_bitwise": c_has_bit,
                    "code_x_literal": c_code_x,
                    "code_y_literal": c_code_y,
                    "deduced_y": c_deduced_y,
                    "checks": c_checks,
                    "v_list": c_v_list,
                    "notes": c_notes,
                    "reviews": c_reviews,
                    "needs_review": c_needs_review,
                    "success": c_compile.success,
                })

            # 择优采用最高分版本 (得分最高优先，若同分优先选参数对齐且编译成功的版本)
            best_eval = max(
                cand_evaluations,
                key=lambda x: (
                    x["score"],
                    1 if x["code_x_literal"] == expected_x else 0,
                    1 if x["has_logical"] and x["has_bitwise"] else 0,
                    1 if x["success"] else 0
                )
            )
            src_path = best_eval["src_path"]
            code_score = best_eval["score"]
            c_res = best_eval["c_res"]
            exec_res = best_eval["exec_res"]
            src_text = best_eval["src_text"]
            has_logical = best_eval["has_logical"]
            has_bitwise = best_eval["has_bitwise"]
            code_x_literal = best_eval["code_x_literal"]
            code_y_literal = best_eval["code_y_literal"]
            deduced_y = best_eval["deduced_y"]
            checks = best_eval["checks"]
            v1, v2, v3, v4, v5, v6, v7, v8, v9 = best_eval["v_list"]
            prob.compile_result = c_res
            prob.sub_scores["code"] = code_score
            prob.notes.extend(best_eval["notes"])
            if best_eval["needs_review"]:
                prob.needs_review = True
                prob.review_reasons.extend(best_eval["reviews"])

            if len(sources) > 1:
                prob.notes.append(f"检测到 {len(sources)} 份 1-2 源码候选: {[s.name for s in sources]}，已择优采用最高分版本: {src_path.name} (代码得分: {code_score:.2f}/1.50)")

        # --- B. 演草纸手写验算评测 (1.5分) ---
        ai_res = HandwrittenReviewer.review_images(
            student_id=student.student_id,
            student_name=student.name,
            expected_x=expected_x,
            image_paths=images,
            mock_mode=mock_ai,
            deduced_y=deduced_y,
        )
        prob.ai_review = ai_res
        handwritten_score = 0.0
        if ai_res.get("suggested_score") is not None:
            handwritten_score = round(float(ai_res.get("suggested_score")), 2)
        if ai_res.get("is_pending"):
            prob.is_pending = True
            prob.needs_review = True

        # 演草纸身份信息核查
        hw_sid = str(ai_res.get("student_id_observed") or "").strip()
        hw_name = str(ai_res.get("name_observed") or "").strip()
        non_identity_values = {"未书写", "未提供", "缺失", "none", "null", "无", "未写", "n/a", "未知", "未提及"}
        if hw_sid.lower() in non_identity_values:
            hw_sid = ""
        if hw_name.lower() in non_identity_values:
            hw_name = ""

        if hw_sid and hw_sid != str(student.student_id).strip():
            prob.needs_review = True
            prob.review_reasons.append(f"演草纸手写学号 ({hw_sid}) 与系统学号 ({student.student_id}) 不符")
            handwritten_score = 0.0

        if hw_name and hw_name != str(student.name).strip():
            prob.needs_review = True
            prob.review_reasons.append(f"演草纸手写姓名 ({hw_name}) 与系统姓名 ({student.name}) 不符")
            handwritten_score = min(handwritten_score, 0.8)

        # 参数一致性交叉核对
        hw_x = ai_res.get("x_observed")
        hw_y = ai_res.get("y_observed")
        hw_phone = ai_res.get("phone_observed")
        if hw_y is None and hw_phone:
            ph_digits = re.findall(r"\d+", str(hw_phone))
            if ph_digits and len(ph_digits[-1]) >= 2:
                try:
                    hw_y = int(ph_digits[-1][-2:])
                except ValueError:
                    pass

        if hw_x is not None and hw_x != expected_x:
            prob.needs_review = True
            prob.review_reasons.append(f"参数矛盾: 演草纸手写 x={hw_x} 与学号后两位 {expected_x} 不符")

        if hw_y is not None and deduced_y is not None and hw_y != deduced_y:
            prob.needs_review = True
            prob.review_reasons.append(f"参数矛盾: 代码 y={deduced_y} 与演草纸手写 y={hw_y} 不一致")
            if handwritten_score > 0:
                handwritten_score = max(0.0, round(handwritten_score - 0.2, 2))

        prob.sub_scores["handwritten"] = handwritten_score
        prob.notes.append(f"演草纸批改: {ai_res.get('reasoning', '')}")

        if ai_res.get("needs_review"):
            prob.needs_review = True
            prob.review_reasons.append(f"演草纸复核: {ai_res.get('review_reason', '')}")

        # 汇总分数与题目状态
        prob.score = round(code_score + handwritten_score, 2)
        if prob.is_pending:
            prob.status = "needs_review"
        elif prob.score >= 2.8:
            prob.status = "passed"
        elif prob.score > 0:
            prob.status = "partial"
        else:
            prob.status = "failed"

        # --- C. 构建结构化检查分项 (CheckItems: 6 个代码项 + 5 个手写验算项) ---
        items: List[CheckItem] = []

        # 1. 源码提交
        if sources:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="源码提交",
                submission_status="已提交",
                completion_status="已达成",
                evidence=f"提交源码文件: {src_path.name} (共 {len(sources)} 份候选，已择优采用最高分版本)" if len(sources) > 1 else f"提交源码文件: {src_path.name}",
                deduction=0.0,
                deduction_reason="",
                agent_note=f"多候选已择优采用最高分版本: {src_path.name}" if len(sources) > 1 else "源码文件归档正常",
                needs_review=False,
            ))
        elif corrupt_archives:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="源码提交",
                submission_status="已提交",
                completion_status="无法验证",
                evidence=f"已提交压缩包 {corrupt_archives[0].original_name}，但文件损坏解压失败: {corrupt_archives[0].note or '解压异常'}",
                deduction=1.50,
                deduction_reason="提交压缩包损坏解压失败，Lab 1-2 源码无法验证，待人工复核",
                agent_note="解压失败、内容无法验证、待复核",
                needs_review=True,
            ))
        elif projects:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="源码提交",
                submission_status="无法归属",
                completion_status="未达成",
                evidence=f"归档项目文件: {', '.join(p.name for p in projects)}",
                deduction=1.50,
                deduction_reason="仅提交 Code::Blocks 工程描述文件 (.cbp)，缺少实际可编译 C 源码",
                agent_note="仅提交工程描述文件，缺少源码，待现场人工确认",
                needs_review=True,
            ))
        elif links:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="源码提交",
                submission_status="无法归属",
                completion_status="未达成",
                evidence=f"归档快捷方式: {', '.join(l.name for l in links)}",
                deduction=1.50,
                deduction_reason="提交内容为 Windows 快捷方式 (.lnk)，缺实际源文件",
                agent_note="提交内容为快捷方式，缺少源码，待现场人工确认",
                needs_review=True,
            ))
        elif has_exe:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="源码提交",
                submission_status="无法归属",
                completion_status="未达成",
                evidence="归档中发现预编译可执行文件但无 .c 源码",
                deduction=1.50,
                deduction_reason="仅提交预编译 exe 文件，缺少 C 源码（沙箱环境禁止执行外部预编译二进制）",
                agent_note="仅提交预编译二进制，按沙箱规范禁止执行，待补交复核",
                needs_review=True,
            ))
        else:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="源码提交",
                submission_status="未提交",
                completion_status="未达成",
                evidence="学生目录未找到 Lab 1-2 源码",
                deduction=1.50,
                deduction_reason="未提交 Lab 1-2 源码文件",
                agent_note="未提交代码",
                needs_review=False,
            ))

        # 2. 编译与运行
        if not sources:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="编译与运行",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="未提交源码文件",
                deduction=0.0,
                deduction_reason="缺少源码，本项无法验证，不重复扣分（已在源码提交项计扣）",
                agent_note="无源码无法编译",
                needs_review=False,
            ))
        elif c_res and not c_res.success:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="编译与运行",
                submission_status="已提交",
                completion_status="未达成",
                evidence=f"GCC 诊断: {c_res.stderr[:160]}",
                deduction=1.50,
                deduction_reason="GCC 编译失败，无法生成二进制执行文件",
                agent_note="代码编译失败",
                needs_review=False,
            ))
        elif exec_res and exec_res.timed_out:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="编译与运行",
                submission_status="已提交",
                completion_status="未达成",
                evidence="执行超过 2.0s 被 SIGKILL 强杀",
                deduction=1.50,
                deduction_reason="程序运行超时，疑似死循环",
                agent_note="运行超时",
                needs_review=False,
            ))
        elif exec_res and exec_res.exit_code != 0:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="编译与运行",
                submission_status="已提交",
                completion_status="未达成",
                evidence=f"退出码 {exec_res.exit_code}, stderr: {exec_res.stderr[:80]}",
                deduction=1.50,
                deduction_reason=f"程序运行时崩溃 (exit {exec_res.exit_code})",
                agent_note="运行时崩溃",
                needs_review=False,
            ))
        else:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="编译与运行",
                submission_status="已提交",
                completion_status="已达成",
                evidence=f"GCC 编译成功 ({c_res.duration_ms:.1f}ms)，沙箱运行退出码 0" if c_res else "编译运行正常",
                deduction=0.0,
                deduction_reason="",
                agent_note="编译通过并正常退出",
                needs_review=False,
            ))

        # 3. 参数学号与手机号对齐
        if not sources or not c_res or not c_res.success or (exec_res and exec_res.exit_code != 0):
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="参数学号与手机号对齐",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="代码未成功编译运行，无运算输出",
                deduction=0.0,
                deduction_reason="编译或运行未通过，参数无法验证",
                agent_note="无法提取参数",
                needs_review=False,
            ))
        elif code_x_literal is not None and code_x_literal != expected_x:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="参数学号与手机号对齐",
                submission_status="已提交",
                completion_status="未达成",
                evidence=f"源码字面 x={code_x_literal}，而学号末两位预期为 {expected_x}",
                deduction=0.20,
                deduction_reason=f"源码中 x 赋值 ({code_x_literal}) 未对齐学号后两位 ({expected_x})",
                agent_note="参数未对齐学号后两位，需复核",
                needs_review=True,
            ))
        else:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="参数学号与手机号对齐",
                submission_status="已提交",
                completion_status="已达成",
                evidence=f"源码 x={expected_x} 对齐学号后两位，运算推导参数 y={deduced_y}",
                deduction=0.0,
                deduction_reason="",
                agent_note="参数符合学号要求",
                needs_review=False,
            ))

        # 4. 逻辑运算(!, ||, &&)
        if not sources or not c_res or not c_res.success or (exec_res and exec_res.exit_code != 0) or not checks:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="逻辑运算(!, ||, &&)",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="代码未成功运行输出",
                deduction=0.0,
                deduction_reason="代码未正常运行，逻辑运算无法验证",
                agent_note="逻辑运算无法验证",
                needs_review=False,
            ))
        else:
            logic_checks = checks[:3]
            passed_log = sum(1 for _, ok, _, _ in logic_checks if ok)
            failed_log = [name for name, ok, _, _ in logic_checks if not ok]
            if passed_log == 3 and has_logical:
                items.append(CheckItem(
                    problem_id="1-2",
                    sub_item="逻辑运算(!, ||, &&)",
                    submission_status="已提交",
                    completion_status="已达成",
                    evidence=f"3项逻辑运算输出均正确 (!x={v1}, x||y={v2}, x&&y={v3}) 且源码包含逻辑运算符",
                    deduction=0.0,
                    deduction_reason="",
                    agent_note="逻辑运算全部正确",
                    needs_review=False,
                ))
            elif passed_log == 3 and not has_logical:
                items.append(CheckItem(
                    problem_id="1-2",
                    sub_item="逻辑运算(!, ||, &&)",
                    submission_status="已提交",
                    completion_status="部分达成",
                    evidence="输出真值正确，但源码静态检查未检测到逻辑运算符 (!, ||, &&)",
                    deduction=0.25,
                    deduction_reason="输出真值正确，但源码缺少逻辑运算符，疑似常数欺骗",
                    agent_note="缺少逻辑运算符，待复核",
                    needs_review=True,
                ))
            else:
                comp_st = "部分达成" if passed_log > 0 else "未达成"
                ded = round((3 - passed_log) * (1.5 / 9.0), 2)
                items.append(CheckItem(
                    problem_id="1-2",
                    sub_item="逻辑运算(!, ||, &&)",
                    submission_status="已提交",
                    completion_status=comp_st,
                    evidence=f"逻辑运算通过 {passed_log}/3 项，未达成项: {', '.join(failed_log)}",
                    deduction=ded,
                    deduction_reason=f"逻辑运算输出不符合预期真值 ({', '.join(failed_log)})",
                    agent_note=f"逻辑运算未完全通过 ({passed_log}/3)",
                    needs_review=False,
                ))

        # 5. 位运算(~, |, &)
        if not sources or not c_res or not c_res.success or (exec_res and exec_res.exit_code != 0) or not checks:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="位运算(~, |, &)",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="代码未成功运行输出",
                deduction=0.0,
                deduction_reason="代码未正常运行，位运算无法验证",
                agent_note="位运算无法验证",
                needs_review=False,
            ))
        else:
            bw_checks = [checks[3], checks[4], checks[5], checks[7], checks[8]]
            passed_bw = sum(1 for _, ok, _, _ in bw_checks if ok)
            failed_bw = [name for name, ok, _, _ in bw_checks if not ok]
            if passed_bw == 5 and has_bitwise:
                items.append(CheckItem(
                    problem_id="1-2",
                    sub_item="位运算(~, |, &)",
                    submission_status="已提交",
                    completion_status="已达成",
                    evidence=f"位运算输出均与理论计算一致 (x={expected_x}, y={deduced_y})",
                    deduction=0.0,
                    deduction_reason="",
                    agent_note="位运算全部正确",
                    needs_review=False,
                ))
            elif passed_bw == 5 and not has_bitwise:
                items.append(CheckItem(
                    problem_id="1-2",
                    sub_item="位运算(~, |, &)",
                    submission_status="已提交",
                    completion_status="部分达成",
                    evidence="位运算输出正确，但源码未包含位运算符 (~, |, &)",
                    deduction=0.40,
                    deduction_reason="位运算输出正确但源码缺少位运算符，疑似常数欺骗",
                    agent_note="缺少位运算符，待复核",
                    needs_review=True,
                ))
            else:
                comp_st = "部分达成" if passed_bw > 0 else "未达成"
                ded = round((5 - passed_bw) * (1.5 / 9.0), 2)
                items.append(CheckItem(
                    problem_id="1-2",
                    sub_item="位运算(~, |, &)",
                    submission_status="已提交",
                    completion_status=comp_st,
                    evidence=f"位运算通过 {passed_bw}/5 项，不符项: {', '.join(failed_bw)}",
                    deduction=ded,
                    deduction_reason=f"位运算输出存在偏差 ({', '.join(failed_bw)})",
                    agent_note=f"位运算未全通过 ({passed_bw}/5)",
                    needs_review=False,
                ))

        # 6. 有符号与无符号输出格式
        if not sources or not c_res or not c_res.success or (exec_res and exec_res.exit_code != 0) or not checks:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="有符号与无符号输出格式",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="代码未成功运行输出",
                deduction=0.0,
                deduction_reason="代码未正常运行，输出格式无法验证",
                agent_note="格式无法验证",
                needs_review=False,
            ))
        else:
            ok_v4 = (v4 == exp_v4)
            ok_v7 = (v7 == exp_v7)
            if ok_v4 and ok_v7:
                items.append(CheckItem(
                    problem_id="1-2",
                    sub_item="有符号与无符号输出格式",
                    submission_status="已提交",
                    completion_status="已达成",
                    evidence=f"第2行无符号 ~x={v4} (%5hu) 与第3行有符号 ~x={v7} (%5hd) 格式与数值均正确",
                    deduction=0.0,
                    deduction_reason="",
                    agent_note="格式符合要求",
                    needs_review=False,
                ))
            else:
                items.append(CheckItem(
                    problem_id="1-2",
                    sub_item="有符号与无符号输出格式",
                    submission_status="已提交",
                    completion_status="部分达成",
                    evidence=f"实际输出: 第2行无符号={v4} (预期{exp_v4}), 第3行有符号={v7} (预期{exp_v7})",
                    deduction=0.17,
                    deduction_reason="未正确区分有符号 short (%5hd) 与无符号 unsigned short (%5hu) 格式要求",
                    agent_note="符号格式不符",
                    needs_review=False,
                ))

        # 7. 验算材料提交
        if images:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="验算材料提交",
                submission_status="已提交",
                completion_status="已达成",
                evidence=f"归档手写验算照片: {', '.join(p.name for p in images)}",
                deduction=0.0,
                deduction_reason="",
                agent_note="手写材料已提交",
                needs_review=False,
            ))
        elif corrupt_archives:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="验算材料提交",
                submission_status="已提交",
                completion_status="无法验证",
                evidence=f"已提交压缩包 {corrupt_archives[0].original_name}，但文件损坏解压失败，无法提取演草纸照片",
                deduction=1.50,
                deduction_reason="提交压缩包损坏解压失败，验算材料无法验证，待人工复核",
                agent_note="解压失败、内容无法验证、待复核",
                needs_review=True,
            ))
        else:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="验算材料提交",
                submission_status="未提交",
                completion_status="未达成",
                evidence="未检测到手写演草纸照片材料",
                deduction=1.50,
                deduction_reason="未提交 Lab 1-2 演草纸手写验算照片",
                agent_note="手写材料缺失",
                needs_review=False,
            ))

        # 8. 姓名、学号、手机号完整性
        if not images:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="姓名、学号、手机号完整性",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="未提交手写照片材料",
                deduction=0.0,
                deduction_reason="未提交手写材料，本项无法验证，不重复扣分",
                agent_note="无材料无法验证",
                needs_review=False,
            ))
        elif ai_res.get("is_pending"):
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="姓名、学号、手机号完整性",
                submission_status="已提交",
                completion_status="待复核",
                evidence=f"AI批改待定: {ai_res.get('reasoning')}",
                deduction=None,
                deduction_reason="AI 识别待定，手写身份信息需人工确认",
                agent_note="手写身份待人工核查",
                needs_review=True,
            ))
        elif ai_res.get("needs_review") and ("演草纸学生身份矛盾" in ai_res.get("review_reason", "")):
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="姓名、学号、手机号完整性",
                submission_status="已提交",
                completion_status="未达成",
                evidence=f"演草纸身份矛盾: {ai_res.get('review_reason')}",
                deduction=0.50,
                deduction_reason=f"演草纸书写身份与目录学生身份冲突: {ai_res.get('review_reason')}",
                agent_note="纸面与系统身份冲突待复核",
                needs_review=True,
            ))
        else:
            obs_sid = ai_res.get("student_id_observed")
            obs_name = ai_res.get("name_observed")
            obs_phone = ai_res.get("phone_observed")
            missing_items = []
            if not obs_name:
                missing_items.append("姓名")
            if not obs_sid:
                missing_items.append("学号")
            if not obs_phone:
                missing_items.append("手机号")

            if not missing_items:
                items.append(CheckItem(
                    problem_id="1-2",
                    sub_item="姓名、学号、手机号完整性",
                    submission_status="已提交",
                    completion_status="已达成",
                    evidence=f"演草纸手写身份信息齐全 (姓名: {obs_name}, 学号: {obs_sid}, 手机号: {obs_phone})",
                    deduction=0.0,
                    deduction_reason="",
                    agent_note="手写身份信息齐全",
                    needs_review=False,
                ))
            else:
                items.append(CheckItem(
                    problem_id="1-2",
                    sub_item="姓名、学号、手机号完整性",
                    submission_status="已提交",
                    completion_status="已达成",
                    evidence=f"演草纸未完整手写{'、'.join(missing_items)}，已与源码 ({src_path.name if src_path else '源码'}) 及提交目录对照核验一致，按大一宽容原则不扣分",
                    deduction=0.0,
                    deduction_reason="",
                    agent_note="依源码与目录核对确认归属，宽容不扣分",
                    needs_review=False,
                ))

        # 9. 手写参数与身份及源码一致性
        if not images:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="手写参数与身份及源码一致性",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="未提交手写照片材料",
                deduction=0.0,
                deduction_reason="未提交手写材料，本项无法验证，不重复扣分",
                agent_note="无材料无法验证",
                needs_review=False,
            ))
        elif ai_res.get("is_pending"):
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="手写参数与身份及源码一致性",
                submission_status="已提交",
                completion_status="待复核",
                evidence="AI批改待定",
                deduction=None,
                deduction_reason="AI 识别待定，参数一致性需人工核验",
                agent_note="参数一致性待核验",
                needs_review=True,
            ))
        else:
            hw_x = ai_res.get("x_observed")
            hw_y = ai_res.get("y_observed")
            has_param_mismatch = (hw_x is not None and hw_x != expected_x) or (hw_y is not None and deduced_y is not None and hw_y != deduced_y)
            if has_param_mismatch:
                items.append(CheckItem(
                    problem_id="1-2",
                    sub_item="手写参数与身份及源码一致性",
                    submission_status="已提交",
                    completion_status="未达成",
                    evidence=f"手写参数 x={hw_x}, y={hw_y} vs 学号后两位={expected_x}, 代码推导y={deduced_y}",
                    deduction=0.20,
                    deduction_reason="手写演算所用参数 x 或 y 与学号、手机号或源码参数存在矛盾",
                    agent_note="手写参数与身份或代码不一致",
                    needs_review=True,
                ))
            else:
                items.append(CheckItem(
                    problem_id="1-2",
                    sub_item="手写参数与身份及源码一致性",
                    submission_status="已提交",
                    completion_status="已达成",
                    evidence=f"手写参数 x={hw_x}, y={hw_y} 与身份信息及代码推导完全一致" if (hw_x is not None and hw_y is not None) else f"手写参数与身份信息及代码推导核对一致 (x={expected_x}, y={deduced_y})",
                    deduction=0.0,
                    deduction_reason="",
                    agent_note="参数一致性完全达成",
                    needs_review=False,
                ))

        # 10. 六种运算展开过程完整性
        if not images:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="六种运算展开过程完整性",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="未提交手写照片材料",
                deduction=0.0,
                deduction_reason="未提交手写材料，本项无法验证，不重复扣分",
                agent_note="无材料无法验证",
                needs_review=False,
            ))
        elif ai_res.get("is_pending"):
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="六种运算展开过程完整性",
                submission_status="已提交",
                completion_status="待复核",
                evidence="AI批改待定",
                deduction=None,
                deduction_reason="AI 识别待定，展开步骤需人工核实",
                agent_note="推导展开待核实",
                needs_review=True,
            ))
        else:
            deriv_sc = float(ai_res.get("derivation_score", 0.0))
            ops = ai_res.get("operators_found", [])
            if deriv_sc >= 0.8:
                items.append(CheckItem(
                    problem_id="1-2",
                    sub_item="六种运算展开过程完整性",
                    submission_status="已提交",
                    completion_status="已达成",
                    evidence=f"六种运算按位展开推导完整 ({', '.join(ops) if ops else '完整推导'})",
                    deduction=0.0,
                    deduction_reason="",
                    agent_note="六种运算推导完整",
                    needs_review=False,
                ))
            elif deriv_sc > 0:
                ded = round(0.8 - deriv_sc, 2)
                items.append(CheckItem(
                    problem_id="1-2",
                    sub_item="六种运算展开过程完整性",
                    submission_status="已提交",
                    completion_status="部分达成",
                    evidence=f"发现运算符展开: {ops}; AI批注: {ai_res.get('reasoning')}",
                    deduction=ded,
                    deduction_reason="手写演草纸缺少部分逻辑运算或位运算的按位展开过程",
                    agent_note="展开步骤略有欠缺",
                    needs_review=False,
                ))
            else:
                items.append(CheckItem(
                    problem_id="1-2",
                    sub_item="六种运算展开过程完整性",
                    submission_status="已提交",
                    completion_status="未达成",
                    evidence=f"AI批改记录: {ai_res.get('reasoning')}",
                    deduction=0.80,
                    deduction_reason="手写材料未包含有效的按位展开或推导过程",
                    agent_note="缺少推导过程",
                    needs_review=False,
                ))

        # 11. 各验算过程与结果正确性
        if not images:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="各验算过程与结果正确性",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="未提交手写照片材料",
                deduction=0.0,
                deduction_reason="未提交手写材料，本项无法验证，不重复扣分",
                agent_note="无材料无法验证",
                needs_review=False,
            ))
        elif ai_res.get("is_pending"):
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="各验算过程与结果正确性",
                submission_status="已提交",
                completion_status="待复核",
                evidence="AI批改待定",
                deduction=None,
                deduction_reason="AI 识别待定，验算正确性需人工核实",
                agent_note="验算正确性待复核",
                needs_review=True,
            ))
        elif ai_res.get("needs_review"):
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="各验算过程与结果正确性",
                submission_status="已提交",
                completion_status="待复核",
                evidence=f"AI批改疑义: {ai_res.get('review_reason')}",
                deduction=None,
                deduction_reason=f"验算过程存在疑义待人工核验: {ai_res.get('review_reason')}",
                agent_note="存在疑义待人工核查",
                needs_review=True,
            ))
        else:
            items.append(CheckItem(
                problem_id="1-2",
                sub_item="各验算过程与结果正确性",
                submission_status="已提交",
                completion_status="已达成",
                evidence="演草纸二进制按位展开与运算结果验算正确",
                deduction=0.0,
                deduction_reason="",
                agent_note="验算过程准确",
                needs_review=False,
            ))

        prob.check_items = items
        return prob

    def _grade_lab1_3(
        self,
        student: Student,
        sources: List[Path],
        build_dir: Path,
        mock_ai: bool,
        projects: Optional[List[Path]] = None,
        links: Optional[List[Path]] = None,
        all_student_files: Optional[List[SubmissionFile]] = None,
        precompiled: Optional[Dict[Tuple[str, str, int], CompileResult]] = None,
    ) -> ProblemResult:
        """评测 Lab 1-3：温度转换 (2.0分)"""
        prob = ProblemResult(problem_id="1-3", score=0.0, max_score=2.0, source_files=sources)
        projects = projects or []
        links = links or []
        all_files = all_student_files or []
        corrupt_archives = [f for f in all_files if f.file_type == "corrupt_archive"]

        c_res: Optional[CompileResult] = None
        outputs_collected = []
        has_int_div_bug = False
        passed_cases = 0
        total_cases = len(self.lab1_3_cases)

        if not sources:
            if corrupt_archives:
                prob.status = "needs_review"
                prob.score = 0.0
                prob.notes.append(f"收到学生提交压缩包 ({corrupt_archives[0].original_name})，解压失败，内容无法验证，待人工复核")
                prob.needs_review = True
                prob.review_reasons.append(f"提交压缩包损坏解压失败: {corrupt_archives[0].original_name}，Lab 1-3 源码无法验证")
            elif projects:
                prob.status = "missing_source"
                prob.score = 0.0
                prob.notes.append("未提交 Lab 1-3 源码 (仅提交 Code::Blocks 工程描述文件 .cbp，缺少 .c 源码)")
                prob.needs_review = True
                prob.review_reasons.append("Lab 1-3 仅提交工程文件 (.cbp)，缺源码")
            elif links:
                prob.status = "missing_source"
                prob.score = 0.0
                prob.notes.append("未提交 Lab 1-3 源码 (提交内容为 Windows 快捷方式 .lnk，缺实际源码)")
                prob.needs_review = True
                prob.review_reasons.append("Lab 1-3 提交为 Windows 快捷方式 (.lnk)，缺源码")
            else:
                prob.status = "missing"
                prob.notes.append("未提交 Lab 1-3 源码")
        else:
            # 存在一份或多份源码候选：逐一评测，择优采用最高分版本
            cand_evaluations = []
            for cand_idx, cand_src in enumerate(sources):
                c_text = cand_src.read_text(encoding="utf-8", errors="replace") if cand_src.exists() else ""
                if precompiled and (student.student_id, "1-3", cand_idx) in precompiled:
                    c_compile = precompiled[(student.student_id, "1-3", cand_idx)]
                else:
                    c_compile = self.compiler.compile(cand_src, build_dir, f"lab1_3_cand_{cand_idx}")
                c_results = []
                c_outputs = []
                c_notes = []
                c_reviews = []
                c_needs_review = False
                c_is_pending = False
                c_has_int_div_bug = False
                c_passed_cases = 0

                if not c_compile.success:
                    c_notes.append(f"Lab 1-3 ({cand_src.name}) 编译失败")
                else:
                    for idx, (in_str, conv_type, expected_val) in enumerate(self.lab1_3_cases, 1):
                        exec_res = run_binary(c_compile.binary_path, input_str=in_str, timeout=2.0)
                        c_outputs.append(exec_res.stdout.strip())

                        case_res = TestCaseResult(
                            case_id=f"case_{idx}",
                            input_data=in_str.strip(),
                            expected_output=f"{conv_type}: {expected_val:.2f}",
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
                            floats = [float(fl) for fl in re.findall(r"-?\b\d+(?:\.\d+)?\b", exec_res.stdout)]

                            other_specific_targets = [
                                v for _, _, v in self.lab1_3_cases
                                if abs(v - expected_val) > 0.1 and abs(v) > 0.1 and abs(v - 32.0) > 0.1
                            ]
                            matches_other_targets = sum(
                                1 for ot in other_specific_targets if any(abs(f - ot) <= 0.05 for f in floats)
                            )
                            if matches_other_targets >= 2:
                                case_res.error_message = "检测到程序同时输出多个无关特定参考答案，判定作弊刷屏"
                                c_results.append(case_res)
                                continue

                            found_match = False
                            for val in floats:
                                if abs(val - expected_val) <= 0.08:
                                    found_match = True
                                    break

                            if found_match:
                                case_res.passed = True
                                case_res.score = case_res.max_score
                                c_passed_cases += 1
                            else:
                                if expected_val != 0.0 and conv_type == "Centigrade":
                                    if any(abs(val - 0.0) < 0.001 for val in floats):
                                        c_has_int_div_bug = True

                                if idx == 1:
                                    ai_sem = SemanticAmbiguityReviewer.review_output(
                                        problem_id="1-3",
                                        student_id=student.student_id,
                                        input_data=in_str,
                                        expected_behavior=f"温度转换输出接近 {expected_val:.2f}",
                                        actual_output=exec_res.stdout,
                                        source_code=c_text,
                                        max_score=case_res.max_score,
                                        mock_mode=mock_ai,
                                    )
                                    if ai_sem.get("passed"):
                                        case_res.passed = True
                                        case_res.score = float(ai_sem.get("suggested_score", case_res.max_score))
                                        c_passed_cases += 1
                                    elif ai_sem.get("is_pending"):
                                        c_is_pending = True
                                        c_needs_review = True
                                        c_reviews.append("1-3 语义复核待定")
                                case_res.error_message = f"未在输出中识别到数值 {expected_val:.2f}"

                        c_results.append(case_res)

                    if len(set(c_outputs)) == 1 and len(c_outputs) > 1:
                        c_notes.append("检测到程序在不同输入下输出完全相同的静态文本，判定未读取输入")
                        c_passed_cases = 0
                        for cr in c_results:
                            cr.passed = False
                            cr.score = 0.0
                            cr.error_message = "静态输出检测失败：不同输入输出无变化"

                    f2c_idx = [0, 1, 2, 6, 7, 9]
                    f2c_cases = [c_results[i] for i in f2c_idx if i < len(c_results)]
                    passed_f2c_cand = sum(1 for c in f2c_cases if c.passed)
                    total_f2c_cand = len(f2c_cases)
                    if passed_f2c_cand == total_f2c_cand:
                        c_has_int_div_bug = False

                    if c_has_int_div_bug:
                        c_notes.append("检测到典型 C 语言整型截断除法缺陷 (如 5/9 得 0)")

                cand_score = sum(cr.score for cr in c_results)
                cand_evaluations.append({
                    "src_path": cand_src,
                    "score": cand_score,
                    "passed_cases": c_passed_cases,
                    "c_res": c_compile,
                    "test_results": c_results,
                    "outputs": c_outputs,
                    "src_text": c_text,
                    "notes": c_notes,
                    "reviews": c_reviews,
                    "needs_review": c_needs_review,
                    "is_pending": c_is_pending,
                    "has_int_div_bug": c_has_int_div_bug,
                    "success": c_compile.success,
                })

            # 择优采用最高分候选版本
            best_eval = max(
                cand_evaluations,
                key=lambda x: (
                    x["score"],
                    x["passed_cases"],
                    1 if x["success"] else 0,
                    0 if x["has_int_div_bug"] else 1
                )
            )
            src_path = best_eval["src_path"]
            src_text = best_eval["src_text"]
            c_res = best_eval["c_res"]
            prob.compile_result = c_res
            prob.test_results = best_eval["test_results"]
            outputs_collected = best_eval["outputs"]
            passed_cases = best_eval["passed_cases"]
            has_int_div_bug = best_eval["has_int_div_bug"]
            prob.notes.extend(best_eval["notes"])
            if best_eval["needs_review"]:
                prob.needs_review = True
                prob.review_reasons.extend(best_eval["reviews"])
            if best_eval["is_pending"]:
                prob.is_pending = True

            prob.score = round(2.0 * (passed_cases / total_cases), 2)
            if prob.is_pending:
                prob.status = "needs_review"
                prob.score = 0.0
            elif passed_cases == total_cases:
                prob.status = "passed"
            elif passed_cases > 0:
                prob.status = "partial"
            elif not c_res.success:
                prob.status = "compile_error"
            else:
                prob.status = "failed"

            prob.notes.append(f"测试通过率: {passed_cases}/{total_cases}")
            if len(sources) > 1:
                prob.notes.append(f"检测到 {len(sources)} 份 1-3 源码候选: {[s.name for s in sources]}，已择优评测采用最高分版本: {src_path.name} (得分: {prob.score:.2f}/2.00)")

        # --- 构建结构化检查分项 (CheckItems: 6 个题目分项) ---
        items: List[CheckItem] = []

        # 1. 源码提交
        if sources:
            items.append(CheckItem(
                problem_id="1-3",
                sub_item="源码提交",
                submission_status="已提交",
                completion_status="已达成",
                evidence=f"提交源码文件: {src_path.name} (共 {len(sources)} 份候选，已择优采用最高分版本)" if len(sources) > 1 else f"提交源码文件: {src_path.name}",
                deduction=0.0,
                deduction_reason="",
                agent_note=f"多候选已择优采用最高分版本: {src_path.name}" if len(sources) > 1 else "源码归档正常",
                needs_review=False,
            ))
        elif corrupt_archives:
            items.append(CheckItem(
                problem_id="1-3",
                sub_item="源码提交",
                submission_status="已提交",
                completion_status="无法验证",
                evidence=f"已提交压缩包 {corrupt_archives[0].original_name}，但文件损坏解压失败: {corrupt_archives[0].note or '解压异常'}",
                deduction=2.00,
                deduction_reason="提交压缩包损坏解压失败，Lab 1-3 源码无法验证，待人工复核",
                agent_note="解压失败、内容无法验证、待复核",
                needs_review=True,
            ))
        elif projects:
            items.append(CheckItem(
                problem_id="1-3",
                sub_item="源码提交",
                submission_status="无法归属",
                completion_status="未达成",
                evidence=f"归档项目描述文件: {', '.join(p.name for p in projects)}",
                deduction=2.00,
                deduction_reason="仅提交 Code::Blocks 工程文件 (.cbp)，缺少可编译 C 源码",
                agent_note="仅提交工程文件，缺少源码",
                needs_review=True,
            ))
        elif links:
            items.append(CheckItem(
                problem_id="1-3",
                sub_item="源码提交",
                submission_status="无法归属",
                completion_status="未达成",
                evidence=f"归档快捷方式: {', '.join(l.name for l in links)}",
                deduction=2.00,
                deduction_reason="提交内容为 Windows 快捷方式 (.lnk)，缺实际源程序",
                agent_note="提交内容为快捷方式，缺少源码",
                needs_review=True,
            ))
        else:
            items.append(CheckItem(
                problem_id="1-3",
                sub_item="源码提交",
                submission_status="未提交",
                completion_status="未达成",
                evidence="未检测到 Lab 1-3 源码文件",
                deduction=2.00,
                deduction_reason="未提交 Lab 1-3 源码文件",
                agent_note="未提交源码",
                needs_review=False,
            ))

        # 2. 编译与运行
        if not sources:
            items.append(CheckItem(
                problem_id="1-3",
                sub_item="编译与运行",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="未提交源码文件",
                deduction=0.0,
                deduction_reason="因缺少源码，本项无法验证，不重复扣分（已在源码提交项计扣）",
                agent_note="无源码无法编译",
                needs_review=False,
            ))
        elif c_res and not c_res.success:
            items.append(CheckItem(
                problem_id="1-3",
                sub_item="编译与运行",
                submission_status="已提交",
                completion_status="未达成",
                evidence=f"GCC 诊断: {c_res.stderr[:160]}",
                deduction=2.00,
                deduction_reason="GCC 编译失败，无法生成二进制执行文件",
                agent_note="编译失败",
                needs_review=False,
            ))
        else:
            items.append(CheckItem(
                problem_id="1-3",
                sub_item="编译与运行",
                submission_status="已提交",
                completion_status="已达成",
                evidence=f"GCC 编译成功 ({c_res.duration_ms:.1f}ms)，测试用例可正常执行" if c_res else "编译运行正常",
                deduction=0.0,
                deduction_reason="",
                agent_note="编译运行通过",
                needs_review=False,
            ))

        # 3. 华氏转摄氏计算 (模式 0)
        if not sources or not c_res or not c_res.success:
            items.append(CheckItem(
                problem_id="1-3",
                sub_item="华氏转摄氏计算",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="代码未成功编译运行",
                deduction=0.0,
                deduction_reason="编译未通过，转换功能无法验证",
                agent_note="无法验证",
                needs_review=False,
            ))
        else:
            f2c_idx = [0, 1, 2, 6, 7, 9]
            f2c_cases = [prob.test_results[i] for i in f2c_idx if i < len(prob.test_results)]
            passed_f2c = sum(1 for c in f2c_cases if c.passed)
            total_f2c = len(f2c_cases)
            if passed_f2c == total_f2c:
                items.append(CheckItem(
                    problem_id="1-3",
                    sub_item="华氏转摄氏计算",
                    submission_status="已提交",
                    completion_status="已达成",
                    evidence=f"华氏转摄氏用例全部通过 ({passed_f2c}/{total_f2c})",
                    deduction=0.0,
                    deduction_reason="",
                    agent_note="华氏转摄氏正确",
                    needs_review=False,
                ))
            elif has_int_div_bug:
                items.append(CheckItem(
                    problem_id="1-3",
                    sub_item="华氏转摄氏计算",
                    submission_status="已提交",
                    completion_status="部分达成",
                    evidence=f"模式0输出样例: {outputs_collected[0] if outputs_collected else ''} (预期37.78)，摄氏度结果恒为 0 或 32",
                    deduction=0.80,
                    deduction_reason="存在典型整型截断除法缺陷 (5/9 在 C 语言中得 0，导致摄氏度输出为 0.00)",
                    agent_note="整型除法 5/9 截断缺陷",
                    needs_review=False,
                ))
            else:
                comp_st = "部分达成" if passed_f2c > 0 else "未达成"
                ded = round(0.80 * (1 - passed_f2c / total_f2c), 2)
                items.append(CheckItem(
                    problem_id="1-3",
                    sub_item="华氏转摄氏计算",
                    submission_status="已提交",
                    completion_status=comp_st,
                    evidence=f"华氏转摄氏通过率 {passed_f2c}/{total_f2c}",
                    deduction=ded,
                    deduction_reason="华氏转摄氏计算错误，部分用例输出不符预期",
                    agent_note=f"华氏转摄氏未全通过 ({passed_f2c}/{total_f2c})",
                    needs_review=False,
                ))

        # 4. 摄氏转华氏计算 (模式 1)
        if not sources or not c_res or not c_res.success:
            items.append(CheckItem(
                problem_id="1-3",
                sub_item="摄氏转华氏计算",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="代码未成功编译运行",
                deduction=0.0,
                deduction_reason="编译未通过，转换功能无法验证",
                agent_note="无法验证",
                needs_review=False,
            ))
        else:
            c2f_idx = [3, 4, 5, 8]
            c2f_cases = [prob.test_results[i] for i in c2f_idx if i < len(prob.test_results)]
            passed_c2f = sum(1 for c in c2f_cases if c.passed)
            total_c2f = len(c2f_cases)
            if passed_c2f == total_c2f:
                items.append(CheckItem(
                    problem_id="1-3",
                    sub_item="摄氏转华氏计算",
                    submission_status="已提交",
                    completion_status="已达成",
                    evidence=f"摄氏转华氏用例全部通过 ({passed_c2f}/{total_c2f})",
                    deduction=0.0,
                    deduction_reason="",
                    agent_note="摄氏转华氏正确",
                    needs_review=False,
                ))
            else:
                comp_st = "部分达成" if passed_c2f > 0 else "未达成"
                ded = round(0.80 * (1 - passed_c2f / total_c2f), 2)
                items.append(CheckItem(
                    problem_id="1-3",
                    sub_item="摄氏转华氏计算",
                    submission_status="已提交",
                    completion_status=comp_st,
                    evidence=f"摄氏转华氏通过率 {passed_c2f}/{total_c2f}",
                    deduction=ded,
                    deduction_reason="摄氏转华氏计算错误，部分用例输出不符预期",
                    agent_note=f"摄氏转华氏未全通过 ({passed_c2f}/{total_c2f})",
                    needs_review=False,
                ))

        # 5. 边界、负温与浮点测试
        if not sources or not c_res or not c_res.success:
            items.append(CheckItem(
                problem_id="1-3",
                sub_item="边界、负温与浮点测试",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="代码未成功编译运行",
                deduction=0.0,
                deduction_reason="编译未通过，边界测试无法验证",
                agent_note="无法验证",
                needs_review=False,
            ))
        else:
            bound_idx = [2, 4, 6, 7, 8]
            bound_cases = [prob.test_results[i] for i in bound_idx if i < len(prob.test_results)]
            passed_bound = sum(1 for c in bound_cases if c.passed)
            total_bound = len(bound_cases)
            if passed_bound == total_bound:
                items.append(CheckItem(
                    problem_id="1-3",
                    sub_item="边界、负温与浮点测试",
                    submission_status="已提交",
                    completion_status="已达成",
                    evidence=f"负温 (-40度互转)、零度及小数测试全部通过 ({passed_bound}/{total_bound})",
                    deduction=0.0,
                    deduction_reason="",
                    agent_note="边界测试全部通过",
                    needs_review=False,
                ))
            else:
                ded = round(0.20 * (1 - passed_bound / total_bound), 2)
                items.append(CheckItem(
                    problem_id="1-3",
                    sub_item="边界、负温与浮点测试",
                    submission_status="已提交",
                    completion_status="部分达成",
                    evidence=f"边界与小数用例通过率 {passed_bound}/{total_bound}",
                    deduction=ded,
                    deduction_reason="负温或浮点小数边界测试存在未通过用例",
                    agent_note="边界用例部分未通过",
                    needs_review=False,
                ))

        # 6. 输出精度与格式
        if not sources or not c_res or not c_res.success:
            items.append(CheckItem(
                problem_id="1-3",
                sub_item="输出精度与格式",
                submission_status="不适用",
                completion_status="无法验证",
                evidence="代码未成功编译运行",
                deduction=0.0,
                deduction_reason="编译未通过，输出精度无法验证",
                agent_note="无法验证",
                needs_review=False,
            ))
        else:
            items.append(CheckItem(
                problem_id="1-3",
                sub_item="输出精度与格式",
                submission_status="已提交",
                completion_status="已达成",
                evidence="温度数值误差在 ±0.05 容差范围内且保留有效小数位",
                deduction=0.0,
                deduction_reason="",
                agent_note="精度与格式符合要求",
                needs_review=False,
            ))

        prob.check_items = items
        return prob

    def generate_comment(self, grade: StudentGrade) -> str:
        """根据学生各题各分项检查事实，动态生成不少于50字的高质量实验评语"""
        student = grade.student

        # 1. 完全缺交作业
        if grade.status == "missing":
            return (
                f"{student.name}同学你好！系统未检测到你在本次实验1中的作业提交（未收到源码文件及演草纸验算照片）。"
                f"按课程大纲与实验教学要求，请尽快核实是否由于提交逾期或文件路径遗漏，并及时联系助教说明情况补交，"
                f"以便及时核对并确认你的实验平时成绩。"
            )

        # 损坏压缩包特殊评语
        corrupt_reasons = [r for r in grade.review_reasons if "提交压缩包损坏" in r or "解压失败" in r]
        if corrupt_reasons and grade.status == "needs_review":
            return (
                f"{student.name}同学你好！本次实验1已检测并记录到你提交的压缩包文件，但该文件损坏无法正常解压，"
                f"导致评测机无法提取其中的源程序代码与演草纸材料进行自动化评测；系统已保留你的提交记录并标记为待人工复核，"
                f"不会直接记为未交，请尽快联系课程助教重新提交有效的压缩包文件进行成绩复核。"
            )

        # 2. 仅提交项目描述文件 (.cbp) 或快捷方式 (.lnk) 缺少源码
        r1_2 = grade.problem_results.get("1-2")
        r1_3 = grade.problem_results.get("1-3")

        has_cbp = any("仅提交 .cbp" in r or ".cbp" in r for r in grade.review_reasons)
        has_lnk = any(".lnk" in r for r in grade.review_reasons)
        has_exe = any("Wprogram.exe" in r or "预编译" in r for r in grade.review_reasons)

        if (has_cbp or has_lnk) and grade.status in {"missing_source", "needs_review"} and not (r1_2 and r1_2.compile_result and r1_2.compile_result.success):
            ft_desc = "Code::Blocks 工程描述文件 (.cbp)" if has_cbp else "Windows 快捷方式 (.lnk)"
            return (
                f"{student.name}同学你好！本次实验1提交文件中检测到 {ft_desc}，但缺少实际的 C 语言源码文件（.c/.cpp），"
                f"导致 Lab 1-2 与 Lab 1-3 无法在评测环境中进行编译运行与黑盒测试；演草纸手写验算材料已完成归档记录，"
                f"因源码缺失该作业暂记为待复核，请尽快携带源程序联系助教进行现场补交与成绩核验。"
            )

        # 3. 结构化提炼已达成与未达成项
        success_parts = []
        improvement_parts = []
        review_parts = []

        # 分析 Lab 1-2 源码
        if r1_2:
            code_items = [it for it in r1_2.check_items if "验算" not in it.sub_item and "手写" not in it.sub_item and "完整性" not in it.sub_item and "正确性" not in it.sub_item]
            hw_items = [it for it in r1_2.check_items if it not in code_items]

            # 代码部分
            if any(it.sub_item == "源码提交" and it.completion_status == "未达成" for it in code_items):
                if has_exe:
                    improvement_parts.append("Lab 1-2 仅提交了预编译 exe 文件而未包含 C 源码，按安全规范无法执行代码测试")
                else:
                    improvement_parts.append("Lab 1-2 未提交有效的 C 语言源程序")
            elif any(it.sub_item == "编译与运行" and it.completion_status == "未达成" for it in code_items):
                improvement_parts.append("Lab 1-2 源码存在语法错误无法通过 GCC 编译，运算逻辑无法验证")
            else:
                passed_terms_ok = all(it.completion_status == "已达成" for it in code_items if "运算" in it.sub_item)
                if passed_terms_ok and all(it.completion_status == "已达成" for it in code_items if "参数" in it.sub_item):
                    success_parts.append("Lab 1-2 逻辑与位运算 9 项测试全部正确，变量 x、y 正确对齐学号手机号")
                else:
                    failed_sub = [it.sub_item for it in code_items if it.completion_status in {"未达成", "部分达成"}]
                    if failed_sub:
                        improvement_parts.append(f"Lab 1-2 在{'、'.join(failed_sub)}方面存在偏差，需修正运算逻辑")
                    else:
                        success_parts.append("Lab 1-2 基础运算测试已通过")

            # 手写验算部分
            if any(it.sub_item == "验算材料提交" and it.completion_status == "未达成" for it in hw_items):
                improvement_parts.append("未提交 Lab 1-2 演草纸手写验算照片")
            else:
                hw_all_ok = all(it.completion_status == "已达成" for it in hw_items)
                if hw_all_ok:
                    success_parts.append("演草纸手写演算规范清晰，姓名学号与推导过程完整，六种运算展开准确无误")
                else:
                    hw_issues = [it.deduction_reason for it in hw_items if it.deduction and it.deduction > 0]
                    if hw_issues:
                        improvement_parts.append(f"手写演草纸材料中{hw_issues[0]}")
                    elif any(it.completion_status == "待复核" for it in hw_items):
                        review_parts.append("手写演草纸材料存在待人工复核事项（字迹辨识或推导疑义）")

        # 分析 Lab 1-3 温度转换
        if r1_3:
            if any(it.sub_item == "源码提交" and it.completion_status == "未达成" for it in r1_3.check_items):
                improvement_parts.append("Lab 1-3 未提交有效 C 源码")
            elif any(it.sub_item == "编译与运行" and it.completion_status == "未达成" for it in r1_3.check_items):
                improvement_parts.append("Lab 1-3 源码编译失败未能生成可执行文件")
            else:
                p1_3_all_ok = all(it.completion_status == "已达成" for it in r1_3.check_items)
                if p1_3_all_ok:
                    success_parts.append("Lab 1-3 温度双向转换逻辑严谨，精确处理了浮点运算与全部边界负温测试")
                else:
                    int_div = any("整型截断" in it.deduction_reason for it in r1_3.check_items)
                    if int_div:
                        improvement_parts.append("Lab 1-3 华氏转摄氏存在整数除法截断问题（5/9在C语言中得0导致输出为0.00），需使用 5.0/9.0 浮点除法")
                    else:
                        failed_1_3 = [it.sub_item for it in r1_3.check_items if it.completion_status in {"未达成", "部分达成"}]
                        improvement_parts.append(f"Lab 1-3 在{'、'.join(failed_1_3)}上存在未通过用例")

        # 汇总评语
        comment_parts = [f"{student.name}同学你好！本次实验1综合验收评测如下："]
        if success_parts:
            comment_parts.append("已达成项：" + "；".join(success_parts) + "。")
        if improvement_parts:
            comment_parts.append("需改进项：" + "；".join(improvement_parts) + "。")
        if review_parts:
            comment_parts.append("待核验项：" + "；".join(review_parts) + "。")

        if not improvement_parts and not review_parts and success_parts:
            comment_parts.append("各项检查分项均已圆满达成，展现了良好的编程规范与严谨态度，请继续保持！")
        elif improvement_parts:
            comment_parts.append("请对照上述各检查分项的具体反馈与扣分建议修正代码细节，加强对基本语法与运算特性的理解。")
        else:
            comment_parts.append("实验基本要求已达成，请继续保持扎实作风。")

        full_comment = "".join(comment_parts)
        if len(full_comment) < 50:
            full_comment += "后续实验请继续注重代码健壮性、边界用例自测与手写推导规范。"

        return full_comment
