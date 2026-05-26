import unittest

from address_matching import (
    AddressRecord,
    detect_country_mode_by_nation,
    normalize_fc_code,
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


if __name__ == "__main__":
    unittest.main()
