from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AmazonTemplatesPresentTest(unittest.TestCase):
    def test_lcl_templates_resolve_to_shared_copies(self):
        from apps.lcl_bot import config

        for path in (config.AMAZON_TEMPLATE_SOURCE_FILE, config.AMAZON_TEMPLATE_SOURCE_FILE_V2):
            self.assertTrue(Path(path).is_file(), path)
            self.assertEqual(Path(path).parent, ROOT / "shared" / "amazon_templates")


if __name__ == "__main__":
    unittest.main()
