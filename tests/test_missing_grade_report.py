"""Missing submissions must use the same finalized comment in every format."""
import tempfile
import unittest
from pathlib import Path
import openpyxl
from checker.config import WORK_DIR
from checker.models import Student
from checker.labs.lab1 import Lab1Judge
from checker.reporter import LabReporter


class MissingGradeReportConsistency(unittest.TestCase):
    def test_excel_keeps_finalized_missing_submission_comment(self):
        with tempfile.TemporaryDirectory(dir=WORK_DIR,prefix='missing_report_') as temp:
            root=Path(temp);template=root/'template.xlsx'
            book=openpyxl.Workbook();book.active.title='Lab 1';book.save(template)
            student=Student(1,'2026999910','测试未提交')
            grade=Lab1Judge().grade_student(student,[],root/'build')
            self.assertEqual(grade.status,'missing')
            paths=LabReporter('lab1',root/'output').generate_all_reports([student],{student.student_id:grade},excel_template_path=template)
            result=openpyxl.load_workbook(paths['roster_xlsx'])['Lab 1']
            self.assertEqual(result['D3'].value,grade.total_score)
            self.assertEqual(result['E3'].value,grade.comment)
