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

    @staticmethod
    def _c_integer_literal(value: str) -> int:
        unsigned = value.lstrip("-")
        base = 16 if unsigned.lower().startswith("0x") else 8 if len(unsigned) > 1 and unsigned.startswith("0") else 10
        try:
            return int(value, base)
        except ValueError:
            return int(value, 10)

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

        # 预先调用视觉模型评测手写图片材料（若有图片），获取基础观察数据，后续由程序按不同候选进行参数匹配
        ai_res_base = HandwrittenReviewer.review_images(
            student_id=student.student_id,
            student_name=student.name,
            expected_x=expected_x,
            image_paths=images,
            mock_mode=mock_ai,
        )

        if images:
            ai_res_base = HandwrittenReviewer.normalize_review_result(
                ai_res_base, student.student_id, student.name, expected_x, expected_phone=student.phone)

        if not sources:
            if corrupt_archives:
                prob.notes.append(f"收到学生提交压缩包 ({corrupt_archives[0].original_name})，解压失败，内容无法验证，待人工复核")
                prob.needs_review = True
                prob.is_pending = True
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

            ai_res = ai_res_base
            prob.ai_review = ai_res
            handwritten_score = 0.0
            if ai_res.get("suggested_score") is not None:
                handwritten_score = round(float(ai_res.get("suggested_score")), 2)
            if ai_res.get("is_pending"):
                prob.is_pending = True
                prob.needs_review = True

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
                # 身份冲突只取消信息0.50分，推导保留。

            if hw_name and hw_name != str(student.name).strip():
                prob.needs_review = True
                prob.review_reasons.append(f"演草纸手写姓名 ({hw_name}) 与系统姓名 ({student.name}) 不符")
                # 归属疑义按身份项复核，不清零推导。

            hw_x = ai_res.get("x_observed")
            if hw_x is not None and hw_x != expected_x:
                prob.needs_review = True
                prob.review_reasons.append(f"参数矛盾: 演草纸手写 x={hw_x} 与学号后两位 {expected_x} 不符")

            prob.sub_scores["handwritten"] = handwritten_score
            prob.notes.append(f"演草纸批改: {ai_res.get('reasoning', '')}")

            if ai_res.get("needs_review"):
                prob.needs_review = True
                prob.review_reasons.append(f"演草纸复核: {ai_res.get('review_reason', '')}")

            prob.score = handwritten_score
        else:
            # 存在一份或多份源码候选：逐一评测，择优采用最高分版本
            cand_evaluations = []
            for cand_idx, cand_src in enumerate(sources):
                sf = next((f for f in all_files if f.path == cand_src), None)
                c_encoding_error = sf.encoding_error if sf else ""
                try:
                    c_text = cand_src.read_text(encoding="utf-8")
                except Exception as e:
                    c_text = ""
                    c_encoding_error = f"UTF-8 解码失败: {e}"

                clean_text = re.sub(r'/\*.*?\*/|//[^\n]*', '', c_text, flags=re.S)
                operator_text = re.sub(r'"(?:\\.|[^"\\])*"', '', clean_text)
                c_has_log = all(op in operator_text for op in ["!", "||", "&&"])
                c_has_bit = all(op in operator_text for op in ["~", "|", "&"])
                m_x = re.search(r'\bx\s*=\s*(-?(?:0[xX][0-9a-fA-F]+|\d+))', clean_text)
                m_y = re.search(r'\by\s*=\s*(-?(?:0[xX][0-9a-fA-F]+|\d+))', clean_text)
                c_code_x = self._c_integer_literal(m_x.group(1)) if m_x else None
                c_code_y = self._c_integer_literal(m_y.group(1)) if m_y else None

                if precompiled and (student.student_id, "1-2", cand_idx) in precompiled:
                    c_compile = precompiled[(student.student_id, "1-2", cand_idx)]
                else:
                    c_compile = self.compiler.compile(cand_src, build_dir, f"lab1_2_cand_{cand_idx}")
                c_notes = []
                c_reviews = []
                c_needs_review = False
                c_code_pending = False
                c_score = 0.0
                c_exec = None
                c_checks = []
                c_deduced_y = None
                c_v_list = [0] * 9

                if c_encoding_error:
                    c_notes.append(f"源码编码损坏: {c_encoding_error}")
                    c_needs_review = True
                    c_code_pending = True
                    c_reviews.append(f"源码存在不可恢复的编码损坏无法严格解码: {c_encoding_error}")
                elif sf and sf.encoding_converted:
                    c_notes.append(f"源码已自 {sf.source_encoding} 规范化为 UTF-8")

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
                                    c_score = 1.5
                                    c_notes.append("9项运算输出正确，但源码缺少运算符，疑似直接打印常数")
                                    c_needs_review = True
                                    c_reviews.append("1-2 源码运算符静态检查未通过")
                            else:
                                c_score = round(1.5 * (passed_terms / 9.0), 2)
                                c_notes.append(f"代码运算有 {len(failed_terms)} 项不符预期: {', '.join(failed_terms)} (通过 {passed_terms}/9)")
                        else:
                            c_notes.append(f"代码输出数字不足9个（实际{len(all_numbers)}个）；已输出项逐项计分，缺失项不通过")
                            partial_y = c_code_y
                            if partial_y is None and len(all_numbers) >= 6:
                                inferred = all_numbers[4] + all_numbers[5] - expected_x
                                partial_y = inferred if 0 <= inferred <= 99 else None
                            c_deduced_y = partial_y
                            y = partial_y if partial_y is not None else 0
                            expected = [int(not expected_x), int(bool(expected_x or y)), int(bool(expected_x and y)),
                                        (~expected_x) & 0xffff, expected_x | y, expected_x & y,
                                        ~expected_x, expected_x | y, expected_x & y]
                            names = ["!x", "x||y", "x&&y", "~x(unsigned)", "x|y(line2)", "x&y(line2)",
                                     "~x(signed)", "x|y(line3)", "x&y(line3)"]
                            c_checks = [(name, i < len(all_numbers) and all_numbers[i] == expected[i] and
                                         (partial_y is not None or i in (0, 3, 6)),
                                         all_numbers[i] if i < len(all_numbers) else None, expected[i])
                                        for i, name in enumerate(names)]
                            c_score = round(sum(ok for _, ok, _, _ in c_checks) * 1.5 / 9, 2)
                            if partial_y is None and all_numbers:
                                c_needs_review = True
                                c_code_pending = True
                                c_reviews.append("输出不足且源码y无法确定，依赖y的输出待复核")

                if images:
                    c_ai_res = HandwrittenReviewer.normalize_review_result(
                        ai_res_base,
                        student_id=student.student_id,
                        student_name=student.name,
                        expected_x=expected_x,
                        deduced_y=c_deduced_y,
                        expected_phone=student.phone,
                    )
                    c_hw_score = 0.0
                    if c_ai_res.get("suggested_score") is not None:
                        c_hw_score = round(float(c_ai_res.get("suggested_score")), 2)
                    c_hw_reviews = []
                    c_hw_needs_review = bool(c_ai_res.get("needs_review"))
                    c_hw_is_pending = bool(c_ai_res.get("is_pending"))

                    hw_sid = str(c_ai_res.get("student_id_observed") or "").strip()
                    hw_name = str(c_ai_res.get("name_observed") or "").strip()
                    non_identity_values = {"未书写", "未提供", "缺失", "none", "null", "无", "未写", "n/a", "未知", "未提及"}
                    if hw_sid.lower() in non_identity_values:
                        hw_sid = ""
                    if hw_name.lower() in non_identity_values:
                        hw_name = ""

                    if hw_sid and hw_sid != str(student.student_id).strip():
                        c_hw_needs_review = True
                        c_hw_reviews.append(f"演草纸手写学号 ({hw_sid}) 与系统学号 ({student.student_id}) 不符")
                        # 信息项已在规范化中处理，不重复取消推导分。

                    if hw_name and hw_name != str(student.name).strip():
                        c_hw_needs_review = True
                        c_hw_reviews.append(f"演草纸手写姓名 ({hw_name}) 与系统姓名 ({student.name}) 不符")
                        # 姓名冲突只影响信息项。

                    hw_x = c_ai_res.get("x_observed")
                    hw_y = c_ai_res.get("y_observed")
                    hw_phone = c_ai_res.get("phone_observed")
                    if hw_y is None and hw_phone:
                        ph_digits = re.findall(r"\d+", str(hw_phone))
                        if ph_digits and len(ph_digits[-1]) >= 2:
                            try:
                                hw_y = int(ph_digits[-1][-2:])
                            except ValueError:
                                pass

                    if hw_x is not None and hw_x != expected_x:
                        c_hw_needs_review = True
                        c_hw_reviews.append(f"参数矛盾: 演草纸手写 x={hw_x} 与学号后两位 {expected_x} 不符")

                    if hw_y is not None and c_deduced_y is not None and hw_y != c_deduced_y:
                        c_hw_needs_review = True
                        c_hw_reviews.append(f"参数矛盾: 代码 y={c_deduced_y} 与演草纸手写 y={hw_y} 不一致")
                        # 参数罚分已由 normalize_review_result 统一计算，仅扣一次。

                    if c_ai_res.get("needs_review") and c_ai_res.get("review_reason"):
                        c_hw_reviews.append(f"演草纸复核: {c_ai_res.get('review_reason')}")
                    hw_y_match = (hw_y is None or c_deduced_y == hw_y)
                else:
                    c_ai_res = ai_res_base
                    c_hw_score = 0.0
                    c_hw_reviews = []
                    c_hw_needs_review = False
                    c_hw_is_pending = False
                    hw_y_match = True

                c_total_score = round(c_score + c_hw_score, 2)
                cand_evaluations.append({
                    "cand_idx": cand_idx,
                    "src_path": cand_src,
                    "total_score": c_total_score,
                    "code_score": c_score,
                    "handwritten_score": c_hw_score,
                    "hw_y_match": 1 if hw_y_match else 0,
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
                    "reviews": c_reviews + c_hw_reviews,
                    "needs_review": c_needs_review or c_hw_needs_review,
                    "is_pending": c_hw_is_pending or c_code_pending,
                    "ai_res": c_ai_res,
                    "success": c_compile.success,
                })

            # 择优采用整题最终最高分版本 (满分 3.0，代码分 + 演算分综合择优，同分按稳定优先级排序)
            best_eval = max(
                cand_evaluations,
                key=lambda x: (
                    x["total_score"],
                    not x["is_pending"],
                    x["code_score"],
                    x["handwritten_score"],
                    1 if x["code_x_literal"] == expected_x else 0,
                    x["hw_y_match"],
                    1 if x["has_logical"] and x["has_bitwise"] else 0,
                    1 if x["success"] else 0,
                    -x["cand_idx"],
                )
            )
            src_path = best_eval["src_path"]
            code_score = best_eval["code_score"]
            handwritten_score = best_eval["handwritten_score"]
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
            ai_res = best_eval["ai_res"]

            prob.compile_result = c_res
            prob.sub_scores["code"] = code_score
            prob.sub_scores["handwritten"] = handwritten_score
            prob.ai_review = ai_res
            prob.notes.extend(best_eval["notes"])
            if best_eval["needs_review"]:
                prob.needs_review = True
                prob.review_reasons.extend(best_eval["reviews"])
            if best_eval["is_pending"]:
                prob.is_pending = True
            if images and ai_res.get("reasoning"):
                prob.notes.append(f"演草纸批改: {ai_res.get('reasoning')}")

            prob.score = best_eval["total_score"]

            prob.candidate_evaluations = [
                {
                    "index": c["cand_idx"],
                    "src_path": str(c["src_path"]),
                    "filename": c["src_path"].name,
                    "total_score": c["total_score"],
                    "code_score": c["code_score"],
                    "handwritten_score": c["handwritten_score"],
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
                "total_score": best_eval["total_score"],
                "code_score": best_eval["code_score"],
                "handwritten_score": best_eval["handwritten_score"],
                "reason": f"整题最高分 ({best_eval['total_score']:.2f}/3.00)",
            }

            if len(sources) > 1:
                prob.notes.append(f"检测到 {len(sources)} 份 1-2 源码候选: {[s.name for s in sources]}，已择优评测采用最高分版本: {src_path.name} (整题得分: {best_eval['total_score']:.2f}/3.00, 代码: {code_score:.2f}, 手写: {handwritten_score:.2f})")

        # 汇总分数与题目状态
        prob.score = round(code_score + handwritten_score, 2)
        if prob.is_pending:
            prob.status = "needs_review"
        elif prob.score == prob.max_score:
            prob.status = "passed"
        elif prob.score > 0:
            prob.status = "partial"
        else:
            prob.status = "failed"

        # 每个实际输出项均分；检查分类只汇总对应用例，不重复计扣。
        items: List[CheckItem] = []
        def add(name, submitted, completed, evidence, deduction=0.0, reason="", review=False):
            items.append(CheckItem("1-2", name, submitted, completed, evidence,
                                   deduction, reason, reason, review))

        special = bool(corrupt_archives or projects or links or has_exe)
        missing_reason = ("提交压缩包损坏解压失败，内容无法验证" if corrupt_archives else
                          "仅提交 .cbp 工程文件，缺少 C 源码" if projects else
                          "提交内容为 .lnk 快捷方式，缺实际源码" if links else
                          "仅提交预编译 exe，缺少 C 源码" if has_exe else "未提交 Lab 1-2 源码")
        add("源码提交", "已提交" if sources or corrupt_archives else "无法归属" if special else "未提交",
            "已达成" if sources else "无法验证" if corrupt_archives else "未达成",
            f"采用源码: {src_path}; 候选数={len(sources)}" if sources else missing_reason,
            0.0 if sources else None if corrupt_archives else 1.5,
            "" if sources else missing_reason, special and not sources)
        if corrupt_archives and not sources:
            items[-1].agent_note = "解压失败、内容无法验证、待复核"
        executable = bool(c_res and c_res.success and exec_res and not exec_res.timed_out and exec_res.exit_code == 0)
        if not sources:
            add("编译与运行", "不适用", "无法验证", "缺少源码，已在源码提交项记录")
        elif not executable:
            evidence = c_res.stderr[:200] if c_res and not c_res.success else "程序运行超时或异常退出"
            add("编译与运行", "已提交", "未达成", evidence, 1.5, "源码无法正常编译运行，九个输出项均无法通过")
        else:
            add("编译与运行", "已提交", "已达成", f"GCC编译成功，运行退出码0；九个输出项各占1.50/9")
        x_mismatch = code_x_literal is not None and code_x_literal != expected_x
        add("参数学号与手机号对齐", "已提交" if sources else "不适用",
            "无法验证" if not executable else "部分达成" if x_mismatch else "已达成",
            f"源码字面 x={code_x_literal}; 学号末两位={expected_x}; 已验证代码y={deduced_y}。参数影响按输出用例计分，不额外重复扣代码分。",
            review=bool(executable and x_mismatch))
        groups = [("逻辑运算(!, ||, &&)", [0, 1, 2]),
                  ("位运算(~, |, &)", [3, 4, 5, 7, 8]),
                  ("有符号与无符号输出格式", [6])]
        # 先按精确均分累计，再分配显示到分的舍入差，确保汇总闭合。
        accumulated = 0
        previous_deduction = 0.0
        for name, indices in groups:
            if not executable:
                add(name, "不适用", "无法验证", "编译或运行未通过，不重复扣分")
                continue
            unknown = bool(sources and best_eval.get("is_pending") and any("源码存在不可恢复" in r or "输出不足且源码y无法确定" in r for r in best_eval["reviews"]))
            failed = [i for i in indices if not checks or not checks[i][1]]
            accumulated += len(failed)
            cumulative = round(accumulated * 1.5 / 9, 2)
            deduction = round(cumulative - previous_deduction, 2)
            previous_deduction = cumulative
            evidence = "; ".join(f"{checks[i][0]}: 实际{checks[i][2]}, 预期{checks[i][3]}" if checks else f"输出项{i+1}: 缺少有效结果" for i in indices)
            add(name, "已提交", "已达成" if not failed else "未达成" if len(failed) == len(indices) else "部分达成",
                evidence, None if unknown else deduction, "输出事实待核验" if unknown else "输出项未通过，每项扣1.50/9（最终按分舍入）" if failed else "", review=unknown or (name.startswith("逻辑运算") and not has_logical) or (name.startswith("位运算") and not has_bitwise))
        prob.test_results = [TestCaseResult(
            case_id=f"term_{i+1}", input_data=f"x={expected_x},y={deduced_y}",
            expected_output=str(checks[i][3]) if checks else "指导书第%d项运算结果" % (i+1),
            actual_output=str(checks[i][2]) if checks else "", passed=bool(checks and checks[i][1]),
            score=1.5/9 if checks and checks[i][1] else 0.0, max_score=1.5/9,
        ) for i in range(9)] if executable else []

        add("验算材料提交", "已提交" if images or corrupt_archives else "未提交",
            "已达成" if images else "待复核" if corrupt_archives else "未达成",
            ", ".join(str(p) for p in images) if images else "验算材料无法取得" if corrupt_archives else "未提交手写验算照片",
            0.0 if images else None if corrupt_archives else 1.5,
            "" if images else "材料无法验证" if corrupt_archives else "未提交手写验算照片", bool(corrupt_archives and not images))
        hw_pending = bool(ai_res.get("is_pending"))
        identity_conflict = bool(ai_res.get("identity_conflict"))
        no_valid = bool(ai_res.get("no_valid_derivation"))
        mismatches = ai_res.get("parameter_mismatches", [])
        base_derivation = float(ai_res.get("derivation_base_score", 0.8))
        error_deduction = round(0.8 - base_derivation, 2)
        parameter_deduction = round(base_derivation - float(ai_res.get("derivation_score", base_derivation)), 2)
        for name, deduction, evidence, needs_review in [
            ("姓名、学号、手机号完整性", 0.5 if identity_conflict else 0.0,
             ai_res.get("review_reason", "") if identity_conflict else "按已确认政策：信息漏写不扣分；保留纸面观察事实，不将免扣写成信息齐全", identity_conflict),
            ("手写参数与身份及源码一致性", parameter_deduction,
             f"明确不符参数={mismatches}; x观察={ai_res.get('x_observed')}; y观察={ai_res.get('y_observed')}; 已验证代码y={deduced_y}。每个参数额外扣0.20，只在推导预算内扣一次。", bool(mismatches)),
            ("六种运算展开过程完整性", error_deduction,
             f"明确错误运算={ai_res.get('clear_error_operators', [])}; 证据={ai_res.get('error_evidence', [])}; 无有效推导={no_valid}。简写、少竖式和小笔误免扣，仅有明确错误时使用AI连续推导分d，扣0.80−d。", False),
            ("各验算过程与结果正确性", 0.0, ai_res.get("review_reason") or "按手写观察核对，明确运算错误已在推导项计扣", False),
        ]:
            if not images:
                add(name, "不适用", "无法验证", "无手写材料，不重复扣分")
            elif hw_pending:
                add(name, "已提交", "待复核", ai_res.get("reasoning", "手写材料待核验"), None, "手写事实待复核", True)
            else:
                add(name, "已提交", "待复核" if needs_review else "未达成" if deduction > 0 else "已达成",
                    evidence, deduction, evidence if deduction > 0 else "", needs_review)
        prob.check_items = items
        return prob

    @staticmethod
    def _temperature_result(stdout: str, conversion: str) -> Tuple[Optional[float], str]:
        """优先取目标温标/结果标签的数值，否则取最后一个数，避免输入回显得分。"""
        number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
        target = r"摄氏(?:度|温度)?|celsius|centigrade|\bC\b" if conversion == "Centigrade" else r"华氏(?:度|温度)?|fahrenheit|\bF\b"
        for label in [target, r"result|结果|转换(?:后)?(?:的)?(?:温度)?"]:
            matches = list(re.finditer(rf"(?:{label})\s*(?:is|为|是|=|:|：)\s*({number})", stdout, re.I))
            matches = [m for m in matches if not re.match(r"\s*[*/]", stdout[m.end():])]
            if matches:
                token = matches[-1].group(1)
                return float(token), token
        matches = list(re.finditer(number, stdout))
        if not matches:
            return None, ""
        token = matches[-1].group(0)
        return float(token), token

    def _grade_lab1_3(
        self, student: Student, sources: List[Path], build_dir: Path,
        mock_ai: bool = False, projects: Optional[List[Path]] = None,
        links: Optional[List[Path]] = None,
        all_student_files: Optional[List[SubmissionFile]] = None,
        precompiled: Optional[Dict[Tuple[str, str, int], CompileResult]] = None,
    ) -> ProblemResult:
        """十例均分2分；数值容差0.08；两位小数格式整题额外扣0.20一次。"""
        prob = ProblemResult(problem_id="1-3", score=0.0, max_score=2.0, source_files=sources)
        all_files = all_student_files or []
        corrupt = [f for f in all_files if f.file_type == "corrupt_archive"]
        projects, links = projects or [], links or []
        weight = 2.0 / len(self.lab1_3_cases)
        candidates = []
        for index, source in enumerate(sources):
            sf = next((f for f in all_files if f.path == source), None)
            encoding_error = sf.encoding_error if sf else ""
            try:
                source_text = source.read_text(encoding="utf-8")
            except (UnicodeError, OSError) as e:
                source_text = ""
                encoding_error = str(e)
            key = (student.student_id, "1-3", index)
            compiled = precompiled[key] if precompiled and key in precompiled else self.compiler.compile(source, build_dir, f"lab1_3_cand_{index}")
            cases, tokens, values, outputs = [], [], [], []
            reviews = [f"源码编码损坏，待复核: {encoding_error}"] if encoding_error else []
            notes = []
            if sf and sf.encoding_converted:
                notes.append(f"源码已自 {sf.source_encoding} 规范化为UTF-8")
            if compiled.success:
                for i, (input_text, conversion, expected) in enumerate(self.lab1_3_cases):
                    execution = run_binary(compiled.binary_path, input_str=input_text, timeout=2.0)
                    outputs.append(execution.stdout.strip())
                    result = TestCaseResult(f"case_{i+1}", input_text.strip(), f"{conversion}: {expected:.2f}", execution.stdout.strip(), False, 0.0, weight,
                                            timed_out=execution.timed_out, exit_code=execution.exit_code)
                    actual, token = None, ""
                    if execution.timed_out:
                        result.error_message = "运行超时"
                    elif execution.exit_code != 0:
                        result.error_message = f"运行异常(exit {execution.exit_code})"
                    else:
                        actual, token = self._temperature_result(execution.stdout, conversion)
                        result.passed = actual is not None and abs(actual - expected) <= 0.08 + 1e-9
                        if not result.passed and i == 0:
                            semantic = SemanticAmbiguityReviewer.review_output(
                                problem_id="1-3", student_id=student.student_id, input_data=input_text,
                                expected_behavior=f"按C/C++实际类型和运算规则核验本次运行；最终{conversion}结果应接近{expected:.2f}，容差0.08。菜单和输入回显不作为结果。两位小数格式由程序单独判断，数值错误不得因公式思路正确而通过。",
                                actual_output=execution.stdout, source_code=source_text,
                                max_score=weight, mock_mode=mock_ai)
                            if semantic.get("is_pending") or (semantic.get("needs_review") and not semantic.get("passed")):
                                result.needs_review = True
                                result.review_reason = semantic.get("review_reason") or "语义复核待定"
                                reviews.append("1-3 语义复核待定: " + result.review_reason)
                            elif semantic.get("passed"):
                                # 用例只分通过/不通过；不使用AI连续分值参与候选择优。
                                result.passed = True
                        if not result.passed:
                            result.error_message = f"最终结果{actual}与预期{expected:.2f}不符（容差0.08）"
                    result.score = weight if result.passed else 0.0
                    cases.append(result)
                    tokens.append(token)
                    values.append(actual)
                if len(set(outputs)) == 1 and len(outputs) > 1:
                    notes.append("不同输入下输出完全相同；单一结果仍逐例比较，不另扣整题")
                    # 保留对倾倒整组答案的拦截：多组未标注结果不能选其中一个刷分。
                    numbers = re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", outputs[0])
                    if len(numbers) > 1 and not re.search(r"result|结果|celsius|centigrade|fahrenheit|摄氏|华氏", outputs[0], re.I):
                        notes.append("多输入固定输出多组未标注答案，无法认定唯一有效结果")
                        for case in cases:
                            case.passed, case.score = False, 0.0
                            case.error_message = "固定倾倒多组答案，未提供当前输入的唯一结果"
                clean_source = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"', '', source_text, flags=re.S)
                nonzero_f = [i for i, (_, conv, exp) in enumerate(self.lab1_3_cases) if conv == "Centigrade" and exp != 0]
                if (re.search(r'\(\s*5\s*/\s*9\s*\)', clean_source)
                        and all(values[i] is not None and abs(values[i]) < 1e-9 and not cases[i].passed for i in nonzero_f)):
                    notes.append("源码括号内整数表达式(5/9)先截断为0，且所有非零预期华氏转换实测结果为0；此诊断不额外扣分")
            format_failures = [i for i, case in enumerate(cases) if case.passed and tokens[i] and not re.fullmatch(r"[-+]?(?:\d+)?\.\d{2}", tokens[i])]
            # 无法解析但语义通过时，格式证据仍须复核。
            format_unknown = [i for i, case in enumerate(cases) if case.passed and not tokens[i]]
            if format_unknown:
                reviews.append("输出数值由语义复核通过，但缺少可核验的小数格式证据")
            numeric_score = sum(case.score for case in cases)
            format_deduction = min(numeric_score, 0.2) if format_failures else 0.0
            pending = bool(encoding_error or format_unknown or any(case.needs_review for case in cases))
            candidates.append(dict(index=index, source=source, compiled=compiled, cases=cases,
                tokens=tokens, numeric_score=numeric_score, format_deduction=format_deduction,
                format_failures=format_failures, score=round(numeric_score-format_deduction, 2),
                reviews=reviews, notes=notes, pending=pending, encoding_error=encoding_error))
        chosen = None
        if candidates:
            chosen = max(candidates, key=lambda c: (c["score"], not c["pending"], c["compiled"].success, -c["index"]))
            prob.compile_result = chosen["compiled"]
            prob.test_results = chosen["cases"]
            prob.score = chosen["score"]
            prob.is_pending = chosen["pending"]
            prob.needs_review = bool(chosen["reviews"])
            prob.review_reasons = chosen["reviews"]
            prob.notes = chosen["notes"] + [f"测试通过率: {sum(c.passed for c in prob.test_results)}/{len(self.lab1_3_cases)}；每例{weight:.2f}分；格式整题扣{chosen['format_deduction']:.2f}"]
            for candidate in candidates:
                prob.candidate_evaluations.append(dict(index=candidate["index"], src_path=str(candidate["source"]), filename=candidate["source"].name,
                    score=candidate["score"], numeric_score=round(candidate["numeric_score"], 2), format_deduction=candidate["format_deduction"],
                    passed_cases=sum(case.passed for case in candidate["cases"]), compile_success=candidate["compiled"].success,
                    needs_review=candidate["pending"], notes=candidate["notes"], reviews=candidate["reviews"]))
            prob.chosen_candidate = {**prob.candidate_evaluations[chosen["index"]], "reason": "按用例均分与整题格式扣分完整评定后最高分"}
            if len(sources) > 1:
                prob.notes.append(f"检测到{len(sources)}份源码候选，采用最高分版本: {chosen['source'].name}")
            prob.status = "needs_review" if prob.is_pending else "compile_error" if not prob.compile_result.success else "passed" if prob.score == 2 else "partial" if prob.score > 0 else "failed"
        else:
            reason = "提交压缩包损坏解压失败，内容无法验证" if corrupt else "仅提交 .cbp 工程文件，缺源码" if projects else "仅提交 .lnk 快捷方式，缺源码" if links else "未提交Lab 1-3源码"
            prob.notes.append(reason)
            prob.needs_review = bool(corrupt or projects or links)
            prob.is_pending = bool(corrupt)
            prob.review_reasons = [reason] if prob.needs_review else []
            prob.status = "needs_review" if prob.is_pending else "missing_source" if prob.needs_review else "missing"

        def add(name, submitted, completed, evidence, deduction=0.0, reason="", review=False):
            prob.check_items.append(CheckItem("1-3", name, submitted, completed, evidence, deduction, reason, reason, review))
        add("源码提交", "已提交" if sources or corrupt else "无法归属" if projects or links else "未提交",
            "已达成" if sources else "待复核" if corrupt else "未达成",
            f"源码: {chosen['source']}；候选数={len(sources)}" if chosen else prob.notes[0],
            0.0 if sources else None if corrupt else 2.0, "" if sources else prob.notes[0], bool(corrupt or projects or links) and not sources)
        compiled_ok = bool(prob.compile_result and prob.compile_result.success)
        if not sources:
            add("编译与运行", "不适用", "无法验证", "缺源码，不重复扣分")
        elif not compiled_ok:
            add("编译与运行", "已提交", "待复核" if chosen["encoding_error"] else "未达成", prob.compile_result.stderr[:200],
                None if chosen["encoding_error"] else 2.0, "编码异常待核验" if chosen["encoding_error"] else "编译失败，无法执行全部用例", bool(chosen["encoding_error"]))
        else:
            abnormal = [c.case_id for c in prob.test_results if c.timed_out or c.exit_code != 0]
            add("编译与运行", "已提交", "部分达成" if abnormal else "已达成",
                f"GCC编译成功；运行异常用例={abnormal}；异常用例按所属方向计扣")
        for name, conversion in [("华氏转摄氏计算", "Centigrade"), ("摄氏转华氏计算", "Fahrenheit")]:
            if not compiled_ok:
                add(name, "不适用", "无法验证", "未成功编译，不重复扣分")
                continue
            cases = [case for case, (_, conv, _) in zip(prob.test_results, self.lab1_3_cases) if conv == conversion]
            failed = [case for case in cases if not case.passed and not case.needs_review]
            pending_cases = [case for case in cases if case.needs_review]
            evidence = "; ".join(f"{c.case_id} 输入[{c.input_data}]：{'待复核' if c.needs_review else '通过' if c.passed else '失败'}，输出[{c.actual_output}]，预期[{c.expected_output}]" for c in cases)
            add(name, "已提交", "待复核" if pending_cases else "已达成" if not failed else "未达成" if len(failed) == len(cases) else "部分达成",
                evidence, None if pending_cases else round(len(failed)*weight, 2),
                "用例待复核" if pending_cases else f"{len(failed)}个用例未通过，每例扣{weight:.2f}" if failed else "", bool(pending_cases))
        boundary = [case for case, (inp, _, _) in zip(prob.test_results, self.lab1_3_cases) if float(inp.split()[1]) <= 0 or '.' in inp.split()[1]]
        add("边界、负温与浮点测试", "已提交" if compiled_ok else "不适用",
            "待复核" if any(c.needs_review for c in boundary) else "已达成" if compiled_ok and all(c.passed for c in boundary) else "部分达成" if compiled_ok else "无法验证",
            "负温、零度和浮点用例按对应方向每例计分，本项只记录覆盖情况，不重复扣分",
            review=any(c.needs_review for c in boundary))
        if not compiled_ok:
            add("输出精度与格式", "不适用", "无法验证", "未成功编译，无法验证格式")
        elif any(case.passed and not token for case, token in zip(prob.test_results, chosen["tokens"])):
            add("输出精度与格式", "已提交", "待复核", "语义通过但未识别到明确结果数值格式", None, "格式证据待核验", True)
        else:
            bad = chosen["format_failures"]
            add("输出精度与格式", "已提交", "部分达成" if bad else "已达成" if any(c.passed for c in prob.test_results) else "无法验证",
                f"容差0.08；数值正确但非两位小数的用例={[i+1 for i in bad]}；整题只扣一次0.20，最低0分",
                round(chosen["format_deduction"], 2), "结果小数位数不等于2，整题额外扣0.20一次" if bad else "")
        return prob

    def generate_comment(self, grade: StudentGrade) -> str:
        """依据检查事实生成整次实验评语，保留具体复核事项。"""
        if grade.status == "missing":
            return (f"{grade.student.name}同学你好！本次实验1未检测到可归属的源码和验算材料提交，请核对提交文件与提交记录，并联系助教确认材料是否已经收到，以便完成实验成绩核验。")
        if any("压缩包损坏" in reason for reason in grade.review_reasons):
            return (f"{grade.student.name}同学你好！已收到你的实验1提交压缩包，但文件损坏无法正常解压，源码及验算材料内容目前无法验证，成绩保留待人工复核。请核对压缩包能否正常打开并联系助教补充可读取的原始材料，本次情况不按未交处理。")
        parts = [f"{grade.student.name}同学你好！本次实验1验收如下："]
        for pid in ["1-2", "1-3"]:
            prob = grade.problem_results.get(pid)
            if not prob:
                continue
            if prob.compile_result and prob.compile_result.success:
                parts.append(f"Lab {pid}源码已提交并通过编译，实际运算测试通过{sum(c.passed for c in prob.test_results)}/{len(prob.test_results)}项。")
            elif prob.compile_result:
                parts.append(f"Lab {pid}源码已提交，但编译失败，计算结果尚无法验证。")
            else:
                parts.append(f"Lab {pid}未取得可编译源码，请依据对应提交项核对。")
            for item in prob.check_items:
                if item.deduction and item.deduction > 0 and item.sub_item not in {"源码提交", "编译与运行"}:
                    parts.append(f"{item.sub_item}：{item.deduction_reason}。")
            if pid == "1-2" and prob.ai_review and not prob.ai_review.get("is_pending") and any(i.sub_item == "验算材料提交" and i.submission_status == "已提交" for i in prob.check_items):
                parts.append(f"手写验算按确认政策评为{prob.sub_scores.get('handwritten', 0.0):.2f}/1.50分，个人信息漏写和过程简写不作酌情扣分。")
            if prob.needs_review:
                parts.append("待复核：" + "；".join(dict.fromkeys(prob.review_reasons)) + "。")
        parts.append("请对照各项输入、输出与验算证据核对反馈，已确认错误按对应检查项计分。")
        return "".join(parts)
