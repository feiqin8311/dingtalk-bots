import unittest

from address_matching import AddressRecord, score_address_candidate


class AddressMatchingTests(unittest.TestCase):
    def test_uk_city_match_allows_region_prefix_from_ocr(self):
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
