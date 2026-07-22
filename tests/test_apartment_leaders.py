import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import apartment_leaders  # noqa: E402
import molit_transactions  # noqa: E402


def _trade(date, price, area=84.8, **extra):
    return {
        "dealDate": date,
        "dealAmountManwon": price,
        "exclusiveArea": area,
        **extra,
    }


def _monthly_trades(prices, area=84.8):
    return [
        _trade(f"{month}-15", price, area=area)
        for month, price in prices
    ]


class ApartmentLeadersTest(unittest.TestCase):
    def test_region_matching_does_not_mix_yangju_into_namyangju(self):
        self.assertFalse(apartment_leaders._region_matches("양주시", "남양주시"))
        self.assertTrue(apartment_leaders._region_matches("성남분당구", "분당구"))

    def test_master_entities_derive_lawd_code_from_parcel_id(self):
        hwaseong = apartment_leaders.matching_entities("경기도", "화성시")

        self.assertTrue(hwaseong)
        self.assertTrue(all(entity.get("lawdCd") == "41590" for entity in hwaseong))

    def test_mapo_leaders_include_rachel_presale_complex(self):
        mapo = apartment_leaders.matching_entities("서울특별시", "마포구")
        rachel = next(
            entity
            for entity in mapo
            if entity.get("name") == "마포자이힐스테이트 라첼스"
        )

        self.assertEqual(rachel.get("status"), "분양권")
        self.assertEqual(rachel.get("lawdCd"), "11440")

    def test_region_prefetches_apartment_and_presale_feeds_separately(self):
        entities = [
            {"name": "기존단지", "district": "테스트구", "lawdCd": "11111"},
            {
                "name": "분양단지",
                "district": "테스트구",
                "lawdCd": "22222",
                "status": "분양권",
            },
        ]
        prefetched = []

        def capture(pairs, transaction_kind):
            prefetched.append((transaction_kind, list(pairs)))

        with mock.patch.object(
            molit_transactions,
            "transaction_kind_for_apartment",
            side_effect=lambda name, _region: (
                molit_transactions.TRANSACTION_KIND_PRESALE
                if name == "분양단지"
                else molit_transactions.TRANSACTION_KIND_APARTMENT
            ),
        ), mock.patch.object(
            molit_transactions, "enabled", return_value=True,
        ), mock.patch.object(
            molit_transactions, "related_lawd_codes", side_effect=lambda code: (code,),
        ), mock.patch.object(
            molit_transactions, "_deal_months", return_value=["202606"],
        ), mock.patch.object(
            molit_transactions, "prefetch_months", side_effect=capture,
        ):
            apartment_leaders._prefetch_region_months(entities, 24, cache_only=False)

        self.assertEqual(
            prefetched,
            [
                (molit_transactions.TRANSACTION_KIND_APARTMENT, [("11111", "202606")]),
                (molit_transactions.TRANSACTION_KIND_PRESALE, [("22222", "202606")]),
            ],
        )

    def test_presale_ranking_exposes_status_and_uses_new_build_category(self):
        presale_entity = {
            "name": "분양단지",
            "province": "서울특별시",
            "district": "테스트구",
            "legalDong": "가동",
            "lawdCd": "11111",
            "status": "분양권",
            "dedupeKey": "presale-leader-test",
        }
        completed_entity = {
            "name": "일반단지",
            "province": "서울특별시",
            "district": "테스트구",
            "legalDong": "나동",
            "lawdCd": "11111",
            "approvedAt": "2020-01-01",
            "dedupeKey": "completed-leader-test",
        }
        result = apartment_leaders.calculate_rankings_from_pairs(
            "서울특별시",
            "테스트구",
            [
                (
                    presale_entity,
                    [_trade("2026-05-10", 200000), _trade("2026-06-10", 220000)],
                ),
                (
                    completed_entity,
                    [_trade("2026-05-10", 300000), _trade("2026-06-10", 320000)],
                ),
            ],
            reference_month="2026-06",
        )

        self.assertEqual(
            [row["apartmentName"] for row in result["rankings"]["price"]],
            ["일반단지", "분양단지"],
        )
        price_item = result["rankings"]["price"][1]
        self.assertEqual(price_item["status"], "분양권")
        self.assertEqual(result["rankings"]["new_build"][0]["apartmentName"], "분양단지")
        self.assertIn("분양권·입주권 실거래", price_item["warnings"][0])

    def test_gyeonggi_source_row_uses_legal_ri_and_parcel_number(self):
        row = {"읍면동": "가평읍", "지번": "대곡리 695"}

        self.assertEqual(molit_transactions._source_legal_dong(row), "대곡리")
        self.assertEqual(molit_transactions._source_jibun(row), "695")
        self.assertEqual(molit_transactions._legal_dong_leaf("가평읍 대곡리"), "대곡리")

    def test_hwaseong_reads_old_and_split_lawd_codes(self):
        self.assertEqual(
            molit_transactions.related_lawd_codes("41590"),
            ("41590", "41591", "41593", "41595", "41597"),
        )

    def test_frontend_exposes_region_categories_and_exact_84m2_help(self):
        html = (ROOT / "앱화면" / "real-estate-search.html").read_text(encoding="utf-8")
        self.assertIn('id="leaderEntry"', html)
        header_start = html.index('<header class="app-header">')
        header = html[header_start:html.index("</header>", header_start)]
        hero_start = html.index('<div class="hero-actions">')
        hero_actions = html[hero_start:html.index("</div>", hero_start)]
        self.assertIn('id="leaderEntry"', header)
        self.assertNotIn('id="leaderEntry"', hero_actions)
        self.assertNotIn('id="leaderBack"', html)
        self.assertIn('class="view-tabs" role="tablist"', header)
        self.assertIn('data-view="condition" aria-selected="true"', header)
        self.assertIn('data-view="leader" aria-selected="false"', header)
        self.assertIn('<span class="view-tab-label-long">내 예산으로 찾기</span>', header)
        self.assertIn('<span class="view-tab-label-long">지역별 대장</span>', header)
        self.assertIn('id="conditionView" role="tabpanel" aria-labelledby="budgetViewTab"', html)
        self.assertIn('id="leaderView" role="tabpanel" aria-labelledby="leaderEntry"', html)
        self.assertIn(
            ".app-header .view-tabs { flex:0 1 auto; min-width:0; "
            "margin-right:auto; margin-left:auto; padding:3px }",
            html,
        )
        self.assertIn("flex:0 0 46px; width:46px; max-width:46px; margin-left:0;", html)
        self.assertIn(
            'id="listingReportHistoryEntry" type="button" hidden',
            hero_actions,
        )
        self.assertIn('id="leaderSido"', html)
        self.assertIn('id="leaderSigungu"', html)
        self.assertNotIn('id="leaderAreaBucket"', html)
        self.assertNotIn('id="leaderAreaTabs"', html)
        self.assertNotIn('data-leader-area-profile=', html)
        self.assertNotIn('id="leaderAreaComparison"', html)
        self.assertNotIn('id="leaderMeta"', html)
        self.assertNotIn('id="leaderCategoryTabs"', html)
        self.assertIn('id="leaderReferenceCaption" hidden', html)
        self.assertIn('leaderReferenceCaption.textContent = `${leaderReferenceLabel(payload?.referenceMonth)} 기준`;', html)
        self.assertIn('${apartmentStatusBadgeHtml(item.status)}</${headingTag}>', html)
        self.assertIn('${apartmentStatusBadgeHtml(item.status)}</span>', html)
        self.assertLess(html.index('id="leaderReferenceCaption"'), html.index('id="leaderPageTitle"'))
        self.assertNotIn("areaProfile,", html)
        self.assertNotIn("activeLeaderAreaProfile", html)
        self.assertIn(
            "border:0; border-radius:0; padding:0; background:transparent; box-shadow:none;",
            html,
        )
        for category in ("price", "leadership", "residence", "new_build", "value"):
            self.assertNotIn(f'data-leader-category="{category}"', html)
        self.assertIn("데이터 신뢰도", html)
        self.assertIn("/api/apartment-leaders", html)
        self.assertIn('item.nearestStationName || "가까운 역"', html)
        self.assertIn("직선 ${Math.round(stationDistance)", html)
        self.assertNotIn("대장(면적별)", html)
        self.assertIn('aria-label="대장아파트 실거래 기준 보기"', html)
        self.assertIn("전용 84.00㎡ 이상 85.00㎡ 미만", html)
        self.assertIn("다른 면적의 거래는 포함하거나 84㎡ 가격으로 환산하지 않습니다", html)
        self.assertNotIn("실거래가 × (84 ÷ 실제면적)", html)
        self.assertNotIn('data-leader-category="overall"', html)
        self.assertNotIn('data-leader-category="leadership"', html)
        self.assertIn("fetchLeaderRanking(activeLeaderCategory, 30", html)
        self.assertIn("leaderGrowthText(item.return6m)", html)
        self.assertIn("data-leader-expand-rank", html)
        self.assertIn('class="leader-list-name">${esc(item.apartmentName)}</span>', html)
        self.assertIn('class="leader-list-area">최근 6개월 · 전용 84㎡ 실거래', html)
        self.assertIn("최근 6개월의 전용 84.00㎡ 이상 85.00㎡ 미만", html)
        self.assertIn("item.leaderPrice6m ?? item.leaderPrice12m", html)
        self.assertIn("function leaderMetaHtml(item)", html)
        self.assertIn('`${Number(item.completionYear)}년 준공`', html)
        self.assertIn('`${Number(item.householdCount).toLocaleString("ko-KR")}세대`', html)
        self.assertIn('class="leader-meta-detail">${esc(completion)} · ${esc(households)}</span>', html)
        self.assertIn('class="leader-winner-sub">${view.meta}</p>', html)
        self.assertIn('class="leader-list-location">${leaderMetaHtml(item)}</span>', html)
        leader_meta_start = html.index("function leaderMetaHtml(item)")
        leader_meta_end = html.index("const GYEONGGI_DISTRICT_CITY_PREFIXES", leader_meta_start)
        self.assertNotIn("전용 ${area}㎡", html[leader_meta_start:leader_meta_end])
        self.assertNotIn("item.address", html[leader_meta_start:leader_meta_end])
        self.assertNotIn("leader-meta-address", html)
        self.assertIn(
            "display:flex; flex-direction:column; align-items:flex-end; justify-content:center; min-width:max-content;",
            html,
        )
        self.assertIn(
            '<span>${esc(view.scoreTitle)}</span><strong>${esc(view.metric)}</strong>',
            html,
        )
        self.assertNotIn(
            "display:grid; place-items:center; align-content:center; width:106px; height:106px; border-radius:50%;",
            html,
        )
        self.assertIn(".leader-list-copy { display:grid; gap:6px; min-width:0 }", html)
        self.assertIn("expandedLeaderRanks", html)
        self.assertIn('let activeLeaderCategory = "price";', html)
        self.assertIn('id="leaderMapFab" type="button" aria-label="지역 대장 지도 보기"', html)
        self.assertIn('id="leaderMapView" role="dialog" aria-modal="true"', html)
        self.assertIn('id="leaderMapCanvas" aria-label="지역 대장 단지 위치"', html)
        self.assertIn('leaderMapFab.hidden = false;', html)
        self.assertIn('leaderMapFab.addEventListener("click", openLeaderMap);', html)
        self.assertIn("rows.map(item => geocodeCandidate(geocoder, kakaoApi, item))", html)
        self.assertIn('data-leader-map-detail', html)
        self.assertIn('class="candidate-map-preview" id="leaderMapPreview"', html)
        self.assertIn("return candidateMapMarkerHtml(leaderMapCandidate(item), selected);", html)
        self.assertIn("setupCandidateMapPreviewSheet(leaderMapPreview);", html)
        self.assertNotIn(".leader-map-marker {", html)

    def test_exact_84m2_actual_price_is_the_default_market_leader_definition(self):
        entities = [
            {
                "name": "시장대장(2단지)",
                "province": "서울특별시",
                "district": "테스트구",
                "legalDong": "가동",
                "households": 500,
                "approvedAt": "2008-01-01",
                "dedupeKey": "market-leader",
            },
            {
                "name": "혼합평형고가",
                "province": "서울특별시",
                "district": "테스트구",
                "legalDong": "나동",
                "households": 1500,
                "approvedAt": "2024-01-01",
                "dedupeKey": "mixed-price",
            },
        ]
        data = [
            (
                entities[0],
                [
                    _trade("2026-06-15", 200000, area=84.8),
                    _trade("2026-05-15", 200000, area=84.9),
                    _trade("2026-04-15", 100000, area=77.0),
                    _trade("2026-03-15", 100000, area=77.0),
                ],
            ),
            (
                entities[1],
                [
                    _trade("2026-06-15", 150000, area=84.8),
                    _trade("2026-05-15", 150000, area=84.9),
                    _trade("2026-04-15", 300000, area=77.0),
                    _trade("2026-03-15", 300000, area=77.0),
                ],
            ),
        ]

        result = apartment_leaders.calculate_rankings_from_pairs(
            "서울특별시",
            "테스트구",
            data,
            area_bucket_value="70-89",
            reference_month="2026-06",
        )
        price = result["rankings"]["price"]

        self.assertEqual(apartment_leaders.DEFAULT_CATEGORY, "price")
        self.assertEqual(price[0]["apartmentName"], "시장대장(2단지)")
        self.assertEqual(price[0]["marketLeaderName"], "시장대장")
        self.assertEqual(price[0]["leaderPrice6m"], 200000)
        self.assertEqual(price[0]["leaderRepresentativeArea"], 84.85)
        self.assertEqual(price[0]["leaderRepresentativeMedianPrice6m"], 200000)
        self.assertIsNone(price[0]["leaderPriceAdjustmentExponent"])
        self.assertEqual(price[0]["leaderPriceTransactionCount6m"], 2)
        self.assertEqual(price[0]["rankingTransactionCount"], 2)
        self.assertIn("최근 6개월 전용 84㎡ 실거래 중위가", price[0]["reasons"][0])
        self.assertEqual(result["leaderPriceBasisLabel"], "최근 6개월 전용 84㎡ 실거래 중위가")
        self.assertEqual(result["priceLookbackMonths"], 6)
        self.assertNotIn("areaProfile", result)
        self.assertEqual(result["areaTarget"], 84.0)

    def test_general_leader_excludes_non_84m2_trades_instead_of_adjusting_them(self):
        def entity(name):
            return {
                "name": name,
                "province": "경기도",
                "district": "테스트구",
                "legalDong": "가동",
                "households": 500,
                "approvedAt": "2011-01-01",
                "dedupeKey": name,
            }

        data = [
            (
                entity("중대형대장"),
                [_trade(f"2026-0{month}-15", 350000, area=104.0) for month in (3, 4, 5, 6)],
            ),
            (
                entity("소형고단가"),
                [_trade(f"2026-0{month}-15", 200000, area=58.7) for month in (2, 3, 4, 5, 6)],
            ),
            (
                entity("국평단지"),
                [_trade(f"2026-0{month}-15", 243000, area=84.7) for month in (3, 4, 5, 6)],
            ),
        ]

        result = apartment_leaders.calculate_rankings_from_pairs(
            "경기도",
            "테스트구",
            data,
            area_bucket_value="70-89",
            reference_month="2026-06",
        )
        price = result["rankings"]["price"]

        self.assertEqual([row["apartmentName"] for row in price], ["국평단지"])
        self.assertAlmostEqual(price[0]["leaderRepresentativeArea"], 84.7)
        self.assertEqual(price[0]["leaderPriceTransactionCount6m"], 4)

    def test_84m2_actual_trade_range_boundaries_are_exact(self):
        transactions = [
            _trade("2026-06-01", 100000, area=83.99),
            _trade("2026-06-02", 100000, area=84.0),
            _trade("2026-06-03", 100000, area=84.99),
            _trade("2026-06-04", 100000, area=85.0),
        ]

        trades, area = apartment_leaders._leader_price_trades(transactions, "2026-06")

        self.assertEqual([row["exclusiveArea"] for row in trades], [84.0, 84.99])
        self.assertAlmostEqual(area, 84.495)

    def test_price_ranking_uses_six_month_median_but_keeps_twelve_month_activity(self):
        entity = {
            "name": "기간분리단지",
            "province": "서울특별시",
            "district": "테스트구",
            "legalDong": "가동",
            "dedupeKey": "six-month-price-window",
        }
        transactions = [
            _trade("2025-11-15", 900000),
            _trade("2025-12-15", 900000),
            _trade("2026-05-15", 100000),
            _trade("2026-06-15", 100000),
        ]

        result = apartment_leaders.calculate_rankings_from_pairs(
            "서울특별시",
            "테스트구",
            [(entity, transactions)],
            reference_month="2026-06",
        )
        item = result["rankings"]["price"][0]

        self.assertEqual(item["leaderPrice6m"], 100000)
        self.assertEqual(item["leaderPriceTransactionCount6m"], 2)
        self.assertEqual(item["transactionCount12m"], 4)

    def test_cache_key_uses_single_general_leader_definition(self):
        path = apartment_leaders._cache_path(
            "서울특별시", "테스트구", "70-89", "2026-06",
        )

        self.assertTrue(str(path).endswith(".json"))

    def test_area_bucket_boundaries(self):
        cases = {
            38.99: "lt39",
            39: "39-49",
            49.99: "39-49",
            50: "50-69",
            69.99: "50-69",
            70: "70-89",
            89.99: "70-89",
            90: "90plus",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(apartment_leaders.area_bucket(value), expected)

    def test_percentile_rank_uses_average_rank_for_ties(self):
        self.assertEqual(
            apartment_leaders.percentile_ranks([10, 20, 20, 30, None]),
            [0.0, 50.0, 50.0, 100.0, None],
        )

    def test_sparse_price_is_adjusted_toward_district_median(self):
        self.assertEqual(apartment_leaders.adjusted_price(120000, 100000, 10), 120000)
        self.assertEqual(apartment_leaders.adjusted_price(120000, 100000, 5), 116000)
        self.assertEqual(apartment_leaders.adjusted_price(120000, 100000, 2), 110000)
        self.assertEqual(apartment_leaders.adjusted_price(120000, 100000, 1), 104000)
        self.assertIsNone(apartment_leaders.adjusted_price(120000, 100000, 0))

    def test_age_station_and_confidence_scores_follow_specification(self):
        self.assertEqual(apartment_leaders.age_score("2024-01-01", "2026-06"), 100)
        self.assertEqual(apartment_leaders.age_score("2013-01-01", "2026-06"), 70)
        self.assertEqual(apartment_leaders.station_score(300), 100)
        self.assertEqual(apartment_leaders.station_score(501), 75)
        self.assertEqual(apartment_leaders.station_score(None), None)
        self.assertEqual(apartment_leaders.confidence_for_count(10)[1], "HIGH")
        self.assertEqual(apartment_leaders.confidence_for_count(5)[1], "MEDIUM")
        self.assertEqual(apartment_leaders.confidence_for_count(2)[1], "LOW")
        self.assertEqual(apartment_leaders.confidence_for_count(1)[1], "CANDIDATE")

    def test_cached_kakao_station_distance_is_used_in_metrics(self):
        entity = {
            "name": "역세권단지",
            "province": "서울특별시",
            "district": "테스트구",
            "legalDong": "가동",
            "households": 500,
            "approvedAt": "2020-01-01",
            "dedupeKey": "station-test",
        }
        trades = [_trade("2026-06-15", 100000), _trade("2026-05-15", 98000)]
        cached = {
            "latitude": 37.5,
            "longitude": 127.0,
            "nearestStationName": "테스트역",
            "nearestStationDistance": 420,
            "nearestStationLatitude": 37.501,
            "nearestStationLongitude": 127.001,
            "stationDistanceType": "straight_line",
            "stationDistanceSource": "kakao-local-v2",
        }
        with mock.patch.object(
            apartment_leaders.kakao_station_distances,
            "cached_station",
            return_value=cached,
        ):
            row = apartment_leaders._base_metrics(
                entity,
                trades,
                "2026-06",
                "70-89",
            )

        self.assertEqual(row["nearestStationName"], "테스트역")
        self.assertEqual(row["nearestStationDistance"], 420)
        self.assertEqual(row["stationScore"], 90)
        self.assertEqual(row["stationDistanceSource"], "kakao-local-v2")

    def test_station_lower_bound_is_scored_for_regions_without_a_nearby_station(self):
        entity = {
            "name": "원거리단지",
            "province": "경기도",
            "district": "테스트군",
            "legalDong": "가리",
            "households": 100,
            "approvedAt": "2020-01-01",
            "dedupeKey": "far-station-test",
        }
        cached = {
            "stationDistanceLowerBound": 20000,
            "stationDistanceType": "straight_line_lower_bound",
            "stationDistanceSource": "kakao-local-v2",
        }
        with mock.patch.object(
            apartment_leaders.kakao_station_distances,
            "cached_station",
            return_value=cached,
        ):
            row = apartment_leaders._base_metrics(
                entity,
                [_trade("2026-06-15", 10000), _trade("2026-05-15", 9900)],
                "2026-06",
                "70-89",
            )
        row["areaBucket"] = "70-89"
        apartment_leaders._score_metrics([row], "2026-06")

        self.assertEqual(row["stationScore"], 10.0)
        self.assertNotIn(
            "지하철 거리 데이터가 없어 역 접근성은 점수에서 제외했습니다.",
            apartment_leaders._warnings(row),
        )
        self.assertIn(
            "반경 20km 안에 지하철역 없음",
            apartment_leaders._reason_candidates(row, "residence"),
        )

    def test_cancelled_direct_and_other_area_trades_are_excluded(self):
        transactions = [
            _trade("2026-06-15", 100000),
            _trade("2026-05-15", 100000, cancellationDate="2026-06-01"),
            _trade("2026-04-15", 100000, dealType="직거래"),
            _trade("2026-03-15", 100000, area=59.8),
        ]
        rows = apartment_leaders._transactions_in_window(
            transactions,
            "2026-06",
            12,
            "70-89",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dealDate"], "2026-06-15")

    def test_missing_leadership_explains_stale_latest_trade(self):
        entity = {
            "name": "희소거래단지",
            "province": "서울특별시",
            "district": "테스트구",
            "legalDong": "가동",
            "households": 500,
            "approvedAt": "2020-01-01",
            "dedupeKey": "sparse-leadership-test",
        }
        trades = [
            _trade("2025-07-15", 100000),
            _trade("2025-10-15", 105000),
            _trade("2026-01-15", 110000),
        ]
        row = apartment_leaders._base_metrics(entity, trades, "2026-06", "70-89")
        row["leadershipScore"] = None

        self.assertEqual(row["latestTransactionMonth"], "2026-01")
        self.assertIn("마지막 비교 거래가 2026년 1월", row["leadershipMissingReason"])
        self.assertIn(row["leadershipMissingReason"], apartment_leaders._warnings(row))

    def test_full_ranking_is_region_and_area_scoped_and_excludes_one_trade(self):
        entities = [
            {
                "name": "선도단지",
                "province": "서울특별시",
                "district": "테스트구",
                "legalDong": "가동",
                "households": 1000,
                "approvedAt": "2021-01-01",
                "dedupeKey": "선도",
            },
            {
                "name": "신축단지",
                "province": "서울특별시",
                "district": "테스트구",
                "legalDong": "나동",
                "households": 600,
                "approvedAt": "2025-01-01",
                "dedupeKey": "신축",
            },
            {
                "name": "한건고가",
                "province": "서울특별시",
                "district": "테스트구",
                "legalDong": "다동",
                "households": 2000,
                "approvedAt": "2018-01-01",
                "dedupeKey": "한건",
            },
        ]
        leader_prices = [
            ("2025-06", 80000),
            ("2025-07", 82000),
            ("2025-08", 84000),
            ("2025-09", 86000),
            ("2025-10", 88000),
            ("2025-11", 90000),
            ("2025-12", 92000),
            ("2026-01", 96000),
            ("2026-02", 100000),
            ("2026-03", 104000),
            ("2026-04", 108000),
            ("2026-05", 112000),
            ("2026-06", 116000),
        ]
        new_prices = [
            ("2025-06", 90000),
            ("2025-07", 90000),
            ("2025-08", 90000),
            ("2025-09", 90000),
            ("2025-10", 90000),
            ("2025-11", 90000),
            ("2025-12", 90000),
            ("2026-01", 90000),
            ("2026-02", 90000),
            ("2026-03", 90000),
            ("2026-04", 90000),
            ("2026-05", 90000),
            ("2026-06", 90000),
        ]
        data = [
            (entities[0], _monthly_trades(leader_prices)),
            (entities[1], _monthly_trades(new_prices)),
            (entities[2], [_trade("2026-06-15", 250000)]),
        ]
        with mock.patch.object(apartment_leaders, "matching_entities", return_value=entities), \
             mock.patch.object(apartment_leaders, "_load_transactions", return_value=data):
            result = apartment_leaders.calculate_rankings(
                "서울특별시",
                "테스트구",
                area_bucket_value="70-89",
                reference_month="2026-06",
            )

        overall = result["rankings"]["overall"]
        self.assertEqual(overall[0]["apartmentName"], "선도단지")
        self.assertNotIn("한건고가", {row["apartmentName"] for row in overall})
        self.assertEqual(result["rankings"]["new_build"][0]["apartmentName"], "신축단지")
        self.assertEqual(result["areaBucket"], "70-89")
        self.assertEqual(overall[0]["calculationVersion"], apartment_leaders.CALCULATION_VERSION)
        self.assertTrue(overall[0]["reasons"])
        self.assertIn(
            "지하철 거리 데이터가 없어 역 접근성은 점수에서 제외했습니다.",
            overall[0]["warnings"],
        )

    def test_growth_ranking_uses_six_month_return_only(self):
        entities = [
            {
                "name": "장기상승단지",
                "province": "서울특별시",
                "district": "테스트구",
                "legalDong": "가동",
                "households": 1000,
                "approvedAt": "2018-01-01",
                "dedupeKey": "long-growth",
            },
            {
                "name": "단기상승단지",
                "province": "서울특별시",
                "district": "테스트구",
                "legalDong": "나동",
                "households": 1000,
                "approvedAt": "2018-01-01",
                "dedupeKey": "short-growth",
            },
        ]
        long_growth = _monthly_trades([
            ("2025-06", 100000),
            ("2025-07", 120000),
            ("2025-08", 125000),
            ("2025-09", 130000),
            ("2025-12", 150000),
            ("2026-03", 180000),
            ("2026-06", 200000),
        ])
        short_growth = _monthly_trades([
            ("2025-06", 100000),
            ("2025-07", 105000),
            ("2025-08", 108000),
            ("2025-09", 109000),
            ("2025-12", 110000),
            ("2026-03", 140000),
            ("2026-06", 150000),
        ])

        result = apartment_leaders.calculate_rankings_from_pairs(
            "서울특별시",
            "테스트구",
            [(entities[0], long_growth), (entities[1], short_growth)],
            area_bucket_value="70-89",
            reference_month="2026-06",
            limit=10,
        )
        growth = result["rankings"]["leadership"]

        self.assertEqual([row["apartmentName"] for row in growth], ["단기상승단지", "장기상승단지"])
        self.assertEqual(growth[0]["categoryLabel"], "상승률 좋은순")
        self.assertEqual(growth[0]["score"], growth[0]["return6m"])
        self.assertGreater(growth[0]["return6m"], growth[1]["return6m"])
        self.assertEqual(growth[0]["transactionCount12m"], 6)

    def test_tie_breaker_prefers_confidence_then_transactions_then_price(self):
        rows = [
            {
                "apartmentName": "나단지",
                "overallScore": 80,
                "dataConfidenceScore": 75,
                "transactionCount12m": 8,
                "priceScore": 90,
            },
            {
                "apartmentName": "가단지",
                "overallScore": 80,
                "dataConfidenceScore": 100,
                "transactionCount12m": 10,
                "priceScore": 70,
            },
        ]
        for row in rows:
            row.update({
                "confidenceLevel": "HIGH",
                "sigungu": "테스트구",
                "areaBucket": "70-89",
                "activeTransactionMonths12m": 3,
                "transactionTurnoverPercentile": 50,
                "activeTransactionMonthsPercentile": 50,
                "scores": {},
                "stationScore": None,
                "ageScore": 50,
                "householdCount": 100,
                "leadershipScore": 50,
                "liquidityScore": 50,
                "completionYear": 2010,
                "isNewBuild": False,
                "relativeReturn6m": 0,
            })
        ranked = apartment_leaders._rank_category(rows, "overall", 5)
        self.assertEqual(ranked[0]["apartmentName"], "가단지")


if __name__ == "__main__":
    unittest.main()
