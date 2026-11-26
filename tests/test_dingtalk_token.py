from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from shared import dingtalk_token


class DingTalkTokenCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        dingtalk_token.clear_cache()

    def tearDown(self) -> None:
        dingtalk_token.clear_cache()

    def test_reuses_token_until_refresh_margin_then_refetches(self):
        responses = iter([{"accessToken": "t1", "expireIn": 7200}, {"accessToken": "t2", "expireIn": 7200}])
        with patch.object(dingtalk_token, "_http_json", side_effect=lambda _req: next(responses)) as http:
            self.assertEqual(dingtalk_token.get_access_token("k", "s"), "t1")
            self.assertEqual(dingtalk_token.get_access_token("k", "s"), "t1")
            self.assertEqual(http.call_count, 1)
            with patch.object(dingtalk_token.time, "time", return_value=time.time() + 7200 - 299):
                self.assertEqual(dingtalk_token.get_access_token("k", "s"), "t2")
            self.assertEqual(http.call_count, 2)

    def test_force_refresh_and_separate_keys(self):
        counter = iter(range(100))
        fake = lambda _req: {"accessToken": f"t{next(counter)}", "access_token": None}
        with patch.object(dingtalk_token, "_http_json", side_effect=fake):
            first = dingtalk_token.get_access_token("k", "s")
            self.assertNotEqual(dingtalk_token.get_access_token("k", "s", force_refresh=True), first)
            self.assertNotEqual(dingtalk_token.get_access_token("other", "s"), first)

    def test_api_and_corp_tokens_cached_separately_and_corp_errors_raise(self):
        def fake(req):
            if "gettoken" in req.full_url:
                return {"errcode": 0, "access_token": "corp", "expires_in": 7200}
            return {"accessToken": "api", "expireIn": 7200}

        with patch.object(dingtalk_token, "_http_json", side_effect=fake):
            self.assertEqual(dingtalk_token.get_access_token("k", "s"), "api")
            self.assertEqual(dingtalk_token.get_corp_access_token("k", "s"), "corp")

        dingtalk_token.clear_cache()
        with patch.object(dingtalk_token, "_http_json", return_value={"errcode": 40089, "errmsg": "bad"}):
            with self.assertRaisesRegex(RuntimeError, "bad"):
                dingtalk_token.get_corp_access_token("k", "s")

    def test_concurrent_callers_trigger_one_fetch(self):
        calls = 0

        def slow(_req):
            nonlocal calls
            calls += 1
            time.sleep(0.05)
            return {"accessToken": "t", "expireIn": 7200}

        with patch.object(dingtalk_token, "_http_json", side_effect=slow):
            threads = [threading.Thread(target=dingtalk_token.get_access_token, args=("k", "s")) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(calls, 1)

    def test_missing_credentials_raise_before_any_request(self):
        with patch.object(dingtalk_token, "_http_json") as http:
            with self.assertRaises(RuntimeError):
                dingtalk_token.get_access_token("", "s")
            http.assert_not_called()


if __name__ == "__main__":
    unittest.main()
