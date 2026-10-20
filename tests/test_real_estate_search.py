import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import real_estate_search  # noqa: E402
import analyze_real_estate  # noqa: E402


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
        self.assertTrue(all(row["jibun"] in row["address"] for row in suggestions))

    def test_manual_alias_uses_complete_unique_source_complex(self):
        cases = {
            "서울숲 트리마제": ("성동구", "성수동1가", 688),
            "광교중흥S클래스": ("수원영통구", "원천동", 2231),
            "동탄 롯데캐슬 알바트로스": ("화성시", "청계동", 1416),
            "동탄 푸른마을 포스코더샵2차": ("화성시", "능동", 1226),
            "아이파크 삼성": ("강남구", "삼성동", 449),
        }

        for query, expected in cases.items():
            with self.subTest(query=query):
                suggestions = real_estate_search.suggest_apartments(query)
                self.assertEqual(len(suggestions), 1)
                self.assertEqual(
                    (
                        suggestions[0]["region"],
                        suggestions[0]["legalDong"],
                        suggestions[0]["households"],
                    ),
                    expected,
                )

    def test_unresolved_editorial_name_never_opens_an_all_unknown_result(self):
        self.assertEqual(
            real_estate_search.suggest_apartments("개포자이프레지던스"),
            [],
        )

    def test_xi_brand_typo_matches_jai_apartment_name(self):
        suggestions = real_estate_search.suggest_apartments("서울숲 리버뷰 ZI")

        self.assertGreaterEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["name"], "서울숲리버뷰자이")
        self.assertEqual(suggestions[0]["region"], "성동구")
        self.assertEqual(suggestions[0]["legalDong"], "행당동")
        self.assertEqual(suggestions[0]["households"], 858)

    def test_apartment_suggestions_always_have_a_region_for_followup_apis(self):
        for entity in real_estate_search.MANUAL_APARTMENT_MASTER:
            with self.subTest(name=entity["name"]):
                suggestions = real_estate_search.suggest_apartments(entity["name"])
                self.assertTrue(all(row["region"] for row in suggestions))

    def test_riversen_conflicting_current_and_presale_parcels_are_not_merged(self):
        suggestions = real_estate_search.suggest_apartments("리버센")
        jungnang_rows = [
            row for row in suggestions
            if row["region"] == "중랑구" and row["legalDong"] == "중화동"
        ]

        # An old presale parcel must not overwrite the completed complex's identity/status.
        self.assertEqual({row["jibun"] for row in jungnang_rows}, {"462", "331-1"})
        current = next(row for row in jungnang_rows if row["jibun"] == "462")
        self.assertEqual(current["name"], "리버센SK뷰롯데캐슬")
        self.assertEqual(current["households"], 1055)
        self.assertEqual(current["status"], "")

    def test_presale_source_typo_uses_consistent_official_name(self):
        for query in ("선샤인힐스", "션샤인힐스"):
            with self.subTest(query=query):
                suggestions = real_estate_search.suggest_apartments(query)
                target_rows = [
                    row for row in suggestions
                    if row["region"] == "부천원미구" and row["legalDong"] == "원미동"
                ]

                self.assertEqual(len(target_rows), 1)
                self.assertEqual(target_rows[0]["name"], "선샤인힐스")
                self.assertEqual(target_rows[0]["households"], 26)
                self.assertEqual(target_rows[0]["status"], "분양권")


class NumberedComplexGroupTest(unittest.TestCase):
    @staticmethod
    def _complex(name, apartment_id, jibun, households, legal_dong="병점동"):
        return {
            "apartmentId": apartment_id, "kaptCode": "", "complexNo": "", "name": name, "aliases": [],
            "province": "경기도", "district": "화성시", "legalDong": legal_dong, "jibun": jibun,
            "dedupeKey": f"{name}|경기도|화성시|{legal_dong}", "households": households,
        }

    @staticmethod
    def _group(name, members):
        return {"name": name, "aggregate": True, "members": list(members)}

    def test_group_records_its_member_complexes_by_id_and_parcel(self):
        group = next(
            entity for entity in real_estate_search.APARTMENT_MASTER
            if entity.get("aggregate") and entity["name"] == "안화동마을주공" and entity["district"] == "화성시"
        )

        members = {member["name"]: member for member in group["members"]}
        self.assertEqual(set(members), {f"안화동마을주공{number}단지" for number in range(5, 10)})
        self.assertEqual(members["안화동마을주공6단지"]["apartmentId"], "41590100255211")
        self.assertEqual(members["안화동마을주공9단지"]["jibun"], "819")
        self.assertTrue(all(member["legalDong"] == "병점동" for member in members.values()))
        self.assertEqual(sum(member["households"] for member in members.values()), group["households"])

    def test_single_member_group_becomes_an_alias_of_that_complex(self):
        member = self._complex("세곡리엔파크4단지", "1", "1", 407)
        groups = real_estate_search._numbered_group_entities([member], [self._group("세곡리엔파크", [member])])

        self.assertEqual(groups, [])
        self.assertIn("세곡리엔파크", member["aliases"])

    def test_single_member_group_name_used_by_another_complex_is_not_borrowed(self):
        member = self._complex("신원당마을9단지", "1", "1", 300)
        plain = self._complex("신원당마을", "2", "2", 500)
        groups = real_estate_search._numbered_group_entities([member, plain], [self._group("신원당마을", [member])])

        self.assertEqual(groups, [])
        self.assertNotIn("신원당마을", member["aliases"])

    def test_same_name_in_another_legal_dong_does_not_block_the_alias(self):
        member = self._complex("세곡리엔파크4단지", "1", "1", 407)
        elsewhere = self._complex("세곡리엔파크", "2", "2", 500, legal_dong="진안동")
        real_estate_search._numbered_group_entities([member, elsewhere], [self._group("세곡리엔파크", [member])])

        self.assertIn("세곡리엔파크", member["aliases"])

    def test_real_single_member_group_is_found_as_its_complex(self):
        rows = [
            entity for entity in real_estate_search.APARTMENT_MASTER
            if entity["district"] == "강남구" and entity["legalDong"] == "세곡동"
            and "세곡리엔파크" in {real_estate_search.compact(value) for value in (entity["name"], *entity["aliases"])}
        ]

        self.assertEqual([(row["name"], row.get("aggregate")) for row in rows], [("세곡리엔파크4단지", False)])
        self.assertEqual(rows[0]["apartmentId"], "11680120145599")


class OpinionAnalysisFailureTest(unittest.TestCase):
    def tearDown(self):
        analyze_real_estate._analysis_blocked_until = 0
        analyze_real_estate._analysis_blocked_reason = ""

    def test_openrouter_billing_error_blocks_repeated_slow_analysis(self):
        calls = 0

        def fail_once(_prompt):
            nonlocal calls
            calls += 1
            raise RuntimeError("402 Client Error: Payment Required")

        with mock.patch.object(analyze_real_estate.config, "ANALYSIS_PROVIDER", "openrouter"), \
             mock.patch.object(analyze_real_estate, "_generate_openrouter", side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError, "결제나 사용량 한도"):
                analyze_real_estate._generate("prompt")
            with self.assertRaisesRegex(RuntimeError, "결제나 사용량 한도"):
                analyze_real_estate._generate("prompt")

        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
