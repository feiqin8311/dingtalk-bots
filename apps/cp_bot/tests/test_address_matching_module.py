import unittest

from address_matching import (
    AddressRecord,
    detect_country_mode_by_nation,
    normalize_fc_code,
    parse_address_record,
    score_address_candidate,
)


class AddressMatchingModuleTests(unittest.TestCase):
    def test_exports_address_matching_api_without_handler_dependency(self):
        self.assertEqual("UK", detect_country_mode_by_nation("英国"))
        self.assertEqual("BHX4", normalize_fc_code(" BHX4 "))

        source = AddressRecord(
            country_mode="UK",
            raw_text="OCR",
            fc_code="",
            street="PLOT 1 LYONS PARK 998 ROAD DISTRICIC SAYER DRIVE",
            street_no="1",
            city="WESTMIDLANDS COVENTRY",
            postal_code="CV5 9PF",
        )
        candidate = AddressRecord(
            country_mode="UK",
            raw_text="Excel",
            fc_code="BHX4",
            company="AMAZON COM SERVICES INC AMAZON EU SARL UK SAYER DR WEST MIDLANDS",
            street="PLOT 1 LYONS PARK SAYER DRIVE",
            street_no="1",
            city="COVENTRY",
            postal_code="CV5 9PF",
        )

        score = score_address_candidate("UK", source, candidate)

        self.assertTrue(score.hard_ok)
        self.assertNotIn("city", score.hard_reason)

    def test_uk_street_prefers_numbered_destination_over_shipfrom_noise(self):
        ocr = (
            "Amazon EU SARL(UK) Zhejiang-Hangzhou-310000 10Oyster Road Room2-3026 "
            "Jiangcun Business Center No.830 Wenwyixi Eastwood Road Xihu District "
            "NOTTINGHAM NG16 3UA England"
        )
        parsed = parse_address_record(ocr, "UK", fc_code="EMA3")
        self.assertEqual(parsed.postal_code, "NG16 3UA")
        self.assertIn("OYSTER", parsed.street)
        self.assertNotIn("EASTWOOD ROAD", parsed.street)
        self.assertNotIn("WENWYIXI", parsed.street)

        candidate = parse_address_record(
            "Amazon.com Services, Inc. / Amazon EU SARL (UK) / "
            "10 Oyster Rd / Eastwood / NOTTINGHAM / NG16 3UA England",
            "UK",
            fc_code="EMA3",
        )
        score = score_address_candidate("UK", parsed, candidate)
        self.assertTrue(score.hard_ok, score.hard_reason)
        self.assertGreaterEqual(score.score, 82.0)


if __name__ == "__main__":
    unittest.main()

