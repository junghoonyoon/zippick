import datetime
import sys
import tempfile
import unittest
from email.utils import format_datetime
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import news_catalysts  # noqa: E402


def _article(title, description=""):
    published = datetime.datetime.now(datetime.timezone.utc)
    return {
        "title": title,
        "description": description,
        "originallink": "https://example.com/news/confirmed-change",
        "link": "https://n.news.naver.com/article/001/0000000000",
        "pubDate": format_datetime(published),
    }


class NewsCatalystsTest(unittest.TestCase):
    def setUp(self):
        self.apartment = {
            "name": "래미안원베일리",
            "displayName": "래미안 원베일리",
            "region": "서초구",
            "legalDong": "반포동",
        }

    def test_selects_only_confirmed_transport_stage_for_the_apartment(self):
        catalyst = news_catalysts._select_catalyst([
            _article(
                "래미안 원베일리 인근 GTX-C 착공",
                "반포동 교통 여건에 영향을 줄 수 있는 GTX-C 사업이 착공했다.",
            ),
        ], self.apartment)

        self.assertEqual(catalyst["category"], "transport")
        self.assertEqual(catalyst["label"], "GTX-C 착공")
        self.assertEqual(catalyst["articleCount"], 1)
        self.assertEqual(catalyst["url"], "https://example.com/news/confirmed-change")

    def test_rejects_speculation_without_a_confirmed_stage(self):
        articles = [
            _article(
                "래미안 원베일리 재건축 호재 기대감",
                "정비사업 추진 가능성이 거론되고 있다.",
            ),
        ]
        catalyst = news_catalysts._select_catalyst(articles, self.apartment)
        related = news_catalysts._select_related_news(articles, self.apartment)

        self.assertIsNone(catalyst)
        self.assertEqual(related[0]["badge"], "단지 소식")
        self.assertEqual(related[0]["status"], "related")

    def test_rejects_article_about_a_different_apartment(self):
        catalyst = news_catalysts._select_catalyst([
            _article(
                "다른아파트 정비구역 지정",
                "반포동 재건축 정비사업의 정비구역 지정이 고시됐다.",
            ),
        ], self.apartment)

        self.assertIsNone(catalyst)

    def test_short_common_name_requires_location_in_the_article(self):
        apartment = {
            "name": "우성아파트",
            "region": "강남구",
            "legalDong": "대치동",
        }
        without_location = news_catalysts._select_catalyst([
            _article("우성아파트 재건축 정비구역 지정"),
        ], apartment)
        with_location = news_catalysts._select_catalyst([
            _article("대치동 우성아파트 재건축 정비구역 지정"),
        ], apartment)

        self.assertIsNone(without_location)
        self.assertEqual(with_location["label"], "정비구역 지정")

    def test_short_complex_name_uses_city_hint_from_display_region(self):
        apartment = {
            "name": "은행주공",
            "displayName": "은행주공",
            "region": "성남중원구",
            "displayRegion": "경기도 성남중원구",
            "legalDong": "은행동",
        }
        article = _article(
            "성남 은행주공 재건축 관리처분인가",
            "은행주공 재건축 정비사업의 관리처분계획이 인가됐다.",
        )

        catalyst = news_catalysts._select_catalyst([article], apartment)
        related = news_catalysts._select_related_news([article], apartment)

        self.assertEqual(catalyst["label"], "정비사업 관리처분인가")
        self.assertEqual(related[0]["scope"], "complex")
        self.assertEqual(related[0]["status"], "confirmed")

    def test_reordered_brand_and_phase_name_is_direct_complex_news(self):
        apartment = {
            "name": "수지4차삼성아파트",
            "region": "용인수지구",
            "displayRegion": "경기도 용인수지구",
            "legalDong": "풍덕천동",
        }
        article = _article(
            "용인 수지 삼성4차 재건축 사업시행인가",
            "수지 삼성4차 정비사업의 사업시행계획이 인가됐다.",
        )

        catalyst = news_catalysts._select_catalyst([article], apartment)
        related = news_catalysts._select_related_news([article], apartment)

        self.assertEqual(catalyst["label"], "정비사업 사업시행인가")
        self.assertEqual(related[0]["scope"], "complex")
        self.assertEqual(related[0]["badge"], "확인된 호재")

    def test_query_restores_legal_dong_from_full_display_address(self):
        apartment = {
            "name": "수지4차삼성아파트",
            "displayName": "수지삼성4차",
            "region": "용인수지구",
            "displayRegion": "경기도 용인수지구 풍덕천동 663-1",
            "legalDong": "",
        }

        self.assertEqual(
            news_catalysts._query(apartment),
            "수지삼성4차 풍덕천동",
        )

    def test_cache_key_distinguishes_full_address_when_legal_dong_is_missing(self):
        base = {
            "name": "우성아파트",
            "displayName": "우성",
            "region": "성남시",
            "legalDong": "",
        }

        left = news_catalysts._cache_key({
            **base,
            "displayRegion": "경기도 성남시 은행동 100",
        })
        right = news_catalysts._cache_key({
            **base,
            "displayRegion": "경기도 성남시 상대원동 200",
        })

        self.assertNotEqual(left, right)

    def test_related_news_rejects_price_only_story(self):
        related = news_catalysts._select_related_news([
            _article(
                "래미안 원베일리 신고가 경신",
                "반포동 매매가와 시세가 올랐다.",
            ),
        ], self.apartment)

        self.assertEqual(related, [])

    def test_general_complex_news_requires_apartment_name_in_title(self):
        related = news_catalysts._select_related_news([
            _article(
                "반포동 재건축 시장 현장",
                "래미안 원베일리는 정비사업 추진 단지 중 하나로 언급됐다.",
            ),
        ], self.apartment)

        self.assertEqual(related, [])

    def test_old_confirmed_stage_is_related_news_not_current_catalyst_badge(self):
        published = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=600)
        article = {
            **_article("래미안 원베일리 재건축 정비구역 지정"),
            "pubDate": format_datetime(published),
        }

        related = news_catalysts._select_related_news([article], self.apartment)

        self.assertEqual(related[0]["badge"], "단지 소식")
        self.assertEqual(related[0]["status"], "related")

    def test_neighborhood_news_requires_location_and_progress_stage(self):
        related = news_catalysts._select_related_news([
            _article(
                "반포동 복합개발 사업자 선정",
                "서초구 생활권에 새 업무시설이 들어설 예정이다.",
            ),
            _article(
                "강남구 복합개발 사업자 선정",
                "다른 생활권의 개발 소식이다.",
            ),
        ], self.apartment)

        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]["badge"], "인근 교통·개발")
        self.assertEqual(related[0]["status"], "nearby")

    def test_neighborhood_news_requires_location_in_the_title(self):
        related = news_catalysts._select_related_news([
            _article(
                "동탄 반도체 호황에 복합개발 추진",
                "반포동을 비롯한 수도권 시장도 함께 언급됐다.",
            ),
        ], self.apartment)

        self.assertEqual(related, [])

    def test_rejects_promotional_story_about_another_nearby_apartment(self):
        apartment = {
            "name": "꿈의숲해링턴플레이스",
            "region": "강북구",
            "legalDong": "미아동",
        }
        related = news_catalysts._select_related_news([
            _article(
                "더 리치먼드 미아 청약예정",
                "꿈의숲해링턴플레이스 인근 공원 개발사업이 착공 예정이다.",
            ),
        ], apartment)

        self.assertEqual(related, [])

    def test_rejects_temporary_local_lifestyle_story(self):
        apartment = {
            "name": "창동주공",
            "region": "도봉구",
            "legalDong": "창동",
        }
        related = news_catalysts._select_related_news([
            _article(
                "도봉구, 관내 곳곳에 물놀이장 개장",
                "창동 공원에서도 여름 물놀이장을 운영한다.",
            ),
        ], apartment)

        self.assertEqual(related, [])

    def test_rejects_school_library_scholarship_and_political_local_news(self):
        cases = [
            (
                {
                    "name": "신내아파트",
                    "region": "중랑구",
                    "legalDong": "신내동",
                },
                "중랑구, ‘동진학교’ 진입로 개설 완료",
                "신내동 동진학교 진입로를 준공하고 개교를 준비한다.",
            ),
            (
                {
                    "name": "신림아파트",
                    "region": "관악구",
                    "legalDong": "신림동",
                },
                "관악문화재단 도서관, '길 위의 인문학·지혜학교' 공모사업 선정",
                "신림동 주민을 위한 프로그램을 추진한다.",
            ),
            (
                {
                    "name": "창동주공",
                    "region": "도봉구",
                    "legalDong": "창동",
                },
                "도봉구 청소년 11명 장학금 1,100만 원 전달",
                "창동 지역사회 후원으로 장학사업을 추진했다.",
            ),
            (
                {
                    "name": "창동주공",
                    "region": "도봉구",
                    "legalDong": "창동",
                },
                "[기획특집] 도봉구청장 당선자, 도봉 대전환 시대 열겠다",
                "창동 개발사업과 교통 정책 추진을 공약했다.",
            ),
        ]
        for apartment, title, description in cases:
            with self.subTest(title=title):
                related = news_catalysts._select_related_news([
                    _article(title, description),
                ], apartment)
                self.assertEqual(related, [])

    def test_rejects_weak_neighborhood_redevelopment_business_agreement(self):
        apartment = {
            "name": "신림아파트",
            "region": "관악구",
            "legalDong": "신림동",
        }
        related = news_catalysts._select_related_news([
            _article(
                "대신자산신탁, 신림 5구역 추진위와 업무협약",
                "재개발 사업 참여를 위한 협약을 체결했다.",
            ),
        ], apartment)

        self.assertEqual(related, [])

    def test_keeps_confirmed_reconstruction_stage_of_nearby_complex(self):
        apartment = {
            "name": "목동신시가지아파트7단지",
            "region": "양천구",
            "legalDong": "목동",
        }
        related = news_catalysts._select_related_news([
            _article(
                "목동 6단지 재건축 조합설립인가",
                "목동신시가지 6단지 정비사업이 조합설립인가를 받았다.",
            ),
        ], apartment)

        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]["badge"], "인근 정비사업")
        self.assertEqual(related[0]["status"], "nearby")

    def test_complex_family_news_can_cross_legal_dong_boundary(self):
        apartment = {
            "name": "목동신시가지아파트10단지",
            "region": "양천구",
            "legalDong": "신정동",
        }
        related = news_catalysts._select_related_news([
            _article(
                "목동 6단지 재건축 시공사 확정",
                "목동신시가지 재건축 시공사를 확정했다.",
            ),
        ], apartment)

        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]["badge"], "인근 정비사업")

    def test_nearby_reconstruction_requires_a_completed_stage_in_title(self):
        apartment = {
            "name": "목동신시가지아파트7단지",
            "region": "양천구",
            "legalDong": "목동",
        }
        related = news_catalysts._select_related_news([
            _article(
                "목동 4·8단지 시공사 선정 준비 막바지",
                "재건축 시공사 선정 절차에 착수했다.",
            ),
            _article(
                "목동 12단지 경쟁입찰 성사되나",
                "재건축 시공사 선정 가능성이 거론된다.",
            ),
        ], apartment)

        self.assertEqual(related, [])

    def test_related_news_reserves_one_slot_for_nearby_reconstruction(self):
        apartment = {
            "name": "목동신시가지아파트7단지",
            "region": "양천구",
            "legalDong": "목동",
        }
        direct = {
            **_article(
                "목동 7단지 재건축 조합설립인가",
                "목동 7단지가 조합설립인가를 받았다.",
            ),
            "originallink": "https://example.com/news/mokdong-7",
        }
        nearby = {
            **_article(
                "목동 6단지 재건축 시공사 확정",
                "목동신시가지 6단지 시공사를 확정했다.",
            ),
            "originallink": "https://example.com/news/mokdong-6",
        }

        related = news_catalysts._select_related_news(
            [direct, nearby],
            apartment,
        )

        self.assertEqual(len(related), 2)
        self.assertEqual(
            [row["badge"] for row in related],
            ["확인된 호재", "인근 정비사업"],
        )

    def test_mokdong_short_name_is_recognized_as_the_target_complex(self):
        apartment = {
            "name": "목동신시가지아파트7단지",
            "region": "양천구",
            "legalDong": "목동",
        }
        catalyst = news_catalysts._select_catalyst([
            _article(
                "목동 7단지 조합설립인가",
                "목동 7단지 재건축 사업이 조합설립인가를 받았다.",
            ),
        ], apartment)

        self.assertIsNotNone(catalyst)
        self.assertEqual(catalyst["label"], "정비사업 조합설립인가")

    def test_keeps_confirmed_transport_change_in_the_same_legal_dong(self):
        apartment = {
            "name": "창동주공",
            "region": "도봉구",
            "legalDong": "창동",
        }
        related = news_catalysts._select_related_news([
            _article(
                "창동 GTX-C 착공",
                "GTX-C 사업이 착공해 광역 교통 여건이 바뀐다.",
            ),
        ], apartment)

        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]["badge"], "인근 교통·개발")

    def test_success_and_empty_result_are_cached(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(news_catalysts, "CACHE_DIR", Path(directory)), \
             mock.patch.object(news_catalysts.config, "NAVER_API_HUB_CLIENT_ID", "id"), \
             mock.patch.object(news_catalysts.config, "NAVER_API_HUB_CLIENT_SECRET", "secret"), \
             mock.patch.object(news_catalysts, "_search_articles", return_value=[]) as search, \
             mock.patch.object(news_catalysts, "_search_area_articles", return_value=[]) as area_search:
            first = news_catalysts.catalyst_for_apartment(self.apartment)
            second = news_catalysts.catalyst_for_apartment(self.apartment)

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(search.call_count, 1)
        self.assertEqual(area_search.call_count, 1)

    def test_api_hub_uses_the_current_endpoint_and_auth_headers(self):
        response = mock.Mock()
        response.raise_for_status = mock.Mock()
        response.json.return_value = {"items": []}
        with mock.patch.object(news_catalysts.config, "NAVER_API_HUB_CLIENT_ID", "hub-id"), \
             mock.patch.object(news_catalysts.config, "NAVER_API_HUB_CLIENT_SECRET", "hub-secret"), \
             mock.patch.object(news_catalysts.requests, "get", return_value=response) as request:
            articles = news_catalysts._search_articles(self.apartment)

        self.assertEqual(articles, [])
        self.assertEqual(request.call_args.args[0], news_catalysts.API_HUB_ENDPOINT)
        self.assertEqual(
            request.call_args.kwargs["headers"],
            {
                "X-NCP-APIGW-API-KEY-ID": "hub-id",
                "X-NCP-APIGW-API-KEY": "hub-secret",
            },
        )
        self.assertEqual(request.call_args.kwargs["params"]["format"], "json")

    def test_batch_returns_no_results_without_credentials(self):
        with mock.patch.object(news_catalysts.config, "NAVER_API_HUB_CLIENT_ID", ""), \
             mock.patch.object(news_catalysts.config, "NAVER_API_HUB_CLIENT_SECRET", ""), \
             mock.patch.object(news_catalysts.config, "NAVER_SEARCH_CLIENT_ID", ""), \
             mock.patch.object(news_catalysts.config, "NAVER_SEARCH_CLIENT_SECRET", ""):
            payload = news_catalysts.catalysts_for_apartments([
                {"id": "apt-1", **self.apartment},
            ])

        self.assertFalse(payload["configured"])
        self.assertEqual(
            payload["results"],
            [{"id": "apt-1", "catalyst": None, "news": []}],
        )


if __name__ == "__main__":
    unittest.main()
