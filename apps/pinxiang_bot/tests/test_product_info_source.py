#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from product_info_source import _is_smb_path, _parse_smb_path  # noqa: E402

SHARE_FILE = "smb://192.168.0.45/供应链管理/2 物流发货管理/17.单证数据表维护/产品信息单证专用.xlsx"
UNC_FILE = r"\\192.168.0.45\供应链管理\2 物流发货管理\17.单证数据表维护\产品信息单证专用.xlsx"


class ProductInfoPathTests(unittest.TestCase):
    def test_smb_url_parses_to_share_and_file(self):
        self.assertTrue(_is_smb_path(SHARE_FILE))
        host, share, remote = _parse_smb_path(SHARE_FILE)
        self.assertEqual(host, "192.168.0.45")
        self.assertEqual(share, "供应链管理")
        self.assertEqual(remote, "/2 物流发货管理/17.单证数据表维护/产品信息单证专用.xlsx")

    def test_unc_path_parses_same_as_smb_url(self):
        self.assertTrue(_is_smb_path(UNC_FILE))
        self.assertEqual(_parse_smb_path(UNC_FILE), _parse_smb_path(SHARE_FILE))


if __name__ == "__main__":
    unittest.main()
