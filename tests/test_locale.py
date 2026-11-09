import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import desktop_locale


class LocaleTests(unittest.TestCase):
    def test_display_language_is_separate_from_region(self):
        with patch.dict(os.environ, {'FM27_UI_LANGUAGE': 'en-GB'}):
            self.assertEqual(desktop_locale.system_language()['language'], 'en')
        with patch.dict(os.environ, {'FM27_UI_LANGUAGE': 'zh-CN'}):
            self.assertEqual(desktop_locale.system_language()['language'], 'zh-CN')

    def test_unsupported_display_language_falls_back_to_english(self):
        for language in ['fr-FR', 'de_DE', '', 'en-US']:
            self.assertEqual(desktop_locale.normalize_language(language), 'en')
        self.assertEqual(desktop_locale.normalize_language('zh_Hans_CN'), 'zh-CN')

    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed for UI regression checks')
    def test_presentation_does_not_translate_native_inputs_or_names(self):
        subprocess.run(['node', str(ROOT / 'tests' / 'test_i18n.cjs')],
                       check=True, cwd=ROOT, capture_output=True, text=True)
