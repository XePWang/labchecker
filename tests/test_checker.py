"""
tests/test_checker.py
判题机全覆盖单元与集成测试套件
"""
import io
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
from checker.models import Student, StudentGrade, SubmissionFile
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
        cls.roster_mgr = RosterManager(DEFAULT_ROSTER_PATH)

    @classmethod
    def tearDownClass(cls):
        # 清理测试运行缓存
        if cls.test_work.exists():
            shutil.rmtree(cls.test_work, ignore_errors=True)

    def test_01_roster_parsing(self):
        """测试 1: 点名册解析与学生身份匹配"""
        self.assertGreater(len(self.roster_mgr.students), 80)
        s1 = self.roster_mgr.students[0]
        self.assertEqual(s1.student_id, "2026110067")
        self.assertEqual(s1.name, "梁宜")

        # 匹配测试
        matched, cands, reason = self.roster_mgr.match_student_from_text("2612901_梁宜_2026110067_实验1.zip")
        self.assertIsNotNone(matched)
        self.assertEqual(matched.student_id, "2026110067")

        # 模糊空格/下划线测试
        matched2, _, _ = self.roster_mgr.match_student_from_text("2026110090  黄明杨  Lab 1-2.c")
        self.assertIsNotNone(matched2)
        self.assertEqual(matched2.student_id, "2026110090")

    def test_02_safe_unpack_and_zipslip_protection(self):
        """测试 2: Zip Slip 恶意路径穿越防御与正常解压"""
        malicious_zip = self.test_work / "malicious.zip"
        # 构造包含 ../../etc/evil.txt 路径的恶意 zip
        with zipfile.ZipFile(malicious_zip, "w") as zf:
            zf.writestr("../../evil.txt", "attack payload")
            zf.writestr("normal.c", "int main(){return 0;}")

        dest = self.test_work / "unsafe_extract"
        extractor = SafeExtractor(self.test_work / "scratch")
        ok, msg, files = extractor.extract_archive(malicious_zip, dest)
        # 必须拒绝并拦截恶意穿越
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

        # 包含典型 Windows 专有库与语法
        win_code = """
#include <stdio.h>
#include <windows.h>
#include <conio.h>

int main() {
    int val = 0;
    // 使用 MSVC 特有的 scanf_s
    scanf_s("%d", &val);
    printf("Received: %d\\n", val * 2);
    fflush(stdin);
    system("pause");
    return 0;
}
"""
        src_path = self.test_work / "win_prog.c"
        src_path.write_text(win_code, encoding="gbk")  # 以 GBK 编码保存

        c_res = compiler.compile(src_path, build_dir, "win_compat_test")
        self.assertTrue(c_res.success)
        self.assertTrue(c_res.compat_applied)
        self.assertGreater(len(c_res.compat_reasons), 0)

        # 运行生成的二进制验证逻辑未被篡改
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
        compiler = ProjectCompiler()
        build_dir = self.test_work / "build_lab1_test"

        student = Student(seq=1, student_id="2026110067", name="梁宜")  # x 应为 67
        # 构造正确的 1-2 源码
        correct_1_2 = """
#include <stdio.h>
int main(void) {
    short x = 67, y = 88;
    printf("%5hd%5hd%5hd\\n", !x, x||y, x&&y);
    printf("%5hu%5hd%5hd\\n", ~x, x|y, x&y);
    printf("%5hd%5hd%5hd\\n \\n", ~x, x|y, x&y);
    return 0;
}
"""
        p_1_2 = self.test_work / "2026110067_Lab 1-2.c"
        p_1_2.write_text(correct_1_2)

        # 构造带有中文提示语但计算正确的 1-3 源码
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
        p_1_3 = self.test_work / "2026110067_Lab 1-3.c"
        p_1_3.write_text(correct_1_3)

        files = [
            SubmissionFile(p_1_2, p_1_2.name, "c_source", "1-2"),
            SubmissionFile(p_1_3, p_1_3.name, "c_source", "1-3"),
        ]

        grade = judge.grade_student(student, files, build_dir, mock_ai=True)
        # 正确但含中文提示语的应当全部通过
        self.assertEqual(grade.problem_results["1-2"].sub_scores["code"], 1.5)
        self.assertEqual(grade.problem_results["1-3"].status, "passed")
        self.assertEqual(grade.problem_results["1-3"].score, 2.0)
        self.assertGreaterEqual(len(grade.comment), 50)

        # 对比：错误逻辑（整型截断除法 5/9）
        wrong_int_div_1_3 = """
#include <stdio.h>
int main() {
    int button;
    float temp;
    if (scanf("%d %f", &button, &temp) == 2) {
        if (button == 0) {
            // 典型错误：5/9 为 0
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

        grade_wrong = judge.grade_student(student, files_wrong, build_dir, mock_ai=True)
        # 整型除法导致华氏转摄氏全部得 0，绝不能满分
        self.assertLess(grade_wrong.problem_results["1-3"].score, 2.0)
        # 且应当检测到整型截断缺陷
        self.assertTrue(any("截断" in n for n in grade_wrong.problem_results["1-3"].notes))

    def test_06_loose_vs_strict_lab2(self):
        """测试 6: Lab 2 宽松问候语匹配、字母金字塔对称性与笔误容错"""
        judge = Lab2Judge()
        build_dir = self.test_work / "build_lab2_test"
        student = Student(seq=2, student_id="2026110090", name="黄明杨")

        # 2-1 问候语：中文表达 "早上好" / "下午好" 能够通过
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
        p_2_1 = self.test_work / "2026110090_Lab 2-1.c"
        p_2_1.write_text(chinese_greeting_2_1)

        # 2-2 字母金字塔：正确实现
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
        p_2_2 = self.test_work / "2026110090_Lab 2-2.c"
        p_2_2.write_text(pyramid_2_2)

        files = [
            SubmissionFile(p_2_1, p_2_1.name, "c_source", "2-1"),
            SubmissionFile(p_2_2, p_2_2.name, "c_source", "2-2"),
        ]

        grade = judge.grade_student(student, files, build_dir, mock_ai=True)
        self.assertEqual(grade.problem_results["2-1"].score, 2.0)
        self.assertEqual(grade.problem_results["2-2"].score, 3.0)
        self.assertEqual(grade.total_score, 5.0)

        # 对比：金字塔逻辑混乱（单向打印未做对称镜像）
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

        grade_bad = judge.grade_student(student, files_bad, build_dir, mock_ai=True)
        # 单向未镜像无法通过对称序列校验
        self.assertLess(grade_bad.problem_results["2-2"].score, 3.0)

    def test_07_ai_review_fallback_on_failure(self):
        """测试 7: AI 调用失败/超时时不误判为 0 分，保留复核标记"""
        # 测试在非 mock 模式下给出一个不存在的图片路径或调用错误
        res = HandwrittenReviewer.review_images(
            student_id="2026110067",
            student_name="梁宜",
            expected_x=67,
            image_paths=[self.test_work / "non_existent.png"],
            mock_mode=False,
        )
        self.assertEqual(res["suggested_score"], 0.0)
        self.assertIn("缺失", res["reasoning"])

    def test_08_reporter_outputs_and_roster_alignment(self):
        """测试 8: 三份报表导出与点名册全量对齐（不少于50字评语）"""
        output_dir = self.test_work / "output"
        reporter = LabReporter("lab1", output_dir)

        # 模拟两位学生成绩，其余为未提交
        s1 = self.roster_mgr.students[0]
        s2 = self.roster_mgr.students[1]

        g1 = StudentGrade(student=s1, total_score=5.0, status="graded")
        g1.comment = "梁宜同学你好！本次实验1针对二进制逻辑与C语言基础语法的掌握情况评测完成。按要求将学号末两位对齐参数x，位运算与逻辑运算执行完全正确，演草纸推导规范清晰；Lab 1-3温度转换程序编写规范，成功通过全部双向精度与边界用例测试，表现优秀！望继续保持！"

        g2 = StudentGrade(student=s2, total_score=3.5, status="graded", needs_review=True, review_reasons=["演草纸字迹待人工核查"])
        g2.comment = "黄明杨同学你好！本次实验1在Lab 1-2中完成了基础位运算代码，但部分输出结果与推导细节存在偏差，演草纸步骤需更加完备；Lab 1-3温度转换程序编写规范，成功通过测试。希望在后续实验中继续加强代码调试与边界测试意识，扎实掌握基础。"

        grades = {s1.student_id: g1, s2.student_id: g2}

        res_files = reporter.generate_all_reports(
            self.roster_mgr.students,
            grades,
            excel_template_path=DEFAULT_TEMPLATE_PATH,
        )

        detail_csv = res_files["detail_csv"]
        summary_md = res_files["summary_md"]
        roster_csv = res_files["roster_csv"]

        self.assertTrue(detail_csv.exists())
        self.assertTrue(summary_md.exists())
        self.assertTrue(roster_csv.exists())

        # 检查成绩单行数是否与点名册完全一致 (表头 1 行 + 92 名学生 = 93 行)
        lines = roster_csv.read_text(encoding="utf-8-sig").splitlines()
        self.assertEqual(len(lines), len(self.roster_mgr.students) + 1)

        # 检查评语长度 >= 50
        self.assertGreaterEqual(len(g1.comment), 50)
        self.assertGreaterEqual(len(g2.comment), 50)

        # 检查总结报告中包含复核清单
        md_text = summary_md.read_text(encoding="utf-8")
        self.assertIn("待人工复核清单", md_text)
        self.assertIn("2026110090", md_text)


if __name__ == "__main__":
    unittest.main()
