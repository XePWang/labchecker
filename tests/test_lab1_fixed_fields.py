import unittest
from checker.labs.lab1 import Lab1Judge


class GuideFixedWidthFields(unittest.TestCase):
    def test_extra_printf_field_does_not_merge_with_the_required_third_result(self):
        for extra in [123456, -12345, 9]:
            output=f'{0:5d}{1:5d}{1:5d}{extra:5d}\n{65451:5d}{92:5d}{0:5d}\n{-85:5d}{92:5d}{0:5d}\n'
            values,y,checks=Lab1Judge._extract_lab1_2_nine_terms(output,84,8,field_width=5)
            self.assertEqual(values,[0,1,1,65451,92,0,-85,92,0])
            self.assertTrue(all(check[1] for check in checks))

    def test_without_source_field_evidence_a_joined_number_is_not_split(self):
        output='    0    1    1123456\n65451   92    0\n  -85   92    0\n'
        _,_,checks=Lab1Judge._extract_lab1_2_nine_terms(output,84,8)
        self.assertFalse(all(check[1] for check in checks))
