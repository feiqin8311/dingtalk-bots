import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter

SKILL_DIR = Path('skills/pdf-zip-splitter')
SCRIPT_PATH = SKILL_DIR / 'scripts' / 'pdf_split_zip.py'


def _python_with_yaml() -> str:
    for candidate in [sys.executable, '/usr/bin/python3', 'python3', 'python']:
        result = subprocess.run(
            [candidate, '-c', 'import yaml'],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return candidate
    return sys.executable


class OpenClawSkillTests(unittest.TestCase):
    def test_skill_files_exist(self):
        self.assertTrue((SKILL_DIR / 'SKILL.md').exists())
        self.assertTrue((SKILL_DIR / 'agents' / 'openai.yaml').exists())
        self.assertTrue(SCRIPT_PATH.exists())

    def test_skill_script_generates_zip(self):
        spec = importlib.util.spec_from_file_location('pdf_split_zip_skill', SCRIPT_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_pdf = tmp_path / 'source.pdf'
            rules_path = tmp_path / 'rules.txt'
            output_dir = tmp_path / 'out'
            self._make_pdf(source_pdf, 6)
            rules_path.write_text(
                '宁波德韵工具有限公司\t900913\t1-2\n余姚嘉城工具工贸有限公司\t911212\t5-6\n',
                encoding='utf-8',
            )

            zip_path = module.run(source_pdf, rules_path, output_dir)

            self.assertTrue(zip_path.exists())
            self.assertEqual(zip_path.suffix, '.zip')
            self.assertEqual(len(list(output_dir.rglob('*.pdf'))), 2)

    def test_skill_validates(self):
        validate_script = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'skills/.system/skill-creator/scripts/quick_validate.py'
        if not validate_script.exists():
            validate_script = Path('/home/yida/.codex/skills/.system/skill-creator/scripts/quick_validate.py')
        result = subprocess.run(
            [
                _python_with_yaml(),
                str(validate_script),
                str(SKILL_DIR),
            ],
            cwd='.',
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def _make_pdf(self, path: Path, pages: int) -> None:
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=72, height=72)
        with path.open('wb') as fh:
            writer.write(fh)


if __name__ == '__main__':
    unittest.main()
