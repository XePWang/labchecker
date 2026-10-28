"""Confirmed Lab1 policy: compiled fixtures, handwriting facts, and score closure."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from checker.ai import HandwrittenReviewer
from checker.config import WORK_DIR
from checker.labs.lab1 import Lab1Judge
from checker.models import Student, SubmissionFile

class TestLab1ScoringPolicy(unittest.TestCase):
    def setUp(self):
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=WORK_DIR, prefix='lab1_policy_')
        self.root = Path(self.tmp.name)
        self.student = Student(1, '2026000067', '测试生甲', phone='13000000088')
        self.judge = Lab1Judge()
        self.reject = patch('checker.labs.lab1.SemanticAmbiguityReviewer.review_output', return_value={
            'passed': False, 'needs_review': False, 'is_pending': False, 'suggested_score': 0.0})
        self.reject.start()
        self.addCleanup(self.reject.stop)
        self.addCleanup(self.tmp.cleanup)

    def source(self, name, text):
        p = self.root/name
        p.write_text(text, encoding='utf-8')
        return p

    def temperature(self, fmt='%.2f', expression='(mode ? 9*t/5+32 : 5*(t-32)/9)', extra='', name='temp.c'):
        # t is double: integer literals in these formulas do NOT imply integer division.
        return self.source(name, '#include <stdio.h>\nint main(){int mode; double t;'
                           'if(scanf("%d%lf",&mode,&t)!=2)return 1;'
                           f'double r={expression};{extra}printf("result={fmt}\\n",r);return 0;}}')

    def temp_grade(self, sources):
        return self.judge._grade_lab1_3(self.student, sources, self.root/'build')

    def facts(self, **kwargs):
        res = dict(task_id='lab1_2_handwritten', info_score=.5, xy_match_score=.2,
                   derivation_score=.8, suggested_score=1.5, needs_review=False,
                   x_observed=67, y_observed=88, phone_observed='88',
                   name_observed='', student_id_observed='', clear_error_operators=[],
                   error_evidence=[], no_valid_derivation=False, derivation_uncertain=False)
        res.update(kwargs)
        return res

    def norm(self, res, y=88):
        return HandwrittenReviewer.normalize_review_result(res,self.student.student_id,self.student.name,67,y,expected_phone=self.student.phone)

    def logic_grade(self, source, facts=None):
        images=[]
        if facts is not None:
            image=self.source('hw.jpg', 'image placeholder'*30)
            images=[image]
        with patch('checker.labs.lab1.HandwrittenReviewer.review_images', return_value=facts or {}):
            return self.judge._grade_lab1_2(self.student,[source],images,self.root/'build',mock_ai=False,all_student_files=[])

    def assert_closed(self, prob):
        self.assertTrue(all(i.deduction is not None for i in prob.check_items))
        self.assertAlmostEqual(sum(i.deduction for i in prob.check_items),prob.max_score-prob.score,places=2)

    def test_real_float_arithmetic_and_two_decimals(self):
        p=self.temp_grade([self.temperature()])
        self.assertEqual(p.score,2)
        self.assertFalse(p.needs_review)
        self.assertTrue(all(c.max_score == .2 for c in p.test_results))
        self.assert_closed(p)

    def test_format_penalty_once_for_all_decimal_counts(self):
        for fmt in ['%.0f','%.1f','%.3f','%.6e']:
            with self.subTest(fmt=fmt):
                p=self.temp_grade([self.temperature(fmt=fmt)])
                # Zero decimal values can also fail the numerical tolerance; every failed case costs .20.
                numeric=sum(c.passed for c in p.test_results)*.2
                self.assertAlmostEqual(p.score,max(0,numeric-.2),places=2)
                self.assertEqual(next(i for i in p.check_items if i.sub_item=='输出精度与格式').deduction,.2)
                self.assert_closed(p)

    def test_tolerance_and_equal_case_deductions(self):
        for offset, score in [(.07,2),(.08,2),(.09,0)]:
            with self.subTest(offset=offset):
                p=self.temp_grade([self.temperature(extra=f'r+={offset};')])
                self.assertEqual(p.score,score)
                self.assert_closed(p)
        for expression in ['(mode ? 999 : 5*(t-32)/9)','(mode ? 9*t/5+32 : 999)']:
            p=self.temp_grade([self.temperature(expression=expression)])
            failed=sum(not c.passed for c in p.test_results)
            self.assertEqual(p.score,round(2-failed*.2,2))
            self.assert_closed(p)

    def test_actual_integer_division_not_menu_zero(self):
        p=self.temp_grade([self.temperature(expression='(mode ? 9*t/5+32 : (5/9)*(t-32))')])
        self.assertEqual(p.score,1.0) # 4 Celsius inputs and the F=32 zero-result case pass.
        self.assertTrue(any('截断' in n for n in p.notes))
        self.assert_closed(p)

    def test_output_echo_cannot_supply_result(self):
        src=self.source('echo.c','#include <stdio.h>\nint main(){int m;double t;scanf("%d%lf",&m,&t);'
                        'printf("echo=37.78; result=999.00\\n");}')
        p=self.temp_grade([src]);self.assertEqual(p.score,0);self.assert_closed(p)

    def test_candidate_selected_after_format_penalty(self):
        a=self.temperature(fmt='%.3f', name='a.c') # 1.80
        b=self.temperature(extra='if(mode==0 && t==100)r=999;',name='b.c') # 1.80
        c=self.temperature(name='c.c') # 2.00
        for sources in [[a,b,c],[c,b,a]]:
            p=self.temp_grade(sources)
            self.assertEqual(p.score,2)
            self.assertEqual(p.chosen_candidate['src_path'],str(c))
            self.assertEqual(len(p.candidate_evaluations),3)

    def test_lenient_handwriting_and_identity_conflict(self):
        res=self.norm(self.facts(derivation_score=.31,info_score=0,xy_match_score=0))
        self.assertEqual(res['suggested_score'],1.5)
        self.assertEqual(res['derivation_score'],.8)
        conflict=self.norm(self.facts(student_id_observed='2026999999'))
        self.assertEqual(conflict['info_score'],0)
        self.assertEqual(conflict['derivation_score'],.8)
        self.assertEqual(conflict['suggested_score'],1)
        self.assertTrue(conflict['needs_review'])

    def test_continuous_derivation_requires_evidence_and_clamps(self):
        for d,expected in [(.61,.61),(-1,0),(4,.8)]:
            res=self.norm(self.facts(derivation_score=d,clear_error_operators=['~'],error_evidence=['~67错误写作67']))
            self.assertEqual(res['derivation_score'],expected)
        no=self.norm(self.facts(no_valid_derivation=True))
        self.assertEqual(no['derivation_score'],0)
        self.assertEqual(no['suggested_score'],.7)

    def test_parameters_once_floor_and_idempotent_per_candidate(self):
        a=self.norm(self.facts(x_observed=66,y_observed=77))
        self.assertEqual(a['derivation_score'],.4)
        self.assertEqual(a['parameter_mismatches'],['x','y'])
        self.assertEqual(self.norm(a)['suggested_score'],1.1)
        # Reusing normalized visual facts for another code candidate must remove the previous candidate's penalty.
        b=self.norm(self.facts(),20)
        self.assertEqual(b['suggested_score'],1.3)
        self.assertEqual(self.norm(b,88)['suggested_score'],1.5)
        low=self.norm(self.facts(x_observed=66,y_observed=77,derivation_score=.1,
                                clear_error_operators=['~'],error_evidence=['明确错误']))
        self.assertEqual(low['derivation_score'],0)
        self.assertEqual(low['suggested_score'],.7)
        self.assertEqual(self.norm(self.facts(),None)['suggested_score'],1.5)

    def test_unclear_derivation_remains_pending(self):
        res=self.norm(self.facts(derivation_uncertain=True,needs_review=True,review_reason='字迹模糊'))
        self.assertTrue(res['is_pending']);self.assertIsNone(res['suggested_score'])

    def test_eight_terms_keep_eight_case_points(self):
        src=self.source('eight.c','#include <stdio.h>\nint main(){short x=67,y=88;'
            'printf("%d %d %d %u %d %d %d %d\\n",!x,x||y,x&&y,(unsigned short)~x,x|y,x&y,~x,x|y);}')
        p=self.logic_grade(src)
        self.assertEqual(p.sub_scores['code'],1.33)
        self.assertEqual(sum(c.passed for c in p.test_results),8)
        self.assert_closed(p)

    def test_identity_only_loses_half_and_deductions_close(self):
        src=self.source('logic.c','#include <stdio.h>\nint main(){short x=67,y=88;'
            'printf("%d %d %d %u %d %d %d %d %d\\n",!x,x||y,x&&y,(unsigned short)~x,x|y,x&y,~x,x|y,x&y);}')
        p=self.logic_grade(src,self.facts(student_id_observed='2026999999'))
        self.assertEqual(p.score,2.5);self.assertTrue(p.needs_review);self.assert_closed(p)
        for facts in [self.facts(x_observed=66,y_observed=77),
                      self.facts(derivation_score=.61,clear_error_operators=['~'],error_evidence=['错误']),
                      self.facts(no_valid_derivation=True,x_observed=66)]:
            p=self.logic_grade(src,facts);self.assert_closed(p)

    def test_compile_failure_does_not_invent_y_zero(self):
        p=self.logic_grade(self.source('bad.c','int main(){ broken; }'),self.facts())
        self.assertEqual(p.sub_scores['handwritten'],1.5)
        self.assertEqual(p.score,1.5);self.assert_closed(p)

    def test_phone_identity_and_registered_suffix(self):
        res=self.norm(self.facts(phone_observed='13000000077',y_observed=77),77)
        self.assertEqual(res['info_score'],0)
        self.assertEqual(res['parameter_mismatches'],['y'])
        self.assertEqual(res['suggested_score'],.8)
        self.assertTrue(res['needs_review'])

    def test_unreadable_or_missing_image_is_pending_not_full_credit(self):
        tiny=self.source('tiny.jpg','broken')
        for path in [tiny,self.root/'does_not_exist.jpg']:
            raw=HandwrittenReviewer.review_images(self.student.student_id,self.student.name,67,[path])
            res=self.norm(raw)
            self.assertTrue(res['is_pending'])
            self.assertIsNone(res['suggested_score'])

    def test_static_single_result_keeps_matching_case_credit(self):
        src=self.source('constant.c','#include <stdio.h>\nint main(){printf("result=0.00\\n");}')
        p=self.temp_grade([src])
        self.assertEqual(p.score,.2)
        self.assertEqual(sum(c.passed for c in p.test_results),1)
        self.assert_closed(p)
