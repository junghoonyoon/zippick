import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_HTML = ROOT / "앱화면" / "real-estate-search.html"


class FrontendApartmentSearchTest(unittest.TestCase):
    def test_condition_stepper_hides_downward_and_returns_upward(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r"function updateConditionFlowForScroll\b(?P<body>.*?)"
            r'\n    window\.addEventListener\("scroll"',
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("direction > 0 && conditionFlowScrollTravel >= 14", body)
        self.assertIn("setConditionFlowScrollHidden(true);", body)
        self.assertIn("direction < 0 && conditionFlowScrollTravel >= 8", body)
        self.assertIn("setConditionFlowScrollHidden(false);", body)
        self.assertIn("#conditionView .condition-flow.is-scroll-hidden", html)
        self.assertIn("body.condition-flow-scroll-hidden .power-persistent", html)

    def test_search_field_opens_a_dedicated_search_view_with_back_button(self):
        html = APP_HTML.read_text(encoding="utf-8")

        self.assertIn('id="aptSearchPageBack"', html)
        self.assertIn('id="aptSearchLanding"', html)
        self.assertIn('body.apt-search-mode .apt-search-page-back { display:grid }', html)
        self.assertIn(
            'aptSearchInput.addEventListener("focus", () => openAptSearchLanding({ focus:false }));',
            html,
        )
        self.assertIn(
            'aptSearchInput.addEventListener("click", () => openAptSearchLanding({ focus:false }));',
            html,
        )
        self.assertIn("if (activeSearchQuery && !searchSuspended) suspendSearchView();", html)
        self.assertIn('aptSearchPageBack.addEventListener("click", closeAptSearchView);', html)

    def test_search_results_start_price_and_signal_enrichment(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r"async function runAptSearch\b(?P<body>.*?)"
            r"\n    const aptReportCache",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("void enrichAptCards(items);", body)
        self.assertIn("void enrichAptAffordability(items);", body)

    def test_pending_budget_enrichment_is_not_labeled_as_insufficient(self):
        html = APP_HTML.read_text(encoding="utf-8")
        score_match = re.search(
            r"function candidateSignalScoreLabel\b(?P<body>.*?)"
            r"\n    function signalBadgesHtml",
            html,
            re.DOTALL,
        )
        badge_match = re.search(
            r"function signalBadgesHtml\b(?P<body>.*?)"
            r"\n    function candidateSignalReportHtml",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(score_match)
        self.assertIsNotNone(badge_match)
        score_body = score_match.group("body")
        badge_body = badge_match.group("body")
        self.assertIn('if (currentBudgetData?.enrichmentPending) return "갱신 중";', score_body)
        self.assertLess(
            score_body.index("currentBudgetData?.enrichmentPending"),
            score_body.index('item.marketInsightState === "ready"'),
        )
        self.assertIn("currentBudgetData?.enrichmentPending", badge_body)
        self.assertIn('? "loading"', badge_body)

    def test_unverified_candidate_over_cap_is_removed_after_price_enrichment(self):
        html = APP_HTML.read_text(encoding="utf-8")
        prices_match = re.search(
            r"function candidatePurchaseCapPrices\b(?P<body>.*?)"
            r"\n    function candidateWithinPurchaseCap",
            html,
            re.DOTALL,
        )
        cap_match = re.search(
            r"function candidateWithinPurchaseCap\b(?P<body>.*?)"
            r"\n    function unverifiedCandidateOverCap",
            html,
            re.DOTALL,
        )
        refresh_match = re.search(
            r"function refreshMarketInsight\b(?P<body>.*?)"
            r"\n    async function loadMarketInsight",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(prices_match)
        self.assertIsNotNone(cap_match)
        self.assertIsNotNone(refresh_match)
        price_body = prices_match.group("body")
        self.assertIn("item?.latestDealPriceEok", price_body)
        self.assertIn("item?.recent3AdjustedAveragePriceEok", price_body)
        self.assertIn("item?.estimatedMidPriceEok", price_body)
        self.assertIn("item?.policyImpact?.cashScenarios", price_body)
        self.assertIn("budget * 1.05", cap_match.group("body"))
        self.assertIn("candidatePurchaseCapPrices(item).every", cap_match.group("body"))
        self.assertIn(
            "item.marketInsightState === \"ready\" && unverifiedCandidateOverCap(item)",
            refresh_match.group("body"),
        )
        self.assertIn("removeOverCapCandidate(item);", refresh_match.group("body"))

    def test_budget_render_filters_all_server_and_cached_rows_by_purchase_cap(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r"function renderBudgetCandidates\b(?P<body>.*?)"
            r"\n    const budgetLoadingStages",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertGreaterEqual(
            body.count(".filter(row => candidateWithinPurchaseCap(row, data.budgetEok))"),
            2,
        )
        self.assertIn("policyExcludedCandidates: excludedRows", body)
        self.assertIn("realEstateSearch.budgetCandidates.v17", html)

    def test_rone_latest_trade_fills_price_before_score_enrichment_finishes(self):
        html = APP_HTML.read_text(encoding="utf-8")
        fallback_match = re.search(
            r"function applyRoneLatestTradeFallback\b(?P<body>.*?)"
            r"\n    async function loadMarketInsight",
            html,
            re.DOTALL,
        )
        load_match = re.search(
            r"async function loadMarketInsight\b(?P<body>.*?)"
            r"\n    function enrichMarketInsights",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(fallback_match)
        self.assertIsNotNone(load_match)
        fallback_body = fallback_match.group("body")
        load_body = load_match.group("body")
        self.assertIn("item.roneEstimate?.latestTrade", fallback_body)
        self.assertIn("trade?.dealAmountEok", fallback_body)
        self.assertIn("!Number(item.latestDealPriceEok || 0)", fallback_body)
        self.assertEqual(load_body.count("applyRoneLatestTradeFallback(item);"), 2)

    def test_report_cache_shares_an_in_flight_request_and_retries_failures(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r"async function fetchAptReport\b(?P<body>.*?)"
            r"\n    function aptCardSignalState",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertLess(
            body.index("aptReportCache.set(cacheKey, pending);"),
            body.index("const data = await pending;"),
        )
        self.assertIn("aptReportCache.delete(cacheKey);", body)

    def test_confirmed_trade_is_not_labeled_as_disconnected(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r"function aptCardSignalState\b(?P<body>.*?)"
            r"\n    function hasCompleteAptPurchaseProfile",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("if (confirmedLatestDate)", body)
        self.assertIn("최근 실거래 확인 · 흐름 분석 준비 중", body)
        self.assertLess(
            body.index("if (confirmedLatestDate)"),
            body.index("실거래 데이터가 연결되지 않았어요"),
        )

    def test_area_sheet_uses_affordability_transactions_as_a_fallback(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r"function fallbackAptAreaOption\b(?P<body>.*?)"
            r"\n    function renderAptAreaOptions",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("data?.market?.adjustedTransactions", body)
        self.assertIn("data?.latestTrade?.exclusiveArea", body)
        self.assertIn("clusters.map", body)

    def test_area_sheet_backdrop_and_escape_close_before_an_area_is_selected(self):
        html = APP_HTML.read_text(encoding="utf-8")
        click_match = re.search(
            r'if \(event\.target\.closest\("\[data-apt-area-sheet-close\]"\)\) \{(?P<body>.*?)\n      \}',
            html,
            re.DOTALL,
        )
        key_match = re.search(
            r'document\.addEventListener\("keydown", event => \{\n'
            r'      if \(event\.key !== "Escape" \|\| aptAreaSheet\.hidden\) return;(?P<body>.*?)\n    \}\);',
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(click_match)
        self.assertIsNotNone(key_match)
        self.assertIn("closeAptAreaSheet();", click_match.group("body"))
        self.assertIn("closeAptAreaSheet();", key_match.group("body"))
        self.assertNotIn("selectedAptArea", click_match.group("body"))
        self.assertNotIn("selectedAptArea", key_match.group("body"))

    def test_candidate_results_use_a_floating_map_button_without_view_tabs(self):
        html = APP_HTML.read_text(encoding="utf-8")
        render_match = re.search(
            r"function renderBudgetCandidates\b(?P<body>.*?)"
            r"\n    const budgetLoadingStages",
            html,
            re.DOTALL,
        )
        map_match = re.search(
            r"function candidateMapViewHtml\b(?P<body>.*?)"
            r"\n    function candidateMapViewElement",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(render_match)
        self.assertIsNotNone(map_match)
        self.assertIn("candidateMapFloatingButtonHtml()", render_match.group("body"))
        self.assertNotIn("candidateViewSwitchHtml()", render_match.group("body"))
        self.assertNotIn("candidate-map-view-switch-row", map_match.group("body"))
        self.assertIn('data-candidate-view="map"', html)
        self.assertIn('aria-label="지도에서 후보 보기"', html)
        self.assertNotIn('data-candidate-view="list"', html)

    def test_candidate_map_reset_removes_stale_sdk_layers(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r"function resetCandidateMap\b(?P<body>.*?)"
            r"\n    function setCandidateMapState",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("candidateMap?.setDraggable?.(false);", body)
        self.assertIn("candidateMapContainer.replaceChildren();", body)
        self.assertLess(
            body.index("candidateMapContainer.replaceChildren();"),
            body.index("candidateMap = null;"),
        )

    def test_candidate_map_latest_render_reenables_navigation(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r"async function renderCandidateMap\b(?P<body>.*?)"
            r"\n    function setCandidateViewMode",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("draggable:true", body)
        self.assertIn("scrollwheel:true", body)
        self.assertIn("candidateMapContainer !== container", body)
        self.assertIn("candidateMap?.setDraggable?.(true);", body)
        self.assertIn("candidateMap?.setZoomable?.(true);", body)


if __name__ == "__main__":
    unittest.main()
