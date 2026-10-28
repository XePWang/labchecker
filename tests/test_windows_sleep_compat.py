"""Execute Windows delay compatibility without altering source behavior."""
import tempfile
import time
import unittest
from pathlib import Path

from checker.compiler import ProjectCompiler
from checker.config import WORK_DIR
from checker.sandbox import run_binary


class WindowsSleepCompatibility(unittest.TestCase):
    def test_c_and_cpp_delay_and_result_are_preserved(self):
        with tempfile.TemporaryDirectory(dir=WORK_DIR, prefix='sleep_compat_') as temp:
            root = Path(temp)
            for extension in ['c', 'cpp']:
                with self.subTest(language=extension):
                    source = root / ('delay.' + extension)
                    original = '#include <windows.h>\n#include <stdio.h>\nint main(){Sleep(80);printf("%.2f",5.0*(100-32)/9);return 0;}\n'
                    source.write_text(original)
                    compiled = ProjectCompiler().compile(source, root / extension, 'delay')
                    self.assertTrue(compiled.success, compiled.stderr)
                    self.assertTrue(compiled.compat_applied)
                    self.assertTrue(any('nanosleep' in r for r in compiled.compat_reasons))
                    before = time.monotonic()
                    execution = run_binary(compiled.binary_path, timeout=2)
                    self.assertGreaterEqual(time.monotonic() - before, 0.065)
                    self.assertEqual(execution.stdout.strip(), '37.78')
                    self.assertEqual(source.read_text(), original)
