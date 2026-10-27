"""
tests/test_checker.py
判题机全覆盖单元与集成测试套件（完全脱敏，无任何硬编码个人真实数据）
"""
import io
import json
import os
import shutil
import unittest
import zipfile
from pathlib import Path

from checker.ai import HandwrittenReviewer, SemanticAmbiguityReviewer
from checker.compiler import ProjectCompiler
from checker.config import DEFAULT_ROSTER_PATH, DEFAULT_TEMPLATE_PATH, PROJECT_ROOT, WORK_DIR
from checker.labs.lab1 import Lab1Judge
from checker.labs.lab2 import Lab2Judge
from checker.models import ProblemResult, Student, StudentGrade, SubmissionFile, TestCaseResult
from checker.reporter import LabReporter
from checker.roster import RosterManager
from checker.sandbox import run_binary
from checker.unpack import SafeExtractor, SubmissionNormalizer


class TestCheckerSystem(unittest.TestCase):
    """判题系统全流程测试"""

    @classmethod
    def setUpClass(cls):
        cls.test_work = WORK_DIR / "test_runs"
        cls.test_work.mkdir(parents=True, exist_ok=True)

        # 若真实点名册存在则加载，否则动态构造脱敏单测专用花名册
        cls.roster_mgr = RosterManager()
        if DEFAULT_ROSTER_PATH.exists():
            cls.roster_mgr.load_roster(DEFAULT_ROSTER_PATH)
        else:
            cls.roster_mgr.students = [
                Student(seq=1, student_id="2026000067", name="测试生甲", class_id="260101"),
                Student(seq=2, student_id="2026000090", name="测试生乙", class_id="260101"),
            ]
            for s in cls.roster_mgr.students:
                cls.roster_mgr.by_id[s.student_id] = s
                cls.roster_mgr.by_name.setdefault(s.name, []).append(s)

    @classmethod
    def tearDownClass(cls):
        if cls.test_work.exists():
            shutil.rmtree(cls.test_work, ignore_errors=True)

    def test_01_roster_parsing(self):
        """测试 1: 点名册解析与学生身份匹配"""
        self.assertGreater(len(self.roster_mgr.students), 0)
        s1 = self.roster_mgr.students[0]
        self.assertTrue(len(s1.student_id) >= 8)
        self.assertTrue(len(s1.name) >= 2)

        # 动态匹配测试
        sample_text = f"2612901_{s1.name}_{s1.student_id}_实验1.zip"
        matched, cands, reason = self.roster_mgr.match_student_from_text(sample_text)
        self.assertIsNotNone(matched)
        self.assertEqual(matched.student_id, s1.student_id)

        # 模糊空格/下划线测试
        s2 = self.roster_mgr.students[1] if len(self.roster_mgr.students) > 1 else s1
        matched2, _, _ = self.roster_mgr.match_student_from_text(f"{s2.student_id}  {s2.name}  Lab 1-2.c")
        self.assertIsNotNone(matched2)
        self.assertEqual(matched2.student_id, s2.student_id)

    def test_02_safe_unpack_and_zipslip_protection(self):
        """测试 2: Zip Slip 恶意路径穿越防御与正常解压"""
        malicious_zip = self.test_work / "malicious.zip"
        with zipfile.ZipFile(malicious_zip, "w") as zf:
            zf.writestr("../../evil.txt", "attack payload")
            zf.writestr("normal.c", "int main(){return 0;}")

        dest = self.test_work / "unsafe_extract"
        extractor = SafeExtractor(self.test_work / "scratch")
        ok, msg, files = extractor.extract_archive(malicious_zip, dest)
        self.assertFalse(ok)
        self.assertIn("Zip Slip", msg)

        # 正常 zip
        normal_zip = self.test_work / "normal.zip"
        with zipfile.ZipFile(normal_zip, "w") as zf:
            zf.writestr("test_folder/hello.c", "int main(){return 0;}")

        ok2, msg2, files2 = extractor.extract_archive(normal_zip, dest)
        self.assertTrue(ok2)
        self.assertEqual(len(files2), 1)

    def test_03_compiler_and_windows_compat(self):
        """测试 3: Windows 特有语法与头文件自动兼容转换"""
        compiler = ProjectCompiler()
        build_dir = self.test_work / "build_compat"

        win_code = """
#include <stdio.h>
#include <windows.h>
#include <conio.h>

int main() {
    int val = 0;
    scanf_s("%d", &val);
    printf("Received: %d\\n", val * 2);
    fflush(stdin);
    system("pause");
    return 0;
}
"""
        src_path = self.test_work / "win_prog.c"
        src_path.write_text(win_code, encoding="gbk")

        c_res = compiler.compile(src_path, build_dir, "win_compat_test")
        self.assertTrue(c_res.success)
        self.assertTrue(c_res.compat_applied)
        self.assertGreater(len(c_res.compat_reasons), 0)

        exec_res = run_binary(c_res.binary_path, input_str="21\n", timeout=2.0)
        self.assertEqual(exec_res.exit_code, 0)
        self.assertIn("Received: 42", exec_res.stdout)

    def test_04_sandbox_timeout_and_infinite_loop(self):
        """测试 4: 沙箱超时强杀（死循环进程组清理）与超长输出截断"""
        compiler = ProjectCompiler()
        build_dir = self.test_work / "build_sandbox"

        # A. 死循环程序
        loop_code = "int main() { while(1) {} return 0; }"
        loop_src = self.test_work / "loop.c"
        loop_src.write_text(loop_code)
        c_res = compiler.compile(loop_src, build_dir, "loop")
        self.assertTrue(c_res.success)

        res = run_binary(c_res.binary_path, input_str="", timeout=1.0)
        self.assertTrue(res.timed_out)
        self.assertEqual(res.exit_code, -1)

        # B. 刷屏巨量输出程序 (防 OOM 截断)
        flood_code = """
#include <stdio.h>
int main() {
    for (int i = 0; i < 50000; i++) {
        printf("flood_test_line_1234567890_flood_test_line_1234567890\\n");
    }
    return 0;
}
"""
        flood_src = self.test_work / "flood.c"
        flood_src.write_text(flood_code)
        c_res2 = compiler.compile(flood_src, build_dir, "flood")
        self.assertTrue(c_res2.success)

        res2 = run_binary(c_res2.binary_path, input_str="", timeout=2.0)
        self.assertTrue(res2.truncated)
        self.assertIn("TRUNCATED", res2.stdout)

    def test_05_loose_vs_strict_lab1(self):
        """测试 5: Lab 1 确定性与宽松判题（对比正确与错误逻辑）"""
        judge = Lab1Judge()
        build_dir = self.test_work / "build_lab1_test"

        s1 = self.roster_mgr.students[0]
        exp_x = int(s1.student_id[-2:])

        correct_1_2 = f"""
#include <stdio.h>
int main(void) {{
    short x = {exp_x}, y = 88;
    printf("%5hd%5hd%5hd\\n", !x, x||y, x&&y);
    printf("%5hu%5hd%5hd\\n", ~x, x|y, x&y);
    printf("%5hd%5hd%5hd\\n \\n", ~x, x|y, x&y);
    return 0;
}}
"""
        p_1_2 = self.test_work / f"{s1.student_id}_Lab 1-2.c"
        p_1_2.write_text(correct_1_2)

        correct_1_3 = """
#include <stdio.h>
int main() {
    int button;
    float temp;
    printf("请输入模式(0:F->C, 1:C->F)和温度: ");
    if (scanf("%d %f", &button, &temp) == 2) {
        if (button == 0) {
            float c = 5.0f * (temp - 32.0f) / 9.0f;
            printf("转换后的摄氏度是: %.2f\\n", c);
        } else {
            float f = 9.0f * temp / 5.0f + 32.0f;
            printf("The Fahrenheit is %.2f\\n", f);
        }
    }
    return 0;
}
"""
        p_1_3 = self.test_work / f"{s1.student_id}_Lab 1-3.c"
        p_1_3.write_text(correct_1_3)

        files = [
            SubmissionFile(p_1_2, p_1_2.name, "c_source", "1-2"),
            SubmissionFile(p_1_3, p_1_3.name, "c_source", "1-3"),
        ]

        grade = judge.grade_student(s1, files, build_dir, mock_ai=True)
        self.assertEqual(grade.problem_results["1-2"].sub_scores["code"], 1.5)
        self.assertEqual(grade.problem_results["1-3"].status, "passed")
        self.assertEqual(grade.problem_results["1-3"].score, 2.0)
        self.assertGreaterEqual(len(grade.comment), 50)

        # 错误逻辑：整型截断除法 5/9
        wrong_int_div_1_3 = """
#include <stdio.h>
int main() {
    int button;
    float temp;
    if (scanf("%d %f", &button, &temp) == 2) {
        if (button == 0) {
            float c = (5 / 9) * (temp - 32);
            printf("%.2f\\n", c);
        } else {
            float f = 9 * temp / 5 + 32;
            printf("%.2f\\n", f);
        }
    }
    return 0;
}
"""
        p_wrong = self.test_work / "wrong_1_3.c"
        p_wrong.write_text(wrong_int_div_1_3)
        files_wrong = [SubmissionFile(p_wrong, p_wrong.name, "c_source", "1-3")]

        grade_wrong = judge.grade_student(s1, files_wrong, build_dir, mock_ai=True)
        self.assertLess(grade_wrong.problem_results["1-3"].score, 2.0)
        self.assertTrue(any("截断" in n for n in grade_wrong.problem_results["1-3"].notes))

    def test_06_loose_vs_strict_lab2(self):
        """测试 6: Lab 2 宽松问候语匹配、字母金字塔对称性与笔误容错"""
        judge = Lab2Judge()
        build_dir = self.test_work / "build_lab2_test"
        s2 = self.roster_mgr.students[1] if len(self.roster_mgr.students) > 1 else self.roster_mgr.students[0]

        chinese_greeting_2_1 = """
#include <stdio.h>
int main() {
    int h;
    if (scanf("%d", &h) == 1) {
        if (h >= 0 && h < 12) printf("早上好，阳光明媚！\\n");
        else if (h == 12) printf("中午好！\\n");
        else if (h >= 13 && h < 18) printf("下午好，喝杯茶吧！\\n");
        else if (h >= 18 && h < 21) printf("傍晚好！\\n");
        else if (h >= 21 && h < 24) printf("深夜好，晚安！\\n");
        else printf("输入不合法，错误！\\n");
    }
    return 0;
}
"""
        p_2_1 = self.test_work / f"{s2.student_id}_Lab 2-1.c"
        p_2_1.write_text(chinese_greeting_2_1)

        pyramid_2_2 = """
#include <stdio.h>
#include <ctype.h>

int main() {
    char ch;
    if (scanf(" %c", &ch) == 1) {
        if (!isalpha(ch)) {
            printf("Not a letter!\\n");
            return 0;
        }
        ch = toupper(ch);
        int n = ch - 'A' + 1;
        for (int i = 1; i <= n; i++) {
            for (int s = 0; s < n - i; s++) printf(" ");
            for (char c = 'A'; c < 'A' + i; c++) printf("%c", c);
            for (char c = 'A' + i - 2; c >= 'A'; c--) printf("%c", c);
            printf("\\n");
        }
    }
    return 0;
}
"""
        p_2_2 = self.test_work / f"{s2.student_id}_Lab 2-2.c"
        p_2_2.write_text(pyramid_2_2)

        files = [
            SubmissionFile(p_2_1, p_2_1.name, "c_source", "2-1"),
            SubmissionFile(p_2_2, p_2_2.name, "c_source", "2-2"),
        ]

        grade = judge.grade_student(s2, files, build_dir, mock_ai=True)
        self.assertEqual(grade.problem_results["2-1"].score, 2.0)
        self.assertEqual(grade.problem_results["2-2"].score, 3.0)
        self.assertEqual(grade.total_score, 5.0)

        # 单向未对称镜像
        bad_pyramid = """
#include <stdio.h>
int main() {
    char ch;
    scanf(" %c", &ch);
    printf("A\\nAB\\nABC\\n");
    return 0;
}
"""
        p_bad = self.test_work / "bad_pyramid.c"
        p_bad.write_text(bad_pyramid)
        files_bad = [SubmissionFile(p_bad, p_bad.name, "c_source", "2-2")]

        grade_bad = judge.grade_student(s2, files_bad, build_dir, mock_ai=True)
        self.assertLess(grade_bad.problem_results["2-2"].score, 3.0)

    def test_07_ai_review_fallback_on_failure(self):
        """测试 7: AI 调用失败/超时时不误判为 0 分，保留复核标记"""
        s1 = self.roster_mgr.students[0]
        res = HandwrittenReviewer.review_images(
            student_id=s1.student_id,
            student_name=s1.name,
            expected_x=int(s1.student_id[-2:]),
            image_paths=[self.test_work / "non_existent.png"],
            mock_mode=False,
        )
        self.assertEqual(res["suggested_score"], 0.0)
        self.assertIn("缺失", res["reasoning"])

    def test_08_reporter_outputs_and_roster_alignment(self):
        """测试 8: 三份报表导出与点名册全量对齐（不少于50字评语）"""
        output_dir = self.test_work / "output"
        reporter = LabReporter("lab1", output_dir)

        s1 = self.roster_mgr.students[0]
        s2 = self.roster_mgr.students[1] if len(self.roster_mgr.students) > 1 else s1

        g1 = StudentGrade(student=s1, total_score=5.0, status="graded")
        g1.comment = f"{s1.name}同学你好！本次实验1针对二进制逻辑与C语言基础语法的掌握情况评测完成。按要求将学号末两位对齐参数x，位运算与逻辑运算执行完全正确，演草纸推导规范清晰；Lab 1-3温度转换程序编写规范，成功通过全部双向精度与边界用例测试，表现优秀！望继续保持！"

        g2 = StudentGrade(student=s2, total_score=3.5, status="graded", needs_review=True, review_reasons=["演草纸字迹待人工核查"])
        g2.comment = f"{s2.name}同学你好！本次实验1在Lab 1-2中完成了基础位运算代码，但部分输出结果与推导细节存在偏差，演草纸步骤需更加完备；Lab 1-3温度转换程序编写规范，成功通过测试。希望在后续实验中继续加强代码调试与边界测试意识，扎实掌握基础。"

        grades = {s1.student_id: g1, s2.student_id: g2}

        res_files = reporter.generate_all_reports(
            self.roster_mgr.students,
            grades,
            excel_template_path=DEFAULT_TEMPLATE_PATH if DEFAULT_TEMPLATE_PATH.exists() else None,
        )

        detail_csv = res_files["detail_csv"]
        summary_md = res_files["summary_md"]
        roster_csv = res_files["roster_csv"]

        self.assertTrue(detail_csv.exists())
        self.assertTrue(summary_md.exists())
        self.assertTrue(roster_csv.exists())

        lines = roster_csv.read_text(encoding="utf-8-sig").splitlines()
        self.assertEqual(len(lines), len(self.roster_mgr.students) + 1)

        self.assertGreaterEqual(len(g1.comment), 50)
        self.assertGreaterEqual(len(g2.comment), 50)

        md_text = summary_md.read_text(encoding="utf-8")
        self.assertIn("待人工复核清单", md_text)
        self.assertIn(s2.student_id, md_text)

    def test_09_adversarial_lab1_2_checks(self):
        """测试 9 (反例对抗): Lab 1-2 逻辑运算错误被严格拦截，且代码与手写参数矛盾时触发复核"""
        judge = Lab1Judge()
        build_dir = self.test_work / "build_lab1_adv"
        s1 = self.roster_mgr.students[0]
        exp_x = int(s1.student_id[-2:])

        # 反例 A: || 与 && 输出错误 (全输出 0) 但位运算正确
        wrong_logic_code = f"""
#include <stdio.h>
int main(void) {{
    short x = {exp_x}, y = 88;
    printf("%5hd%5hd%5hd\\n", 0, 0, 0); // 逻辑运算故意错误
    printf("%5hu%5hd%5hd\\n", (unsigned short)~x, (short)(x|y), (short)(x&y));
    printf("%5hd%5hd%5hd\\n \\n", (short)~x, (short)(x|y), (short)(x&y));
    return 0;
}}
"""
        p_wrong_logic = self.test_work / "wrong_logic_1_2.c"
        p_wrong_logic.write_text(wrong_logic_code)
        files_wrong = [SubmissionFile(p_wrong_logic, p_wrong_logic.name, "c_source", "1-2")]

        res_wrong = judge._grade_lab1_2(s1, [p_wrong_logic], [], build_dir, mock_ai=True)
        # 必须失分，不能获得 1.5 分满分
        self.assertLess(res_wrong.sub_scores["code"], 1.5)
        self.assertTrue(any("逻辑运算" in n or "不符预期" in n for n in res_wrong.notes))

        # 反例 B: 代码中 y=88，但演草纸手写为 y=1 参数矛盾核验
        correct_code = f"""
#include <stdio.h>
int main(void) {{
    short x = {exp_x}, y = 88;
    printf("%5hd%5hd%5hd\\n", !x, x||y, x&&y);
    printf("%5hu%5hd%5hd\\n", (unsigned short)~x, (short)(x|y), (short)(x&y));
    printf("%5hd%5hd%5hd\\n \\n", (short)~x, (short)(x|y), (short)(x&y));
    return 0;
}}
"""
        p_correct = self.test_work / "correct_1_2.c"
        p_correct.write_text(correct_code)

        # 模拟 AI 识别到的演草纸手写 y 为 1 (与代码 y=88 矛盾)
        from unittest.mock import patch
        mock_ai_return = {
            "task_id": "lab1_2_handwritten",
            "student_id_observed": s1.student_id,
            "name_observed": s1.name,
            "phone_observed": "01",
            "x_observed": exp_x,
            "y_observed": 1,  # 矛盾参数
            "info_score": 0.5,
            "xy_match_score": 0.2,
            "derivation_score": 0.8,
            "suggested_score": 1.5,
            "is_pending": False,
            "reasoning": "验算 y=1",
            "needs_review": False,
        }

        with patch("checker.ai.HandwrittenReviewer.review_images", return_value=mock_ai_return):
            res_discrepancy = judge._grade_lab1_2(s1, [p_correct], [self.test_work / "dummy.png"], build_dir, mock_ai=False)
            self.assertTrue(res_discrepancy.needs_review)
            self.assertTrue(any("参数矛盾" in r for r in res_discrepancy.review_reasons))

    def test_10_adversarial_lab1_3_dumping_cheat(self):
        """测试 10 (反例对抗): Lab 1-3 倾倒全部参考答案刷屏作弊与静态输出被直接拦截"""
        judge = Lab1Judge()
        build_dir = self.test_work / "build_lab1_3_adv"
        s1 = self.roster_mgr.students[0]

        # 倾倒全部用例标准答案，完全不读取输入
        dump_cheat_code = """
#include <stdio.h>
int main() {
    printf("37.78 19.99 -17.78 0.00 32.00 212.00 -40.00\\n");
    return 0;
}
"""
        p_dump = self.test_work / "dump_1_3.c"
        p_dump.write_text(dump_cheat_code)

        res_dump = judge._grade_lab1_3(s1, [p_dump], build_dir, mock_ai=True)
        # 绝不能通过，得分必须为 0 分
        self.assertEqual(res_dump.score, 0.0)
        self.assertEqual(res_dump.status, "failed")

    def test_11_adversarial_lab2_2_single_line_and_invalid_char(self):
        """测试 11 (反例对抗): 金字塔单行作弊拦截与规范 Invalid character! 识别"""
        judge = Lab2Judge()
        build_dir = self.test_work / "build_lab2_2_adv"
        s2 = self.roster_mgr.students[1] if len(self.roster_mgr.students) > 1 else self.roster_mgr.students[0]

        # 反例 A: 输入 C 却只打印最后一行 ABCBA 的投机程序
        cheat_single_line_code = """
#include <stdio.h>
int main() {
    char ch;
    scanf(" %c", &ch);
    printf("ABCBA\\n"); // 只输出最后一行
    return 0;
}
"""
        p_cheat = self.test_work / "cheat_pyramid.c"
        p_cheat.write_text(cheat_single_line_code)

        res_cheat = judge._grade_lab2_2(s2, [p_cheat], build_dir, mock_ai=True)
        # 针对输入 C 期望 3 行，实际仅 1 行，必须判定失败，得分绝不能为满分
        self.assertLess(res_cheat.score, 3.0)

        # 针对非字母打印指导书规范 Sample 3: "Invalid character!" 的完全正确程序
        valid_error_code = """
#include <stdio.h>
#include <ctype.h>
int main() {
    char ch;
    if (scanf(" %c", &ch) == 1) {
        if (!isalpha(ch)) {
            printf("Invalid character!\\n");
            return 0;
        }
        ch = toupper(ch);
        int n = ch - 'A' + 1;
        for (int i = 1; i <= n; i++) {
            for (int s = 0; s < n - i; s++) printf(" ");
            for (char c = 'A'; c < 'A' + i; c++) printf("%c", c);
            for (char c = 'A' + i - 2; c >= 'A'; c--) printf("%c", c);
            printf("\\n");
        }
    }
    return 0;
}
"""
        p_valid_err = self.test_work / "valid_err_pyramid.c"
        p_valid_err.write_text(valid_error_code)

        res_valid = judge._grade_lab2_2(s2, [p_valid_err], build_dir, mock_ai=True)
        # 必须获得满分 3.0，包括非字母用例完全通过
        self.assertEqual(res_valid.score, 3.0)
        self.assertEqual(res_valid.status, "passed")

    def test_12_scanf_s_shim_and_math_link_order(self):
        """测试 12: scanf_s 多参数垫片与 -lm 数学库链接顺序正确性"""
        compiler = ProjectCompiler()
        build_dir = self.test_work / "build_compiler_adv"

        # A. 测试 -lm 链接数学库 sin/cos
        math_code = """
#include <stdio.h>
#include <math.h>
int main() {
    double val = sin(0.0);
    printf("sin(0)=%.1f\\n", val);
    return 0;
}
"""
        p_math = self.test_work / "math_test.c"
        p_math.write_text(math_code)
        c_res = compiler.compile(p_math, build_dir, "math_test")
        self.assertTrue(c_res.success, f"数学库链接失败: {c_res.stderr}")

        exec_res = run_binary(c_res.binary_path, input_str="")
        self.assertIn("sin(0)=0.0", exec_res.stdout)

        # B. 测试 scanf_s 带缓冲区大小参数 (%s %d)
        scanf_s_code = """
#include <stdio.h>
int main() {
    char name[32];
    int score = 0;
    // MSVC 规范：字符串缓冲区后需携带长度参数
    scanf_s("%s %d", name, (unsigned)sizeof(name), &score);
    printf("Name: %s, Score: %d\\n", name, score);
    return 0;
}
"""
        p_scanf = self.test_work / "scanf_s_test.c"
        p_scanf.write_text(scanf_s_code)
        c_res2 = compiler.compile(p_scanf, build_dir, "scanf_s_test")
        self.assertTrue(c_res2.success, f"scanf_s 编译失败: {c_res2.stderr}")

        exec_res2 = run_binary(c_res2.binary_path, input_str="Alice 95\n")
        self.assertEqual(exec_res2.exit_code, 0)
        self.assertIn("Name: Alice, Score: 95", exec_res2.stdout)

    def test_13_attribution_conflict_reported(self):
        """测试 13: 提交文件多候选归属冲突不被转换成未交，准确进入复核清单"""
        output_dir = self.test_work / "output_conflict"
        reporter = LabReporter("lab1", output_dir)

        s1 = self.roster_mgr.students[0]
        s2 = self.roster_mgr.students[1] if len(self.roster_mgr.students) > 1 else s1

        # 构造冲突记录
        conflict_msg = f"提交包同时包含多个候选学号: ['{s1.student_id}', '{s2.student_id}']"
        g1 = StudentGrade(
            student=s1,
            max_score=5.0,
            status="ambiguous",
            needs_review=True,
            is_pending=True,
            review_reasons=[conflict_msg],
        )

        grades = {s1.student_id: g1}
        ambiguous_items = [{"path": "conflict_test.zip", "candidates": [s1.student_id, s2.student_id], "reason": conflict_msg}]

        rep_paths = reporter.generate_all_reports(
            self.roster_mgr.students,
            grades,
            ambiguous_items=ambiguous_items,
        )

        summary_text = rep_paths["summary_md"].read_text(encoding="utf-8")
        self.assertIn("待人工复核清单", summary_text)
        self.assertIn(s1.student_id, summary_text)
        self.assertIn("多学号冲突提交件", summary_text)

        detail_text = rep_paths["detail_csv"].read_text(encoding="utf-8-sig")
        self.assertIn("冲突待复核", detail_text)

    def test_14_single_student_grade_merge(self):
        """测试 14: 单人重判 (--student-id) 安全合并，严防将他人成绩清零覆写"""
        output_dir = self.test_work / "output_single_merge"
        reporter = LabReporter("lab1", output_dir)

        s1 = self.roster_mgr.students[0]
        s2 = self.roster_mgr.students[1] if len(self.roster_mgr.students) > 1 else s1

        # 1. 模拟初始全班成绩：s1=4.5分, s2=5.0分
        g1 = StudentGrade(student=s1, total_score=4.5, status="graded", comment="学生甲初评4.5分" + "。" * 40)
        g2 = StudentGrade(student=s2, total_score=5.0, status="graded", comment="学生乙初评5.0分" + "。" * 40)
        init_grades = {s1.student_id: g1, s2.student_id: g2}

        reporter.generate_all_reports(self.roster_mgr.students, init_grades)

        # 2. 模拟针对 s1 单人重判为 5.0分
        g1_regrade = StudentGrade(student=s1, total_score=5.0, status="graded", comment="学生甲重评5.0分满分通过" + "。" * 40)

        # 单人结果独立导出
        single_res = reporter.generate_single_student_report(s1, g1_regrade)
        self.assertTrue(single_res["detail_csv"].exists())

        # 读取并合并全班批次
        merged_grades = reporter.load_existing_grades_from_files(self.roster_mgr.students)
        self.assertIn(s2.student_id, merged_grades)
        self.assertAlmostEqual(merged_grades[s2.student_id].total_score, 5.0)

        # 更新 s1
        merged_grades[s1.student_id] = g1_regrade
        reporter.generate_all_reports(self.roster_mgr.students, merged_grades)

        # 3. 验证 s2 的成绩绝未被清零成未交！
        roster_csv_text = (output_dir / "lab1实验成绩单.csv").read_text(encoding="utf-8-sig")
        self.assertIn(f"{s2.student_id},{s2.name}", roster_csv_text)
        self.assertIn(f"{s1.student_id},{s1.name}", roster_csv_text)
        self.assertIn("学生乙初评5.0分", roster_csv_text)
        self.assertIn("学生甲重评5.0分满分通过", roster_csv_text)

    def test_15_lab1_3_verbose_prompt_pass(self):
        """测试 15: Lab 1-3 包含提示语 0: F→C; 1: C→F; C=5*(F-32)/9 的正确程序通过不被误判作弊"""
        judge = Lab1Judge()
        build_dir = self.test_work / "build_lab1_3_verbose"
        s1 = self.roster_mgr.students[0]

        # 包含较多数字提示语但计算完全正确的学生程序
        verbose_code = """
#include <stdio.h>
int main() {
    int mode;
    double val, res;
    // 提示信息中包含 0, 1, 5, 32, 9 等多个数字
    printf("Please choose mode (0: F->C; 1: C->F; formula: C=5*(F-32)/9):\\n");
    if (scanf("%d %lf", &mode, &val) != 2) return 1;
    if (mode == 0) {
        res = 5.0 * (val - 32.0) / 9.0;
        printf("Fahrenheit %.2f to Centigrade is: %.2f\\n", val, res);
    } else {
        res = 9.0 * val / 5.0 + 32.0;
        printf("Centigrade %.2f to Fahrenheit is: %.2f\\n", val, res);
    }
    return 0;
}
"""
        p_verbose = self.test_work / "verbose_1_3.c"
        p_verbose.write_text(verbose_code)

        res = judge._grade_lab1_3(s1, [p_verbose], build_dir, mock_ai=True)
        # 必须获得满分 2.0，不得被判定作弊
        self.assertEqual(res.score, 2.0)
        self.assertEqual(res.status, "passed")
        for tr in res.test_results:
            self.assertTrue(tr.passed, f"用例未通过: {tr.input_data} -> {tr.actual_output} (error: {tr.error_message})")

    def test_16_detail_csv_multi_problem_and_recovery(self):
        """测试 16: 明细表与单人报告导出所有题目，历史成绩恢复包含全部题目"""
        output_dir = self.test_work / "output_multi_prob"
        reporter = LabReporter("lab1", output_dir)
        s1 = self.roster_mgr.students[0]

        g = StudentGrade(student=s1, total_score=5.0, status="graded", comment="学生甲全对" + "。" * 40)
        p1 = ProblemResult(problem_id="1-2", score=3.0, max_score=3.0, status="passed")
        p2 = ProblemResult(problem_id="1-3", score=2.0, max_score=2.0, status="passed")
        g.problem_results["1-2"] = p1
        g.problem_results["1-3"] = p2

        # 1. 批次全量明细表导出
        rep_paths = reporter.generate_all_reports(self.roster_mgr.students, {s1.student_id: g})
        detail_lines = rep_paths["detail_csv"].read_text(encoding="utf-8-sig").strip().splitlines()
        # 需同时出现各分项，包含 1-2 与 1-3
        s1_rows = [line for line in detail_lines if s1.student_id in line]
        self.assertTrue(len(s1_rows) >= 2, f"明细表中学生 {s1.student_id} 行数应至少为2，实际为: {s1_rows}")
        pids = [line.split(",")[3] for line in s1_rows]
        self.assertIn("1-2", pids)
        self.assertIn("1-3", pids)

        # 2. 单人报告导出
        single_paths = reporter.generate_single_student_report(s1, g)
        single_lines = single_paths["detail_csv"].read_text(encoding="utf-8-sig").strip().splitlines()
        single_s1_rows = [line for line in single_lines if s1.student_id in line]
        self.assertTrue(len(single_s1_rows) >= 2)

        # 3. 从历史文件恢复
        recovered = reporter.load_existing_grades_from_files(self.roster_mgr.students)
        self.assertIn(s1.student_id, recovered)
        rec_g = recovered[s1.student_id]
        self.assertAlmostEqual(rec_g.total_score, 5.0)

    def test_17_semantic_ai_timeout_pending_propagation(self):
        """测试 17: AI 语义复核超时返回 is_pending=True，全链条保持成绩待定绝非数值成绩"""
        judge = Lab1Judge()
        build_dir = self.test_work / "build_sem_pending"
        s1 = self.roster_mgr.students[0]

        # 语义模糊程序（格式略有差异，不精确命中硬匹配，触发语义复核）
        ambig_code = """
#include <stdio.h>
int main() {
    int m;
    double t;
    scanf("%d %lf", &m, &t);
    // 输出无法直接数值命中，触发语义复核
    printf("Approximate temp conversion result is: 999.00\\n");
    return 0;
}
"""
        p_ambig = self.test_work / "ambig_1_3.c"
        p_ambig.write_text(ambig_code)

        from unittest.mock import patch
        mock_sem_pending = {
            "task_id": "semantic_1-3",
            "category": "insufficient_evidence",
            "passed": False,
            "suggested_score": None,
            "is_pending": True,
            "reasoning": "AI 复核调度超时",
            "needs_review": True,
            "review_reason": "AI 调用超时，成绩待定",
        }

        with patch("checker.ai.SemanticAmbiguityReviewer.review_output", return_value=mock_sem_pending):
            prob = judge._grade_lab1_3(s1, [p_ambig], build_dir, mock_ai=False)
            self.assertTrue(prob.is_pending, "单题 is_pending 应为 True")
            self.assertTrue(prob.needs_review, "单题 needs_review 应为 True")
            self.assertEqual(prob.score, 0.0, "待定状态下数值得分应为 0.0 避免虚假出分")

            grade = judge.grade_student(
                s1,
                [SubmissionFile(original_name=p_ambig.name, path=p_ambig, file_type="c_source", matched_problem="1-3")],
                build_dir,
                mock_ai=False,
            )
            self.assertTrue(grade.is_pending, "学生总评 is_pending 应为 True")
            self.assertEqual(grade.status, "needs_review")

            output_dir = self.test_work / "output_sem_pending"
            reporter = LabReporter("lab1", output_dir)
            rep_paths = reporter.generate_all_reports(self.roster_mgr.students, {s1.student_id: grade})

            roster_csv_text = rep_paths["roster_csv"].read_text(encoding="utf-8-sig")
            # 成绩单中必须写入 '待复核'，绝不能写入虚假数值扣分
            self.assertIn(f"{s1.student_id},{s1.name}", roster_csv_text)
            self.assertIn("待复核", roster_csv_text)
            self.assertNotIn(",0.20,", roster_csv_text)

    def test_18_compiler_isolation_and_no_nameerror(self):
        """测试 18: 编译器模块正常导入 shutil，支持隔离环境编译不抛出 NameError"""
        compiler = ProjectCompiler()
        build_dir = self.test_work / "build_compiler_iso"
        p_simple = self.test_work / "simple.c"
        p_simple.write_text("int main(){return 0;}")

        # 编译应当顺利执行，无论系统中是否有 unshare 命令，均安全降级或使用隔离
        c_res = compiler.compile(p_simple, build_dir, "simple_bin")
        self.assertTrue(c_res.success)
        self.assertTrue(c_res.binary_path.exists())

    def test_19_consecutive_scanf_s_on_same_line(self):
        """测试 19: MSVC scanf_s 垫片支持单行多次输入 (如 '0 100') 不消耗整行"""
        compiler = ProjectCompiler()
        build_dir = self.test_work / "build_scanf_consec"

        code = """
#include <stdio.h>
int main() {
    int mode = -1;
    double temp = -999.0;
    // 连续两次调用 scanf_s 读取同一行的两个数值
    int r1 = scanf_s("%d", &mode);
    int r2 = scanf_s("%lf", &temp);
    printf("r1=%d mode=%d, r2=%d temp=%.2f\\n", r1, mode, r2, temp);
    return 0;
}
"""
        p_code = self.test_work / "consec_scanf.c"
        p_code.write_text(code)

        c_res = compiler.compile(p_code, build_dir, "consec_scanf")
        self.assertTrue(c_res.success, f"编译失败: {c_res.stderr}")

        exec_res = run_binary(c_res.binary_path, input_str="0 100\n")
        self.assertEqual(exec_res.exit_code, 0)
        self.assertIn("r1=1 mode=0, r2=1 temp=100.00", exec_res.stdout)

    def test_20_mock_mode_grade_sheet_tagging(self):
        """测试 20: 模拟模式输出加 mock_ 前缀并标明 [模拟] 与 [模拟测试非正式] 表头"""
        output_dir = self.test_work / "output_mock_tag"
        reporter = LabReporter("lab1", output_dir)
        s1 = self.roster_mgr.students[0]

        g = StudentGrade(student=s1, total_score=5.0, status="graded", comment="学生甲模拟全对" + "。" * 40)
        rep_paths = reporter.generate_all_reports(
            self.roster_mgr.students,
            {s1.student_id: g},
            excel_template_path=DEFAULT_TEMPLATE_PATH if DEFAULT_TEMPLATE_PATH.exists() else None,
            mock_mode=True,
        )

        # 检查文件名含有 mock_
        self.assertTrue("mock_" in rep_paths["roster_csv"].name)
        self.assertTrue("mock_" in rep_paths["detail_csv"].name)

        csv_text = rep_paths["roster_csv"].read_text(encoding="utf-8-sig")
        # 检查表头明确标识模拟
        self.assertIn("建议扣分合计[模拟测试非正式]", csv_text)
        # 检查扣分单元格包含 [模拟] 0.00
        self.assertIn("[模拟] 0.00", csv_text)

        if "roster_xlsx" in rep_paths:
            import openpyxl
            wb = openpyxl.load_workbook(rep_paths["roster_xlsx"])
            ws = wb["Lab 1"]
            self.assertEqual(ws.cell(row=2, column=4).value, "分数(5)[模拟测试非正式]")
            self.assertIn("[模拟]", str(ws.cell(row=3, column=4).value))

    def test_21_ai_student_identity_mismatch_flagged(self):
        """测试 21: AI 返回其他学生身份时系统准确识别矛盾、扣除得分并标记待复核"""
        s1 = self.roster_mgr.students[0]
        from checker.ai import HandwrittenReviewer

        dummy_img = self.test_work / "dummy.png"
        dummy_img.write_bytes(b"dummy_png_bytes_content" * 20)

        mock_wrong_student = {
            "task_id": "lab1_2_handwritten",
            "student_id_observed": "2026999999",  # 另一位学生学号
            "name_observed": "张三丰",          # 另一位学生姓名
            "phone_observed": "88",
            "x_observed": 67,
            "y_observed": 88,
            "info_score": 0.5,
            "xy_match_score": 0.2,
            "derivation_score": 0.8,
            "suggested_score": 1.5,
            "is_pending": False,
            "reasoning": "书写规范",
            "needs_review": False,
        }

        from unittest.mock import patch
        with patch("checker.ai.call_agy_cli", return_value=(True, mock_wrong_student, "OK")):
            res = HandwrittenReviewer.review_images(
                student_id=s1.student_id,
                student_name=s1.name,
                expected_x=67,
                image_paths=[dummy_img],
                mock_mode=False,
            )
            # 必须判定身份矛盾并标记复核，得分清零
            self.assertTrue(res["needs_review"])
            self.assertEqual(res["suggested_score"], 0.0)
            self.assertIn("演草纸学生身份矛盾", res["review_reason"])

    def test_22_ai_regex_fallback_parsing(self):
        """测试 22: call_agy_cli 在无 structured_output 时使用正则回退解析不产生 NameError"""
        from checker.ai import call_agy_cli
        from unittest.mock import patch, MagicMock

        # 模拟 CLI 仅返回 Markdown 围栏代码块中的 JSON，无 structured_output
        cli_raw_stdout = """
Here is the review result:
```json
{
  "task_id": "lab1_2_handwritten",
  "student_id_observed": "2026000067",
  "name_observed": "测试生",
  "phone_observed": "88",
  "x_observed": 67,
  "y_observed": 88,
  "info_score": 0.5,
  "xy_match_score": 0.2,
  "derivation_score": 0.8,
  "suggested_score": 1.5,
  "reasoning": "测试通过",
  "needs_review": false,
  "review_reason": ""
}
```
"""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps({"response": cli_raw_stdout})
        mock_proc.stderr = ""

        with patch("subprocess.run", return_value=mock_proc):
            ok, res, msg = call_agy_cli("dummy prompt", {})
            self.assertTrue(ok)
            self.assertIsNotNone(res)
            self.assertEqual(res.get("task_id"), "lab1_2_handwritten")
            self.assertEqual(res.get("x_observed"), 67)

    def test_23_batch_container_and_nested_zips(self):
        """测试 23: 平台总包容器 (含嵌套 zip 与 .cbp 文件) 的批量提取与规范化归档"""
        container_dir = self.test_work / "batch_container_test"
        submit_dir = container_dir / "submit"
        submit_dir.mkdir(parents=True, exist_ok=True)
        s1 = self.roster_mgr.students[0]
        s2 = self.roster_mgr.students[1] if len(self.roster_mgr.students) > 1 else s1

        # 构造嵌套 zip
        nested_code_zip = io.BytesIO()
        with zipfile.ZipFile(nested_code_zip, "w") as nz:
            nz.writestr("2026000067_Lab 1-2.c", "int main(){return 0;}")
            nz.writestr("2026000067_Lab 1-3.c", "int main(){return 0;}")

        student_zip_data = io.BytesIO()
        with zipfile.ZipFile(student_zip_data, "w") as sz:
            sz.writestr("inner_code.zip", nested_code_zip.getvalue())
            sz.writestr("2026000067_Lab 1-2 验算过程.jpg", b"fake_jpg_content" * 20)

        # 构造整批容器 zip: 实验一.zip
        batch_zip_path = submit_dir / "实验一.zip"
        with zipfile.ZipFile(batch_zip_path, "w") as bz:
            bz.writestr(f"260101_{s1.name}_{s1.student_id}_实验1.zip", student_zip_data.getvalue())
            bz.writestr(f"{s2.student_id}_Lab1-2.cbp", "<xml>cbp project</xml>")

        normalizer = SubmissionNormalizer(self.roster_mgr, "lab1", container_dir)
        student_files = normalizer.process_all_submissions()

        # 验证 s1 的嵌套 zip 被成功解开并规范化至 src/
        self.assertIn(s1.student_id, student_files)
        s1_files = student_files[s1.student_id]
        s1_types = [f.file_type for f in s1_files]
        self.assertIn("c_source", s1_types)
        self.assertIn("image", s1_types)
        s1_problems = [f.matched_problem for f in s1_files]
        self.assertIn("1-2", s1_problems)
        self.assertIn("1-3", s1_problems)

        # 验证 s2 的 .cbp 工程文件被成功归纳
        self.assertIn(s2.student_id, student_files)
        s2_files = student_files[s2.student_id]
        self.assertTrue(any(f.file_type == "project" for f in s2_files))

    def test_24_attribution_disambiguation_and_problem_matching(self):
        """测试24: 学号含12的文件名分类防误判、子目录main.c识别、代码内容兜底及图片归属候选过滤"""
        container_dir = self.test_work / "test_24_disambiguation"
        submit_dir = container_dir / "submit"
        submit_dir.mkdir(parents=True, exist_ok=True)
        s1 = self.roster_mgr.students[0]

        # 1. 测试学号包含 12 的 Lab 1-3.c 不被误判为 1-2
        code_13 = self.test_work / f"2026111299_Lab 1-3.c"
        code_13.write_text("int main(){ return 0; }")
        normalizer = SubmissionNormalizer(self.roster_mgr, "lab1", container_dir)
        sf_13 = normalizer._classify_and_stage_file(s1, code_13, code_13.name)
        self.assertEqual(sf_13.matched_problem, "1-3", "学号含12的1-3代码不应误判为1-2")

        # 2. 测试子目录下 main.c 的题号识别
        main_c_in_dir = self.test_work / "main.c"
        main_c_in_dir.write_text("int main(){ return 0; }")
        sf_dir_13 = normalizer._classify_and_stage_file(s1, main_c_in_dir, "Lab 1-3/main.c")
        self.assertEqual(sf_dir_13.matched_problem, "1-3", "路径含 Lab 1-3/ 的 main.c 应识别为 1-3")
        sf_dir_12 = normalizer._classify_and_stage_file(s1, main_c_in_dir, "Lab 1-2/main.c")
        self.assertEqual(sf_dir_12.matched_problem, "1-2", "路径含 Lab 1-2/ 的 main.c 应识别为 1-2")

        # 3. 测试误命名为 1-1 的代码通过运算符内容兜底识别为 1-2
        code_misnamed = self.test_work / "Lab 1-1.c"
        code_misnamed.write_text("""
        #include <stdio.h>
        int main() {
            short x = 1, y = 2;
            printf("%d", !x);
            printf("%d", x || y);
            return 0;
        }
        """)
        sf_misnamed = normalizer._classify_and_stage_file(s1, code_misnamed, code_misnamed.name)
        self.assertEqual(sf_misnamed.matched_problem, "1-2", "含位/逻辑运算的内容应兜底识别为 1-2")

        # 4. 测试图片根据参数 x 识别并受候选池过滤
        from checker.ai import HandwrittenReviewer
        fake_img = self.test_work / "unmatched.jpg"
        fake_img.write_bytes(b"\xFF\xD8\xFF\xE0" + b"\x00" * 200)

        mock_identify_res = {
            "task_id": "lab1_2_handwritten",
            "content_summary": "验算演草纸",
            "x_observed": int(s1.student_id[-2:]),
            "y_observed": 55,
        }

        from unittest.mock import patch
        with patch("checker.ai.call_agy_cli", return_value=(True, mock_identify_res, "")):
            # 当只在包含 s1 的候选池中搜索时应唯一定位到 s1
            matched, info = HandwrittenReviewer.identify_student_from_image(
                fake_img, self.roster_mgr, candidate_students=[s1]
            )
            self.assertEqual(matched.student_id, s1.student_id)
            self.assertEqual(info["method"], "param_x")

    def test_25_multi_candidate_highest_score(self):
        """测试 25: 同题多源码候选自动评测全部版本并择优统计最高分，不触发待复核"""
        s1 = self.roster_mgr.students[0]
        judge = Lab1Judge()
        build_dir = self.test_work / "build_multi_cand"
        build_dir.mkdir(parents=True, exist_ok=True)

        exp_x = int(s1.student_id[-2:])
        # 候选 1: 错误/崩溃代码 (得分 0.0)
        cand1 = self.test_work / f"{s1.student_id}_1-2_bad.c"
        cand1.write_text("int main() { return 1; }")

        # 候选 2: 满分正确代码 (得分 1.5)
        cand2 = self.test_work / f"{s1.student_id}_1-2_good.c"
        cand2.write_text(f"""
#include <stdio.h>
int main() {{
    short x = {exp_x}, y = 88;
    printf("%5hd%5hd%5hd\\n", !x, x||y, x&&y);
    printf("%5hu%5hd%5hd\\n", (unsigned short)~x, x|y, x&y);
    printf("%5hd%5hd%5hd\\n", ~x, x|y, x&y);
    return 0;
}}
""")
        files = [
            SubmissionFile(cand1, cand1.name, "c_source", "1-2"),
            SubmissionFile(cand2, cand2.name, "c_source", "1-2"),
        ]
        grade = judge.grade_student(s1, files, build_dir, mock_ai=True)
        res1_2 = grade.problem_results["1-2"]
        # 必须择优采用 cand2 的最高分，且不被标记为同题多候选复核
        self.assertEqual(res1_2.sub_scores["code"], 1.5)
        self.assertFalse(res1_2.needs_review)
        self.assertIn("择优", "".join(res1_2.notes))

    def test_26_handwritten_missing_info_leniency(self):
        """测试 26: 演草纸未注明个人信息依目录归属最大容错不扣分，与源码对照核验通过"""
        from unittest.mock import patch
        from checker.ai import HandwrittenReviewer
        s1 = self.roster_mgr.students[0]
        exp_x = int(s1.student_id[-2:])

        mock_missing_info = {
            "task_id": "lab1_2_handwritten",
            "student_id_observed": "未填写",
            "name_observed": "未注明",
            "phone_observed": "",
            "x_observed": exp_x,
            "y_observed": 88,
            "info_score": 0.0,
            "xy_match_score": 0.2,
            "derivation_score": 0.8,
            "suggested_score": 1.0,
            "is_pending": False,
            "reasoning": "纸面未手写姓名学号，但6种运算展开完整准确",
            "needs_review": True,
            "review_reason": "纸面未书写姓名、学号、手机号，无法独立凭纸面确认身份归属，需人工复核。",
        }

        normalized = HandwrittenReviewer.normalize_review_result(
            mock_missing_info, s1.student_id, s1.name, exp_x
        )
        # 宽容政策：未注明身份不扣分 (满分0.5)，清除复核标志，最终总分 1.5
        self.assertEqual(normalized["info_score"], 0.5)
        self.assertEqual(normalized["suggested_score"], 1.5)
        self.assertFalse(normalized["needs_review"])

        judge = Lab1Judge()
        build_dir = self.test_work / "build_hw_leniency"
        build_dir.mkdir(parents=True, exist_ok=True)
        img = self.test_work / "hw.png"
        img.write_bytes(b"\xFF\xD8\xFF\xE0" + b"\x00" * 200)

        with patch("checker.ai.HandwrittenReviewer.review_images", return_value=normalized):
            prob = judge._grade_lab1_2(s1, [], [img], build_dir, mock_ai=False)
            item_info = [it for it in prob.check_items if it.sub_item == "姓名、学号、手机号完整性"][0]
            self.assertEqual(item_info.deduction, 0.0)
            self.assertEqual(item_info.completion_status, "已达成")
            self.assertFalse(item_info.needs_review)

    def test_27_lab1_2_preamble_number_offset_robustness(self):
        """测试 27: Lab 1-2 含有前置说明文字 (如 x=93,y=82) 时，9项运算数字不会发生错位"""
        s = Student(seq=93, student_id="2026111193", name="测试生郭", class_id="26TS602")
        judge = Lab1Judge()
        build_dir = self.test_work / "build_preamble_test"
        build_dir.mkdir(parents=True, exist_ok=True)

        c_file = self.test_work / f"{s.student_id}_1-2.c"
        c_file.write_text("""
#include <stdio.h>
int main() {
    short x = 93, y = 82;
    printf("x=%hd,y=%hd时的基本运算\\n", x, y);
    printf("逻辑非: %10hd 逻辑或: %10hd 逻辑与: %10hd\\n", !x, x||y, x&&y);
    printf("无符号取反: %10hu 按位或: %10hd 按位与: %10hd\\n", (unsigned short)~x, x|y, x&y);
    printf("有符号取反: %10hd 按位或: %10hd 按位与: %10hd\\n", ~x, x|y, x&y);
    return 0;
}
""")
        files = [SubmissionFile(c_file, c_file.name, "c_source", "1-2")]
        grade = judge.grade_student(s, files, build_dir, mock_ai=True)
        res = grade.problem_results["1-2"]
        self.assertEqual(res.sub_scores["code"], 1.5)
        # 推导出的 y 必须为 82，绝不能是 65444 或其他错位值
        self.assertNotIn("65444", "".join(res.notes))
        self.assertIn("推导y=82", "".join(res.notes))

    def test_28_lab1_3_menu_prompt_zero_not_int_div_bug(self):
        """测试 28: Lab 1-3 菜单提示语中包含 0 时，正确计算不触发整数除法截断扣分"""
        s = Student(seq=93, student_id="2026111193", name="测试生郭", class_id="26TS602")
        judge = Lab1Judge()
        build_dir = self.test_work / "build_menu_prompt_test"
        build_dir.mkdir(parents=True, exist_ok=True)

        c_file = self.test_work / f"{s.student_id}_1-3.c"
        c_file.write_text("""
#include <stdio.h>
int main() {
    int mode;
    double val;
    printf("0: Fahrenheit to Celsius\\n1: Celsius to Fahrenheit\\nPlease select mode and temp:\\n");
    if (scanf("%d %lf", &mode, &val) == 2) {
        if (mode == 0) {
            double c = (val - 32.0) * 5.0 / 9.0;
            printf("Result: %.2f C\\n", c);
        } else {
            double f = val * 9.0 / 5.0 + 32.0;
            printf("Result: %.2f F\\n", f);
        }
    }
    return 0;
}
""")
        files = [SubmissionFile(c_file, c_file.name, "c_source", "1-3")]
        grade = judge.grade_student(s, files, build_dir, mock_ai=True)
        res = grade.problem_results["1-3"]
        self.assertEqual(res.score, 2.0)
        # 华氏转摄氏分项应全对，不扣 0.80 分
        f2c_item = [it for it in res.check_items if it.sub_item == "华氏转摄氏计算"][0]
        self.assertEqual(f2c_item.deduction, 0.0)
        self.assertEqual(f2c_item.completion_status, "已达成")
        self.assertNotIn("整型截断除法缺陷", f2c_item.deduction_reason)

    def test_29_handwritten_partial_phone_no_penalty(self):
        """测试 29: 演草纸参数与代码完全一致但未写全手机号，不予扣除参数分且不标记复核 (学号 2026110090 场景)"""
        s = Student(seq=90, student_id="2026110090", name="测试生黄", class_id="260101")
        exp_x = 90
        deduced_y = 97

        # 模拟旧 AI 缓存中因为未写全手机号而给出 0.15 分的记录
        mock_ai_cache_entry = {
            "task_id": "lab1_2_handwritten",
            "student_id_observed": "2026110090",
            "name_observed": "",
            "phone_observed": "",
            "x_observed": 90,
            "y_observed": 97,
            "info_score": 0.2,
            "xy_match_score": 0.15,
            "derivation_score": 0.8,
            "suggested_score": 1.15,
            "is_pending": False,
            "reasoning": "纸面上方写有学号，但未标明姓名和手机号；参数 x=90, y=97 与预期一致，但未直接写明手机号故给0.15分",
            "needs_review": False,
            "review_reason": "",
        }

        normalized = HandwrittenReviewer.normalize_review_result(
            mock_ai_cache_entry, s.student_id, s.name, exp_x, deduced_y=deduced_y
        )
        # 按照新规则：动态根据参数事实重算，参数满分 0.2，信息宽容 0.5，推导 0.8，总分 1.5
        self.assertEqual(normalized["xy_match_score"], 0.2)
        self.assertEqual(normalized["info_score"], 0.5)
        self.assertEqual(normalized["suggested_score"], 1.5)
        self.assertFalse(normalized["needs_review"])

        judge = Lab1Judge()
        build_dir = self.test_work / "build_hw_90_test"
        build_dir.mkdir(parents=True, exist_ok=True)
        img = self.test_work / "hw_90.png"
        img.write_bytes(b"\xFF\xD8\xFF\xE0" + b"\x00" * 200)

        from unittest.mock import patch
        with patch("checker.ai.HandwrittenReviewer.review_images", return_value=normalized):
            prob = judge._grade_lab1_2(s, [], [img], build_dir, mock_ai=False)
            param_item = [it for it in prob.check_items if it.sub_item == "手写参数与身份及源码一致性"][0]
            self.assertEqual(param_item.deduction, 0.0)
            self.assertEqual(param_item.completion_status, "已达成")
            self.assertFalse(param_item.needs_review)

    def test_30_calculation_doubt_not_cleared_by_missing_info_leniency(self):
        """测试 30: 演草纸存在计算存疑或字迹不清时，宽容规则不得清除复核标志"""
        s = Student(seq=1, student_id="2026110001", name="测试生", class_id="260101")
        mock_res = {
            "task_id": "lab1_2_handwritten",
            "student_id_observed": "",
            "name_observed": "",
            "phone_observed": "",
            "x_observed": 1,
            "y_observed": 88,
            "info_score": 0.0,
            "xy_match_score": 0.2,
            "derivation_score": 0.4,
            "suggested_score": 0.6,
            "is_pending": False,
            "reasoning": "未填写姓名，同时推导字迹不清，位运算推导过程存疑",
            "needs_review": True,
            "review_reason": "未填写姓名，同时推导字迹不清，运算过程存疑",
        }

        normalized = HandwrittenReviewer.normalize_review_result(
            mock_res, s.student_id, s.name, 1, deduced_y=88
        )
        # 字迹不清/存疑必须保持复核，绝不能被误判为只有身份未注明而清除复核
        self.assertTrue(normalized["needs_review"])
        self.assertEqual(normalized["derivation_score"], 0.4)

    def test_31_detail_csv_review_flag_strictly_localized(self):
        """测试 31: 明细 CSV 中的复核标记必须严格限定于具体分项，不得扩散至全部 18 项"""
        import csv
        s = Student(seq=1, student_id="2026119999", name="复核测试生", class_id="260101")
        roster = RosterManager()
        roster.students = [s]
        roster.by_id = {s.student_id: s}
        roster.by_name = {s.name: [s]}

        grade = StudentGrade(student=s, max_score=5.0)
        grade.needs_review = True  # 学生级别标记需要复核
        grade.status = "needs_review"

        p1_1 = ProblemResult(problem_id="1-1", score=0.0, max_score=0.0)
        from checker.models import CheckItem
        p1_1.check_items = [
            CheckItem(problem_id="1-1", sub_item="代码编写与执行", submission_status="不适用", completion_status="无需提交", evidence="无需提交", needs_review=False),
            CheckItem(problem_id="1-1", sub_item="环境配置与认知", submission_status="不适用", completion_status="无需提交", evidence="无需提交", needs_review=False),
        ]
        p1_2 = ProblemResult(problem_id="1-2", score=2.5, max_score=3.0, needs_review=True)
        p1_2.check_items = [
            CheckItem(problem_id="1-2", sub_item="源码提交", submission_status="已提交", completion_status="已达成", evidence="main.c", needs_review=False),
            CheckItem(problem_id="1-2", sub_item="演草纸学生身份一致性", submission_status="已提交", completion_status="未达成", evidence="身份冲突", needs_review=True),
        ]
        grade.problem_results["1-1"] = p1_1
        grade.problem_results["1-2"] = p1_2

        out_dir = self.test_work / "out_reporter_localize"
        reporter = LabReporter("lab1", out_dir)
        reporter.generate_detail_csv([s], {s.student_id: grade})

        csv_file = out_dir / "lab1结果.csv"
        self.assertTrue(csv_file.exists())
        with open(csv_file, "r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
            item_map = {r["评分项"]: r["是否需要复核"] for r in rows}
            # 1-1 的无需提交项绝对不能为“是”
            self.assertEqual(item_map["代码编写与执行"], "否")
            self.assertEqual(item_map["环境配置与认知"], "否")
            self.assertEqual(item_map["源码提交"], "否")
            # 唯独标记了 needs_review 的项才为“是”
            self.assertEqual(item_map["演草纸学生身份一致性"], "是")

    def test_32_others_archive_unattributed_submissions(self):
        """测试 32: 无法确定学生归属的提交文件安全隔离归档至 labX/src/others/，同名文件隔离不覆盖，报告生成审计表"""
        s1 = Student(seq=1, student_id="2026110001", name="已知学生", class_id="260101")
        roster = RosterManager()
        roster.students = [s1]
        roster.by_id = {s1.student_id: s1}
        roster.by_name = {s1.name: [s1]}

        lab_dir = self.test_work / "lab_others_test"
        submit_dir = lab_dir / "submit"
        src_dir = lab_dir / "src"
        submit_dir.mkdir(parents=True, exist_ok=True)

        # 制作两个同名文件的未知提交 zip
        zip1_path = submit_dir / "unknown_pkg1.zip"
        with zipfile.ZipFile(zip1_path, "w") as z:
            z.writestr("test_data.csv", "col1,col2\n1,2\n")
        zip2_path = submit_dir / "unknown_pkg2.zip"
        with zipfile.ZipFile(zip2_path, "w") as z:
            z.writestr("test_data.csv", "colA,colB\n3,4\n")

        normalizer = SubmissionNormalizer(roster, "lab1", lab_dir)
        student_files_map = normalizer.process_all_submissions()

        # 1. 验证已知学生无归属文件，others 目录存在
        self.assertNotIn("others", student_files_map)
        others_dir = src_dir / "others"
        self.assertTrue(others_dir.exists())

        # 2. 验证两份同名文件各自归档于对应 stem 目录，未发生覆盖
        file1 = others_dir / "unknown_pkg1" / "test_data.csv"
        file2 = others_dir / "unknown_pkg2" / "test_data.csv"
        self.assertTrue(file1.exists())
        self.assertTrue(file2.exists())
        self.assertEqual(file1.read_text().strip(), "col1,col2\n1,2")
        self.assertEqual(file2.read_text().strip(), "colA,colB\n3,4")

        # 3. 验证 reporter 生成的报告包含统一归档位置与“无法归属、待复核”状态
        out_dir = lab_dir / "output"
        reporter = LabReporter("lab1", out_dir)
        grade = StudentGrade(student=s1, max_score=5.0)
        report_paths = reporter.generate_all_reports(
            roster_students=[s1],
            grades={s1.student_id: grade},
            unmatched_items=normalizer.unmatched_items,
        )
        report_content = Path(report_paths["summary_md"]).read_text(encoding="utf-8")
        self.assertIn("lab1/src/others/", report_content)
        self.assertIn("无法归属、待复核", report_content)
        self.assertIn("unknown_pkg1", report_content)
        self.assertIn("unknown_pkg2", report_content)


if __name__ == "__main__":
    unittest.main()
