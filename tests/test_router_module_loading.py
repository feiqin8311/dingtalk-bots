from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RouterModuleLoadingTest(unittest.TestCase):
    def test_each_branch_handler_comes_from_its_own_app(self):
        """cp_bot and pinxiang_bot both ship a top-level handler.py; the router must
        bind each class to the right file no matter which app touched sys.path first.
        Runs in a fresh interpreter so other tests' module caches cannot mask a clash."""
        script = textwrap.dedent(
            """
            import inspect, json, sys
            from types import ModuleType
            sys.modules.update({name: ModuleType(name) for name in ("handler", "config", "settings")})
            before = sys.path[:]
            from apps.logistics_bot import router
            from apps.track_notify import runner
            assert sys.path == before
            print(json.dumps({
                name: inspect.getfile(getattr(router, name))
                for name in ("ShipmentQueryHandler", "PinxiangBotHandler", "PdfSplitBotHandler",
                             "LclBotHandler", "FbaLabelBotHandler")
            }))
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=120
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        import json

        files = {k: Path(v).resolve().relative_to(ROOT).as_posix() for k, v in json.loads(proc.stdout.strip().splitlines()[-1]).items()}
        self.assertEqual(
            files,
            {
                "ShipmentQueryHandler": "apps/cp_bot/handler.py",
                "PinxiangBotHandler": "apps/pinxiang_bot/handler.py",
                "PdfSplitBotHandler": "apps/split_bot/Bot/handler.py",
                "LclBotHandler": "apps/lcl_bot/handlers.py",
                "FbaLabelBotHandler": "apps/fba_label_bot/handler.py",
            },
        )


if __name__ == "__main__":
    unittest.main()
