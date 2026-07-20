import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import real_estate_search  # noqa: E402


class ApartmentSearchSuggestionTest(unittest.TestCase):
    def test_gyeonggi_source_uses_eup_myeon_dong_as_legal_dong(self):
        self.assertEqual(
            real_estate_search._row_legal_dong({"읍면동": "하안동", "지번": "682"}),
            "하안동",
        )
        self.assertEqual(
            real_estate_search._row_legal_dong({"읍면동": "가평읍", "지번": "읍내리 270"}),
            "읍내리",
        )

    def test_generic_representative_name_uses_numbered_official_name(self):
        row = {
            "대표단지명": "주공아파트",
            "단지명_공시가격": "주공12",
            "단지명_건축물대장": "주공아파트",
        }

        self.assertEqual(real_estate_search._apartment_display_name(row), "주공12")

    def test_village_family_uses_numbered_official_name(self):
        row = {
            "대표단지명": "한솔마을",
            "단지명_공시가격": "한솔마을(4단지)(주공)",
            "단지명_도로명주소": "한솔마을",
        }

        self.assertEqual(
            real_estate_search._apartment_display_name(row),
            "한솔마을(4단지)(주공)",
        )

    def test_numbered_query_does_not_match_part_of_a_building_number(self):
        self.assertFalse(
            real_estate_search._is_ordered_subsequence("한솔마을4", "한솔마을204동"),
        )

    def test_hansol_fourth_complex_is_not_duplicated_by_local_alias(self):
        suggestions = real_estate_search.suggest_apartments("한솔마을 4")

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["name"], "한솔마을 4단지 주공")
        self.assertEqual(suggestions[0]["legalDong"], "정자동")
        self.assertEqual(suggestions[0]["jibun"], "102")
        self.assertEqual(suggestions[0]["households"], 1651)

    def test_haan_jugong_search_returns_numbered_complexes(self):
        suggestions = real_estate_search.suggest_apartments("하안주공")
        names = [row["name"] for row in suggestions]

        self.assertGreaterEqual(len(suggestions), 11)
        self.assertIn("주공1", names)
        self.assertIn("주공9", names)
        self.assertIn("주공11", names)
        self.assertIn("하안주공13단지", names)
        self.assertTrue(all(row["legalDong"] == "하안동" for row in suggestions))
        self.assertTrue(all("하안동" in row["address"] for row in suggestions))


if __name__ == "__main__":
    unittest.main()
