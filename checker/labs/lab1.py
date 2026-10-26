"""
checker.labs.lab1
《程序设计思维与实践》Lab 1 评测实现
包含：
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
    CompileResult,
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
        # 包含官方样例、边界值及动态金丝雀用例（防范硬编码全部样例答案的作弊行为）
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

    def grade_student(
        self,
        student: Student,
        files: List[SubmissionFile],
        build_dir: Path,
        mock_ai: bool = False,
    ) -> StudentGrade:
        """评测单个学生的 Lab 1"""
        student_build_dir = build_dir / student.student_id
        student_build_dir.mkdir(parents=True, exist_ok=True)

        grade = StudentGrade(student=student, max_score=5.0)

        # 整理学生提交的文件
        p1_2_sources = [f.path for f in files if f.matched_problem == "1-2" and f.file_type in {"c_source", "cpp_source"}]
        p1_2_images = [f.path for f in files if f.matched_problem == "1-2" and f.file_type == "image"]
        # 若图片未命中具体题号，也归入 1-2 验算备选
        if not p1_2_images:
            p1_2_images = [f.path for f in files if f.file_type == "image"]

        p1_3_sources = [f.path for f in files if f.matched_problem == "1-3" and f.file_type in {"c_source", "cpp_source"}]

        # 1. 评测 Lab 1-2
        res1_2 = self._grade_lab1_2(student, p1_2_sources, p1_2_images, student_build_dir, mock_ai)
        grade.problem_results["1-2"] = res1_2

        # 2. 评测 Lab 1-3
        res1_3 = self._grade_lab1_3(student, p1_3_sources, student_build_dir, mock_ai)
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
        elif res1_2.status == "compile_error" and res1_3.status == "compile_error":
            grade.status = "compile_error"
        elif grade.needs_review:
            grade.status = "needs_review"
        else:
            grade.status = "graded"

        # 生成评语
        grade.comment = self.generate_comment(grade)
        return grade

    def _grade_lab1_2(
        self,
        student: Student,
        sources: List[Path],
        images: List[Path],
        build_dir: Path,
        mock_ai: bool,
    ) -> ProblemResult:
        """评测 Lab 1-2：代码运算 (1.5分) + 手写验算 (1.5分)"""
        prob = ProblemResult(problem_id="1-2", score=0.0, max_score=3.0, source_files=sources)

        if not sources and not images:
            prob.status = "missing"
            prob.notes.append("未提交 Lab 1-2 源码与验算图片")
            return prob

        # 学号末两位预期值 x
        try:
            expected_x = int(student.student_id[-2:])
        except Exception:
            expected_x = 0

        # --- A. 代码部分评测 (1.5分) ---
        code_score = 0.0
        deduced_y = None
        if not sources:
            prob.notes.append("未找到 Lab 1-2 代码文件")
            prob.sub_scores["code"] = 0.0
        else:
            src_path = sources[0]
            if len(sources) > 1:
                prob.notes.append(f"发现多份 1-2 源码候选，默认评测首个: {src_path.name}")
                prob.needs_review = True
                prob.review_reasons.append(f"同题多候选: {[s.name for s in sources]}")

            src_text = src_path.read_text(encoding="utf-8", errors="ignore")
            # 源码静态检查：必须含有逻辑运算与位运算符
            has_logical = all(op in src_text for op in ["!", "||", "&&"])
            has_bitwise = all(op in src_text for op in ["~", "|", "&"])

            # 静态提取代码中直接赋值的 x 和 y
            m_x = re.search(r'\bx\s*=\s*(-?\d+)', src_text)
            m_y = re.search(r'\by\s*=\s*(-?\d+)', src_text)
            code_x_literal = int(m_x.group(1)) if m_x else None
            code_y_literal = int(m_y.group(1)) if m_y else None

            if code_x_literal is not None and code_x_literal != expected_x:
                prob.notes.append(f"源码中 x 赋值 ({code_x_literal}) 与学号后两位 ({expected_x}) 不一致")
                prob.needs_review = True
                prob.review_reasons.append(f"代码 x 赋值为 {code_x_literal}，而学号末两位为 {expected_x}")

            c_res = self.compiler.compile(src_path, build_dir, "lab1_2")
            prob.compile_result = c_res

            if not c_res.success:
                prob.notes.append(f"Lab 1-2 编译失败: {c_res.stderr[:200]}")
                prob.status = "compile_error"
                prob.sub_scores["code"] = 0.0
            else:
                exec_res = run_binary(c_res.binary_path, input_str="", timeout=2.0)
                if exec_res.timed_out:
                    prob.notes.append("Lab 1-2 运行超时")
                    prob.sub_scores["code"] = 0.0
                elif exec_res.exit_code != 0:
                    prob.notes.append(f"Lab 1-2 运行时崩溃 (exit {exec_res.exit_code})")
                    prob.sub_scores["code"] = 0.0
                else:
                    # 解析程序输出的全部整数项
                    numbers = [int(n) for n in re.findall(r"-?\b\d+\b", exec_res.stdout)]
                    if len(numbers) >= 9:
                        v1, v2, v3 = numbers[0], numbers[1], numbers[2]
                        v4, v5, v6 = numbers[3], numbers[4], numbers[5]
                        v7, v8, v9 = numbers[6], numbers[7], numbers[8]

                        # 根据位运算恒等式 x + y = (x | y) + (x & y) 推导代码中的实际参数 y
                        deduced_y = v5 + v6 - expected_x
                        if code_y_literal is not None and code_y_literal != deduced_y:
                            prob.notes.append(f"代码字面 y={code_y_literal} 与运算输出推导 y={deduced_y} 存在偏差")

                        # 理论预期 9 项全量计算
                        exp_v1 = 0 if expected_x != 0 else 1
                        exp_v2 = 1 if (expected_x != 0 or deduced_y != 0) else 0
                        exp_v3 = 1 if (expected_x != 0 and deduced_y != 0) else 0
                        exp_v4 = (65536 + (~expected_x)) & 0xFFFF
                        exp_v5 = (expected_x | deduced_y)
                        exp_v6 = (expected_x & deduced_y)
                        exp_v7 = (~expected_x)
                        exp_v8 = (expected_x | deduced_y)
                        exp_v9 = (expected_x & deduced_y)

                        # 逐项核验九个结果，杜绝漏查逻辑运算或局部假通过
                        checks = [
                            ("!x", v1 == exp_v1, v1, exp_v1),
                            ("x||y", v2 == exp_v2, v2, exp_v2),
                            ("x&&y", v3 == exp_v3, v3, exp_v3),
                            ("~x(unsigned)", v4 == exp_v4, v4, exp_v4),
                            ("x|y(line2)", v5 == exp_v5, v5, exp_v5),
                            ("x&y(line2)", v6 == exp_v6, v6, exp_v6),
                            ("~x(signed)", v7 == exp_v7, v7, exp_v7),
                            ("x|y(line3)", v8 == exp_v8, v8, exp_v8),
                            ("x&y(line3)", v9 == exp_v9, v9, exp_v9),
                        ]

                        passed_terms = sum(1 for _, ok, _, _ in checks if ok)
                        failed_terms = [name for name, ok, _, _ in checks if not ok]

                        if passed_terms == 9:
                            if has_logical and has_bitwise:
                                code_score = 1.5
                                prob.notes.append(f"代码逻辑与位运算 9 项校验完全正确 (x={expected_x}, 推导y={deduced_y})")
                            else:
                                code_score = 0.75
                                prob.notes.append("9项运算输出正确，但源码缺少运算符，疑似直接打印常数")
                                prob.needs_review = True
                                prob.review_reasons.append("1-2 源码运算符静态检查未通过")
                        else:
                            # 逻辑运算如 ||, && 错误直接导致失分并记录
                            code_score = round(1.5 * (passed_terms / 9.0), 2)
                            prob.notes.append(f"代码运算有 {len(failed_terms)} 项不符预期: {', '.join(failed_terms)} (通过 {passed_terms}/9)")
                    else:
                        prob.notes.append(f"代码输出数字不足 9 个 (实际输出 {len(numbers)} 个)")
                        code_score = 0.2

            prob.sub_scores["code"] = code_score

        # --- B. 演草纸手写验算评测 (1.5分) ---
        ai_res = HandwrittenReviewer.review_images(
            student_id=student.student_id,
            student_name=student.name,
            expected_x=expected_x,
            image_paths=images,
            mock_mode=mock_ai,
        )
        prob.ai_review = ai_res
        handwritten_score = 0.0
        if ai_res.get("suggested_score") is not None:
            handwritten_score = round(float(ai_res.get("suggested_score")), 2)
        if ai_res.get("is_pending"):
            prob.is_pending = True
            prob.needs_review = True

        # 演草纸学生身份核对（学号与姓名）
        hw_sid = ai_res.get("student_id_observed")
        hw_name = ai_res.get("name_observed")
        if hw_sid and str(hw_sid).strip() != str(student.student_id).strip():
            prob.needs_review = True
            prob.review_reasons.append(f"演草纸手写学号 ({hw_sid}) 与系统学号 ({student.student_id}) 不符")
            handwritten_score = 0.0

        if hw_name and str(hw_name).strip() != str(student.name).strip():
            prob.needs_review = True
            prob.review_reasons.append(f"演草纸手写姓名 ({hw_name}) 与系统姓名 ({student.name}) 不符")
            handwritten_score = min(handwritten_score, 0.8)

        # 参数一致性交叉核对（代码、手机号、演草纸）
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
            # 扣除参数一致性子项得分
            if handwritten_score > 0:
                handwritten_score = max(0.0, round(handwritten_score - 0.2, 2))

        if student.phone and len(student.phone) >= 2:
            try:
                roster_y = int(student.phone[-2:])
                if deduced_y is not None and deduced_y != roster_y:
                    prob.needs_review = True
                    prob.review_reasons.append(f"代码 y={deduced_y} 与点名册手机号末两位 {roster_y} 不一致")
                if hw_y is not None and hw_y != roster_y:
                    prob.needs_review = True
                    prob.review_reasons.append(f"演草纸 y={hw_y} 与点名册手机号末两位 {roster_y} 不一致")
            except ValueError:
                pass

        prob.sub_scores["handwritten"] = handwritten_score
        prob.notes.append(f"演草纸批改: {ai_res.get('reasoning', '')}")

        if ai_res.get("needs_review"):
            prob.needs_review = True
            prob.review_reasons.append(f"演草纸复核: {ai_res.get('review_reason', '')}")

        # 汇总分数与状态
        prob.score = round(code_score + handwritten_score, 2)
        if prob.is_pending:
            prob.status = "needs_review"
        elif prob.score >= 2.8:
            prob.status = "passed"
        elif prob.score > 0:
            prob.status = "partial"
        else:
            prob.status = "failed"

        return prob

    def _grade_lab1_3(
        self,
        student: Student,
        sources: List[Path],
        build_dir: Path,
        mock_ai: bool,
    ) -> ProblemResult:
        """评测 Lab 1-3：温度转换 (2.0分)"""
        prob = ProblemResult(problem_id="1-3", score=0.0, max_score=2.0, source_files=sources)

        if not sources:
            prob.status = "missing"
            prob.notes.append("未提交 Lab 1-3 源码")
            return prob

        src_path = sources[0]
        if len(sources) > 1:
            prob.notes.append(f"发现多份 1-3 源码候选，默认评测首个: {src_path.name}")
            prob.needs_review = True
            prob.review_reasons.append(f"同题多候选: {[s.name for s in sources]}")

        src_text = src_path.read_text(encoding="utf-8", errors="ignore")
        c_res = self.compiler.compile(src_path, build_dir, "lab1_3")
        prob.compile_result = c_res

        if not c_res.success:
            prob.status = "compile_error"
            prob.notes.append("Lab 1-3 编译失败")
            return prob

        passed_cases = 0
        total_cases = len(self.lab1_3_cases)
        has_int_div_bug = False
        outputs_collected = []

        for idx, (in_str, conv_type, expected_val) in enumerate(self.lab1_3_cases, 1):
            exec_res = run_binary(c_res.binary_path, input_str=in_str, timeout=2.0)
            outputs_collected.append(exec_res.stdout.strip())

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
                # 提取输出中所有浮点数
                floats = [float(fl) for fl in re.findall(r"-?\b\d+(?:\.\d+)?\b", exec_res.stdout)]

                # 防作弊检测: 程序同时倾倒多个用例的标准参考答案
                # 排除 0.0 与 32.0 等公式与输入常见整数常数，仅关注特异性温度浮点答案（如 37.78, 19.99, -17.78, 212.00, 29.72, 77.00）
                other_specific_targets = [
                    v for _, _, v in self.lab1_3_cases
                    if abs(v - expected_val) > 0.1 and abs(v) > 0.1 and abs(v - 32.0) > 0.1
                ]
                matches_other_targets = sum(
                    1 for ot in other_specific_targets if any(abs(f - ot) <= 0.05 for f in floats)
                )
                if matches_other_targets >= 2:
                    case_res.error_message = "检测到程序同时输出多个无关特定参考答案，判定作弊刷屏"
                    prob.test_results.append(case_res)
                    continue

                # 识别本次输入对应的实际转换结果
                found_match = False
                for val in floats:
                    if abs(val - expected_val) <= 0.08:
                        found_match = True
                        break
                    # 检查整数除法陷阱 (如 5/9 截断为 0 导致结果为 0 或 32)
                    if expected_val != 0.0 and abs(val - 0.0) < 0.001 and conv_type == "Centigrade":
                        has_int_div_bug = True

                if found_match:
                    case_res.passed = True
                    case_res.score = case_res.max_score
                    passed_cases += 1
                else:
                    if idx == 1:
                        ai_sem = SemanticAmbiguityReviewer.review_output(
                            problem_id="1-3",
                            student_id=student.student_id,
                            input_data=in_str,
                            expected_behavior=f"温度转换输出接近 {expected_val:.2f}",
                            actual_output=exec_res.stdout,
                            source_code=src_text,
                            max_score=case_res.max_score,
                            mock_mode=mock_ai,
                        )
                        if ai_sem.get("passed"):
                            case_res.passed = True
                            case_res.score = case_res.max_score
                            passed_cases += 1
                            prob.notes.append(f"用例 {idx} 经 AI 语义复核确认逻辑正确通过")
                        elif ai_sem.get("is_pending"):
                            case_res.needs_review = True
                            sem_reason = ai_sem.get("review_reason") or "AI 语义复核超时或异常，成绩待定"
                            case_res.review_reason = sem_reason
                            prob.is_pending = True
                            prob.needs_review = True
                            prob.review_reasons.append(f"1-3 语义复核待定: {sem_reason}")
                            prob.notes.append(f"用例 {idx} AI 语义复核待定: {sem_reason}")
                        elif ai_sem.get("needs_review"):
                            case_res.needs_review = True
                            sem_reason = ai_sem.get("review_reason") or "AI 语义复核需人工介入"
                            case_res.review_reason = sem_reason
                            prob.needs_review = True
                            prob.review_reasons.append(f"1-3 需人工复核: {sem_reason}")

            prob.test_results.append(case_res)

        # 防作弊检测 2: 检查不同输入下输出是否完全相同 (不读输入直接打印固定静态内容)
        if len(outputs_collected) >= 2:
            unique_outputs = set(outputs_collected)
            if len(unique_outputs) == 1 and total_cases > 1:
                prob.notes.append("检测到程序在不同输入下输出完全相同的静态文本，判定未读取输入")
                passed_cases = 0
                for cr in prob.test_results:
                    cr.passed = False
                    cr.score = 0.0
                    cr.error_message = "静态输出检测失败：不同输入输出无变化"

        if has_int_div_bug:
            prob.notes.append("检测到典型 C 语言整型截断除法缺陷 (如 5*(fahr-32)/9 写成了 5/9*(fahr-32))")

        # 计分
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
        return prob

    def generate_comment(self, grade: StudentGrade) -> str:
        """生成不少于 50 字的定制评语"""
        student = grade.student
        r1_2 = grade.problem_results.get("1-2")
        r1_3 = grade.problem_results.get("1-3")

        parts = [f"{student.name}同学你好！本次实验1针对二进制逻辑与C语言基础语法的掌握情况评测完成。"]

        if grade.status == "missing":
            return f"{student.name}同学你好！系统未检测到你在实验1的有效代码提交，请核查是否打包格式有误或漏交。按教学大纲要求，请尽快联系助教补交并进行复核，以便确认实验平时成绩。"

        # 1-2 评述
        if r1_2:
            if r1_2.status == "passed":
                parts.append("在Lab 1-2中，按要求将学号末两位对齐参数x，位运算与逻辑运算执行完全正确，演草纸推导规范清晰；")
            elif r1_2.status == "partial":
                parts.append("在Lab 1-2中完成了基础位运算代码，但部分输出结果与推导细节存在偏差，演草纸步骤需更加完备；")
            elif r1_2.status == "compile_error":
                parts.append("在Lab 1-2中程序编译未能通过，请注意排查语法错误与标准库头文件声明；")
            else:
                parts.append("在Lab 1-2中运算逻辑或演草纸提交存在缺失，需加强位运算展开练习；")

        # 1-3 评述
        if r1_3:
            if r1_3.status == "passed":
                parts.append("Lab 1-3温度转换程序编写规范，成功通过全部双向精度与边界用例测试，表现优秀！")
            elif r1_3.status == "partial":
                parts.append("Lab 1-3温度转换基本逻辑具备，但个别用例或除法浮点精度未达标，需注意5/9等整型除法陷阱。")
            elif r1_3.status == "compile_error":
                parts.append("Lab 1-3程序未能成功编译，建议在IDE中先确认本地运行无误后再提交。")
            else:
                parts.append("Lab 1-3未能正确完成两种温度互转，需巩固选择分支与算式表达。")

        parts.append("总体实验完成度良好，望继续保持严谨求实的编程习惯！")
        comment = "".join(parts)

        # 确保满足 50 字要求
        if len(comment) < 50:
            comment += "希望在后续实验中继续加强代码调试与边界测试意识，扎实掌握基础。"

        return comment
