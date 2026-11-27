from __future__ import annotations

import json
from unittest.mock import patch

from shared.lingxing import format_params, generate_sign
from apps.cp_bot.api.lingxing_client import SignBase


def test_shared_lingxing_sign_matches_cp_client_contract():
    params = {"z": "", "b": ["二", "一"], "a": 1}
    assert format_params(params) == 'a=1&b=["二","一"]'
    key = "1234567890123456"
    assert generate_sign(key, params) == "YKt8Nx+kUQ0QKsC3my0UqZ8PmcOWvk2Y7kxL6DPLeRoFAYegzeWphyy6sJGrc+VT"
    with patch("apps.cp_bot.api.lingxing_client.json_dumps", side_effect=lambda value: json.dumps(value, sort_keys=True).encode()):
        assert SignBase.generate_sign(key, params) == "vcagdhDXQZ41cwwUz1TAXXYaGRknAV6PXvHOzAb/4CsFAYegzeWphyy6sJGrc+VT"
