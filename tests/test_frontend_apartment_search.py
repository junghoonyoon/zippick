import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_HTML = ROOT / "앱화면" / "real-estate-search.html"


class FrontendApartmentSearchTest(unittest.TestCase):
    def test_posthog_analytics_tracks_core_dau_events_without_money_values(self):
        html = APP_HTML.read_text(encoding="utf-8")

        self.assertIn('getJson("/api/analytics-config")', html)
        self.assertIn("function installPostHogSnippet", html)
        self.assertIn("window.posthog.init(projectKey, config)", html)
        self.assertIn('trackEvent("active_user"', html)
        self.assertIn('trackEvent("budget_search_submitted"', html)
        self.assertIn('trackEvent("budget_search_completed"', html)
        self.assertIn('trackEvent("apartment_search_submitted"', html)
        self.assertIn('trackEvent("apartment_search_completed"', html)
        self.assertIn('trackEvent("naver_land_opened"', html)
        self.assertIn('trackEvent("listing_review_completed"', html)
        self.assertIn("cash_eok", html)
        analytics_match = re.search(
            r"function trackEvent\b(?P<body>.*?)"
            r"\n    function trackDailyActiveUser",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(analytics_match)
        self.assertNotIn("policyCash.value", analytics_match.group("body"))
        self.assertNotIn("policyAnnualIncome.value", analytics_match.group("body"))

    def test_candidate_comparison_adds_a_shared_price_trend_chart(self):
        html = APP_HTML.read_text(encoding="utf-8")
        data_match = re.search(
            r"function comparisonTrendData\b(?P<body>.*?)"
            r"\n    function comparisonTrendSegments",
            html,
            re.DOTALL,
        )
        chart_match = re.search(
            r"function comparisonTrendHtml\b(?P<body>.*?)"
            r"\n    function comparisonTableHtml",
            html,
            re.DOTALL,
        )
        open_match = re.search(
            r"async function openComparison\b(?P<body>.*?)"
            r"\n    function closeComparison",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(data_match)
        self.assertIsNotNone(chart_match)
        self.assertIsNotNone(open_match)
        self.assertIn("sparklineMonthlyTransactions(row.roneEstimate, periods)", data_match.group("body"))
        self.assertIn("value / basePrice * 100", data_match.group("body"))
        self.assertIn("trades:monthly.trades", data_match.group("body"))
        self.assertIn('class="comparison-trend-line"', chart_match.group("body"))
        self.assertIn('class="comparison-trend budget-sparkline"', chart_match.group("body"))
        self.assertIn("data-sparkline", chart_match.group("body"))
        self.assertIn('class="budget-sparkline-svg"', chart_match.group("body"))
        self.assertIn('class="spark-grid"', chart_match.group("body"))
        self.assertIn('class="spark-axis-label"', chart_match.group("body"))
        self.assertIn('class="budget-sparkline-legend"', chart_match.group("body"))
        self.assertIn('${esc(candidateDisplayName(item.row))} <em class="spark-legend-rate ${esc(trendClass(item.latestValue))}">${esc(rateText)}</em>', chart_match.group("body"))
        self.assertNotIn('class="spark-summary-values">${summaryValues}', chart_match.group("body"))
        self.assertLess(
            chart_match.group("body").index('class="budget-sparkline-legend"'),
            chart_match.group("body").index('class="budget-sparkline-svg"'),
        )
        self.assertNotIn('<div class="spark-trade-tooltip" data-spark-tooltip role="status" aria-live="polite" hidden></div>\n        <div class="budget-sparkline-legend"', chart_match.group("body"))
        self.assertIn('stroke-width="2.4"', chart_match.group("body"))
        self.assertIn('class="spark-trade-point-group"', chart_match.group("body"))
        self.assertIn("data-spark-point", chart_match.group("body"))
        self.assertIn("data-spark-name", chart_match.group("body"))
        self.assertIn("data-spark-trades", chart_match.group("body"))
        self.assertIn('class="comparison-trend-point"', chart_match.group("body"))
        self.assertIn('r="3"><title>${esc(pointLabel)}</title></circle>', chart_match.group("body"))
        self.assertIn('class="spark-trade-tooltip"', chart_match.group("body"))
        self.assertIn('const width = window.matchMedia("(max-width: 760px)").matches ? 420 : 640;', chart_match.group("body"))
        self.assertIn("const height = 292;", chart_match.group("body"))
        self.assertIn("const plot = { left:44, right:2, top:16, bottom:24 };", chart_match.group("body"))
        self.assertIn('class="spark-tooltip-name"', html)
        self.assertIn("point.dataset.sparkName", html)
        self.assertIn('class="spark-dot comparison-trend-dot"', chart_match.group("body"))
        self.assertNotIn("단지별 기준월", chart_match.group("body"))
        self.assertNotIn("spark-legend-primary", chart_match.group("body"))
        self.assertNotIn('stroke-width="${index === 0 ? "3" : "1.5"}"', chart_match.group("body"))
        self.assertIn("...rows.map(row => loadMarketInsight(row))", open_match.group("body"))
        self.assertIn("...rows.map(row => refreshLocationScoreSheet(row))", open_match.group("body"))
        self.assertIn("comparisonContentHtml(currentRows)", open_match.group("body"))
        self.assertIn("const preserveStep = options?.preserveStep === true;", open_match.group("body"))
        self.assertIn("if (!preserveStep) {", open_match.group("body"))
        self.assertIn('comparisonContent.addEventListener("click"', html)
        self.assertIn('comparisonContent.addEventListener("keydown"', html)
        self.assertIn("showSparkPointDetails(sparkPoint)", html)
        self.assertIn(".comparison-trend {\n      margin:22px -10px 0; padding:0;", html)
        self.assertIn(".comparison-trend .budget-sparkline-svg { width:100%; height:auto; max-height:400px; aspect-ratio:auto }", html)
        self.assertIn(".comparison-trend { margin:18px 0 0; padding:0 }", html)
        self.assertIn(".spark-trade-point-group.is-selected .comparison-trend-point", html)
        self.assertIn(".comparison-trend-dot { border-color:var(--trend-color); border-top-width:2.4px }", html)
        self.assertNotIn(".comparison-trend-chart svg {", html)
        self.assertNotIn("border:1px solid #dfe7f1; border-radius:18px; padding:20px", html)

    def test_mobile_refresh_restores_the_current_spa_page(self):
        html = APP_HTML.read_text(encoding="utf-8")
        save_match = re.search(
            r"function saveRefreshPageState\b(?P<body>.*?)"
            r"\n    async function restoreRefreshPageState",
            html,
            re.DOTALL,
        )
        restore_match = re.search(
            r"async function restoreRefreshPageState\b(?P<body>.*?)"
            r"\n    let activeSearchQuery",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(save_match)
        self.assertIsNotNone(restore_match)
        save_body = save_match.group("body")
        restore_body = restore_match.group("body")
        self.assertIn("refreshPageName()", save_body)
        self.assertIn("currentAptSearchItems[0]", save_body)
        self.assertIn("budgetReturnStatePayload()", save_body)
        self.assertIn("currentBudgetData", html)
        self.assertIn('saved.page === "budget-result"', restore_body)
        self.assertIn('saved.page === "apt-result"', restore_body)
        self.assertIn('saved.page === "region"', restore_body)
        self.assertIn('saved.page === "leader"', restore_body)
        self.assertIn('window.addEventListener("pagehide", saveRefreshPageState)', html)
        self.assertIn("void restoreRefreshPageState()", html)

    def test_mobile_naver_return_restores_budget_candidates_from_backup(self):
        html = APP_HTML.read_text(encoding="utf-8")
        save_match = re.search(
            r"function saveNaverReturnState\b(?P<body>.*?)"
            r"\n    function restoreNaverReturnState",
            html,
            re.DOTALL,
        )
        restore_match = re.search(
            r"function restoreNaverReturnState\b(?P<body>.*?)"
            r"\n    function refreshPageName",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(save_match)
        self.assertIsNotNone(restore_match)
        save_body = save_match.group("body")
        restore_body = restore_match.group("body")
        self.assertIn("const payload = budgetReturnStatePayload();", save_body)
        self.assertIn("sessionStorage.setItem(naverReturnStateKey, serialized)", save_body)
        self.assertIn("localStorage.setItem(naverReturnBackupKey, serialized)", save_body)
        self.assertIn("naverReturnHistoryStateKey", html)
        self.assertIn("history.replaceState(", save_body)
        self.assertIn("history.state?.[naverReturnHistoryStateKey]", restore_body)
        self.assertIn("localStorage.getItem(naverReturnBackupKey)", restore_body)
        self.assertIn("localStorage.removeItem(naverReturnBackupKey)", restore_body)
        self.assertIn('setActiveView("condition")', restore_body)
        self.assertIn("renderBudgetCandidates(saved.currentBudgetData, { preserveSelection:true })", restore_body)

    def test_chart_keeps_regional_average_while_requiring_leader_comparisons(self):
        html = APP_HTML.read_text(encoding="utf-8")
        load_match = re.search(
            r"async function loadCandidateTrendInsight\b(?P<body>.*?)"
            r"\n    function enrichMarketInsights",
            html,
            re.DOTALL,
        )
        direct_match = re.search(
            r"async function loadAptSearchTrendInsight\b(?P<body>.*?)"
            r"\n    function aptPolicyImpactHtml",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(load_match)
        self.assertIsNotNone(direct_match)
        load_body = load_match.group("body")
        self.assertIn("const loaded = await loadMarketInsight(item);", load_body)
        self.assertIn("const leaderContextPromise = ensureLeaderComparisonContext(item, refreshMarketInsight);", load_body)
        self.assertIn("await leaderContextPromise;", load_body)
        self.assertLess(
            load_body.index("const leaderContextPromise = ensureLeaderComparisonContext(item, refreshMarketInsight);"),
            load_body.index("const loaded = await loadMarketInsight(item);"),
        )
        self.assertNotIn("requireLeaderComparison:true", load_body)
        self.assertIn("const series = sparklineSeries(item);", load_body)
        self.assertIn("const chartReady = loaded && Boolean(series);", load_body)
        self.assertIn(
            "leaderComparisonCoverage(item, series).ready",
            load_body,
        )
        self.assertIn("chartReady && !leaderComparisonReady", load_body)
        direct_body = direct_match.group("body")
        self.assertIn("const leaderContextPromise = ensureLeaderComparisonContext(candidate, refreshAptSearchTrendCandidate);", direct_body)
        self.assertIn("const series = sparklineSeries(candidate);", direct_body)
        self.assertIn("const chartReady = Boolean(series);", direct_body)
        self.assertIn(
            "leaderComparisonCoverage(candidate, series).ready",
            direct_body,
        )
        self.assertIn("chartReady && !leaderComparisonReady", direct_body)
        self.assertLess(
            direct_body.index("const leaderContextPromise = ensureLeaderComparisonContext(candidate, refreshAptSearchTrendCandidate);"),
            direct_body.index("const chartReady = Boolean(series);"),
        )
        self.assertIn("async function ensureLeaderComparisonContext(item, onUpdate = refreshMarketInsight)", html)
        self.assertIn("const payload = await requestLeaderContext(item);", html)
        self.assertIn("const complete = await fillLeaderComparisonEstimates(item);", html)
        self.assertIn("function leaderComparisonCoverage(item, existingSeries = null)", html)
        self.assertIn("function usableComparableEstimate(payload)", html)
        self.assertIn("!usableComparableEstimate(result?.payload)", html)
        self.assertIn("if (usableComparableEstimate(item[entry.property])) return;", html)
        self.assertIn("const hasRegionalLeader = Boolean(", html)
        self.assertIn(
            "series && leaderComparisonCoverage(item, series).ready",
            html,
        )
        self.assertIn(
            'const leaderState = item.leaderContextState || (leaderComparisonReady ? "ready" : "idle");',
            html,
        )
        self.assertNotIn("const hasLeaderContext = Boolean(", html)
        self.assertIn(
            "ready:Boolean(series.region) && hasRegionalLeader && localLeaderReady && districtLeaderReady",
            html,
        )
        self.assertIn('const regionLabel = `${regionName} 아파트 평균`;', html)
        self.assertNotIn('`${regionName} 대표 흐름`', html)
        self.assertIn(
            'data-trend-action="load" aria-expanded="false">차트보기</button>',
            html,
        )

    def test_apt_search_reuses_enriched_candidate_data_for_map_and_scores(self):
        html = APP_HTML.read_text(encoding="utf-8")
        sync_match = re.search(
            r"function syncAptSearchCandidateData\b(?P<body>.*?)"
            r"\n    function candidateForLocationScoreButton",
            html,
            re.DOTALL,
        )
        render_match = re.search(
            r"function renderAptCandidateResult\b(?P<body>.*?)"
            r"\n    async function refreshAptSearchTrendAfterAreaChange",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(sync_match)
        self.assertIsNotNone(render_match)
        sync_body = sync_match.group("body")
        self.assertIn("currentAptSearchItems[index] = { ...(previous || {}), ...candidate }", sync_body)
        self.assertIn("aptCandidateResults.set(index, currentAptSearchItems[index])", sync_body)
        self.assertIn('candidateMapOrigin !== "aptSearch"', sync_body)
        self.assertIn("candidateMapEntries.forEach", sync_body)
        self.assertIn("candidateMapLocatedEntries.forEach", sync_body)
        self.assertIn("selectCandidateMapItem(currentAptSearchItems[index], { pan:false })", sync_body)
        self.assertNotIn("fetchAptAffordability", sync_body)
        self.assertIn("candidate = syncAptSearchCandidateData(index, candidate)", render_match.group("body"))
        self.assertIn('<span data-apt-score-badges>${candidateTopScoreBadgesHtml(item)}</span>', html)

    def test_budget_chart_resolves_the_exact_candidate_by_identity_key(self):
        html = APP_HTML.read_text(encoding="utf-8")
        handler_match = re.search(
            r"async function handleBudgetResultClick\b(?P<body>.*?)"
            r"\n    budgetResultEl.addEventListener",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(handler_match)
        handler_body = handler_match.group("body")
        self.assertIn("candidateCard?.dataset.candidateKey", handler_body)
        self.assertIn("candidateIdentityKey(item) === candidateKey", handler_body)
        self.assertNotIn("item.name === candidateName", handler_body)

    def test_view_tab_round_trip_preserves_budget_candidate_state(self):
        html = APP_HTML.read_text(encoding="utf-8")
        clear_match = re.search(
            r"function clearSharedSearchResult\b(?P<body>.*?)"
            r"\n    function leaderReferenceLabel",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(clear_match)
        clear_body = clear_match.group("body")
        self.assertNotIn("resetComparisonState()", clear_body)
        self.assertNotIn("currentBudgetData = null", clear_body)
        self.assertIn('budgetResultEl.addEventListener("click", handleBudgetResultClick)', html)

    def test_leader_region_filters_match_budget_input_style(self):
        html = APP_HTML.read_text(encoding="utf-8")
        style_match = re.search(
            r"\.leader-field select\s*\{(?P<body>.*?)\}",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(style_match)
        style_body = style_match.group("body")
        self.assertIn("appearance:none", style_body)
        self.assertIn("-webkit-appearance:none", style_body)
        self.assertIn("border:1px solid #dfe4ec", style_body)
        self.assertIn("background:#fff; color:#30343b; font-size:15px; font-weight:700", style_body)
        self.assertNotIn("-webkit-appearance:menulist", style_body)
        self.assertIn(".leader-field::after", html)

    def test_mobile_leader_submit_spans_all_gyeonggi_filter_columns(self):
        html = APP_HTML.read_text(encoding="utf-8")

        self.assertIn(".leader-submit { grid-column:1 / -1 }", html)
        self.assertNotIn(".leader-submit { grid-column:1 }", html)

    def test_leader_results_put_a_labeled_back_button_above_the_title(self):
        html = APP_HTML.read_text(encoding="utf-8")
        head_match = re.search(
            r'<div class="leader-result-head">(?P<body>.*?)</div>',
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(head_match)
        head_body = head_match.group("body")
        self.assertLess(head_body.index('id="leaderBackToSearch"'), head_body.index('class="leader-result-copy"'))
        self.assertIn('aria-label="지역 선택 화면으로 뒤로가기"', head_body)
        self.assertIn("<span>뒤로가기</span>", head_body)
        self.assertIn('aria-hidden="true" focusable="false"', head_body)
        self.assertNotIn("조건 바꾸기", head_body)
        self.assertIn("display:inline-flex; align-items:center; justify-self:start;", html)
        self.assertIn('leaderBackToSearch.addEventListener("click"', html)
        self.assertIn('setLeaderStage("search")', html)

    def test_mobile_leader_region_fields_match_budget_form_stack(self):
        html = APP_HTML.read_text(encoding="utf-8")

        self.assertIn(
            '.leader-filter-card[data-region-depth="3"] {\n'
            "        grid-template-columns:minmax(0,1fr);",
            html,
        )
        self.assertIn(
            '.leader-filter-card[data-region-depth="3"] #leaderSigunguField '
            "{ grid-column:1 }",
            html,
        )
        self.assertIn("min-height:56px; border:1px solid transparent; border-radius:13px;", html)
        self.assertIn("background:#f0f2f5; color:#242a32; font-size:17px; font-weight:650;", html)
        self.assertIn(".leader-field select:hover { background:#e9edf1 }", html)

    def test_mobile_leader_price_uses_budget_result_style_instead_of_circle(self):
        html = APP_HTML.read_text(encoding="utf-8")

        self.assertIn("grid-template-columns:minmax(0,1fr) auto; gap:10px 10px; padding:26px 16px;", html)
        self.assertIn(
            "align-items:flex-end; justify-content:flex-start; align-self:start; width:auto; min-width:max-content;",
            html,
        )
        self.assertIn("color:#191f28; text-align:right;", html)
        self.assertIn(".leader-list-end { grid-column:3; justify-content:flex-end;", html)
        self.assertIn(".leader-score strong { margin-top:5px; font-size:24px;", html)
        self.assertNotIn("width:106px; height:106px; border-radius:50%", html)

    def test_mobile_leader_runner_title_wraps_and_badge_sits_below(self):
        html = APP_HTML.read_text(encoding="utf-8")

        self.assertIn(".leader-list-name-row { display:grid; justify-items:start; gap:6px }", html)
        self.assertIn(
            ".leader-list-name { overflow:visible; text-overflow:clip; white-space:normal; line-height:1.35; word-break:keep-all }",
            html,
        )
        self.assertIn(
            ".leader-area-rank-badge {\n      display:inline-flex; align-items:center; flex:none; min-height:22px; border:1px solid #d8dee8; border-radius:999px;",
            html,
        )
        self.assertIn("padding:3px 8px; background:#fff; color:#1767c5;", html)
        self.assertIn(".leader-area-rank-badge { margin-top:1px; border-color:#d8dee8; background:#fff }", html)

    def test_leader_detail_button_is_black_cta(self):
        html = APP_HTML.read_text(encoding="utf-8")

        self.assertIn(
            ".leader-detail-button {\n      min-height:50px; border:1px solid #191f28; border-radius:14px; background:#191f28;",
            html,
        )
        self.assertIn("color:#fff; font-size:15px; font-weight:900; cursor:pointer;", html)
        self.assertIn(".leader-detail-button:hover { border-color:#000; background:#000 }", html)
        self.assertIn(".leader-detail-button:focus-visible { outline:3px solid rgba(25,31,40,.22); outline-offset:2px }", html)

    def test_first_place_leader_card_starts_collapsed_and_keeps_state_during_rerender(self):
        html = APP_HTML.read_text(encoding="utf-8")
        card_match = re.search(
            r"function leaderRankCardHtml\b(?P<body>.*?)"
            r"\n    function renderLeaderResult",
            html,
            re.DOTALL,
        )
        result_match = re.search(
            r"function renderLeaderResult\b(?P<body>.*?)"
            r"\n    async function loadLeaderRanking",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(card_match)
        self.assertIsNotNone(result_match)
        card_body = card_match.group("body")
        self.assertIn('collapsible = false, collapsed = false', card_body)
        self.assertIn('const rootTag = collapsible ? "details" : "article"', card_body)
        self.assertIn('data-leader-winner-toggle', card_body)
        self.assertIn('상세 접기', card_body)
        self.assertIn('상세 펼치기', card_body)
        self.assertIn(
            'leaderRankCardHtml(winner, payload, { collapsible:true, collapsed:leaderWinnerCollapsed })',
            result_match.group("body"),
        )
        self.assertIn('leaderWinnerCollapsed = !leaderWinnerCollapsed', html)
        self.assertIn('let leaderWinnerCollapsed = true;', html)
        self.assertIn('leaderWinnerCollapsed = true;', html)

    def test_gyeonggi_leader_filter_splits_city_and_district(self):
        html = APP_HTML.read_text(encoding="utf-8")
        parts_match = re.search(
            r"function gyeonggiRegionParts\b(?P<body>.*?)"
            r"\n    function syncLeaderSubdistricts",
            html,
            re.DOTALL,
        )
        sync_match = re.search(
            r"function syncLeaderDistricts\b(?P<body>.*?)"
            r"\n    async function loadLeaderRegions",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(parts_match)
        self.assertIsNotNone(sync_match)
        self.assertIn('city:`${cityPrefix}시`', parts_match.group("body"))
        self.assertIn('district:original.slice(cityPrefix.length)', parts_match.group("body"))
        sync_body = sync_match.group("body")
        self.assertIn('leaderSido.value === "경기도"', sync_body)
        self.assertIn('leaderCityField.hidden = !isGyeonggi', sync_body)
        self.assertIn('leaderSigunguLabel.textContent = isGyeonggi ? "구" : "시·군·구"', sync_body)
        self.assertIn('syncLeaderSubdistricts(preferred)', sync_body)
        self.assertIn('id="leaderCity"', html)

    def test_value_ranking_puts_price_in_metric_and_score_in_subcopy(self):
        html = APP_HTML.read_text(encoding="utf-8")
        helper_match = re.search(
            r"function leaderValueScoreHtml\b(?P<body>.*?)"
            r"\n    function syncLeaderDistricts",
            html,
            re.DOTALL,
        )
        presentation_match = re.search(
            r"function leaderRankPresentation\b(?P<body>.*?)"
            r"\n    function leaderRankCardHtml",
            html,
            re.DOTALL,
        )
        card_match = re.search(
            r"function leaderRankCardHtml\b(?P<body>.*?)"
            r"\n    function renderLeaderResult",
            html,
            re.DOTALL,
        )
        result_match = re.search(
            r"function renderLeaderResult\b(?P<body>.*?)"
            r"\n    async function loadLeaderRanking",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(helper_match)
        self.assertIsNotNone(presentation_match)
        self.assertIsNotNone(card_match)
        self.assertIsNotNone(result_match)
        helper_body = helper_match.group("body")
        self.assertIn('payload.category !== "value"', helper_body)
        self.assertIn("leaderScoreText(item.score)", helper_body)
        self.assertIn('class="leader-value-score"', helper_body)
        presentation_body = presentation_match.group("body")
        self.assertIn('isValueRanking = payload.category === "value"', presentation_body)
        self.assertIn(
            "leaderPriceText(item.leaderPrice6m ?? item.leaderPrice12m)",
            presentation_body,
        )
        self.assertIn("leaderValueScoreHtml(item, payload)", card_match.group("body"))
        self.assertIn(
            "leaderValueScoreHtml(item, payload, { compact:true })",
            result_match.group("body"),
        )

    def test_latest_trade_direction_skips_a_flagged_outlier_but_keeps_raw_trade(self):
        html = APP_HTML.read_text(encoding="utf-8")
        trades_match = re.search(
            r"function candidateLatestDirectionTrades\b(?P<body>.*?)"
            r"\n    function candidateLatestTradeDirectionHtml",
            html,
            re.DOTALL,
        )
        direction_match = re.search(
            r"function candidateLatestTradeDirectionHtml\b(?P<body>.*?)"
            r"\n    function candidateLatestTradeOutlierNoteHtml",
            html,
            re.DOTALL,
        )
        note_match = re.search(
            r"function candidateLatestTradeOutlierNoteHtml\b(?P<body>.*?)"
            r"\n    function candidatePriceComparisonContentHtml",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(trades_match)
        self.assertIsNotNone(direction_match)
        self.assertIsNotNone(note_match)
        trades_body = trades_match.group("body")
        direction_body = direction_match.group("body")
        note_body = note_match.group("body")
        self.assertIn(
            ".sort((left, right) => right.date.localeCompare(left.date))",
            trades_body,
        )
        self.assertNotIn("median", trades_body)
        self.assertNotIn("Math.abs(row.price", trades_body)
        self.assertIn("item.comparisonDealPriceEok", direction_body)
        self.assertIn("직전 정상 거래 대비", direction_body)
        self.assertIn("item.previousDealPriceEok", note_body)
        self.assertIn("흐름 비교에서 제외", note_body)
        self.assertIn(
            "latestTrades[0].price / latestTrades[1].price",
            direction_body,
        )

    def test_market_sparkline_compares_price_growth_from_a_common_base(self):
        html = APP_HTML.read_text(encoding="utf-8")
        series_match = re.search(
            r"function sparklineSeries\b(?P<body>.*?)"
            r"\n    function leaderFormulaHtml",
            html,
            re.DOTALL,
        )
        summary_match = re.search(
            r"function candidateTrendSummary\b(?P<body>.*?)"
            r"\n    function candidateTrendSummaryHtml",
            html,
            re.DOTALL,
        )
        summary_html_match = re.search(
            r"function candidateTrendSummaryHtml\b(?P<body>.*?)"
            r"\n    function candidateSparklineHtml",
            html,
            re.DOTALL,
        )
        chart_match = re.search(
            r"function candidateSparklineHtml\b(?P<body>.*?)"
            r"\n    function sparkTradeDetailDate",
            html,
            re.DOTALL,
        )
        legend_match = re.search(
            r"function candidateSparklineLegendHtml\b(?P<body>.*?)"
            r"\n    function candidateSparklineContext",
            html,
            re.DOTALL,
        )
        regional_index_match = re.search(
            r"function regionalIndexValues\b(?P<body>.*?)"
            r"\n    function regionalIndexAtPeriod",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(series_match)
        self.assertIsNotNone(summary_match)
        self.assertIsNotNone(summary_html_match)
        self.assertIsNotNone(chart_match)
        self.assertIsNotNone(legend_match)
        self.assertIsNotNone(regional_index_match)
        series_body = series_match.group("body")
        summary_body = summary_match.group("body")
        summary_html_body = summary_html_match.group("body")
        chart_body = chart_match.group("body")
        legend_body = legend_match.group("body")
        self.assertIn("const complexPrices =", series_body)
        self.assertIn("value / anchorPrice * 100", series_body)
        self.assertIn("value / anchorIndex * 100", series_body)
        self.assertIn("value / leaderAnchorPrice * 100", series_body)
        self.assertIn("item.leaderRoneEstimate", series_body)
        self.assertIn("item.districtLeaderRoneEstimate", series_body)
        self.assertIn("leaderMonthly?.prices[index] != null", series_body)
        self.assertIn("districtLeaderMonthly.prices[index] != null", series_body)
        self.assertIn("value / districtLeaderAnchorPrice * 100", series_body)
        self.assertNotIn("anchorPrice * value / anchorIndex", series_body)
        self.assertIn("anchorPeriod:periods[anchor]", series_body)
        self.assertIn("axisTrend(value)", chart_body)
        self.assertIn('const w = window.matchMedia("(max-width: 760px)").matches ? 420 : 510;', chart_body)
        self.assertIn("const h = 292;", chart_body)
        self.assertIn("const plot = { left:58, right:10, top:16, bottom:24 };", chart_body)
        self.assertIn(".budget-sparkline-svg { display:block; width:100%; max-width:100%; min-width:0; height:auto; max-height:400px; aspect-ratio:auto }", html)
        self.assertIn('return `<svg class="budget-sparkline-svg"', html)
        self.assertNotIn(".flex-fill { flex:1 1 auto; min-width:0 }", html)
        self.assertNotIn("width:calc(100% + 40px)", html)
        self.assertNotIn("width:calc(100% + 28px)", html)
        self.assertNotIn("max-height:320px", html)
        self.assertIn("border:0; border-radius:12px; padding:10px 12px;", html)
        self.assertIn("background:#f8fafc;", html)
        self.assertIn(".insight-trend .trend-toggle { font-size:14px; line-height:1.4 }", html)
        self.assertNotIn("spark-summary-title", summary_html_body)
        self.assertNotIn("spark-summary-message", summary_html_body)
        self.assertIn("windowMonths % 12 === 0", summary_html_body)
        self.assertIn("최근 ${windowMonths / 12}년 기준", summary_html_body)
        self.assertIn('<span class="spark-summary-basis">${esc(windowLabel)}</span>', summary_html_body)
        self.assertIn(".spark-summary-basis { color:#868e99; font-size:14px; font-weight:750; line-height:1.35 }", html)
        self.assertIn(".budget-sparkline-legend { position:relative; display:flex; align-items:center; flex-wrap:wrap; gap:6px 12px; max-width:100%; min-width:0; color:#8b95a1; font-size:14px; font-weight:800; line-height:1.3 }", html)
        self.assertIn(".spark-legend-rate { flex:0 0 auto; color:#191f28; font-size:14px; font-weight:900; white-space:nowrap }", html)
        self.assertNotIn("spark-summary-values", summary_html_body)
        self.assertIn("function sparkLegendRateHtml(value, tone = \"\")", html)
        self.assertIn("${legendHtml}", summary_html_body)
        self.assertIn("candidateSparklineLegendHtml(item, series, summary, context)", html)
        self.assertIn("${esc(complexName)} ${sparkLegendRateHtml(summary.complexValue, summary.tone)}", legend_body)
        self.assertIn("${esc(summary.regionLabel)} ${sparkLegendRateHtml(summary.regionValue)}", legend_body)
        self.assertIn("${esc(series.leaderName)} · ${esc(sharedLeaderRegionName)} 대장 ${sparkLegendRateHtml(summary.leaderValue)}", legend_body)
        self.assertIn("candidateTrendSummaryHtml(summary, legendHtml)", chart_body)
        self.assertIn("const pattern = candidateTrendPattern(series);", summary_body)
        self.assertIn("candidateTrendComparison(complexRate, regionRate, leaderRate, regionLabel, leaderRegionName, series)", summary_body)
        self.assertIn('[pattern.message, comparison].filter(Boolean).join(" ")', summary_body)
        self.assertIn("${esc(summary.regionLabel)} ${sparkLegendRateHtml(summary.regionValue)}", legend_body)
        self.assertIn("series.regionSource.includes(\"R-ONE\")", chart_body)
        self.assertIn("가격 대비 · 지역 흐름은 ${esc(regionBasis)} 기준", chart_body)
        self.assertIn("payload?.index?.history", regional_index_match.group("body"))
        self.assertIn("payload?.adjustedTransactions", regional_index_match.group("body"))
        self.assertIn("regionalIndexValues(payload, periods)", series_body)
        self.assertIn("regionSource:String(payload?.index?.source || \"\")", series_body)
        self.assertNotIn("=100", chart_body)
        self.assertNotIn("%p", chart_body)
        self.assertIn("function candidateTrendPattern(series)", html)
        self.assertIn("function candidateTrendComparison(complexRate, regionRate, leaderRate, regionLabel, leaderRegionName, series = null)", html)
        self.assertNotIn("아파트 시장", chart_body)
        self.assertIn(": [max, 100, min]", chart_body)
        self.assertIn("data-complex-trend-label", chart_body)
        self.assertIn("data-region-trend-label", chart_body)
        self.assertNotIn("spark-peak", chart_body)
        self.assertNotIn("최근 2년 고점", chart_body)
        self.assertNotIn(".spark-peak-", html)
        self.assertIn('stroke="#d99024"', chart_body)
        self.assertIn("spark-dot spark-leader", legend_body)
        self.assertIn('class="spark-legend-item spark-legend-primary"', legend_body)
        self.assertIn(".spark-legend-primary { color:#344054; font-weight:850 }", html)
        self.assertIn(".spark-legend-rate { flex:0 0 auto; color:#191f28; font-size:14px; font-weight:900; white-space:nowrap }", html)
        self.assertIn('class="spark-leader-group"', legend_body)
        self.assertIn('class="spark-legend-item spark-leader-search"', legend_body)
        self.assertIn('data-leader-search-name="${esc(series.leaderName)}"', legend_body)
        self.assertIn('data-leader-search-region="${esc(leaderSearchRegion)}"', legend_body)
        self.assertIn('aria-label="${esc(`${series.leaderName} ${sharedLeaderRegionName} 대장 검색, ${sparklineTrendRateText(summary.leaderValue)}`)}"', legend_body)
        self.assertIn("leaderFormulaHtml(item, leaderRegionName)", html)
        self.assertIn("series.districtLeaderSharesLocality", html)
        self.assertIn("`${leaderRegionName}/${districtLeaderRegionName}`", html)
        self.assertIn("${esc(series.leaderName)} · ${esc(sharedLeaderRegionName)} 대장", legend_body)
        self.assertIn("${esc(series.districtLeaderName)} · ${esc(districtLeaderRegionName)} 대장", legend_body)
        self.assertIn('stroke="#8067c7"', chart_body)
        self.assertNotIn('stroke-dasharray="5 3"', chart_body)
        self.assertIn('stroke="#1677ff" stroke-width="3"', chart_body)
        self.assertIn("spark-dot spark-district-leader", legend_body)
        self.assertNotIn("지역 대장", chart_body)
        self.assertIn('kind:"rebound"', html)
        self.assertIn("최근 하락을 멈추고 반등했어요", html)
        self.assertIn('kind:"downturn"', html)
        self.assertIn("최근 상승을 멈추고 하락했어요", html)
        self.assertIn('kind:"surge"', html)
        self.assertIn("최근 거래에서 가격이 크게 뛰었어요", html)
        self.assertIn('kind:"sharp_drop"', html)
        self.assertIn("최근 거래에서 가격이 크게 떨어졌어요", html)
        self.assertIn("Math.max(3.5, fullRange * .35)", html)
        self.assertIn('kind:"fast_rise"', html)
        self.assertIn("최근 몇 달 동안 가격이 빠르게 올랐어요", html)
        self.assertIn('kind:"fast_fall"', html)
        self.assertIn("최근 몇 달 동안 가격이 빠르게 내렸어요", html)
        self.assertIn("Math.max(5, fullRange * .5)", html)
        self.assertIn('kind:"rise_continuing"', html)
        self.assertIn("최근 거래에서 상승 흐름이 이어졌어요", html)
        self.assertIn("최근 몇 달 동안 상승 흐름이 이어졌어요", html)
        self.assertIn('kind:"rise_slowing"', html)
        self.assertIn("상승은 이어졌지만 최근 상승 폭은 줄었어요", html)
        self.assertIn('kind:"fall_continuing"', html)
        self.assertIn('kind:"fall_slowing"', html)
        self.assertIn('kind:"volatile"', html)
        self.assertIn('kind:"high_flat"', html)
        self.assertIn('kind:"low_flat"', html)
        self.assertIn('kind:"insufficient"', html)
        self.assertIn('kind:"stale"', html)
        self.assertIn('${regionLabel}·${leaderLabel}', html)
        self.assertIn('상승 폭이 ${target.difference > 0 ? "컸어요" : "작았어요"}', html)
        self.assertIn("보다 높은 흐름을 이어갔어요", html)
        self.assertIn('하락 폭이 ${target.difference > 0 ? "작았어요" : "컸어요"}', html)
        self.assertNotIn("지역 대장", summary_body)
        pattern_match = re.search(
            r"function candidateTrendPattern\b(?P<body>.*?)"
            r"\n    function candidateTrendComparison",
            html,
            re.DOTALL,
        )
        comparison_match = re.search(
            r"function candidateTrendComparison\b(?P<body>.*?)"
            r"\n    function candidateTrendSummary",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(pattern_match)
        self.assertIsNotNone(comparison_match)
        factual_copy = pattern_match.group("body") + comparison_match.group("body")
        self.assertNotIn("좋은 흐름", factual_copy)
        self.assertNotIn("흐름이 좋아요", factual_copy)
        self.assertNotIn("잘 버티", factual_copy)
        self.assertNotIn("지켜봐야", factual_copy)
        self.assertNotIn("방어력", factual_copy)
        self.assertNotIn("매수", factual_copy)
        self.assertNotIn("추천", factual_copy)
        self.assertIn('aria-label="${esc(`${regionName} 대장아파트 산정식 보기`)}"', html)
        self.assertIn("전용 ${leaderAreaText(targetArea)}㎡ 실거래 중위가", html)
        self.assertIn("leaderRepresentativeArea", html)
        self.assertIn("leaderRepresentativeMedianPrice12m", html)
        self.assertIn("실제 거래 중앙면적", html)
        self.assertIn("기준 거래가 2건 미만인 단지는 기본 대장에서 제외", html)
        self.assertNotIn("실거래가 × (${esc(leaderAreaText(targetArea))} ÷ 실제면적)<sup>0.75</sup>", html)
        self.assertNotIn("최근 12개월 중위가", html)
        self.assertIn("전용 84㎡ 실거래", html)
        self.assertNotIn("가격 수준 · 35%", html)
        self.assertNotIn("상승 선도력 · 25%", html)
        self.assertNotIn("역 접근성 · 10%", html)
        self.assertIn("syncSparkAxisLabelSizes();\n      hideSparkTooltips();", html)
        self.assertIn(".spark-axis-label { fill:#7b8491; font-size:var(--spark-axis-font-size,13px); font-weight:700 }", html)
        self.assertIn("const minRenderedSize = 13;", html)
        self.assertIn("const maxRenderedSize = 13;", html)
        self.assertIn('const targetRenderedSize = window.matchMedia("(max-width: 760px)").matches', html)
        self.assertIn("const renderedFontSize = Math.min(maxRenderedSize, Math.max(minRenderedSize, targetRenderedSize));", html)
        self.assertIn("renderedFontSize / renderedScale", html)
        self.assertIn('const leaderSearch = event.target.closest("[data-leader-search-name]");', html)
        self.assertIn("await runLeaderApartmentSearch(leaderSearch);", html)
        self.assertIn("void runLeaderApartmentSearch(leaderSearch);", html)
        self.assertIn("async function runLeaderApartmentSearch(trigger)", html)
        self.assertIn("await runAptSearch(name, selectedItem);", html)
        self.assertIn(".spark-leader-search:hover", html)
        self.assertIn("text-decoration:underline", html)
        self.assertIn("text-underline-offset:3px", html)

    def test_market_sparkline_labels_the_regional_leader_itself(self):
        html = APP_HTML.read_text(encoding="utf-8")
        chart_match = re.search(
            r"function candidateSparklineContext\b(?P<body>.*?)"
            r"\n    function candidateSparklineHtml",
            html,
            re.DOTALL,
        )
        legend_match = re.search(
            r"function candidateSparklineLegendHtml\b(?P<body>.*?)"
            r"\n    function candidateSparklineContext",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(chart_match)
        self.assertIsNotNone(legend_match)
        context_body = chart_match.group("body")
        legend_body = legend_match.group("body")
        self.assertIn("item.signals?.isRegionalLeader", context_body)
        self.assertIn('class="spark-leader-badge"', context_body)
        self.assertIn("(${esc(selfLeaderRegionName)} 대장)", context_body)
        self.assertIn("${esc(complexName)} ${sparkLegendRateHtml(summary.complexValue, summary.tone)}${selfLeaderBadgeHtml}", legend_body)
        self.assertIn("item.signals?.isDistrictLeader", context_body)
        self.assertIn(".spark-leader-badge {", html)
        self.assertNotIn(".spark-self-leader {", html)

    def test_budget_chart_loads_leader_context_then_both_series_in_parallel(self):
        html = APP_HTML.read_text(encoding="utf-8")
        context_match = re.search(
            r"async function requestLeaderContext\b(?P<body>.*?)"
            r"\n    function applyLeaderContext",
            html,
            re.DOTALL,
        )
        load_match = re.search(
            r"async function loadMarketInsight\b(?P<body>.*?)"
            r"\n    async function loadCandidateTrendInsight",
            html,
            re.DOTALL,
        )
        selected_match = re.search(
            r"async function loadCandidateTrendInsight\b(?P<body>.*?)"
            r"\n    function enrichMarketInsights",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(context_match)
        self.assertIsNotNone(load_match)
        self.assertIsNotNone(selected_match)
        self.assertIn("/api/apartment-leader-context?", context_match.group("body"))
        load_body = load_match.group("body")
        self.assertIn("const leaderRequest = leaderItem", load_body)
        self.assertIn("const districtLeaderRequest = districtLeaderItem", load_body)
        self.assertIn("await Promise.all([", load_body)
        selected_body = selected_match.group("body")
        self.assertIn("const leaderContextPromise = ensureLeaderComparisonContext(item, refreshMarketInsight);", selected_body)
        self.assertIn("const payload = await requestLeaderContext(item);", html)
        self.assertIn("const complete = await fillLeaderComparisonEstimates(item);", html)
        self.assertIn("await loadMarketInsight(item)", selected_body)
        self.assertLess(
            selected_body.index("const leaderContextPromise = ensureLeaderComparisonContext(item, refreshMarketInsight);"),
            selected_body.index("const loaded = await loadMarketInsight(item);"),
        )
        self.assertIn("await leaderContextPromise;", selected_body)
        self.assertNotIn("requireLeaderComparison:true", selected_body)
        self.assertIn("const series = sparklineSeries(item);", selected_body)
        self.assertIn("const chartReady = loaded && Boolean(series);", selected_body)
        self.assertIn(
            "leaderComparisonCoverage(item, series).ready",
            selected_body,
        )
        self.assertIn("대장 비교 불러오는 중", html)
        self.assertIn("await loadCandidateTrendInsight(candidate)", html)

    def test_candidate_insight_shows_factual_price_flow_and_news(self):
        html = APP_HTML.read_text(encoding="utf-8")
        summary_lines_match = re.search(
            r"function candidateChoiceSummaryLines\(item\) \{(?P<body>.*?)"
            r"\n    function candidateChoiceSummaryHtml",
            html,
            re.DOTALL,
        )
        trend_insight_match = re.search(
            r"function candidateTrendInsightHtml\(item, options = \{\}\) \{(?P<body>.*?)"
            r"\n    function candidateVerdictHtml",
            html,
            re.DOTALL,
        )
        verdict_match = re.search(
            r"function candidateVerdictHtml\(item, options = \{\}\) \{(?P<body>.*?)"
            r"\n    // 중수용 근거 숫자",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(summary_lines_match)
        self.assertIsNotNone(trend_insight_match)
        self.assertIsNotNone(verdict_match)
        summary_lines_body = summary_lines_match.group("body")
        trend_insight_body = trend_insight_match.group("body")
        verdict_body = verdict_match.group("body")
        self.assertIn("const trendSummary = candidateTrendSummary(item);", summary_lines_body)
        self.assertIn("? [trendMessage]", summary_lines_body)
        self.assertIn("가격 흐름을 비교할 자료가 부족해요", summary_lines_body)
        self.assertNotIn("candidateChoiceFundingCost", summary_lines_body)
        self.assertNotIn("candidateChoiceCatalystSubject", summary_lines_body)
        self.assertNotIn("candidateChoiceGains", summary_lines_body)
        self.assertNotIn('<span class="insight-kicker">시세 흐름</span>', html)
        self.assertNotIn(".insight-kicker {", html)
        self.assertNotIn('<span class="insight-kicker">핵심 요약</span>', html)
        self.assertIn('<ul class="insight-title">${lines.map(line => `<li>${esc(line)}</li>`).join("")}</ul>', html)
        self.assertIn(".insight-title {\n      display:grid; gap:5px; margin:0;", html)
        self.assertIn("font-size:14px; font-weight:650; line-height:1.45;", html)
        self.assertNotIn(".insight-title li::before", html)
        self.assertIn(".condition-stage-results .insight-summary { padding:10px 12px }", html)
        self.assertIn("${candidateTrendInsightHtml(item, options)}", verdict_body)
        self.assertIn("${candidateRelatedNewsHtml(item)}", verdict_body)
        self.assertLess(
            verdict_body.index("${candidateRelatedNewsHtml(item)}"),
            verdict_body.index("${candidateTrendInsightHtml(item, options)}"),
        )
        self.assertIn("candidateTrendPanelHtml(item, series)", trend_insight_body)
        self.assertIn('<div class="trend-status" data-trend-control>${controlHtml}</div>', trend_insight_body)
        self.assertIn('class="insight-news"', html)
        self.assertIn('class="insight-news-item"', html)
        self.assertIn('data-trend-toggle data-trend-action="toggle"', html)
        self.assertIn("차트보기", html)

    def test_direct_apartment_search_keeps_funding_impact_in_core_summary(self):
        html = APP_HTML.read_text(encoding="utf-8")
        candidate_match = re.search(
            r"function aptMarketCandidate\b(?P<body>.*?)"
            r"\n    async function enrichAptLeaderEstimate",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(candidate_match)
        body = candidate_match.group("body")
        self.assertIn("...canonical", body)
        self.assertIn("policyImpact:canonical.policyImpact || data?.policyImpact || null", body)
        self.assertIn("signals:canonical.signals || {}", body)
        self.assertIn("locationScore:canonical.locationScore || report?.locationScore || item?.locationScore || null", body)

    def test_condition_stepper_is_hidden_on_candidate_results(self):
        html = APP_HTML.read_text(encoding="utf-8")
        self.assertIn("--app-header-sticky-height:64px", html)
        self.assertIn("position:sticky; top:0; z-index:60", html)
        self.assertIn("top:var(--app-header-sticky-height); z-index:20", html)
        self.assertIn("top:calc(var(--app-header-sticky-height) + 68px)", html)
        self.assertIn("body.condition-stage-results #conditionView .condition-flow { display:none }", html)
        self.assertIn(
            "body.condition-stage-results .power-persistent {\n"
            "        top:calc(var(--app-header-sticky-height) + 8px);",
            html,
        )
        self.assertIn(
            ".power-persistent { top:64px; width:100%; margin-top:8px; "
            "border-radius:15px; padding:8px 12px }",
            html,
        )
        self.assertIn(
            "body.condition-stage-results .power-persistent { top:calc(var(--app-header-sticky-height) + 12px); margin-top:8px }",
            html,
        )
        self.assertIn(
            "position:sticky; top:calc(var(--app-header-sticky-height) + 12px); z-index:18;",
            html,
        )
        self.assertNotIn("condition-flow.is-scroll-hidden", html)
        self.assertNotIn("condition-flow-scroll-hidden", html)
        self.assertNotIn("updateConditionFlowForScroll", html)
        self.assertNotIn("setConditionFlowScrollHidden", html)

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

    def test_condition_region_selection_refreshes_selected_chips(self):
        html = APP_HTML.read_text(encoding="utf-8")
        sync_match = re.search(
            r"function syncConditionEditRegionSelectedChips\b(?P<body>.*?)"
            r"\n    function conditionEditFieldHtml",
            html,
            re.DOTALL,
        )
        change_match = re.search(
            r'conditionItemEditForm\.addEventListener\("change", event => \{(?P<body>.*?)'
            r"\n    \}\);",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(sync_match)
        self.assertIsNotNone(change_match)
        self.assertIn("chips.outerHTML = conditionEditRegionSelectedChipsHtml();", sync_match.group("body"))
        self.assertIn("syncConditionRegionChoices(event.target);", change_match.group("body"))
        self.assertIn("syncConditionEditRegionSelectedChips();", change_match.group("body"))

    def test_result_header_shows_all_selected_house_conditions(self):
        html = APP_HTML.read_text(encoding="utf-8")
        summary_match = re.search(
            r"function persistentPreferenceSummary\b(?P<body>.*?)"
            r"\n    function renderPersistentRegion",
            html,
            re.DOTALL,
        )
        render_match = re.search(
            r"function renderPreferenceSinglePickers\b(?P<body>.*?)"
            r"\n    function openPreferenceSinglePicker",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(summary_match)
        self.assertIsNotNone(render_match)
        summary_body = summary_match.group("body")
        self.assertIn('selectionSummary("region")', summary_body)
        self.assertIn("selectedOptionText(budgetMinArea)", summary_body)
        self.assertIn("`세대수 ${selectedOptionText(budgetMinHouseholds)}`", summary_body)
        self.assertIn("selectedOptionText(budgetMaxBuildingAge)", summary_body)
        self.assertIn('.join(" · ")', summary_body)
        self.assertIn("renderPersistentRegion();", render_match.group("body"))
        self.assertIn(".power-persistent-copy { overflow:hidden; flex-wrap:nowrap; gap:8px }", html)
        self.assertIn("text-overflow:ellipsis; white-space:nowrap", html)
        self.assertIn('data-condition-summary-open="power"] { flex:0 0 auto; padding-right:6px }', html)
        self.assertIn("flex:1 1 0; min-width:0; overflow:hidden", html)
        self.assertIn('<span class="power-persistent-label">매매가 상한</span>', html)
        self.assertIn('<span class="power-persistent-label">지역</span>', html)
        self.assertIn('>변경</button>', html)
        self.assertIn('{ label:"매매가 상한", value:budgetLabel', html)
        self.assertIn('{ label:"지역", value:regionLabel', html)

    def test_candidate_map_header_shows_full_selected_conditions(self):
        html = APP_HTML.read_text(encoding="utf-8")
        condition_match = re.search(
            r"function candidateMapConditionItems\b(?P<body>.*?)"
            r"\n    function candidateMapConditionShortcutHtml",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(condition_match)
        condition_body = condition_match.group("body")
        self.assertIn('const regionLabel = selectionSummary("region")', condition_body)
        self.assertNotIn('compactSelectionSummary("region")', condition_body)
        self.assertIn('{ label:"전용면적", value:selectedOptionText(budgetMinArea)', condition_body)
        self.assertIn('{ label:"세대수", value:selectedOptionText(budgetMinHouseholds)', condition_body)
        self.assertIn('{ label:"연식", value:selectedOptionText(budgetMaxBuildingAge)', condition_body)
        self.assertIn(".candidate-map-condition-copy {\n        flex-wrap:wrap;", html)
        self.assertNotIn(".candidate-map-condition-shortcut:nth-child(n+3)", html)

    def test_apartment_suggestions_render_as_search_page_content(self):
        html = APP_HTML.read_text(encoding="utf-8")
        search_box = re.search(
            r'<div class="apt-search" id="aptSearchBox">(?P<body>.*?)'
            r"\n      </div>",
            html,
            re.DOTALL,
        )
        landing = re.search(
            r'<div class="app-view apt-search-landing" id="aptSearchLanding"'
            r'(?P<body>.*?)\n    </div>\n\n    <div class="app-view condition-stage-results"',
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(search_box)
        self.assertIsNotNone(landing)
        self.assertNotIn('id="aptSearchSuggest"', search_box.group("body"))
        self.assertIn('id="aptSearchSuggest"', landing.group("body"))
        self.assertIn(
            "body.apt-search-mode.apt-search-suggest-open "
            ".apt-search-landing:not([hidden])",
            html,
        )
        self.assertIn("padding:20px 0 56px", html)
        self.assertIn("padding-top:14px", html)
        self.assertIn(
            "body.apt-search-mode #aptSearchView:not([hidden]) { padding-top:16px }",
            html,
        )
        suggest_style = re.search(
            r"\.apt-search-suggest \{(?P<body>.*?)\}",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(suggest_style)
        self.assertNotIn("position:absolute", suggest_style.group("body"))
        self.assertNotIn("box-shadow", suggest_style.group("body"))

    def test_search_results_start_the_common_candidate_enrichment(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r"async function runAptSearch\b(?P<body>.*?)"
            r"\n    const aptReportCache",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertNotIn("enrichAptCards(items)", body)
        self.assertIn("void enrichAptAffordability(items);", body)
        self.assertIn("동일한 공통 후보 응답", body)
        self.assertNotIn("openAptAreaSheet(0)", body)
        self.assertIn('aptSearchInput.value = "";', body)
        self.assertLess(
            body.index('aptSearchInput.value = "";'),
            body.index("if (!items.length)"),
        )

    def test_apartment_search_field_uses_black_six_percent_stroke(self):
        html = APP_HTML.read_text(encoding="utf-8")

        self.assertIn("border:1px solid rgba(0,0,0,.06)", html)
        self.assertIn(
            "body.apt-search-mode .apt-search form { height:50px; border-color:rgba(0,0,0,.06)",
            html,
        )

    def test_apartment_results_require_an_exact_clicked_suggestion(self):
        html = APP_HTML.read_text(encoding="utf-8")
        fallback_match = re.search(
            r"function aptSearchFallbackItem\b(?P<body>.*?)"
            r"\n    function aptSearchResultItems",
            html,
            re.DOTALL,
        )
        result_match = re.search(
            r"function aptSearchResultItems\b(?P<body>.*?)"
            r"\n    async function runAptSearch",
            html,
            re.DOTALL,
        )
        run_match = re.search(
            r"async function runAptSearch\b(?P<body>.*?)"
            r"\n    const aptReportCache",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(fallback_match)
        self.assertIsNotNone(result_match)
        self.assertIsNotNone(run_match)
        self.assertIn("!selectedItem", fallback_match.group("body"))
        self.assertIn('String(query || "").trim() !== name', fallback_match.group("body"))
        self.assertIn("if (!fallback) return [];", result_match.group("body"))
        self.assertIn("const regionMatches = (left, right) =>", result_match.group("body"))
        self.assertIn("leftKey.includes(rightKey) || rightKey.includes(leftKey)", result_match.group("body"))
        self.assertIn("selectedItem.legalDong", result_match.group("body"))
        self.assertIn("selectedItem.jibun", result_match.group("body"))
        self.assertIn("item.legalDong", result_match.group("body"))
        self.assertIn("item.jibun", result_match.group("body"))
        self.assertIn("...exactSelectedItems[0]", result_match.group("body"))
        self.assertIn("displayRegion:String(exact.displayRegion || exact.address", result_match.group("body"))
        self.assertIn("legalDong:String(exact.legalDong || selectedItem.legalDong", result_match.group("body"))
        self.assertIn("jibun:String(exact.jibun || selectedItem.jibun", result_match.group("body"))
        self.assertIn("preferredArea:String(selectedItem.preferredArea", result_match.group("body"))
        self.assertIn("return [fallback];", result_match.group("body"))
        self.assertNotIn("if (items.length) return items;", result_match.group("body"))
        self.assertIn("if (!aptSearchFallbackItem(query, selectedItem))", run_match.group("body"))
        self.assertIn("const fallback = aptSearchFallbackItem(query, selectedItem);", run_match.group("body"))
        self.assertIn("items = [fallback];", run_match.group("body"))

    def test_apartment_search_submit_does_not_expose_partial_match_results(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r'aptSearchForm\.addEventListener\("submit", event => \{(?P<body>.*?)'
            r'\n    \}\);',
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("event.preventDefault();", body)
        self.assertIn("openAptSearchLanding({ focus:false });", body)
        self.assertNotIn("runAptSearch", body)

    def test_apartment_affordability_request_times_out_instead_of_loading_forever(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r"async function fetchAptAffordability\b(?P<body>.*?)"
            r"\n    async function fetchAptAreaOptions",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("const controller = new AbortController();", body)
        self.assertIn("setTimeout(() => controller.abort(), MARKET_INSIGHT_TIMEOUT_MS);", body)
        self.assertIn("signal:controller.signal", body)
        self.assertIn("finally(() => clearTimeout(timeout))", body)
        self.assertIn('search_region:item.region || ""', body)
        self.assertIn('legal_dong:item.legalDong || ""', body)
        self.assertIn('jibun:item.jibun || ""', body)
        self.assertIn("budget:currentPurchasePower?.budgetEok", body)
        self.assertIn("min_area:area ? 0 : budgetMinArea.value", body)
        self.assertIn("min_households:0", body)
        self.assertIn("max_building_age:0", body)
        self.assertNotIn("min_households:budgetMinHouseholds.value", body)
        self.assertNotIn("max_building_age:budgetMaxBuildingAge.value", body)

    def test_chart_request_uses_canonical_name_and_physical_identity(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r"async function requestRoneEstimate\b(?P<body>.*?)"
            r"\n    function candidateLeaderEstimateItem",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("name:item.name || candidateDisplayName(item)", body)
        self.assertIn('params.set("legal_dong", item.legalDong)', body)
        self.assertIn('params.set("jibun", item.jibun)', body)

    def test_leader_comparison_requests_do_not_reuse_candidate_area(self):
        html = APP_HTML.read_text(encoding="utf-8")
        leader_match = re.search(
            r"function candidateLeaderEstimateItem\(item\) \{(?P<body>.*?)"
            r"\n    function candidateDistrictLeaderEstimateItem",
            html,
            re.DOTALL,
        )
        district_match = re.search(
            r"function candidateDistrictLeaderEstimateItem\(item\) \{(?P<body>.*?)"
            r"\n    async function requestComparableEstimate",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(leader_match)
        self.assertIsNotNone(district_match)
        leader_body = leader_match.group("body")
        district_body = district_match.group("body")
        for body in (leader_body, district_body):
            self.assertIn("legalDong:", body)
            self.assertIn("jibun:", body)
            self.assertNotIn("latestDealExclusiveArea", body)
            self.assertNotIn("areaMin", body)
            self.assertNotIn("areaMax", body)

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

    def test_candidate_buttons_open_review_report_without_score(self):
        html = APP_HTML.read_text(encoding="utf-8")
        report_match = re.search(
            r"function candidateSignalReportHtml\b(?P<body>.*?)"
            r"\n    function candidateDisplayName",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(report_match)
        report_body = report_match.group("body")
        self.assertIn("function candidateSharedActionsHtml", html)
        self.assertIn("리포트 보기", html)
        self.assertNotIn('<span data-candidate-signal-label>최근 가격 흐름', html)
        self.assertNotIn("${candidateSignalRankBadgeHtml(item)}", html)
        self.assertNotIn("매수 후보 분석", report_body)
        for title in ("종합 의견", "가격 의견", "주의할 점"):
            self.assertIn(f"<h4>{title}</h4>", report_body)
        self.assertIn("candidateReviewReferenceHtml(item)", report_body)
        self.assertIn('<h3 class="candidate-review-title">${esc(general.headline)} ${esc(caution.headline)}</h3>', report_body)
        self.assertIn('<p class="candidate-review-subtitle">${esc(price.headline)}</p>', report_body)
        self.assertNotIn('<h3 class="candidate-review-title">${esc(price.headline)}</h3>', report_body)
        self.assertLess(report_body.index("<h4>종합 의견</h4>"), report_body.index("<h4>가격 의견</h4>"))
        self.assertLess(report_body.index("<h4>가격 의견</h4>"), report_body.index("<h4>주의할 점</h4>"))
        self.assertIn("실제 수요가 넓어졌다고 단정하긴 어려워요", html)
        self.assertIn("가격과 거래량이 함께 증가하고 있어요", html)
        self.assertIn("가격과 거래가 늘었지만 표본이 적어요", html)
        self.assertNotIn("가격과 거래가 함께 좋아지고 있어요", html)
        self.assertIn("${periodLabel} 거래량은 직전 6개월보다", html)
        self.assertIn('<span class="signal-report-score-value">${esc(score)}점</span>', html)
        self.assertIn("최근 시장 신호 측정 불가", html)
        self.assertIn("확인된 자료로는 최근 시장 신호를 측정할 수 없어요", html)
        self.assertIn("score <= 0", html)
        self.assertIn("`${flowLabel} 측정 불가`", html)
        self.assertIn("candidateReviewSnapshotHtml(item, price, caution)", report_body)
        self.assertIn("candidate-review-section-lead", report_body)
        for label in (
            "최근 시세와 비슷해요",
            "가격이 높은 편이에요",
            "가격이 낮은 이유를 확인하세요",
            "거래가 적어 판단이 어려워요",
            "현재 매물가를 확인해 주세요",
            "호가 확인이 필요해요",
        ):
            self.assertIn(label, html)
        self.assertIn("function candidateReviewTradeRecency", html)
        self.assertIn("ageDays <= 92", html)
        self.assertIn("마지막 거래 기준 시장 신호", html)
        self.assertNotIn("참고 범위 안", html)
        self.assertIn(".candidate-review-snapshot { display:flex", html)
        self.assertIn(".candidate-review-snapshot-value { overflow-wrap:anywhere; color:#667085; font-size:12px", html)
        self.assertIn(".candidate-detail-sheet .candidate-review-report,.apt-report-sheet .candidate-review-report { gap:0 }", html)
        self.assertIn(".candidate-review-section { padding:14px 0", html)

    def test_signal_peer_cards_focus_the_matching_budget_result(self):
        html = APP_HTML.read_text(encoding="utf-8")
        focus_match = re.search(
            r"function focusBudgetCandidateResult\b(?P<body>.*?)"
            r"\n    function budgetLoadingStageIndex",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(focus_match)
        body = focus_match.group("body")
        self.assertIn("setCandidateDetailOpen(sheet, false)", body)
        self.assertIn("setCandidateMapDetailOpen(false)", body)
        self.assertIn('setCandidateViewMode("list")', body)
        self.assertIn("candidateVisibleCount = Math.max(", body)
        self.assertIn("renderBudgetCandidates(currentBudgetData, { preserveSelection:true });", body)
        self.assertIn('targetCard.scrollIntoView({ behavior:"smooth", block:"center" });', body)
        self.assertIn("targetCard.focus({ preventScroll:true });", body)
        self.assertIn("focusBudgetCandidateResult(signalPeer.dataset.signalPeerKey);", html)
        self.assertIn('tabindex="-1" data-candidate-name=', html)
        self.assertIn("void runApartmentResultSearch({", html)
        self.assertIn('data-leader-detail-area-target="${esc(detailAreaTarget)}"', html)
        self.assertIn("단지 검색 결과 보기", html)
        self.assertNotIn("openAptReport(peer.dataset.aptPeerName", html)
        self.assertNotIn("최근 상승 흐름 리포트 보기", html)

    def test_map_leader_click_moves_map_and_syncs_apartment_search_value(self):
        html = APP_HTML.read_text(encoding="utf-8")
        focus_match = re.search(
            r"async function focusCandidateMapLeader\b(?P<body>.*?)"
            r"\n    async function runLeaderApartmentSearch",
            html,
            re.DOTALL,
        )
        navigation_match = re.search(
            r"async function runLeaderApartmentSearch\b(?P<body>.*?)"
            r"\n    const aptReportCache",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(focus_match)
        self.assertIsNotNone(navigation_match)
        focus_body = focus_match.group("body")
        navigation_body = navigation_match.group("body")
        self.assertIn("/api/apartment-suggest?q=", focus_body)
        self.assertIn("&region=${encodeURIComponent(region)}", focus_body)
        self.assertIn("mapAddress:candidateMapAddress", focus_body)
        self.assertIn("geocodeCandidate(geocoder, kakao, mapItem)", focus_body)
        self.assertIn("appendCandidateMapEntry(kakao, mapItem, position)", focus_body)
        self.assertIn("selectCandidateMapItem(entry.item)", focus_body)
        self.assertIn("aptSearchInput.value = name;", navigation_body)
        self.assertIn('candidateViewMode === "map" && candidateMap', navigation_body)
        self.assertIn("await focusCandidateMapLeader(name, region);", navigation_body)
        self.assertIn("await runApartmentResultSearch({ name, region });", navigation_body)

    def test_map_geocode_cache_uses_complex_identity_not_only_address(self):
        html = APP_HTML.read_text(encoding="utf-8")
        cache_match = re.search(
            r"function candidateMapLocationKey\b(?P<body>.*?)"
            r"\n    function candidateMapCacheKey",
            html,
            re.DOTALL,
        )
        coordinates_match = re.search(
            r"function candidateCoordinates\b(?P<body>.*?)"
            r"\n    async function loadKakaoMapApi",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(cache_match)
        self.assertIsNotNone(coordinates_match)
        cache_body = cache_match.group("body")
        self.assertIn("item.name || item.apartmentName", cache_body)
        self.assertIn("item.legalDong || item.dong", cache_body)
        self.assertIn("item.jibun", cache_body)
        self.assertIn("realEstateSearch.mapGeocode.v2", html)
        self.assertIn("inKoreaMetroBounds", coordinates_match.group("body"))

    def test_region_leader_area_field_switches_list_and_detail_area(self):
        html = APP_HTML.read_text(encoding="utf-8")

        self.assertIn("우리 동네 아파트 대장 찾기", html)
        self.assertIn("지역과 면적을 고르면 실거래 상위 아파트를 보여드려요.", html)
        self.assertNotIn("leader-price-help", html)
        self.assertNotIn("대장아파트 실거래 기준 보기", html)
        self.assertIn('leaderReferenceCaption.textContent = "";', html)
        self.assertIn("leaderReferenceCaption.hidden = true;", html)
        self.assertNotIn("84㎡ 리스트는 그대로 보고", html)
        self.assertNotIn("59㎡를 누르면 소형 평형 리스트", html)
        self.assertIn('<label for="leaderAreaSelect">면적</label>', html)
        self.assertIn('<select id="leaderAreaSelect" aria-label="면적 선택">', html)
        self.assertIn('<option value="70-89">전용 84㎡</option>', html)
        self.assertIn('<option value="50-69">전용 59㎡</option>', html)
        self.assertNotIn('id="leaderAreaTabs"', html)
        self.assertNotIn('data-leader-area-bucket', html)
        self.assertIn('leaderAreaSelect?.addEventListener("change"', html)
        self.assertIn('const next = leaderAreaSelect.value || "70-89";', html)
        self.assertIn("function renderLeaderAreaSelect()", html)
        self.assertIn("async function fetchLeaderRanking(category, limit, signal, areaBucket = activeLeaderAreaBucket)", html)
        self.assertIn("areaBucket,", html)
        self.assertIn('id="leaderAreaComparison"', html)
        self.assertIn("function leaderAreaRankBadgeHtml(item, payload)", html)
        self.assertIn("const LEADER_RANK_LIMIT = 20;", html)
        self.assertIn('const label = baseRank ? `84㎡에서는 ${baseRank}위` : `84㎡에서는 ${LEADER_RANK_LIMIT}위 밖`;', html)
        self.assertIn('class="leader-area-rank-badge"', html)
        self.assertIn("${leaderAreaRankBadgeHtml(item, payload)}</${headingTag}>", html)
        self.assertIn("${leaderAreaRankBadgeHtml(item, payload)}</span>", html)
        self.assertIn('leaderAreaComparison.innerHTML = "";', html)
        self.assertNotIn('`<strong class="leader-list-area">최근 6개월 · ${esc(areaLabel)} 실거래</strong> · `', html)
        self.assertNotIn("59㎡ 대장은 ${esc(currentName)}예요.", html)
        self.assertNotIn("84㎡와 59㎡ 대장이 같아요.", html)
        self.assertNotIn("2위 이하 상위권도 많이 달라져요.", html)
        self.assertNotIn('2~30위 중 ${changedRanks.map(rank => `${rank}위`).join(", ")}는 바뀌었어요.', html)
        self.assertNotIn("30위 밖", html)
        self.assertIn('const payload = await fetchLeaderRanking(activeLeaderCategory, LEADER_RANK_LIMIT, signal);', html)
        self.assertIn('const basePayload = await fetchLeaderRanking("price", LEADER_RANK_LIMIT, signal, "70-89");', html)
        self.assertIn('data-leader-detail-area-target="${esc(detailAreaTarget)}"', html)
        self.assertIn('data-leader-detail-legal-dong="${esc(item.dong || "")}"', html)
        self.assertIn('data-leader-detail-jibun="${esc(item.jibun || "")}"', html)
        self.assertIn("legalDong:detail.dataset.leaderDetailLegalDong || \"\"", html)
        self.assertIn("jibun:detail.dataset.leaderDetailJibun || \"\"", html)
        self.assertIn('data-leader-map-detail ${detailAttrs}', html)
        self.assertGreaterEqual(html.count("preferredArea:detail.dataset.leaderDetailAreaTarget || leaderAreaProfile().target"), 2)

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
        self.assertIn("previousTrendToggle", refresh_match.group("body"))
        self.assertIn("previousTrendPanel", refresh_match.group("body"))
        self.assertIn("candidateVerdictHtml(item, { trendExpanded })", refresh_match.group("body"))
        self.assertIn("sparklineEl.hidden = !trendExpanded;", refresh_match.group("body"))
        self.assertIn("removeOverCapCandidate(item);", refresh_match.group("body"))

    def test_policy_impact_omits_manual_naver_asking_price_check(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r"function policyImpactHtml\b(?P<body>.*?)"
            r"\n    function syncCoBorrowerFields",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertNotIn("impact.growthScenario", body)
        self.assertNotIn('scenario.type === "regional_growth"', body)
        self.assertNotIn("askingPriceCheckHtml", html)
        self.assertNotIn("확인한 매물가", html)
        self.assertNotIn('data-asking-price-form', html)
        self.assertNotIn('getJson("/api/asking-price-financing"', html)
        self.assertNotIn('asking_price_submitted', html)
        self.assertNotIn('check.classList.add("is-ready")', html)
        self.assertNotIn('policy-cash-scenario-copy">입력 매물가', html)
        self.assertIn("const requiredCashValues = scenarios", body)
        self.assertIn("예상 필요 자기자금 ${policyMoney(requiredMin)}~${policyMoney(requiredMax)}", body)
        self.assertIn('class="policy-cash-label">예상 필요 자기자금</span>', body)
        self.assertIn('<strong class="policy-cash-amount">${esc(requiredAmountText)}</strong>', body)
        self.assertIn(".policy-cash-label { color:#191f28; font-size:15px; font-weight:900; line-height:1.35 }", html)
        self.assertIn(".condition-stage-results .policy-metric.policy-cash-summary .policy-cash-label {\n      color:#191f28; font-size:15px; font-weight:900;", html)
        self.assertIn("최근 실거래·3개월 평균", body)
        self.assertIn("최근 3개월 평균", body)
        self.assertIn("최대 ${readableGapMoney(maxShortage)} 부족", body)
        self.assertIn("예산 범위 내", body)
        self.assertIn('small class="${statusClass}"', body)
        self.assertIn("margin-top:13px; border:0; border-top:1px solid #edf0f4; border-radius:0; padding:12px 0 0;", html)
        self.assertIn("grid-template-columns:minmax(0,1fr) auto; align-items:baseline; gap:12px;", html)
        self.assertIn(".policy-cash-summary { display:grid; gap:6px; padding:0 }", html)
        self.assertIn("display:grid; justify-content:stretch; align-items:start; gap:6px; width:100%;", html)
        self.assertIn(".policy-cash-amount {\n      color:#191f28; font-size:18px; font-weight:850; line-height:1.35; text-align:right; white-space:nowrap;", html)
        self.assertIn(".policy-cash-summary small {\n      display:block; color:#667085; font-size:13px; font-weight:650;", html)
        self.assertIn(".condition-stage-results .policy-cash-summary small { width:100%; font-size:13px; text-align:left }", html)
        self.assertIn(".condition-stage-results .policy-cash-summary small { text-align:right }", html)
        self.assertIn("width:100%; margin:0; font-size:16px; text-align:left; white-space:normal;", html)
        self.assertIn(".condition-stage-results .policy-metric.policy-cash-summary .policy-cash-amount {\n      width:auto; margin:0; font-size:16px; text-align:right; white-space:nowrap;", html)
        self.assertIn(".policy-cash-summary small.is-ok { color:#147a55 }", html)
        self.assertIn(".policy-cash-summary small.is-short { color:#b42318; font-weight:700 }", html)
        self.assertNotIn("부족한 돈 없음", body)
        self.assertIn("policy-cash-summary", html)
        self.assertNotIn(".policy-required-line .policy-required-label", html)

    def test_direct_apartment_search_omits_manual_asking_price_check(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r"async function runAptSearch\b(?P<body>.*?)"
            r"\n    async function runApartmentResultSearch",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertNotIn("${askingPriceCheckHtml(item)}", body)
        self.assertNotIn("void calculateAskingPrice(form);", html)
        self.assertNotIn("[data-asking-price-check]", html)
        self.assertIn(".apt-result-card { overflow:hidden; padding:14px }", html)
        self.assertIn(".apt-result-card .candidate-price-comparison { grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 }", html)
        self.assertIn(".apt-result-card .candidate-price-cell + .candidate-price-cell", html)
        self.assertIn("border-top:0; border-left:1px solid #e5e9ef;", html)
        self.assertIn(".apt-affordability-row { grid-template-columns:minmax(0,1fr); gap:4px; padding:11px 0 }", html)
        self.assertIn(".apt-result-actions .candidate-primary-actions.candidate-shared-actions", html)
        self.assertIn("display:flex; grid-template-columns:none; gap:8px; width:100%;", html)
        self.assertIn('${candidateSharedActionsHtml(item, "apt-result-naver")}', body)
        self.assertNotIn("검토 리포트 준비 중", body)

    def test_direct_apartment_search_shows_rivals_below_result_card(self):
        html = APP_HTML.read_text(encoding="utf-8")
        result_match = re.search(
            r"async function runAptSearch\b(?P<body>.*?)"
            r"\n    async function runApartmentResultSearch",
            html,
            re.DOTALL,
        )
        render_match = re.search(
            r"function renderAptCandidateResult\b(?P<body>.*?)"
            r"\n    async function refreshAptSearchTrendAfterAreaChange",
            html,
            re.DOTALL,
        )
        click_match = re.search(
            r"aptSearchResults\.addEventListener\(\"click\", async event => \{(?P<body>.*?)"
            r"\n    \}\);",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(result_match)
        self.assertIsNotNone(render_match)
        self.assertIsNotNone(click_match)
        self.assertIn("data-apt-rivals hidden", result_match.group("body"))
        self.assertIn('</article>\n      <div class="apt-rival-standalone" data-apt-rivals hidden></div>', html)
        self.assertIn('card?.nextElementSibling?.matches?.("[data-apt-rivals]")', html)
        self.assertIn("function aptSearchRivalsHtml", html)
        self.assertIn("라이벌 아파트", html)
        self.assertIn("가격, 흐름, 규모를 나란히 보며 비교할", html)
        self.assertIn("const score = Number(peer.locationScore?.score);", html)
        self.assertIn("종합 ${esc(Math.round(score))}점", html)
        self.assertNotIn("peer.locationScore?.score ?? peer.score", html)
        self.assertIn("apt-rival-rate ${rateTone}", html)
        self.assertIn("const recent3 = Number(peer.recent3Pct);", html)
        self.assertIn("const latestArea = Number(peer.latestDealExclusiveArea || 0);", html)
        self.assertIn("<span>최근 실거래</span><strong>${priceText}</strong>", html)
        self.assertIn('class="apt-rival-area">· ${latestAreaText}</span>', html)
        self.assertIn('.apt-rival-area { color:#8b95a1; font-size:13px; font-weight:600; line-height:1.35; white-space:nowrap }', html)
        self.assertIn('? `${esc(latestArea.toLocaleString("ko-KR", { maximumFractionDigits:1 }).replace(/\\\\.0$/, ""))}㎡`', html)
        self.assertIn('? `${esc(latestPrice.toFixed(1).replace(/\\.0$/, ""))}억${esc(dealDateText)}`', html)
        self.assertIn(".signal-peer-meta strong { color:#191f28; font-weight:900 }", html)
        self.assertIn(".apt-rival-title-block", html)
        self.assertIn(".apt-rival-meta { color:#8b95a1; font-size:13px; font-weight:600; line-height:1.4 }", html)
        self.assertIn('<span class="apt-rival-meta">${householdText}</span>', html)
        self.assertIn("<span>가격 흐름</span>", html)
        self.assertIn("<b>6개월</b> ${flowText}", html)
        self.assertIn("<b>3개월</b> ${recent3Text}", html)
        self.assertIn("peers.slice(0, 3).map(peer =>", html)
        self.assertIn('data-apt-peer-legal-dong="${esc(peer.legalDong || "")}"', html)
        self.assertIn('data-apt-peer-jibun="${esc(peer.jibun || "")}"', html)
        self.assertIn('data-apt-peer-preferred-area="${esc(peer.latestDealExclusiveArea || "")}"', html)
        self.assertIn(".apt-rival-metrics", html)
        self.assertIn(".apt-rival-metric", html)
        self.assertIn(".apt-rival-flow-values", html)
        self.assertNotIn("비교 포인트", html)
        self.assertNotIn("최근 흐름을 먼저 비교해보세요", html)
        self.assertNotIn("결과 카드로 자세히 보기", html)
        self.assertNotIn(".apt-rival-action", html)
        self.assertIn('const rateTone = momentum > 0 ? "up" : momentum < 0 ? "down" : "flat";', html)
        self.assertIn(".apt-rival-rate.up { color:#d92d20 }", html)
        self.assertIn(".apt-rival-rate.down { color:#1767c5 }", html)
        self.assertIn(".apt-rival-metric {", html)
        self.assertIn(".apt-rival-metric { grid-template-columns:76px minmax(0,1fr); gap:8px }", html)
        self.assertNotIn(".apt-rival-metric { display:grid; gap:4px; min-width:0; border:", html)
        self.assertNotIn(".apt-rival-metric:first-child", html)
        self.assertNotIn("<span>규모</span><strong>${householdText}</strong>", html)
        self.assertNotIn('<span class="signal-peer-reason match">결과 카드로 보기</span>', html)
        self.assertIn("fetchAptReport(item.name, item.region || \"\", item)", html)
        self.assertIn('params.set("households", String(Math.round(households)))', html)
        self.assertIn('params.set("price_eok", String(price))', html)
        self.assertIn("void enrichAptSearchRivals(card, candidate, requestToken);", render_match.group("body"))
        self.assertIn("function aptSearchRivalMapItem(peer, peerRegion = \"\")", html)
        self.assertIn("locationScore:peer?.locationScore || null,", html)
        self.assertNotIn("Number.isFinite(Number(peer?.score)) ? { score:Number(peer.score) } : null", html)
        self.assertIn("function mergeAptSearchRivalsForMap(report)", html)
        self.assertIn("currentAptSearchRivalItems = nextItems;", html)
        self.assertIn("void renderCandidateMap(aptSearchMapRows());", html)
        self.assertIn("function aptPeerSelectedItem(peer)", html)
        self.assertIn("const match = currentAptSearchRivalItems.find(item =>", html)
        self.assertIn("const legalDong = String(peer?.dataset?.aptPeerLegalDong || \"\").trim();", html)
        self.assertIn("const jibun = String(peer?.dataset?.aptPeerJibun || \"\").trim();", html)
        self.assertIn("const preferredArea = String(peer?.dataset?.aptPeerPreferredArea || \"\").trim();", html)
        self.assertIn("legalDong:legalDong || match?.legalDong || \"\",", html)
        self.assertIn("jibun:jibun || match?.jibun || \"\",", html)
        self.assertIn("preferredArea:preferredArea || match?.preferredArea || \"\",", html)
        self.assertIn("const selectedSignals = selectedItem.signals && Object.keys(selectedItem.signals).length", html)
        self.assertIn("signals:selectedSignals || exact.signals || {},", html)
        self.assertIn("locationScore:selectedItem.locationScore || exact.locationScore || null,", html)
        self.assertIn("const peer = event.target.closest(\"[data-apt-peer-name]\");", click_match.group("body"))
        self.assertIn("void runApartmentResultSearch(aptPeerSelectedItem(peer));", click_match.group("body"))
        self.assertIn('const compareButton = event.target.closest("[data-compare-name]");', click_match.group("body"))
        self.assertIn(
            "toggleComparison(compareButton.dataset.compareName, compareButton.dataset.candidateKey, {",
            click_match.group("body"),
        )
        self.assertIn('stayCollapsed:candidateMapBottomSheetMedia.matches && Boolean(compareButton.closest("[data-candidate-map-preview]"))', click_match.group("body"))

    def test_design_guideline_keeps_apartment_metadata_subtle(self):
        skill = Path("/Users/jay/.codex/skills/zippick-ui-ux-designer/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Apartment Metadata Rule", skill)
        self.assertIn("directly under the apartment name", skill)
        self.assertIn("light gray", skill)
        self.assertIn("Do not render apartment metadata in bold", skill)

    def test_budget_render_filters_all_server_and_cached_rows_by_purchase_cap(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r"function renderBudgetCandidates\b(?P<body>.*?)"
            r"\n    function budgetLoadingStageIndex",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertGreaterEqual(
            body.count(".filter(row => candidateWithinPurchaseCap(row, data.budgetEok))"),
            2,
        )
        self.assertGreaterEqual(
            body.count(".filter(candidateHasVerifiedSelectedArea)"),
            2,
        )
        self.assertIn("policyExcludedCandidates: excludedRows", body)
        self.assertIn("realEstateSearch.budgetCandidates.v22", html)

    def test_completed_no_trade_state_is_not_rendered_as_still_checking(self):
        html = APP_HTML.read_text(encoding="utf-8")
        headline_match = re.search(
            r"function candidateHeadlinePrice\b(?P<body>.*?)"
            r"\n    function candidateHeadlinePriceHtml",
            html,
            re.DOTALL,
        )
        latest_match = re.search(
            r"function candidatePriceComparisonContentHtml\b(?P<body>.*?)"
            r"\n    function candidatePriceComparisonHtml",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(headline_match)
        self.assertIsNotNone(latest_match)
        self.assertIn('"no_recent_trade"', headline_match.group("body"))
        self.assertIn('"no_selected_area_trade"', headline_match.group("body"))
        self.assertIn("개월 거래 없음", headline_match.group("body"))
        self.assertIn('"no_recent_trade"', latest_match.group("body"))
        self.assertIn("최근 6개월 거래 없음", latest_match.group("body"))

    def test_budget_candidates_render_only_after_background_enrichment_finishes(self):
        html = APP_HTML.read_text(encoding="utf-8")
        render_match = re.search(
            r"function renderBudgetCandidates\b(?P<body>.*?)"
            r"\n    function budgetLoadingStageIndex",
            html,
            re.DOTALL,
        )
        load_match = re.search(
            r"async function loadBudgetCandidates\b(?P<body>.*?)"
            r"\n    async function loadRegionApartments",
            html,
            re.DOTALL,
        )
        progress_match = re.search(
            r"function budgetEnrichmentProgressHtml\b(?P<body>.*?)"
            r"\n    function updateBudgetEnrichmentProgress",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(render_match)
        self.assertIsNotNone(load_match)
        self.assertIsNotNone(progress_match)
        render_body = render_match.group("body")
        load_body = load_match.group("body")
        progress_body = progress_match.group("body")
        self.assertNotIn("pendingCandidatesHtml", html)
        self.assertNotIn("displayRows.map", render_body)
        self.assertIn(
            "await waitForCompletedBudgetCandidates(initialData, url, controller)",
            load_body,
        )
        self.assertIn(
            "await revealBudgetCandidatesTogether(data, controller)",
            load_body,
        )
        self.assertLess(
            render_body.index("if (data.enrichmentPending)"),
            render_body.index("const allRows"),
        )
        self.assertNotIn("data-budget-background-status", render_body)
        self.assertLess(
            load_body.index("await waitForCompletedBudgetCandidates(initialData, url, controller)"),
            load_body.index("await revealBudgetCandidatesTogether(data, controller)"),
        )
        self.assertIn("const stageCount = BUDGET_ENRICHMENT_STAGES.length", progress_body)
        self.assertIn("`${stageCount}/${stageCount} 완료`", progress_body)
        self.assertIn("const requestedStage = completed", html)
        self.assertIn("Math.max(displayedStage, requestedStage)", html)
        self.assertIn('const state = completed || index < safeStage ? "done"', progress_body)
        self.assertIn("준비가 끝나면 후보 카드를 한 번에 보여드릴게요.", progress_body)

    def test_condition_change_waits_for_complete_signal_enrichment(self):
        html = APP_HTML.read_text(encoding="utf-8")
        load_match = re.search(
            r"async function loadBudgetCandidates\b(?P<body>.*?)"
            r"\n    async function loadRegionApartments",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(load_match)
        load_body = load_match.group("body")
        self.assertIn(
            "await waitForCompletedBudgetCandidates(initialData, url, controller)",
            load_body,
        )
        self.assertIn(
            "await revealBudgetCandidatesTogether(data, controller)",
            load_body,
        )

    def test_map_condition_change_shows_loading_then_reopens_map(self):
        html = APP_HTML.read_text(encoding="utf-8")
        loading_match = re.search(
            r"function startBudgetLoading\b(?P<body>.*?)"
            r"\n    async function revealBudgetCandidatesTogether",
            html,
            re.DOTALL,
        )
        load_match = re.search(
            r"async function loadBudgetCandidates\b(?P<body>.*?)"
            r"\n    async function loadRegionApartments",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(loading_match)
        self.assertIsNotNone(load_match)
        loading_body = loading_match.group("body")
        load_body = load_match.group("body")
        self.assertIn('document.body.classList.remove("candidate-map-open");', loading_body)
        self.assertIn("removeCandidateMapPortal();", loading_body)
        self.assertIn("budgetResultEl.innerHTML = budgetEnrichmentHtml(0);", loading_body)
        self.assertIn("const totalSeconds = 10;", html)
        self.assertIn("const stageSeconds = totalSeconds / stageCount;", html)
        self.assertIn("Math.max(currentStage, timeStage)", html)
        self.assertIn('const restoreMapAfterSearch = candidateViewMode === "map" && candidateMapOrigin === "budget";', load_body)
        self.assertLess(
            load_body.index("const restoreMapAfterSearch"),
            load_body.index("startBudgetLoading();"),
        )
        self.assertIn('if (restoreMapAfterSearch) {', load_body)
        self.assertIn('candidateMapOrigin = "budget";', load_body)
        self.assertIn('candidateViewMode = "map";', load_body)
        self.assertLess(
            load_body.index('candidateViewMode = "map";'),
            load_body.index("await revealBudgetCandidatesTogether(data, controller)"),
        )

    def test_frontend_signal_formula_version_matches_backend(self):
        html = APP_HTML.read_text(encoding="utf-8")
        backend = (ROOT / "pipeline" / "momentum_signals.py").read_text(encoding="utf-8")
        version_match = re.search(
            r"const SIGNAL_FORMULA_VERSION = (?P<version>\d+);",
            html,
        )
        backend_version_match = re.search(
            r"^SCORE_FORMULA_VERSION = (?P<version>\d+)$",
            backend,
            re.MULTILINE,
        )

        self.assertIsNotNone(version_match)
        self.assertIsNotNone(backend_version_match)
        self.assertEqual(
            int(version_match.group("version")),
            int(backend_version_match.group("version")),
        )

    def test_condition_modal_refreshes_results_only_after_final_confirmation(self):
        html = APP_HTML.read_text(encoding="utf-8")
        item_submit_match = re.search(
            r"async function submitConditionItemEdit\b(?P<body>.*?)"
            r"\n    function renderConditionSummary",
            html,
            re.DOTALL,
        )
        close_match = re.search(
            r"function closeConditionSummary\b(?P<body>.*?)"
            r"\n\n    function fieldErrorAnchor",
            html,
            re.DOTALL,
        )
        complete_match = re.search(
            r'conditionSummaryComplete\.addEventListener\("click", \(\) => \{(?P<body>.*?)'
            r"\n    \}\);",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(item_submit_match)
        self.assertIsNotNone(close_match)
        self.assertIsNotNone(complete_match)
        self.assertNotIn("loadBudgetCandidates();", item_submit_match.group("body"))
        self.assertIn("if (!commit) restoreConditionSummaryState();", close_match.group("body"))
        complete_body = complete_match.group("body")
        self.assertIn("closeConditionSummary(true, true);", complete_body)
        self.assertIn("loadBudgetCandidates();", complete_body)
        self.assertLess(
            complete_body.index("closeConditionSummary(true, true);"),
            complete_body.index("loadBudgetCandidates();"),
        )

    def test_budget_completion_updates_cache_before_results_are_revealed(self):
        html = APP_HTML.read_text(encoding="utf-8")
        completion_match = re.search(
            r"async function waitForCompletedBudgetCandidates\b(?P<body>.*?)"
            r"\n    async function loadBudgetCandidates",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(completion_match)
        completion_body = completion_match.group("body")
        self.assertIn("if (!next.done)", completion_body)
        self.assertIn("if (next.enrichmentPending) continue;", completion_body)
        self.assertIn("writeBudgetBrowserCache(url, next)", completion_body)
        self.assertIn("return next", completion_body)
        self.assertLess(
            completion_body.index("writeBudgetBrowserCache(url, next)"),
            completion_body.index("return next"),
        )

    def test_optional_naver_links_update_after_complete_list_is_revealed(self):
        html = APP_HTML.read_text(encoding="utf-8")
        optional_match = re.search(
            r"async function enrichOptionalBudgetLinks\b(?P<body>.*?)"
            r"\n    function waitForBudgetPoll",
            html,
            re.DOTALL,
        )
        load_match = re.search(
            r"async function loadBudgetCandidates\b(?P<body>.*?)"
            r"\n    async function loadRegionApartments",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(optional_match)
        self.assertIsNotNone(load_match)
        optional_body = optional_match.group("body")
        load_body = load_match.group("body")
        self.assertIn("/api/budget-candidates/optional-progress", optional_body)
        self.assertIn("applyOptionalNaverLinks(payload, optionalId)", optional_body)
        self.assertIn("data-naver-land-pending", html)
        self.assertIn("candidateNaverPropertyActionHtml(", html)
        self.assertIn("pending.outerHTML", html)
        self.assertIn("void enrichOptionalBudgetLinks(data);", load_body)
        self.assertLess(
            load_body.index("await revealBudgetCandidatesTogether(data, controller)"),
            load_body.index("void enrichOptionalBudgetLinks(data);"),
        )

    def test_budget_result_trends_auto_load_without_card_button_clicks(self):
        html = APP_HTML.read_text(encoding="utf-8")
        render_match = re.search(
            r"function renderBudgetCandidates\b(?P<body>.*?)"
            r"\n    function budgetLoadingStageIndex",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(render_match)
        body = render_match.group("body")
        self.assertIn("mountCandidateMapPortal();", body)
        self.assertIn("syncCompareSelection();", body)
        self.assertIn("enrichMarketInsights(rows);", body)
        post_portal_sync_index = body.index("syncCompareSelection();", body.index("mountCandidateMapPortal();"))
        self.assertLess(
            body.index("mountCandidateMapPortal();"),
            post_portal_sync_index,
        )
        self.assertLess(
            post_portal_sync_index,
            body.index("enrichMarketInsights(rows);"),
        )

    def test_budget_candidate_cards_render_compare_controls(self):
        html = APP_HTML.read_text(encoding="utf-8")
        render_match = re.search(
            r"function renderBudgetCandidates\b(?P<body>.*?)"
            r"\n    function budgetLoadingStageIndex",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(render_match)
        body = render_match.group("body")
        self.assertIn("${candidateSharedActionsHtml(item)}", body)
        self.assertNotIn('data-candidate-detail-open', body)
        self.assertNotIn('리포트 보기', body)
        self.assertIn('class="compare-toggle candidate-compare-action"', html)
        self.assertNotIn('data-compare-label="view"', html)
        self.assertIn('${selectedCandidateNames.has(name) ? "담기 해제" : "비교 담기"}</button>', html)
        self.assertIn('document.querySelectorAll("[data-compare-name]").forEach(button => {', html)
        self.assertIn('button.classList.contains("candidate-map-compare-toggle")', html)
        self.assertIn('? (isSelected ? "담김" : "비교 담기")', html)
        self.assertIn(': (isSelected ? "담기 해제" : "비교 담기");', html)
        self.assertIn('if (!Number.isFinite(score) && !signals.status) return "";', html)
        self.assertIn('const measurable = Number.isFinite(score) && score > 0;', html)
        self.assertIn('const label = measurable ? `${Math.round(score)}점` : "측정 불가";', html)
        self.assertIn('grid-template-columns:minmax(0,1.65fr) minmax(0,1fr)', html)
        self.assertIn('padding:8px 12px !important; color:#475467; background:#fff', html)
        self.assertNotIn('padding:8px 13px !important; color:#475467; background:#fff', html)
        self.assertIn('border:1px solid #e1e5ea !important; border-radius:14px !important;', html)
        self.assertIn('background:#fff !important; color:#4e5968 !important; font-size:14px; font-weight:800', html)
        self.assertIn(".budget-name { display:block; color:#23272f; font-size:20px;", html)
        self.assertIn(".condition-stage-results .budget-name { color:#191f28; font-size:20px;", html)
        self.assertIn(".condition-stage-results .budget-meta { margin-top:7px; color:#8b95a1; font-size:14px; line-height:1.5 }", html)
        self.assertIn(".condition-stage-results .budget-meta { font-size:13px }", html)
        self.assertIn(".candidate-score-badges { display:flex; align-items:center; flex-wrap:wrap; gap:6px; margin-top:11px }", html)
        self.assertIn(".candidate-price-label { align-items:flex-start; gap:4px; font-size:13px }", html)
        self.assertIn(".candidate-price-value { margin-top:6px; font-size:20px }", html)
        self.assertIn(".candidate-price-date, .candidate-price-direction { font-size:13px }", html)
        self.assertIn(".trend-toggle { align-self:flex-start; font-size:14px }", html)
        self.assertIn('.candidate-primary-actions.candidate-shared-actions { flex-wrap:nowrap; gap:8px; width:100% }', html)
        self.assertIn(
            ".candidate-primary-actions > .compare-toggle {\n"
            "      flex:0 0 auto; width:fit-content; min-width:max-content; max-width:100%; justify-self:start;",
            html,
        )
        self.assertNotIn("이 매물 계약 전 분석", body)
        self.assertIn('class="compare-floating-bar"', html)
        self.assertIn('id="compareCart"', html)
        self.assertIn('id="compareCartCount"', html)
        self.assertIn('id="compareCartAction"', html)
        self.assertIn('id="compareCartAction" type="button" disabled>비교</button>', html)
        self.assertNotIn('id="compareCartAction" type="button" disabled>비교하기</button>', html)
        self.assertIn('id="compareCartClose"', html)
        self.assertIn('id="compareCartChip"', html)
        self.assertIn('class="compare-floating-count" id="compareCartCount"', html)
        self.assertIn("function compareFloatingSelectedChipHtml(item)", html)
        self.assertIn('class="compare-floating-selected-chip"', html)
        self.assertIn('class="candidate-map-compare-toggle"', html)
        self.assertIn('data-compare-name="${esc(name)}"', html)
        self.assertIn('${selectedCandidateNames.has(name) ? "담김" : "비교 담기"}</button>', html)
        self.assertIn('class="compare-floating-selected-name"', html)
        self.assertIn('data-compare-remove-name="${esc(item.name || name)}"', html)
        self.assertIn('aria-label="${esc(name)} 비교 후보 삭제"', html)
        self.assertIn('title="삭제">×</button>', html)
        self.assertNotIn("선택 비우기", html)
        self.assertNotIn('id="compareCartClear"', html)
        self.assertIn("비교 바 작게 접기", html)
        self.assertNotIn('class="compare-cart"', html)
        self.assertNotIn('id="compareCartBadge"', html)
        self.assertIn("compareCart.hidden = selected.length === 0 || compareCartCollapsed", html)
        self.assertIn("compareCartChip.hidden = selected.length === 0 || !compareCartCollapsed", html)
        self.assertIn("compareCartChip.textContent = `비교할 집 ${selected.length}곳`", html)
        self.assertIn("let compareCartCollapsed = false;", html)
        self.assertIn("const compareCandidateCart = new Map();", html)
        self.assertIn("const saved = compareCandidateCart.get(name);", html)
        self.assertIn("if (item) compareCandidateCart.set(name, item);", html)
        self.assertIn("const stayCollapsed = options?.stayCollapsed === true;", html)
        self.assertIn("compareCartCollapsed = stayCollapsed;", html)
        self.assertIn('stayCollapsed:candidateMapBottomSheetMedia.matches && (', html)
        self.assertIn('document.body.classList.contains("candidate-map-open") || Boolean(compareButton.closest("[data-candidate-map-preview]"))', html)
        self.assertIn("compareCandidateCart.delete(name);", html)
        self.assertIn("compareCandidateCart.clear();", html)
        self.assertIn("body:not(.condition-stage-results):not(.apt-search-mode) .compare-floating-bar", html)
        self.assertIn("body:not(.condition-stage-results):not(.apt-search-mode) .compare-floating-chip", html)
        self.assertIn("body.candidate-map-open.compare-cart-collapsed .compare-floating-chip { display:none !important }", html)
        self.assertNotIn("body.apt-search-mode .compare-floating-bar", html)
        self.assertNotIn("body.apt-search-mode .compare-floating-chip", html)
        self.assertIn('document.body.classList.toggle("compare-floating-visible", selected.length > 0);', html)
        self.assertIn("height:60px", html)
        self.assertIn("align-items:stretch; width:min(360px,calc(100% - 24px)); height:auto; min-height:0; padding:12px;", html)
        self.assertIn("align-items:stretch; flex-direction:column; justify-content:flex-start; min-height:0; gap:10px;", html)
        self.assertIn("flex:1 1 auto; flex-wrap:wrap; overflow:visible; gap:6px;", html)
        self.assertIn("max-width:100%; min-height:30px; padding:4px 8px 4px 10px; font-size:13px; font-weight:800;", html)
        self.assertIn("overflow:visible; text-overflow:clip; white-space:normal;", html)
        self.assertIn(".compare-floating-action { flex:1 1 auto; min-width:0; min-height:42px; max-height:none; border-radius:10px; padding:0 12px; font-size:14px }", html)
        self.assertIn("right:max(18px,env(safe-area-inset-right)); bottom:calc(18px + env(safe-area-inset-bottom));", html)
        self.assertIn("bottom:max(78px,calc(env(safe-area-inset-bottom) + 74px))", html)
        self.assertIn("body.compare-floating-visible:not(.compare-cart-collapsed) .candidate-map-fab", html)
        self.assertIn("bottom:max(156px,calc(env(safe-area-inset-bottom) + 152px))", html)
        self.assertIn('class="candidate-map-compare-cart"', html)
        self.assertIn('data-candidate-map-compare-open hidden>비교할 집 0곳</button>', html)
        self.assertIn('${directSearch ? "" : `<div class="candidate-map-funding-option">${additionalFundingToggleHtml(includeAdditionalFundingCandidates)}</div>`}\n          <button class="candidate-map-compare-cart"', html)
        self.assertIn('document.querySelectorAll("[data-candidate-map-compare-open]").forEach(button => {', html)
        self.assertIn('button.textContent = selected.length < 2 ? "한 곳 더 담기" : `비교할 집 ${selected.length}곳`;', html)
        self.assertIn('const candidateMapCompareOpen = event.target.closest("[data-candidate-map-compare-open]");', html)
        self.assertIn('document.body.classList.contains("candidate-map-open") && !compareCartCollapsed', html)
        self.assertIn("if (candidateMapCompareOpen) {\n        expandComparisonBar();\n        return;\n      }", html)
        self.assertIn(': `비교함 열기, 비교할 집 ${selected.length}곳 담김`,', html)
        self.assertIn(".compare-floating-close svg { width:18px; height:18px;", html)
        self.assertIn('<path d="M6 9l6 6 6-6"></path>', html)
        self.assertIn(".compare-floating-chip {", html)
        self.assertIn("compareCartAction.hidden = selected.length < 2", html)
        self.assertIn("compareCartAction.disabled = selected.length < 2", html)
        self.assertIn('selected.map(compareFloatingSelectedChipHtml).join("")', html)
        self.assertNotIn("compareCartCount.innerHTML = `매수 후보 ${selected.length}곳", html)
        self.assertIn('class="compare-floating-hint">한 곳 더 선택하세요</span>', html)
        self.assertIn("body.compare-floating-visible .candidate-map-fab", html)
        self.assertIn(".candidate-map-view {\n      position:fixed; z-index:120;", html)
        self.assertIn(".comparison-overlay {\n      display:none; position:fixed; z-index:180;", html)
        self.assertIn("width:52px; height:52px;", html)
        self.assertIn("currentBudgetData?.candidates || currentBudgetData?.visibleCandidates || []", html)
        self.assertIn("const CANDIDATE_MAP_CLUSTER_LEVEL = 8", html)
        self.assertIn("for (let index = 0; index < rows.length; index += CANDIDATE_PAGE_SIZE)", html)
        self.assertIn("주소 확인 ${located.length}/${rows.length}곳", html)
        self.assertIn("전체 후보 위치를 불러오고 있어요", html)
        self.assertIn(".candidate-map-cluster {", html)
        self.assertIn("min-width:77px", html)
        self.assertIn(".candidate-map-cluster span { color:#1267d8; font-size:14px;", html)
        self.assertIn(".candidate-map-shell:not(:has(.candidate-map-preview:not([hidden])))", html)
        self.assertIn("grid-template-columns:minmax(0,1fr)", html)
        self.assertIn(".candidate-map-shell:not(:has(.candidate-map-preview:not([hidden]))) .candidate-map-canvas { grid-column:1 }", html)
        self.assertIn(".candidate-map-shell:not(:has(.candidate-map-preview:not([hidden]))) .candidate-map-map-tools { left:50% }", html)
        self.assertIn("function renderCandidateMapClusters(kakao, entries)", html)
        self.assertIn("function renderCandidateMapMarkers(kakao, entries, options = {})", html)
        self.assertIn("function focusCandidateMapEntry(entry, level = 4)", html)
        self.assertIn("renderCandidateMapMarkers(kakao, located, { fit:false, pan:false, selectFirst:false });", html)
        self.assertIn("const selectedEntry = located.find(entry => candidateIdentityKey(entry.item) === candidateMapSelectedKey);", html)
        self.assertIn("focusCandidateMapEntry(selectedEntry);", html)
        self.assertIn("function syncCandidateMapPresentation(kakao, options = {})", html)
        self.assertIn('let candidateMapPresentationMode = "clusters";', html)
        self.assertIn("let candidateMapLastLevel = null;", html)
        self.assertIn("function candidateMapMarkerScoreText(item)", html)
        self.assertIn("const score = Number(item?.locationScore?.score);", html)
        self.assertIn("return `${Math.round(score)}점`;", html)
        marker_score_body = re.search(r"function candidateMapMarkerScoreText\b(?P<body>.*?)\n    function appendCandidateMapEntry", html, re.DOTALL).group("body")
        self.assertNotIn("종합점수", marker_score_body)
        self.assertIn('marker.setAttribute("aria-label", `${candidateDisplayName(item)}${scoreText ? `, ${scoreText}` : ""}, 최근 실거래 ${mapPrice.value}, ${mapAverage.ariaLabel} ${mapAverage.value}`);', html)
        self.assertNotIn("if (signals.score !== null && Number.isFinite(Number(signals.score))) return `${signals.score}점`;", html)
        self.assertIn('candidateMapPresentationMode = "markers";', html)
        self.assertIn('candidateMapPresentationMode = "clusters";', html)
        self.assertIn("const previousLevel = Number.isFinite(candidateMapLastLevel) ? candidateMapLastLevel : level;", html)
        self.assertIn("const zoomedOut = level > previousLevel;", html)
        self.assertIn("const zoomedIn = level < previousLevel;", html)
        self.assertIn("candidateMapLastLevel = level;", html)
        self.assertIn('if (candidateMapPresentationMode === "markers") {', html)
        self.assertIn("if (zoomedOut && level >= CANDIDATE_MAP_CLUSTER_LEVEL) renderCandidateMapClusters(kakao, candidateMapLocatedEntries);", html)
        self.assertIn("Date.now() < candidateMapSuppressPresentationSyncUntil", html)
        self.assertIn("const level = Number(candidateMap.getLevel?.() || 99);", html)
        self.assertIn('kakao.maps.event.addListener(candidateMap, "zoom_changed", () => syncCandidateMapPresentation(kakao));', html)
        self.assertIn("candidateMapSelectedKey = \"\";", html)
        self.assertIn("setCandidateMapDetailOpen(false);", html)
        self.assertIn("button.innerHTML = `<strong>${esc(group.district)}</strong><span>후보 ${esc(group.rows.length)}</span>`", html)
        self.assertIn("suppressCandidateMapPresentationSync();", html)

    def test_review_report_titles_include_the_selected_area(self):
        html = APP_HTML.read_text(encoding="utf-8")

        self.assertIn("function candidateDetailAreaText(item)", html)
        self.assertIn('return `${Number.isInteger(value) ? value : value.toFixed(1).replace(/\\.0$/, "")}㎡`;', html)
        self.assertIn('class="candidate-detail-title-area"', html)
        self.assertIn("${candidateDetailTitleHtml(item)}", html)
        self.assertIn("aptReportTitle.innerHTML = candidateDetailTitleHtml(candidate, name);", html)
        self.assertIn("aptReportTitle.innerHTML = candidateDetailTitleHtml(report, name);", html)
        self.assertIn('compareCart.addEventListener("click"', html)
        self.assertIn('const removeButton = event.target.closest("[data-compare-remove-name]");', html)
        self.assertIn("selectedCandidateNames.delete(removeButton.dataset.compareRemoveName);", html)
        self.assertIn('compareCartAction.addEventListener("click", openComparison);', html)
        self.assertIn('compareCartClose.addEventListener("click", collapseComparisonBar);', html)
        self.assertIn('compareCartChip.addEventListener("click", expandComparisonBar);', html)
        self.assertIn("function collapseComparisonBar()", html)
        self.assertIn("function expandComparisonBar()", html)
        self.assertIn("function scheduleCompareCartAutoCollapse()", html)
        self.assertIn("compareCartAutoCollapseTimer = setTimeout(() => {", html)
        self.assertIn("compareCartChip.textContent = `비교할 집 ${selected.length}곳`;", html)
        self.assertIn('document.body.classList.toggle("compare-cart-collapsed"', html)
        self.assertIn('id="comparisonLimitToast"', html)
        self.assertIn("else showComparisonLimitToast();", html)
        self.assertIn('comparisonLimitToast.textContent = "비교는 최대 3건까지 담을 수 있어요."', html)
        self.assertIn("compare-floating-action", html)
        self.assertNotIn("compare-dock-close.svg", html)

    def test_candidate_comparison_uses_report_highlights_without_auto_summary(self):
        html = APP_HTML.read_text(encoding="utf-8")

        self.assertIn('<h2 id="comparisonTitle">사전 질문</h2>', html)
        self.assertIn('id="comparisonClose" type="button" aria-label="비교 화면 닫기" hidden', html)
        self.assertIn('class="comparison-stepper"', html)
        self.assertIn('data-comparison-stepper-item="questions"', html)
        self.assertIn('data-comparison-stepper-item="results"', html)
        self.assertIn(".comparison-head { position:relative; display:grid; justify-items:center; gap:18px }", html)
        self.assertIn(".comparison-head > div { display:grid; justify-items:center; width:100%; min-width:0 }", html)
        self.assertIn("grid-template-columns:minmax(0,1fr) minmax(42px,88px) minmax(0,1fr)", html)
        self.assertIn(".comparison-stepper-item:first-child { justify-self:end }", html)
        self.assertIn(".comparison-stepper-item:last-child { justify-self:start }", html)
        self.assertIn(".comparison-close { position:absolute; top:0; right:0;", html)
        self.assertNotIn("점수와 필요한 돈을 먼저 보고, 아래에서 근거를 확인하세요.", html)
        self.assertNotIn("어떤 차이가 있는지 볼게요", html)
        self.assertNotIn('class="comparison-summary"', html)
        self.assertIn('["시세 흐름", "summary"]', html)
        self.assertIn('["종합점수", "totalScore", "section"]', html)
        self.assertIn('["가격 적정성", "score:price"]', html)
        self.assertIn('["전세가율·투자금 효율", "score:jeonse"]', html)
        self.assertIn('["입지·실수요", "score:demand"]', html)
        self.assertIn('["상품성·희소성", "score:product"]', html)
        self.assertIn('["거래 유동성·시장 신호", "score:market"]', html)
        self.assertIn('["최근 시장 신호", "signal", "section"]', html)
        self.assertIn("candidateChoiceSummaryLines(row)", html)
        self.assertIn("function comparisonSignalHtml(row)", html)
        self.assertIn("function comparisonScoreOverviewHtml(rows, loading = false)", html)
        self.assertIn("function comparisonLocationScoreCellHtml(row, key)", html)
        self.assertIn("function comparisonJeonseFallbackCellHtml(row, max = 20)", html)
        self.assertIn('if (key === "jeonse" && missing)', html)
        self.assertIn("comparisonJeonseFallbackCellHtml(row, max || 20)", html)
        self.assertIn("comparisonNumber(row?.jeonseRatioPct)", html)
        self.assertIn("comparisonNumber(row?.latestJeonseDepositEok)", html)
        self.assertIn("comparisonNumber(row?.jeonseSalePriceBasisEok)", html)
        self.assertIn("필요 투자금 ${transactionMoney(gap)}", html)
        self.assertIn("<strong>최신 계산 중</strong>", html)
        self.assertIn("function comparisonCandidateQuality(item)", html)
        self.assertIn("function comparisonCloseScoreVerdict(rows, leadGap, scoredRows)", html)
        self.assertIn("function comparisonLeadingStrengthLabel(row, rows)", html)
        self.assertIn('strength:parts[0].label,', html)
        self.assertIn('caution:parts[parts.length - 1].label,', html)
        self.assertIn('<div class="comparison-score-fact"><span>강점</span><strong>${esc(balance.strength)}</strong></div>', html)
        self.assertIn('<div class="comparison-score-fact"><span>확인</span><strong>${esc(balance.caution)}</strong></div>', html)
        self.assertNotIn('class="comparison-score-balance"', html)
        self.assertNotIn('strength:`강점 · ${parts[0].label}`', html)
        self.assertNotIn('caution:`확인 · ${parts[parts.length - 1].label}`', html)
        self.assertNotIn('strength:`강점: ${parts[0].label}`', html)
        self.assertNotIn('caution:`확인: ${parts[parts.length - 1].label}`', html)
        self.assertIn('comparisonPreferenceDefaults = { type:"", period:"", priority:"" }', html)
        self.assertIn("function comparisonPreferenceHtml()", html)
        self.assertIn("function comparisonPreferenceComplete(preference = comparisonPreference)", html)
        self.assertIn("function comparisonPreferenceRecommendation(rows, preference = comparisonPreference)", html)
        self.assertIn("function comparisonPreferenceScore(row, preference = comparisonPreference)", html)
        self.assertIn("function comparisonContentHtml(rows, loading = {})", html)
        self.assertIn("let comparisonPreferenceQuestionIndex = 0;", html)
        self.assertIn('let comparisonStep = "questions";', html)
        self.assertIn("let comparisonQuestionsCompleted = false;", html)
        self.assertNotIn("먼저 기준을 골라주세요", html)
        self.assertIn('comparisonTitle.textContent = "사전 질문";', html)
        self.assertIn('comparisonTitle.textContent = "후보 비교";', html)
        self.assertIn('questionStep?.classList.add("is-active");', html)
        self.assertIn('questionStep?.classList.add("is-complete");', html)
        self.assertIn('type="radio" name="comparisonPreference_${esc(group.key)}"', html)
        self.assertNotIn("한 가지씩 고르면, 내 기준에 가장 잘 맞는 후보를 먼저 보여드릴게요.", html)
        self.assertIn("먼저 하나를 선택해 주세요", html)
        self.assertIn("${currentIndex + 1}/${COMPARISON_PREFERENCE_GROUPS.length}", html)
        self.assertIn("color:#0878df; font-size:11px; font-weight:900; line-height:1;", html)
        self.assertIn("다음", html)
        self.assertIn("추천 보기", html)
        self.assertNotIn("function comparisonResultHeadHtml()", html)
        self.assertIn("기준 다시 선택", html)
        self.assertNotIn("comparison-result-head", html)
        self.assertNotIn("comparison-result-step", html)
        self.assertNotIn('${esc(comparisonPreferenceLabel("type", comparisonPreference.type))} · ${esc(comparisonPreferenceLabel("period", comparisonPreference.period))} · ${esc(comparisonPreferenceLabel("priority", comparisonPreference.priority))} 기준</span>', html)
        self.assertNotIn("추천 결과 ·", html)
        self.assertIn("[data-comparison-preference-next]", html)
        self.assertIn("[data-comparison-preference-back]", html)
        self.assertIn("width:100%; min-height:42px; margin-top:8px; border:1px solid #e1e6ee; border-radius:14px; padding:0 16px;", html)
        self.assertIn("background:#fff; color:#667085; font-size:15px; font-weight:750; cursor:pointer;", html)
        self.assertIn(".comparison-preference-back:hover { background:#f8fafc; border-color:#d7deea; color:#475467 }", html)
        self.assertNotIn("background:#edf4ff; color:#2f82f6; font-size:17px; font-weight:800;", html)
        self.assertIn("comparisonPreferenceQuestionIndex += 1;", html)
        self.assertIn("comparisonPreferenceQuestionIndex = Math.max(0, comparisonPreferenceQuestionIndex - 1);", html)
        self.assertIn("comparisonPreferenceQuestionIndex = 0;", html)
        self.assertIn('if (comparisonStep === "questions") {', html)
        self.assertIn("return comparisonPreferenceHtml();", html)
        self.assertIn('comparisonStep = "questions";', html)
        self.assertIn('comparisonStep = "results";', html)
        self.assertIn("if (comparisonQuestionsCompleted && comparisonPreferenceComplete())", html)
        self.assertIn("comparisonQuestionsCompleted = true;", html)
        self.assertIn("comparisonQuestionsCompleted = false;", html)
        self.assertIn("[data-comparison-preference-edit]", html)
        self.assertIn('<button class="comparison-result-edit" type="button" data-comparison-preference-edit>기준 다시 선택</button>', html)
        self.assertIn("어떤 선택이 더 편하세요?", html)
        self.assertIn("이 집을 얼마나 오래 볼 생각인가요?", html)
        self.assertIn("가장 중요하게 보는 건 뭐예요?", html)
        self.assertNotIn("질문 1. 어떤 선택이 더 편하세요?", html)
        self.assertIn("안정형", html)
        self.assertIn("가격·입지·단지 조건이 고르게 좋은 곳", html)
        self.assertIn("균형형", html)
        self.assertIn("가격 부담은 낮추고 입지도 놓치지 않는 곳", html)
        self.assertNotIn("조건도 좋고 최근 흐름도 괜찮은 곳", html)
        self.assertNotIn("예산 안에서 점수와 흐름을 함께 보는 곳", html)
        self.assertIn("기회형", html)
        self.assertIn("가격이 오르고 거래도 붙은 곳", html)
        self.assertIn("5년 이상 보고 싶어요", html)
        self.assertIn("3~5년 정도 보고 싶어요", html)
        self.assertIn("1~3년 안의 흐름도 중요해요", html)
        self.assertIn("가격", html)
        self.assertIn("매수 상한 안에서 더 싸게 살 수 있는 곳", html)
        self.assertNotIn("가격이 적당한지가 중요해요", html)
        self.assertIn("교통", html)
        self.assertIn("가까운 역 접근성이 중요해요", html)
        self.assertIn("학군", html)
        self.assertIn("학교와 교육환경이 중요해요", html)
        self.assertIn("상승 가능성", html)
        self.assertIn("최근 거래 흐름이 중요해요", html)
        self.assertNotIn("생활편의", html)
        self.assertIn('<div class="comparison-verdict-copy">', html)
        self.assertIn('<h3 class="comparison-verdict-title">추천 후보는 ${esc(candidateDisplayName(recommendation.row))}예요</h3>', html)
        self.assertIn("reasonParts,", html)
        self.assertIn("function comparisonPreferenceHighlightsHtml(parts = [])", html)
        self.assertIn('class="comparison-preference-highlight"', html)
        self.assertIn("${comparisonPreferenceHighlightsHtml(recommendation.reasonParts)}", html)
        self.assertIn("<p class=\"comparison-verdict-subtitle\">선택한 기준으로 추천했어요. ${esc(recommendation.caution)}</p>", html)
        self.assertIn(".comparison-preference-highlight {\n      display:inline-flex; align-items:center; min-height:28px; border-radius:999px; padding:0 10px;\n      background:#edf5ff; color:#1767d8;", html)
        self.assertIn(".comparison-verdict {\n      display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:start; gap:12px 16px;", html)
        self.assertIn(".comparison-verdict-copy { min-width:0 }", html)
        self.assertIn("justify-self:end;", html)
        self.assertIn(".comparison-verdict { grid-template-columns:1fr; gap:8px; margin-bottom:18px }", html)
        self.assertIn(".comparison-verdict-copy { width:100% }", html)
        self.assertIn(".comparison-result-edit { padding:7px 11px; font-size:12px }", html)
        self.assertIn(".comparison-verdict-title { margin:0; color:#191f28; font-size:24px; font-weight:900; line-height:1.35; overflow-wrap:anywhere }", html)
        self.assertIn(".comparison-verdict-subtitle { margin:10px 0 0; color:#4e5968; font-size:15px; font-weight:700; line-height:1.6; overflow-wrap:anywhere }", html)
        self.assertIn(".comparison-score-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px }", html)
        verdict_style = re.search(r"\.comparison-verdict \{(?P<body>.*?)\n    \}", html, re.DOTALL)
        self.assertIsNotNone(verdict_style)
        self.assertNotIn("border-left", verdict_style.group("body"))
        self.assertNotIn("padding:2px 0 2px 12px", verdict_style.group("body"))
        self.assertNotIn("${esc(candidateDisplayName(recommendation.row))}를 먼저 보세요.</strong>", html)
        self.assertNotIn("${esc(candidateDisplayName(recommendation.row))}를 먼저 보세요</h3>", html)
        self.assertIn("${reasonParts.join(\" · \")}을 기준으로 추천했어요.", html)
        self.assertIn("도 차이가 크지 않아요. 두 후보의 세부 점수를 함께 비교해보세요.", html)
        self.assertIn("필요 자기자금과 주의할 점도 같이 확인하세요.", html)
        self.assertNotIn("당신에게는 ${esc(candidateDisplayName(recommendation.row))}가 가장 잘 맞아요.", html)
        self.assertNotIn("쪽이 가장 잘 맞아요.", html)
        self.assertNotIn("차이가 크지 않으니, 아래 세부 점수도 함께 보세요.", html)
        self.assertIn('const preferenceButton = event.target.closest("[data-comparison-preference]");', html)
        self.assertIn("refreshOpenComparisonContent();", html)
        self.assertIn('data-candidate-key="${esc(candidateIdentityKey(item))}"', html)
        self.assertIn("function comparisonNumber(value)", html)
        self.assertNotIn("flow !== null && flow > 0", html)
        self.assertIn("종합점수 차이는 ${Math.round(leadGap)}점으로 거의 같아요.", html)
        self.assertIn("예산과 이 항목 중 더 중요한 기준으로 고르세요.", html)
        self.assertIn("먼저 필요한 자기자금이 내 예산에 맞는지 확인하세요.", html)
        self.assertIn("comparisonContentHtml(rows, { trend:needsTrendData, locationScore:needsLocationScoreData })", html)
        self.assertIn("...rows.map(row => refreshLocationScoreSheet(row))", html)
        self.assertNotIn("한눈에 비교", html)
        self.assertNotIn("현재 데이터로는 ${candidateDisplayName(leader)}가 종합 ${Math.round(bestTotal)}점으로 앞서요.", html)
        self.assertNotIn("점수만 보지 말고 필요한 자기자금과 확인할 점도 함께 보세요.", html)
        self.assertNotIn("종합점수 앞섬", html)
        self.assertNotIn("comparison-score-leader", html)
        self.assertNotIn("is-leader", html)
        self.assertIn("function comparisonPreferenceVerdictHtml(rows, recommendation = comparisonPreferenceRecommendation(rows))", html)
        self.assertIn("const recommendation = comparisonPreferenceRecommendation(rows);", html)
        self.assertIn("${comparisonPreferenceVerdictHtml(rows, recommendation)}", html)
        self.assertIn("const recommendedKey = recommendation.row ? candidateIdentityKey(recommendation.row) : \"\";", html)
        self.assertIn('const isRecommended = Boolean(recommendedKey && candidateIdentityKey(row) === recommendedKey);', html)
        self.assertIn('class="comparison-score-card${isRecommended ? " is-recommended" : ""}" data-candidate-key="${esc(candidateIdentityKey(row))}"', html)
        self.assertIn('class="comparison-score-actions"', html)
        self.assertIn("${candidateMapInlineButtonHtml(row)}", html)
        self.assertIn("let candidateMapReturnToComparison = false;", html)
        self.assertIn("function closeCandidateMapView()", html)
        self.assertIn("const shouldReturnToComparison = candidateMapReturnToComparison;", html)
        self.assertIn("candidateMapReturnToComparison = false;", html)
        self.assertIn('void openComparison({ preserveStep:true });', html)
        self.assertIn("closeCandidateMapView();", html)
        self.assertIn('const candidateViewButton = event.target.closest("[data-candidate-view]");', html)
        self.assertIn('if (candidateViewButton.dataset.candidateMapKey) candidateMapSelectedKey = candidateViewButton.dataset.candidateMapKey;', html)
        self.assertIn('candidateMapReturnToComparison = true;\n        closeComparison();\n        setCandidateViewMode(candidateViewButton.dataset.candidateView);', html)
        self.assertIn('<strong class="comparison-score-name">${esc(candidateDisplayName(row))}${isRecommended ? \'<span class="comparison-score-badge">추천</span>\' : ""}</strong>', html)
        self.assertNotIn('<span class="comparison-score-badge">가장 잘 맞음</span>', html)
        self.assertIn("background:#3182f6;", html)
        self.assertIn("color:#fff; font-size:13px; font-weight:900; line-height:1.35; white-space:nowrap;", html)
        self.assertIn('<div class="comparison-score-fact"><span>종합점수</span><strong>${total !== null ? `${esc(Math.round(total))}점 · ${esc(row?.locationScore?.label || "판단불가")}` : "판단불가"}</strong></div>', html)
        self.assertIn("function comparisonMarketSignalSummary(row)", html)
        self.assertIn('if (momentum !== null && momentum >= .5) label = "상승흐름";', html)
        self.assertIn('else if (momentum !== null && momentum <= -.5) label = "하락흐름";', html)
        self.assertIn('return `${Math.round(score)}점 · ${label || "확인 필요"}`;', html)
        self.assertIn('<div class="comparison-score-fact"><span>최근 시장 신호</span><strong>${esc(comparisonMarketSignalSummary(row))}</strong></div>', html)
        self.assertNotIn('<div class="comparison-score-fact"><span>데이터 반영</span>', html)
        self.assertNotIn('const coverage = comparisonNumber(row?.locationScore?.coverage);', re.search(r"function comparisonScoreOverviewHtml\b(?P<body>.*?)\n    function comparisonValue", html, re.DOTALL).group("body"))
        self.assertIn(".comparison-score-facts {\n      display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin-top:14px;", html)
        self.assertIn(".comparison-score-facts { grid-template-columns:1fr }", html)
        self.assertIn(".comparison-table { min-width:640px }", html)
        self.assertIn("overflow-wrap:anywhere", html)
        self.assertIn(".comparison-score-fact span { display:block; color:#8b95a1; font-size:12px; font-weight:800; line-height:1.35 }", html)
        self.assertNotIn(".comparison-score-fact span { display:block; color:#8b95a1; font-size:11px;", html)
        self.assertNotIn("comparison-score-total-row", html)
        self.assertNotIn("comparison-score-total", html)
        self.assertNotIn("comparison-score-label", html)
        self.assertIn("필요 자기자금", html)
        self.assertIn(".comparison-score-grid { display:grid;", html)
        self.assertIn("body.comparison-open .compare-floating-bar,", html)

    def test_candidate_comparison_chart_matches_candidate_card_on_mobile(self):
        html = APP_HTML.read_text(encoding="utf-8")

        self.assertIn(".comparison-trend {\n      margin:22px -10px 0; padding:0;", html)
        self.assertIn("background:transparent; box-shadow:none;", html)
        self.assertIn(".comparison-trend .budget-sparkline-svg { width:100%; height:auto; max-height:400px; aspect-ratio:auto }", html)
        self.assertIn('const width = window.matchMedia("(max-width: 760px)").matches ? 420 : 640;', html)
        self.assertIn("const height = 292;", html)
        self.assertIn("const renderedFontSize = Math.min(maxRenderedSize, Math.max(minRenderedSize, targetRenderedSize));", html)
        self.assertIn("requestAnimationFrame(() => syncSparkAxisLabelSizes(comparisonContent));", html)

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
        self.assertEqual(load_body.count("applyRoneLatestTradeFallback(item);"), 1)
        self.assertIn("candidateLeaderEstimateItem(item)", load_body)
        self.assertIn("candidateDistrictLeaderEstimateItem(item)", load_body)
        self.assertLess(load_body.index("await candidateRequest"), load_body.index("await Promise.all"))
        self.assertGreaterEqual(load_body.count("refreshMarketInsight(item);"), 3)
        self.assertIn("item.leaderRoneEstimate", load_body)
        self.assertIn("item.districtLeaderRoneEstimate", load_body)

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
        self.assertIn("검토 리포트 준비 중…", body)
        self.assertLess(
            body.index("if (confirmedLatestDate)"),
            body.index("검토 리포트 · 데이터 연결 안 됨"),
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
        self.assertIn("data?.resolvedArea", body)
        self.assertIn("candidate?.latestDealExclusiveArea", body)
        self.assertIn("card?.dataset?.selectedAptAreaChoice", body)
        self.assertIn("clusters.map", body)

    def test_direct_search_renders_exclusive_areas_as_inline_chips(self):
        html = APP_HTML.read_text(encoding="utf-8")
        search_match = re.search(
            r"async function runAptSearch\b(?P<body>.*?)"
            r"\n    const aptReportCache",
            html,
            re.DOTALL,
        )
        render_match = re.search(
            r"function renderAptAreaOptions\b(?P<body>.*?)"
            r"\n    async function enrichAptAreaOptions",
            html,
            re.DOTALL,
        )
        click_match = re.search(
            r'aptSearchResults\.addEventListener\("click", async event => \{(?P<body>.*?)'
            r'\n    \}\);\n    aptAreaSheet\.addEventListener',
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(search_match)
        self.assertIsNotNone(render_match)
        self.assertIsNotNone(click_match)
        self.assertIn('data-apt-area-options role="radiogroup"', search_match.group("body"))
        self.assertNotIn('<button class="apt-area-change"', search_match.group("body"))
        self.assertNotIn('apt-area-picker-title', search_match.group("body"))
        self.assertNotIn('data-apt-area-copy', search_match.group("body"))
        self.assertIn('role="radio"', render_match.group("body"))
        self.assertIn('data-apt-area-label', render_match.group("body"))
        self.assertIn("fallbackAptAreaOption(fallbackData, item, card)", html)
        self.assertIn("fallbackAptAreaOption(initialData, item, card)", html)
        self.assertIn("function aptAreaOptionMatches(optionValue, selectedArea = \"\")", html)
        self.assertIn("Math.floor(optionNumber) === Math.floor(selectedNumber)", html)
        self.assertIn("const selected = aptAreaOptionMatches(value, selectedArea);", render_match.group("body"))
        self.assertIn("const selected = aptAreaOptionMatches(button.dataset.aptArea, selectedArea);", html)
        self.assertNotIn('data-apt-area=""', render_match.group("body"))
        self.assertIn('event.target.closest("[data-apt-area]")', click_match.group("body"))
        self.assertIn('selectAptArea(card, area, `전용 ${label}`, area, "user");', click_match.group("body"))
        self.assertIn("overflow-x:auto", html)
        self.assertIn("background:#20252b", html)
        self.assertIn(".apt-result-card .candidate-price-comparison { margin-top:10px }", html)

    def test_direct_search_defaults_to_the_same_minimum_area_rule_as_step_search(self):
        html = APP_HTML.read_text(encoding="utf-8")
        fetch_match = re.search(
            r"async function fetchAptAffordability\b(?P<body>.*?)"
            r"\n    async function fetchAptAreaOptions",
            html,
            re.DOTALL,
        )
        enrich_match = re.search(
            r"async function enrichAptAffordability\b(?P<body>.*?)"
            r"\n    function refreshAptSearchProfileResults",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(fetch_match)
        self.assertIsNotNone(enrich_match)
        fetch_body = fetch_match.group("body")
        enrich_body = enrich_match.group("body")
        self.assertIn('search_region:item.region || ""', fetch_body)
        self.assertNotIn("multiSelections.region", fetch_body)
        self.assertNotIn("representativeAptAreaOption", html)
        self.assertIn("const minimum = Number(budgetMinArea.value || 0);", enrich_body)
        self.assertIn("const preferredArea = Number(item.preferredArea || 0);", enrich_body)
        self.assertIn("await selectAptArea(", enrich_body)
        self.assertIn('preferredArea ? String(preferredArea) : ""', enrich_body)
        self.assertIn("minimum ? `전용 ${minimum}㎡ 이상`", enrich_body)

    def test_direct_search_enriches_the_regional_leader_chart(self):
        html = APP_HTML.read_text(encoding="utf-8")
        candidate_match = re.search(
            r"function aptMarketCandidate\b(?P<body>.*?)"
            r"\n    async function enrichAptLeaderEstimate",
            html,
            re.DOTALL,
        )
        leader_match = re.search(
            r"async function enrichAptLeaderEstimate\b(?P<body>.*?)"
            r"\n    function aptPolicyImpactHtml",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(candidate_match)
        self.assertIsNotNone(leader_match)
        candidate_body = candidate_match.group("body")
        leader_body = leader_match.group("body")
        self.assertIn("...canonical", candidate_body)
        self.assertIn("latestTrade,", candidate_body)
        self.assertIn("candidateLeaderEstimateItem(candidate)", leader_body)
        self.assertIn("candidateDistrictLeaderEstimateItem(candidate)", leader_body)
        self.assertIn("requestComparableEstimate(target)", leader_body)
        self.assertIn("candidate.leaderEstimateErrors = []", leader_body)
        self.assertIn('enrich(leaderItem, "leaderRoneEstimate"', leader_body)
        self.assertIn('"districtLeaderRoneEstimate"', leader_body)
        self.assertIn("candidate.leaderEstimateErrors.push(failureLabel)", leader_body)

        self.assertIn("async function loadAptSearchTrendInsight(candidate)", html)
        self.assertIn('aptSearchResults.addEventListener("click", async event => {', html)
        self.assertIn('if (trendToggle.dataset.trendAction === "load")', html)
        self.assertIn("const loaded = await loadAptSearchTrendInsight(candidate);", html)
        self.assertIn('candidateMapPreview && candidateMapOrigin === "aptSearch"', html)
        self.assertIn("await loadAptSearchTrendInsight(candidate)", html)
        self.assertIn("candidateMapPreview.innerHTML = candidateMapPreviewHtml(candidate);", html)
        self.assertIn('setupCandidateMapPreviewSheet(candidateMapPreview, { mode:"expanded" });', html)
        self.assertIn("candidateVerdictHtml(candidate, { trendExpanded:loaded })", html)
        self.assertIn("async function refreshAptSearchTrendAfterAreaChange", html)
        self.assertIn('const shouldReloadTrend = card.dataset.aptTrendExpanded === "true"', html)
        self.assertIn('candidate.leaderContextState = "loading";', html)
        self.assertIn('card.dataset.aptTrendExpanded = "true";', html)
        self.assertIn(
            "void refreshAptSearchTrendAfterAreaChange(card, item, data, candidate, requestToken);",
            html,
        )
        self.assertLess(
            html.index("renderAptCandidateResult(card, item, data, candidate, requestToken);"),
            html.index("void refreshAptSearchTrendAfterAreaChange(card, item, data, candidate, requestToken);"),
        )
        self.assertIn(
            "function aptAffordabilityHtml(data, item = {}, report = {}, preparedCandidate = null)",
            html,
        )

    def test_leader_comparison_retries_and_explains_missing_lines(self):
        html = APP_HTML.read_text(encoding="utf-8")
        retry_match = re.search(
            r"async function requestComparableEstimate\b(?P<body>.*?)"
            r"\n    function enrichRoneEstimates",
            html,
            re.DOTALL,
        )
        series_match = re.search(
            r"function sparklineSeries\b(?P<body>.*?)"
            r"\n    function leaderFormulaHtml",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(retry_match)
        self.assertIsNotNone(series_match)
        self.assertIn("attempt < 2", retry_match.group("body"))
        self.assertIn("addVariant({ ...target, jibun:\"\" });", retry_match.group("body"))
        self.assertIn("addVariant({ ...target, legalDong:\"\", jibun:\"\" });", retry_match.group("body"))
        self.assertIn("scheduleLeaderComparisonRetry", html)
        self.assertIn("LEADER_COMPARISON_RETRY_DELAYS_MS", html)
        self.assertIn("comparisonNotices", series_match.group("body"))
        self.assertIn("comparisonPending", series_match.group("body"))
        self.assertIn("겹치는 기준월 없음", series_match.group("body"))
        self.assertIn('class="spark-compare-error"', html)
        self.assertIn("완료되면 차트에 자동으로 추가돼요", html)

    def test_direct_search_uses_the_same_news_enrichment_function(self):
        html = APP_HTML.read_text(encoding="utf-8")
        select_match = re.search(
            r"async function selectAptArea\b(?P<body>.*?)"
            r"\n    async function enrichAptAffordability",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(select_match)
        body = select_match.group("body")
        self.assertIn("void enrichNewsCatalysts([candidate], updated =>", body)
        self.assertIn("renderAptCandidateResult(card, item, data, updated, requestToken);", body)

    def test_direct_search_applies_the_same_latest_trade_fallback_before_render(self):
        html = APP_HTML.read_text(encoding="utf-8")
        select_match = re.search(
            r"async function selectAptArea\b(?P<body>.*?)"
            r"\n    async function enrichAptAffordability",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(select_match)
        body = select_match.group("body")
        self.assertIn("applyRoneLatestTradeFallback(candidate);", body)
        self.assertLess(
            body.index("applyRoneLatestTradeFallback(candidate);"),
            body.index("renderAptCandidateResult(card, item, data, candidate, requestToken);"),
        )

    def test_auto_resolved_area_updates_the_area_button_and_explains_fallback(self):
        html = APP_HTML.read_text(encoding="utf-8")
        render_match = re.search(
            r"function renderAptCandidateResult\b(?P<body>.*?)"
            r"\n    async function refreshAptSearchTrendAfterAreaChange",
            html,
            re.DOTALL,
        )
        affordability_match = re.search(
            r"function aptAffordabilityHtml\b(?P<body>.*?)"
            r"\n    async function fetchAptAffordability",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(render_match)
        self.assertIsNotNone(affordability_match)
        render_body = render_match.group("body")
        affordability_body = affordability_match.group("body")
        self.assertIn('const resolvedArea = String(data?.resolvedArea || "");', render_body)
        self.assertIn("card.dataset.selectedAptArea = resolvedArea;", render_body)
        self.assertIn('if (!card.querySelector("[data-apt-area]"))', render_body)
        self.assertIn("renderAptAreaOptions(card, fallbackAptAreaOption(data, candidate, card), resolvedArea);", render_body)
        self.assertIn("changeButton.textContent = buttonLabel;", render_body)
        self.assertIn("data.areaFallback && Number(data.requestedMinArea || 0)", affordability_body)
        self.assertIn("가장 가까운 실제 거래 평형 자동 선택", affordability_body)

    def test_apartment_search_chart_is_closed_by_default_and_keeps_user_choice(self):
        html = APP_HTML.read_text(encoding="utf-8")
        affordability_match = re.search(
            r"function aptAffordabilityHtml\b(?P<body>.*?)"
            r"\n    async function fetchAptAffordability",
            html,
            re.DOTALL,
        )
        render_match = re.search(
            r"function renderAptCandidateResult\b(?P<body>.*?)"
            r"\n    async function selectAptArea",
            html,
            re.DOTALL,
        )
        click_match = re.search(
            r"aptSearchResults\.addEventListener\(\"click\", async event => \{(?P<body>.*?)"
            r"\n    \}\);\n    aptAreaSheet\.addEventListener",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(affordability_match)
        self.assertIsNotNone(render_match)
        self.assertIsNotNone(click_match)
        self.assertIn(
            "candidateVerdictHtml(candidate, { trendExpanded:candidate.aptSearchTrendExpanded === true })",
            affordability_match.group("body"),
        )
        self.assertIn(
            'const trendExpanded = card.dataset.aptTrendExpanded === "true";',
            render_match.group("body"),
        )
        self.assertIn(
            "candidate.aptSearchTrendExpanded = trendExpanded;",
            render_match.group("body"),
        )
        self.assertIn(
            "aptAffordabilityHtml(data, item, {}, candidate)",
            render_match.group("body"),
        )
        self.assertIn(
            "candidateCard.dataset.aptTrendExpanded = String(!expanded);",
            click_match.group("body"),
        )
        self.assertIn(
            "candidate.aptSearchTrendExpanded = true;",
            click_match.group("body"),
        )

    def test_direct_apartment_search_uses_card_top_map_button(self):
        html = APP_HTML.read_text(encoding="utf-8")
        search_match = re.search(
            r"async function runAptSearch\b(?P<body>.*?)"
            r"\n    async function runApartmentResultSearch",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(search_match)
        search_body = search_match.group("body")

        self.assertIn('let candidateMapOrigin = "budget";', html)
        self.assertIn('candidateMapOrigin = "aptSearch";', html)
        self.assertIn('class="candidate-top has-map-action"', search_body)
        self.assertIn("candidateMapInlineButtonHtml(item)", search_body)
        self.assertIn('data-candidate-map-key="${esc(candidateIdentityKey(item))}"', html)
        self.assertIn("candidateMapViewHtml(items, false, { directSearch:true })", search_body)
        self.assertNotIn("candidateMapFloatingButtonHtml()", search_body)
        self.assertIn("mountCandidateMapPortal(aptSearchResults);", html)
        self.assertIn('candidateMapOrigin === "aptSearch"', html)
        self.assertIn("function aptSearchMapRows()", html)
        self.assertIn("...currentAptSearchRivalItems", html)
        self.assertIn("? aptSearchMapRows()", html)

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

    def test_candidate_detail_modal_locks_background_scroll(self):
        html = APP_HTML.read_text(encoding="utf-8")
        sync_match = re.search(
            r"function syncCandidateDetailScrollLock\b(?P<body>.*?)"
            r"\n    function setCandidateDetailOpen",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(sync_match)
        self.assertIn(
            '".candidate-detail-sheet:not([hidden]), .apt-report-sheet:not([hidden]), .listing-review-sheet:not([hidden]), .location-score-sheet:not([hidden])"',
            sync_match.group("body"),
        )
        self.assertIn(
            'document.body.classList.toggle("candidate-detail-sheet-open", Boolean(openSheet));',
            sync_match.group("body"),
        )
        self.assertIn(
            "body.candidate-detail-sheet-open { overflow:hidden; overscroll-behavior:none }",
            html,
        )
        self.assertIn(
            "min-height:0; overflow:auto; overscroll-behavior:contain; "
            "-webkit-overflow-scrolling:touch;",
            html,
        )
        self.assertGreaterEqual(html.count("syncCandidateDetailScrollLock();"), 4)

    def test_candidate_results_use_a_floating_map_button_without_view_tabs(self):
        html = APP_HTML.read_text(encoding="utf-8")
        render_match = re.search(
            r"function renderBudgetCandidates\b(?P<body>.*?)"
            r"\n    function budgetLoadingStageIndex",
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
        self.assertIn("candidateMapInlineButtonHtml(item)", render_match.group("body"))
        self.assertIn('class="candidate-top has-map-action"', render_match.group("body"))
        self.assertIn(".candidate-top.has-map-action .candidate-name-row,", html)
        self.assertIn(".candidate-top.has-map-action .apartment-name-row { padding-right:82px }", html)
        self.assertIn(".candidate-top > .candidate-map-inline { position:absolute; top:0; right:0;", html)
        self.assertNotIn("candidateViewSwitchHtml()", render_match.group("body"))
        self.assertNotIn("candidate-map-view-switch-row", map_match.group("body"))
        self.assertIn('data-candidate-view="map"', html)
        self.assertIn('data-candidate-map-key="${esc(candidateIdentityKey(item))}"', html)
        self.assertIn("candidateMapSelectedKey = candidateViewButton.dataset.candidateMapKey;", html)
        self.assertIn('<span>지도</span>', html)
        self.assertIn(".candidate-map-inline {", html)
        self.assertIn('aria-label="지도에서 후보 보기"', html)
        self.assertIn("grid-template-columns:minmax(0,1fr) auto auto 44px", html)
        self.assertIn("grid-template-columns:40px minmax(0,1fr) auto", html)
        self.assertIn('class="power-condition-change candidate-map-condition-change"', map_match.group("body"))
        self.assertIn('data-condition-summary-open="power"', map_match.group("body"))
        self.assertIn(".candidate-map-condition-change { grid-column:3; grid-row:1;", html)
        self.assertNotIn('data-candidate-view="list"', html)
        self.assertIn(
            "position:fixed; z-index:75; right:max(22px,env(safe-area-inset-right));",
            html,
        )
        self.assertIn(
            "right:max(18px,env(safe-area-inset-right)); "
            "bottom:max(20px,calc(env(safe-area-inset-bottom) + 12px));",
            html,
        )
        self.assertNotIn("position:static; display:grid; width:52px; height:52px", html)

    def test_flow_score_badge_opens_the_score_sheet_like_total_score(self):
        html = APP_HTML.read_text(encoding="utf-8")
        lookup_match = re.search(
            r"function candidateForLocationScoreButton\b(?P<body>.*?)"
            r"\n    function candidateDetailAreaText",
            html,
            re.DOTALL,
        )
        preview_match = re.search(
            r"function candidateMapPreviewHtml\b(?P<body>.*?)"
            r"\n    function candidateMapUsesBottomSheet",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(lookup_match)
        self.assertIsNotNone(preview_match)
        self.assertIn(
            '<button class="location-score-badge" type="button" data-location-score-open',
            html,
        )
        self.assertIn(
            '<button class="flow-score-badge" type="button" data-flow-score-open',
            html,
        )
        self.assertIn(".location-score-badge::after", html)
        self.assertIn(".flow-score-badge::after", html)
        self.assertIn("background:#f1f7ff; color:#1767c5; font-size:13px; font-weight:850;", html)
        self.assertIn("box-shadow:0 1px 2px rgba(49,130,246,.13)", html)
        self.assertIn("transform:translateY(-1px)", html)
        self.assertIn('const measurable = Number.isFinite(score) && score > 0;', html)
        self.assertIn('const label = measurable ? `${Math.round(score)}점` : "측정 불가";', html)
        self.assertIn('최근 시장 신호 ${esc(label)}', html)
        self.assertIn("function candidateTopScoreBadgesHtml(item)", html)
        self.assertIn("const badges = `${candidateLocationScoreBadgeHtml(item)}${candidateFlowScoreBadgeHtml(item)}`;", html)
        self.assertIn("signals:item?.signals || {}", html)
        self.assertIn("locationScore:item?.locationScore || null", html)
        self.assertNotIn("showFlowScore", html)
        self.assertNotIn('candidateTopScoreBadgesHtml(item, budgetSort === "flow_best")', html)
        self.assertIn("const locationScoreOpen = event.target.closest(\"[data-location-score-open]\");", html)
        self.assertIn("const flowScoreOpen = event.target.closest(\"[data-flow-score-open]\");", html)
        self.assertIn("openLocationScoreSheet(candidate, locationScoreOpen);", html)
        self.assertIn("openFlowScoreSheet(candidate, flowScoreOpen);", html)
        self.assertIn("function locationScoreNeedsRefresh(item)", html)
        self.assertIn('const LOCATION_SCORE_FORMULA_VERSION = "purchase-judgment-v3";', html)
        self.assertIn("item?.locationScore?.scoreFormulaVersion !== LOCATION_SCORE_FORMULA_VERSION", html)
        self.assertIn("const jeonseRatio = Number(item?.jeonseRatioPct);", html)
        self.assertIn('if (!["price", "jeonse", "demand", "product", "market"].every(key => partKeys.has(key))) return true;', html)
        self.assertIn('if (!["jeonse_ratio", "jeonse_freshness", "investment_gap"].every(key => jeonseDetailKeys.has(key))) return true;', html)
        self.assertIn('["jeonse", "transport", "education"].includes(key)', html)
        self.assertIn('["jeonse_ratio", "jeonse_freshness", "investment_gap", "station", "education"].includes(String(detail?.key || ""))', html)
        self.assertIn('getJson("/api/apartment-location-score"', html)
        self.assertIn("const originalKey = candidateIdentityKey(item);", html)
        self.assertIn("candidateRowsForLookup().forEach(row =>", html)
        self.assertIn("void refreshLocationScoreSheet(item);", html)
        self.assertIn('data-candidate-key="${esc(candidateIdentityKey(item))}"', preview_match.group("body"))
        self.assertIn('const mapPreview = button.closest("[data-candidate-map-preview]");', lookup_match.group("body"))
        self.assertIn('const previewKey = mapPreview.dataset.candidateKey || button.closest("[data-candidate-key]")?.dataset.candidateKey || candidateMapSelectedKey;', lookup_match.group("body"))
        self.assertIn("...candidateMapEntries.map(entry => entry.item)", html)
        self.assertIn("...candidateMapLocatedEntries.map(entry => entry.item)", html)
        self.assertIn("preview.dataset.candidateKey = candidateIdentityKey(item);", html)
        self.assertIn("preview.dataset.candidateKey = candidateIdentityKey(candidate);", html)
        self.assertIn(".location-score-sheet { z-index:170 }", html)
        self.assertIn("종합 점수표", html)
        self.assertIn("function locationScoreJudge(points, max)", html)
        self.assertIn("function locationScoreJudgeHtml(points, max)", html)
        self.assertIn('return { label:"판단불가", tone:"missing" };', html)
        self.assertIn("function locationScorePartHasNoData(part)", html)
        self.assertIn('missing ? "판단불가"', html)
        self.assertIn("location-score-judge is-", html)
        self.assertIn(".location-score-judge.is-good", html)
        self.assertIn(".location-score-judge.is-caution", html)
        self.assertIn('${esc(part?.label || "항목")} ${locationScoreJudgeHtml(judgePoints, max)}', html)
        self.assertIn("location-score-details", html)
        self.assertIn("<summary>세부 근거 보기</summary>", html)
        self.assertIn("location-score-details-body", html)
        self.assertIn("location-score-detail-list", html)
        self.assertIn(".location-score-reason { grid-column:1 / -1; color:#667085; font-size:14px;", html)
        self.assertIn("display:inline-flex; align-items:center; justify-content:center; gap:7px; min-height:36px;", html)
        self.assertIn("background:#fff; color:#3182f6; font-size:14px; font-weight:800; line-height:1.4; cursor:pointer; list-style:none;", html)
        self.assertIn(".location-score-details summary:hover { background:#f8f9fa; color:#1b64da }", html)
        self.assertIn(".location-score-details summary:focus-visible { outline:2px solid #3182f6; outline-offset:2px }", html)
        self.assertIn(".location-score-detail-list { display:grid; gap:10px; margin:0; padding:0; list-style:none }", html)
        self.assertIn(".location-score-detail-list strong { color:#303846; font-size:13px; font-weight:850; line-height:1.35 }", html)
        self.assertIn(".location-score-detail-list small { grid-column:1 / -1; color:#8b95a1; font-size:13px; font-weight:650; line-height:1.38 }", html)
        self.assertIn("padding:0;\n      color:#4e5968; font-size:13px;", html)
        self.assertLess(
            html.index('<span class="location-score-bar" aria-hidden="true">'),
            html.index("${disclosureHtml}"),
        )
        self.assertIn("const detailBlockHtml = [jeonseSummaryHtml, detailHtml].filter(Boolean).join(\"\");", html)
        self.assertNotIn("location-score-basis", html)
        self.assertIn("function locationScoreJeonseSummaryHtml(item)", html)
        self.assertIn('const jeonseSummaryHtml = item && typeof item === "object" && part?.key === "jeonse" ? locationScoreJeonseSummaryHtml(item) : "";', html)
        self.assertIn("전세 실거래 기준", html)
        self.assertIn("전세 추정 기준", html)
        self.assertIn('const estimated = status === "estimated";', html)
        self.assertIn('estimated ? "추정값"', html)
        self.assertIn("전세 실거래를 지금 불러오지 못했어요. 잠시 후 다시 확인해 주세요.", html)
        self.assertIn("전세가율 계산에 쓸 매매 기준가를 먼저 확인해야 해요.", html)
        self.assertIn('const missingLabel = ["api_error", "key_missing"].includes(status) ? "확인 중" : "미수집";', html)
        self.assertNotIn("국토부 실거래가 API 권한이 없거나 인증키가 승인되지 않았어요.", html)
        self.assertNotIn('status === "key_missing" ? "키 필요"', html)
        self.assertIn("location-score-jeonse-grid", html)
        self.assertIn("parts.map(part => locationScorePartHtml(part, item)).join(\"\")", html)
        self.assertNotIn("<p class=\"location-score-coverage\">반영된 데이터: ${esc(Math.round(coverage * 100))}%</p>\\n        ${locationScoreJeonseSummaryHtml(item)}", html)
        self.assertIn('const source = item?.jeonseSourceNote || "국토부 전월세 실거래가 · 월세 제외";', html)
        self.assertIn("medianJeonseDepositEok:item?.medianJeonseDepositEok || 0", html)
        self.assertIn("currentEstimateMinPriceEok:item?.currentEstimateMinPriceEok || 0", html)
        self.assertIn("currentEstimateMaxPriceEok:item?.currentEstimateMaxPriceEok || 0", html)
        self.assertIn("locationScoreTitle.textContent = `${candidateDisplayName(item)} 최근 시장 신호표`;", html)
        self.assertIn("locationScoreContent.innerHTML = candidateLegacySignalReportHtml(item);", html)
        self.assertIn('aria-label="최근 시장 신호 계산 기준"', html)
        self.assertIn("현재 매물 호가와 입주 물량은 아직 반영하지 않았어요.", html)
        self.assertIn("${candidateSharedActionsHtml(item)}", preview_match.group("body"))
        self.assertNotIn("data-candidate-map-detail-open", preview_match.group("body"))
        self.assertNotIn("검토 리포트", preview_match.group("body"))

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

    def test_candidate_map_mobile_sheet_starts_compact_and_swipes_full(self):
        html = APP_HTML.read_text(encoding="utf-8")
        setup_match = re.search(
            r"function setupCandidateMapPreviewSheet\b(?P<body>.*?)"
            r"\n    function beginCandidateMapSheetDrag",
            html,
            re.DOTALL,
        )
        drag_match = re.search(
            r"function endCandidateMapSheetDrag\b(?P<body>.*?)"
            r"\n    function candidateMapMarkerHtml",
            html,
            re.DOTALL,
        )
        pointer_match = re.search(
            r"function handleCandidateMapPointerDown\b(?P<body>.*?)"
            r"\n    budgetResultEl\.addEventListener\(\"pointerdown\"",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(setup_match)
        self.assertIsNotNone(drag_match)
        self.assertIsNotNone(pointer_match)
        self.assertIn('options.expanded === true ? "expanded" : "collapsed"', setup_match.group("body"))
        self.assertIn("const collapsedTargetRect = (comparison || summary).getBoundingClientRect();", setup_match.group("body"))
        self.assertIn("swipeDistance >= 48", drag_match.group("body"))
        self.assertIn("swipeDistance <= -48", drag_match.group("body"))
        self.assertIn('"minimized"', drag_match.group("body"))
        self.assertIn("drag.currentHeight <= minimizeThreshold", drag_match.group("body"))
        self.assertIn('preview?.dataset.mobileState === "collapsed" ? preview : null', pointer_match.group("body"))
        self.assertIn(
            '.candidate-map-preview[data-mobile-state="collapsed"] .candidate-price-comparison',
            html,
        )
        self.assertIn(
            '.candidate-map-preview[data-mobile-state="minimized"] .candidate-map-sheet-content',
            html,
        )
        self.assertIn(
            '.candidate-map-preview[data-mobile-state="collapsed"] .candidate-map-sheet-content',
            html,
        )

    def test_market_sparkline_tooltip_shows_selected_month_trade_date_and_price(self):
        html = APP_HTML.read_text(encoding="utf-8")
        tooltip_match = re.search(
            r"function showSparkPointDetails\b(?P<body>.*?)"
            r"\n    function candidateTrendControlHtml",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(tooltip_match)
        tooltip_body = tooltip_match.group("body")
        self.assertIn("point.dataset.periodTitle", tooltip_body)
        self.assertIn('class="spark-tooltip-period"', tooltip_body)
        self.assertIn("sparkTradeDetailDate(trade.dealDate)", tooltip_body)
        self.assertIn("policyMoney(Number(trade.price || 0))", tooltip_body)
        self.assertNotIn("주변 평균보다", tooltip_body)
        self.assertNotIn("<span>이 단지</span>", tooltip_body)
        self.assertNotIn("평균 거래가", tooltip_body)
        self.assertNotIn("실거래 ${trades.length}건", tooltip_body)
        self.assertIn('data-period-title="${esc(sparkTradeDetailPeriod(series.periods[index]))}"', html)
        self.assertIn('return match ? `${match[1]}년 ${Number(match[2])}월`', html)

    def test_minimum_area_picker_can_switch_between_square_metres_and_pyeong(self):
        html = APP_HTML.read_text(encoding="utf-8")

        self.assertGreaterEqual(html.count("data-area-unit-toggle"), 3)
        self.assertIn('class="area-input-wrap"', html)
        self.assertIn(".area-input-wrap > .area-unit-toggle", html)
        self.assertIn("condition-item-area-unit-tools", html)
        self.assertIn("syncConditionEditAreaUnitDisplay();", html)
        self.assertIn('activeConditionEditTarget !== "budgetMinArea"', html)
        self.assertNotIn("budget-field-label-row", html)
        self.assertIn('let areaDisplayUnit = "sqm";', html)
        self.assertIn('squareMetres / 3.305785', html)
        self.assertIn('return `${pyeong}평 이상`;', html)
        self.assertIn('return `${squareMetres}㎡ 이상`;', html)
        self.assertIn('areaDisplayUnit = areaDisplayUnit === "sqm" ? "pyeong" : "sqm";', html)
        self.assertIn('areaDisplayUnit = saved.preference?.areaDisplayUnit', html)
        self.assertIn('areaDisplayUnit,', html)

    def test_naver_property_actions_stay_in_app_on_mobile(self):
        html = APP_HTML.read_text(encoding="utf-8")
        action_match = re.search(
            r"function candidateNaverPropertyActionHtml\b(?P<body>.*?)"
            r"\n    function candidateListMetaHtml",
            html,
            re.DOTALL,
        )
        handler_match = re.search(
            r"function handleNaverLandLinkClick\b(?P<body>.*?)"
            r"\n    function candidateListMetaHtml",
            html,
            re.DOTALL,
        )
        budget_click_match = re.search(
            r"async function handleBudgetResultClick\(event\) \{(?P<body>.*?)"
            r"\n      const candidateMapSheetHandle",
            html,
            re.DOTALL,
        )
        apt_click_match = re.search(
            r'aptSearchResults\.addEventListener\("click", async event => \{(?P<body>.*?)'
            r"\n      const candidateViewButton",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(action_match)
        self.assertIsNotNone(handler_match)
        self.assertIsNotNone(budget_click_match)
        self.assertIsNotNone(apt_click_match)
        action_body = action_match.group("body")
        handler_body = handler_match.group("body")
        self.assertNotIn('target="_blank"', action_body)
        self.assertIn("function candidateNaverPropertyFallbackUrl(item)", html)
        self.assertIn("fin.land.naver.com/search", html)
        self.assertIn('rel="noopener noreferrer"', action_body)
        self.assertIn('candidateNaverPropertyActionHtml(item, "네이버 부동산에서 시세보기"', html)
        self.assertIn('pending.dataset.naverLandLabel || "네이버 부동산에서 시세보기"', html)
        self.assertNotIn("네이버 부동산에서 시세보기 >", html)
        self.assertIn(".condition-stage-results .naver-land-action {", html)
        self.assertIn("background:#3182f6; color:#fff; font-size:14px; font-weight:800;", html)
        self.assertIn(".condition-stage-results .naver-land-action:hover { background:#1b64da }", html)
        self.assertIn(".apt-result-naver { display:block; border:0; border-radius:12px; padding:14px 16px; background:#3182f6;", html)
        self.assertIn(".apt-result-naver:hover { background:#1b64da;", html)
        self.assertNotIn("background:#0b0b0c; color:#fff; box-shadow:none;", html)
        self.assertIn("const url = candidateNaverPropertyUrl(item) || candidateNaverPropertyFallbackUrl(item);", action_body)
        self.assertNotIn("네이버 단지 연결 확인 중", action_body)
        self.assertIn("data-naver-land-title", action_body)
        self.assertIn('window.matchMedia?.("(max-width:700px)")?.matches', html)
        self.assertIn("saveNaverReturnState();", handler_body)
        self.assertIn("event.preventDefault();", handler_body)
        self.assertIn("isPlainPrimaryClick(event)", handler_body)
        self.assertIn("isMobileNaverInAppView()", handler_body)
        self.assertIn("if (isMobileNaverInAppView()) return false;", handler_body)
        self.assertNotIn("window.location.assign(link.href);", handler_body)
        self.assertIn('window.open(link.href, "_blank", "noopener,noreferrer");', handler_body)
        self.assertIn("handleNaverLandLinkClick(event, naverLandLink)", budget_click_match.group("body"))
        self.assertIn("handleNaverLandLinkClick(event, naverLandLink)", apt_click_match.group("body"))
        self.assertNotIn("새 탭으로 열기", html)

    def test_candidate_sort_and_filter_options_match_the_review_workflow(self):
        html = APP_HTML.read_text(encoding="utf-8")
        sort_match = re.search(
            r"function candidateSortHtml\b(?P<body>.*?)"
            r"\n    function sortCandidateRows",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(sort_match)
        sort_body = sort_match.group("body")
        for label in (
            "종합 정보 높은 순",
            "시장 신호 강한 순",
            "지역보다 많이 움직인 순",
            "예산에 가까운 순",
            "실거래가 낮은 순",
            "새 아파트 순",
            "대단지 순",
            "거래 많은 순",
        ):
            self.assertIn(label, sort_body)
        for help_text in (
            "가격·전세·입지·흐름을 함께 본 집",
            "가격과 거래가 크게 움직인 집",
            "같은 구 평균보다 움직임이 큰 집",
        ):
            self.assertIn(help_text, sort_body)
        for removed in (
            "반등 시작 순",
            "대장보다 강한 순",
            "고점보다 싼 순",
            "최근 3개월 다시 오르는 집",
            "대장 아파트보다 더 오른 집",
            "최근 2년 최고가보다 낮은 집",
            "최근 시장 신호 점수 높은순",
            "최근 시장 신호 점수 낮은순",
            "마지막 동일 면적 거래가 3개월 이내",
            "데이터 신뢰도가 보통 이상",
            "최근 거래순",
            "추가 자금 적은순",
        ):
            self.assertNotIn(removed, sort_body)
        self.assertIn("function candidateReboundRank", html)
        self.assertIn("function candidateLocationScoreNumber", html)
        self.assertIn("candidateLocationScoreNumber(left)", html)
        self.assertIn('candidateSignalNumber(left, "leaderRelativePct")', html)
        self.assertIn('candidateSignalNumber(left, "districtRelativePct")', html)
        self.assertIn("candidateSortReasonHtml(item, budgetSort)", html)
        self.assertIn('<strong>${esc(message)}</strong>', html)
        for label in (
            "1개월 이내 거래",
            "3개월 이내 거래",
            "거래자료 충분",
            "추가 자금 +5%까지",
        ):
            self.assertIn(label, html)
        self.assertIn('let includeAdditionalFundingCandidates = true;', html)
        self.assertIn('candidateTradeAgeFilter === "1m" ? "" : "1m"', html)
        self.assertIn('candidateTradeAgeFilter === "3m" ? "" : "3m"', html)
        self.assertIn("filterSourceRows.filter(candidateMatchesActiveFilters)", html)
        self.assertIn("function candidateSameAreaTradeAgeDays", html)
        self.assertIn('data-candidate-filter="${value}"', html)
        self.assertNotIn("<strong>남길 집</strong>을 골라요", html)
        self.assertNotIn("<strong>먼저 볼 순서</strong>를 정해요", html)
        self.assertNotIn("candidate-sort-trigger-prefix", html)
        self.assertIn('<h4 class="result-info-sheet-title" id="${titleId}">먼저 볼 순서</h4>', html)
        self.assertIn('`매수 후보 <span class="title-count">${esc(resultCount)}단지</span>`', html)
        self.assertNotIn('조건에 맞는 주요 단지 <span class="title-count">', html)
        self.assertIn(
            "gap:8px; min-height:24px; border:0; border-radius:0;",
            html,
        )
        self.assertIn(".candidate-filter-option:hover,.candidate-filter-option[aria-checked=\"true\"] { color:#191f28 }", html)
        self.assertIn(".condition-stage-results .candidate-filter-trigger { min-height:32px; padding:0 12px; font-size:14px }", html)
        self.assertIn("padding-bottom:2px; color:#1d1d1f; font-size:21px; font-weight:800; line-height:1.32;", html)
        self.assertIn("margin:6px calc(50% - 50vw) 10px; padding:6px max(16px,calc((100vw - 760px) / 2));", html)
        self.assertIn("grid-template-columns:minmax(0,1fr) auto; align-items:center; gap:8px 14px;", html)
        self.assertIn("margin:6px calc(50% - 50vw) 12px; padding-top:6px;", html)
        self.assertIn(".condition-stage-results .candidate-filter-group { min-width:0 }", html)
        self.assertIn("grid-template-columns:auto minmax(0,1fr); align-items:center; gap:8px;", html)

    def test_listing_review_can_be_saved_shared_and_printed(self):
        html = APP_HTML.read_text(encoding="utf-8")

        self.assertNotIn('id="listingReviewEntry"', html)
        self.assertIn('id="listingReportHistoryEntry"', html)
        self.assertNotIn('data-listing-review-name=', html)
        self.assertIn('getJson("/api/listing-review"', html)
        self.assertIn('"X-Report-Owner-Token":ownerToken', html)
        self.assertIn("data-listing-review-share", html)
        self.assertIn("data-listing-review-print", html)
        self.assertIn("window.print();", html)
        self.assertIn('<option value="3" selected>매매가의 3%</option>', html)
        self.assertIn("let includeAdditionalFundingCandidates = true;", html)
        self.assertIn("includeAdditionalFundingCandidates = true;", html)
        self.assertIn(
            "includeAdditionalFundingCandidates = saved.includeAdditionalFundingCandidates !== false;",
            html,
        )


if __name__ == "__main__":
    unittest.main()
