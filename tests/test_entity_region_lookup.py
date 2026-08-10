import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import budget_candidates as bc  # noqa: E402


class RegionLookupTest(unittest.TestCase):
    """사람들이 법정동까지 붙여서 검색해도 단지를 찾아야 한다."""

    def _names(self, matches):
        return [entity.get("name") for entity in matches]

    def test_district_only_finds_the_complex(self):
        matches = bc._find_entities("대림아파트", "서울 동작구")
        self.assertIn("대림아파트", self._names(matches))

    def test_legal_dong_in_region_still_finds_the_complex(self):
        for region in (
            "서울 동작구 대방동",
            "서울시 동작구 대방동",
            "동작구 대방동",
            "대방동",
        ):
            matches = bc._find_entities("대림아파트", region)
            self.assertTrue(matches, f"{region}에서 못 찾았어요")
            self.assertEqual(matches[0].get("legalDong"), "대방동", region)

    def test_legal_dong_narrows_the_result(self):
        wide = bc._find_entities("대림아파트", "서울 동작구")
        narrow = bc._find_entities("대림아파트", "서울 동작구 대방동")
        self.assertGreater(len(wide), len(narrow))

    def test_wrong_dong_does_not_match(self):
        matches = bc._find_entities("대림아파트", "서울 동작구 사당동")
        for entity in matches:
            self.assertNotEqual(entity.get("legalDong"), "대방동")

    def test_find_entity_returns_the_registered_name(self):
        entity = bc._find_entity("대림아파트", "서울 동작구 대방동")
        self.assertIsNotNone(entity)
        self.assertEqual(entity.get("jibun"), "501")


if __name__ == "__main__":
    unittest.main()
