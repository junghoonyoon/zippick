import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import naver_complex  # noqa: E402


def _response(complexes):
    response = mock.Mock()
    response.raise_for_status = mock.Mock()
    response.json.return_value = {"complexes": complexes}
    return response


class NaverComplexTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch_cache = mock.patch.object(naver_complex, "CACHE_DIR", Path(self._tmp.name))
        self._patch_cache.start()
        naver_complex._DISABLED_UNTIL = 0

    def tearDown(self):
        self._patch_cache.stop()
        self._tmp.cleanup()

    def test_resolves_renamed_complex_by_dong(self):
        complexes = [
            {"complexNo": "111", "complexName": "둔촌주공(올림픽파크포레온)", "cortarAddress": "서울시 강동구 둔촌동"},
            {"complexNo": "222", "complexName": "둔촌푸르지오", "cortarAddress": "서울시 강동구 성내동"},
        ]
        with mock.patch.object(naver_complex.requests, "get", return_value=_response(complexes)):
            resolved = naver_complex.resolve("둔촌주공", legal_dong="둔촌동")
        self.assertEqual(resolved["complexNo"], "111")

    def test_ambiguous_name_without_dong_falls_back(self):
        complexes = [
            {"complexNo": "111", "complexName": "동아아파트", "cortarAddress": "서울시 강동구 둔촌동"},
            {"complexNo": "222", "complexName": "동아아파트", "cortarAddress": "서울시 강동구 성내동"},
        ]
        with mock.patch.object(naver_complex.requests, "get", return_value=_response(complexes)):
            resolved = naver_complex.resolve("동아아파트")
        self.assertIsNone(resolved)

    def test_negative_result_is_cached(self):
        with mock.patch.object(naver_complex.requests, "get", return_value=_response([])) as fake:
            self.assertIsNone(naver_complex.resolve("없는단지", legal_dong="둔촌동"))
            first_calls = fake.call_count
            self.assertIsNone(naver_complex.resolve("없는단지", legal_dong="둔촌동"))
            self.assertEqual(fake.call_count, first_calls)  # 캐시 히트, 재호출 없음

    def test_attach_links_fallback_chain(self):
        rows = [
            {"name": "직링크단지", "legalDong": "둔촌동", "jibun": "170", "naverPropertyUrl": "old"},
            {
                "name": "이름폴백단지",
                "legalDong": "성내동",
                "jibun": "55-1",
                "naverPropertyQuery": "성내동 이름폴백단지",
                "naverPropertyUrl": "old",
            },
            {"name": "이름폴백단지", "legalDong": "", "jibun": "", "naverPropertyUrl": "old"},
        ]

        def fake_resolve(name, **kwargs):
            if name == "직링크단지":
                return {"complexNo": "12345", "complexName": "직링크단지"}
            return None

        with mock.patch.object(naver_complex, "resolve", side_effect=fake_resolve):
            naver_complex.attach_links(rows)

        self.assertEqual(rows[0]["naverPropertyUrl"], "https://new.land.naver.com/complexes/12345")
        self.assertEqual(rows[0]["naverLinkKind"], "complex")
        self.assertEqual(rows[0]["displayName"], "직링크단지")
        self.assertEqual(rows[0]["displayNameSource"], "naver_complex")
        self.assertIn("%EC%84%B1%EB%82%B4%EB%8F%99%20%EC%9D%B4%EB%A6%84%ED%8F%B4%EB%B0%B1%EB%8B%A8%EC%A7%80", rows[1]["naverPropertyUrl"])
        self.assertNotIn("55-1", rows[1]["naverPropertyUrl"])
        self.assertEqual(rows[1]["naverLinkKind"], "name")
        self.assertIn("%EC%9D%B4%EB%A6%84%ED%8F%B4%EB%B0%B1%EB%8B%A8%EC%A7%80", rows[2]["naverPropertyUrl"])
        self.assertEqual(rows[2]["naverLinkKind"], "name")

    def test_attach_links_uses_verified_naver_name_as_display_name(self):
        row = {
            "name": "돈암2-1 삼부아파트",
            "displayName": "돈암2-1 삼부아파트",
            "legalDong": "길음동",
            "jibun": "1276",
        }
        with mock.patch.object(
            naver_complex,
            "resolve",
            return_value={"complexNo": "98765", "complexName": "돈암삼부(삼부컨비니언)"},
        ):
            naver_complex.attach_links([row])

        self.assertEqual(row["displayName"], "돈암삼부(삼부컨비니언)")
        self.assertEqual(row["naverComplexName"], "돈암삼부(삼부컨비니언)")

    def test_verified_duplicate_name_uses_apartment_complex_override(self):
        resolved = naver_complex.resolve(
            "마포 한화 오벨리스크",
            legal_dong="도화동",
            jibun="555",
            region="마포구",
        )

        self.assertEqual(resolved["complexNo"], "12240")
        self.assertIn("주상복합", resolved["complexName"])

    def test_verified_naver_name_resolves_public_data_aliases_to_one_complex(self):
        names = ("돈암2-1 삼부아파트", "삼부컨비니언")
        resolved = [
            naver_complex.resolve(name, legal_dong="길음동", jibun="1276", region="성북구")
            for name in names
        ]

        self.assertEqual({item["complexNo"] for item in resolved}, {"576"})
        self.assertEqual({item["complexName"] for item in resolved}, {"돈암삼부(삼부컨비니언)"})

    def test_api_error_disables_temporarily(self):
        with mock.patch.object(naver_complex.requests, "get", side_effect=RuntimeError("blocked")):
            self.assertIsNone(naver_complex.resolve("아무단지", legal_dong="둔촌동"))
        self.assertGreater(naver_complex._DISABLED_UNTIL, 0)


if __name__ == "__main__":
    unittest.main()
