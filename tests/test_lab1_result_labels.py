"""Result extraction regressions discovered during the full-class review."""
import unittest
from checker.labs.lab1 import Lab1Judge

class TemperatureLabels(unittest.TestCase):
    def test_chinese_mode_menu_cannot_shadow_result_or_units(self):
        text='输入两个数，选择华氏度转摄氏度为0，摄氏度转华氏度为1：您要的结果是:37.78℃'
        self.assertEqual(Lab1Judge._temperature_result(text,'Centigrade'),(37.78,'37.78'))
        self.assertEqual(Lab1Judge._temperature_result('华氏度转摄氏度为0：37.78','Centigrade'),(37.78,'37.78'))
    def test_guide_fahr_label_selects_result_instead_of_input_echo(self):
        self.assertEqual(Lab1Judge._temperature_result('fahr=77.00,celsius=25.00','Fahrenheit'),(77.0,'77.00'))
        self.assertEqual(Lab1Judge._temperature_result('celsius=37.78,fahr=100.00','Centigrade'),(37.78,'37.78'))
    def test_compound_chinese_markers_and_result_units(self):
        for label in ['摄氏度为：','摄氏温度是:','结果是：','result is:']:
            self.assertEqual(Lab1Judge._temperature_result(label+'37.78','Centigrade'),(37.78,'37.78'))
    def test_echo_does_not_override_a_wrong_explicit_result(self):
        self.assertEqual(Lab1Judge._temperature_result('result=999.00;input=37.78','Centigrade'),(999.0,'999.00'))

    def test_compiled_programs_with_chinese_menus_and_guide_pair_labels(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from checker.config import WORK_DIR
        from checker.models import Student
        with tempfile.TemporaryDirectory(dir=WORK_DIR,prefix='result_labels_') as temp:
            root=Path(temp);j=Lab1Judge();student=Student(1,'2026999901','结果提取测试')
            outputs=[r'printf("华氏度转摄氏度为0，摄氏度转华氏度为1，您要的结果是:%.2f",result);',
                     r'printf("fahr=%.2f,celsius=%.2f",mode?result:t,mode?t:result);']
            for index,output in enumerate(outputs):
                source=root/f'labels_{index}.c'
                source.write_text('#include <stdio.h>\nint main(){int mode;double t;scanf("%d%lf",&mode,&t);double result=mode?9*t/5+32:5*(t-32)/9;'+output+'}')
                with patch('checker.labs.lab1.SemanticAmbiguityReviewer.review_output',return_value={'passed':False,'is_pending':False,'needs_review':False}):
                    result=j._grade_lab1_3(student,[source],root/'build')
                self.assertEqual(result.score,2)
                self.assertTrue(all(c.passed for c in result.test_results))
