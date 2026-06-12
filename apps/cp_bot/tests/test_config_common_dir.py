import importlib.util
import os
import types
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch


class ConfigCommonDirTests(unittest.TestCase):
    def test_project_env_does_not_load_external_common_env(self):
        repo = Path(tempfile.mkdtemp())
        common = Path(tempfile.mkdtemp())
        config_path = repo / "config.py"
        source = (Path(__file__).resolve().parents[1] / "config.py").read_text(encoding="utf-8")
        config_path.write_text(source, encoding="utf-8")
        (repo / ".env").write_text(
            textwrap.dedent(
                f"""
                COMMON_DIR={common}
                LINGXING_API_KEY=project_key
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        (common / ".env").write_text(
            textwrap.dedent(
                """
                LINGXING_API_KEY=common_key
                LINGXING_API_SECRET=common_secret
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        old_env = dict(os.environ)
        try:
            os.environ.clear()
            spec = importlib.util.spec_from_file_location("isolated_config_for_test", config_path)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            fake_dotenv = types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None)
            with patch.dict(
                "sys.modules",
                {"isolated_config_for_test": module, "dotenv": fake_dotenv},
            ):
                spec.loader.exec_module(module)

            self.assertEqual(module.LINGXING_API_KEY, "project_key")
            self.assertEqual(module.LINGXING_API_SECRET, "")
            self.assertFalse(hasattr(module, "COMMON_ENV_PATH"))
        finally:
            os.environ.clear()
            os.environ.update(old_env)


if __name__ == "__main__":
    unittest.main()
