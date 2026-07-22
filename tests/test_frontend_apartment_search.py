import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_HTML = ROOT / "앱화면" / "real-estate-search.html"


class FrontendApartmentSearchTest(unittest.TestCase):
    def test_chart_open_is_not_blocked_by_optional_leader_comparisons(self):
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
        self.assertNotIn("requireLeaderComparison:true", load_body)
        self.assertIn("loaded && Boolean(sparklineSeries(item))", load_body)
        self.assertIn("Boolean(sparklineSeries(candidate))", direct_match.group("body"))
        self.assertIn(
            'data-trend-action="load" aria-expanded="false">차트보기</button>',
            html,
        )

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

    def test_leader_region_filters_use_os_native_select_menu(self):
        html = APP_HTML.read_text(encoding="utf-8")
        style_match = re.search(
            r"\.leader-field select\s*\{(?P<body>.*?)\}",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(style_match)
        style_body = style_match.group("body")
        self.assertIn("appearance:auto", style_body)
        self.assertIn("-webkit-appearance:menulist", style_body)
        self.assertNotIn("appearance:none", style_body)

    def test_mobile_leader_submit_spans_all_gyeonggi_filter_columns(self):
        html = APP_HTML.read_text(encoding="utf-8")

        self.assertIn(".leader-submit { grid-column:1 / -1 }", html)
        self.assertNotIn(".leader-submit { grid-column:1 }", html)

    def test_first_place_leader_card_can_collapse_and_keeps_state_during_rerender(self):
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
        self.assertIn('leaderWinnerCollapsed = false;', html)

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
        self.assertIn("leaderPriceText(item.leaderPrice12m)", presentation_body)
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
        self.assertIsNotNone(regional_index_match)
        series_body = series_match.group("body")
        summary_body = summary_match.group("body")
        summary_html_body = summary_html_match.group("body")
        chart_body = chart_match.group("body")
        self.assertIn("const complexPrices =", series_body)
        self.assertIn("value / anchorPrice * 100", series_body)
        self.assertIn("value / anchorIndex * 100", series_body)
        self.assertIn("value / leaderAnchorPrice * 100", series_body)
        self.assertIn("item.leaderRoneEstimate", series_body)
        self.assertIn("item.districtLeaderRoneEstimate", series_body)
        self.assertIn("value / districtLeaderAnchorPrice * 100", series_body)
        self.assertNotIn("anchorPrice * value / anchorIndex", series_body)
        self.assertIn("anchorPeriod:periods[anchor]", series_body)
        self.assertIn("axisTrend(value)", chart_body)
        self.assertIn("const w = 420, h = 194;", chart_body)
        self.assertIn("aspect-ratio:210 / 97", html)
        self.assertIn(".insight-trend .trend-toggle { font-size:15px; line-height:1.4 }", html)
        self.assertNotIn("spark-summary-title", summary_html_body)
        self.assertNotIn("spark-summary-message", summary_html_body)
        self.assertIn("windowMonths % 12 === 0", summary_html_body)
        self.assertIn("최근 ${windowMonths / 12}년 기준", summary_html_body)
        self.assertIn('<span class="spark-summary-basis">${esc(windowLabel)}</span>', summary_html_body)
        self.assertIn(".spark-summary-basis {", html)
        self.assertIn("<strong>${esc(summary.complexName)} <em", summary_html_body)
        self.assertIn("${esc(summary.regionName)} 평균 <em>", summary_html_body)
        self.assertIn("${esc(summary.series.leaderName)} <em>", summary_html_body)
        self.assertIn("candidateTrendSummaryHtml(summary)", chart_body)
        self.assertIn("${regionName} 평균보다 더 많이 내려 흐름은 지켜봐야 해요", summary_body)
        self.assertIn("${esc(regionName)} 평균 지수", chart_body)
        self.assertIn("series.regionSource.includes(\"R-ONE\")", chart_body)
        self.assertIn("가격 대비 · 지역 흐름은 ${esc(regionBasis)} 기준", chart_body)
        self.assertIn("payload?.index?.history", regional_index_match.group("body"))
        self.assertIn("payload?.adjustedTransactions", regional_index_match.group("body"))
        self.assertIn("regionalIndexValues(payload, periods)", series_body)
        self.assertIn("regionSource:String(payload?.index?.source || \"\")", series_body)
        self.assertNotIn("=100", chart_body)
        self.assertNotIn("%p", chart_body)
        self.assertIn("${regionName} 평균보다 더 올라 흐름이 좋아요", summary_body)
        self.assertNotIn("아파트 시장", chart_body)
        self.assertIn(": [max, 100, min]", chart_body)
        self.assertIn("data-complex-trend-label", chart_body)
        self.assertIn("data-region-trend-label", chart_body)
        self.assertNotIn("spark-peak", chart_body)
        self.assertNotIn("최근 2년 고점", chart_body)
        self.assertNotIn(".spark-peak-", html)
        self.assertIn('stroke="#d99024"', chart_body)
        self.assertIn("spark-dot spark-leader", chart_body)
        self.assertIn('class="spark-legend-item spark-legend-primary"', chart_body)
        self.assertIn(".spark-legend-primary { color:#344054; font-weight:850 }", html)
        self.assertIn('class="spark-leader-group"', chart_body)
        self.assertIn('class="spark-legend-item spark-leader-search"', chart_body)
        self.assertIn('data-leader-search-name="${esc(series.leaderName)}"', chart_body)
        self.assertIn('data-leader-search-region="${esc(leaderSearchRegion)}"', chart_body)
        self.assertIn('aria-label="${esc(`${series.leaderName} ${sharedLeaderRegionName} 대장 검색`)}"', chart_body)
        self.assertIn("leaderFormulaHtml(item, leaderRegionName)", chart_body)
        self.assertIn("series.districtLeaderSharesLocality", chart_body)
        self.assertIn("`${leaderRegionName}/${districtLeaderRegionName}`", chart_body)
        self.assertIn("${esc(series.leaderName)} · ${esc(sharedLeaderRegionName)} 대장", chart_body)
        self.assertIn("${esc(series.districtLeaderName)} · ${esc(districtLeaderRegionName)} 대장", chart_body)
        self.assertIn('stroke="#8067c7"', chart_body)
        self.assertNotIn('stroke-dasharray="5 3"', chart_body)
        self.assertIn('stroke="#1677ff" stroke-width="3"', chart_body)
        self.assertIn("spark-dot spark-district-leader", chart_body)
        self.assertNotIn("지역 대장", chart_body)
        self.assertIn("complexRate - leaderRate", summary_body)
        self.assertIn("${regionName} 평균보다 강하고, ${leaderRegionName} 대장과 같은 방향으로 오르는 좋은 흐름이에요", summary_body)
        self.assertIn("${regionName} 평균과 ${leaderRegionName} 대장을 모두 앞서는 강한 상승 흐름이에요", summary_body)
        self.assertIn("하락장에서도 잘 버티고 있어요", summary_body)
        self.assertIn("${regionName} 평균과 ${leaderRegionName} 대장보다 더 많이 내려 흐름은 지켜봐야 해요", summary_body)
        self.assertNotIn("지역 대장", summary_body)
        self.assertNotIn("가격 방어력이 약한 흐름이에요", summary_body)
        self.assertIn('aria-label="${esc(`${regionName} 대장아파트 산정식 보기`)}"', html)
        self.assertIn("전용 ${leaderAreaText(targetArea)}㎡ 실거래 중위가", html)
        self.assertIn("leaderRepresentativeArea", html)
        self.assertIn("leaderRepresentativeMedianPrice12m", html)
        self.assertIn("실제 거래 중앙면적", html)
        self.assertIn("전용 84㎡ 거래가 2건 미만인 단지는 제외", html)
        self.assertNotIn("실거래가 × (${esc(leaderAreaText(targetArea))} ÷ 실제면적)<sup>0.75</sup>", html)
        self.assertNotIn("최근 12개월 중위가", html)
        self.assertIn("전용 84㎡ 실제 거래", html)
        self.assertNotIn("가격 수준 · 35%", html)
        self.assertNotIn("상승 선도력 · 25%", html)
        self.assertNotIn("역 접근성 · 10%", html)
        self.assertIn("syncSparkAxisLabelSizes();\n      hideSparkTooltips();", html)
        self.assertIn("const minRenderedSize = 11;", html)
        self.assertIn("const maxRenderedSize = 11;", html)
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
            r"function candidateSparklineHtml\b(?P<body>.*?)"
            r"\n    function sparkTradeDetailDate",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(chart_match)
        chart_body = chart_match.group("body")
        self.assertIn("item.signals?.isRegionalLeader", chart_body)
        self.assertIn('class="spark-self-leader"', chart_body)
        self.assertIn("${esc(complexName)} · ${esc(sharedLeaderRegionName)} 대장", chart_body)
        self.assertIn("item.signals?.isDistrictLeader", chart_body)
        self.assertIn(".spark-self-leader {", html)

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
        self.assertIn("await requestLeaderContext(item)", selected_body)
        self.assertIn("await loadMarketInsight(item)", selected_body)
        self.assertNotIn("requireLeaderComparison:true", selected_body)
        self.assertIn("Boolean(sparklineSeries(item))", selected_body)
        self.assertIn("대장 비교 불러오는 중", html)
        self.assertIn("const loaded = await loadCandidateTrendInsight(candidate);", html)

    def test_candidate_insight_combines_personal_choice_price_flow_and_news(self):
        html = APP_HTML.read_text(encoding="utf-8")
        gains_match = re.search(
            r"function candidateChoiceGains\(item\) \{(?P<body>.*?)"
            r"\n    function candidateChoiceGainObject",
            html,
            re.DOTALL,
        )
        funding_severity_match = re.search(
            r"function candidateChoiceFundingSeverity\(gap\) \{(?P<body>.*?)"
            r"\n    function candidateChoiceFundingCost",
            html,
            re.DOTALL,
        )
        funding_match = re.search(
            r"function candidateChoiceFundingCost\(item\) \{(?P<body>.*?)"
            r"\n    function candidateChoiceCost",
            html,
            re.DOTALL,
        )
        cost_match = re.search(
            r"function candidateChoiceCost\(item\) \{(?P<body>.*?)"
            r"\n    function candidateChoiceCatalyst",
            html,
            re.DOTALL,
        )
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

        self.assertIsNotNone(gains_match)
        self.assertIsNotNone(funding_severity_match)
        self.assertIsNotNone(funding_match)
        self.assertIsNotNone(cost_match)
        self.assertIsNotNone(summary_lines_match)
        self.assertIsNotNone(trend_insight_match)
        self.assertIsNotNone(verdict_match)
        gains_body = gains_match.group("body")
        funding_severity_body = funding_severity_match.group("body")
        funding_body = funding_match.group("body")
        cost_body = cost_match.group("body")
        summary_lines_body = summary_lines_match.group("body")
        trend_insight_body = trend_insight_match.group("body")
        verdict_body = verdict_match.group("body")
        self.assertIn('rarity?.kind === "households"', gains_body)
        self.assertIn('rarity?.kind === "age"', gains_body)
        self.assertIn('["short", "restricted"].includes(fundingStatus) || cash?.gap < 0', gains_body)
        self.assertIn('cash?.gap >= .3 && fundingStatus === "possible"', gains_body)
        self.assertIn("!hasFundingShortfall", gains_body)
        self.assertIn('gains.push("최근 고점보다 낮은 가격")', gains_body)
        self.assertNotIn('gains.push("가격 여유")', gains_body)
        self.assertIn("return gains.slice(0, 2);", gains_body)
        self.assertIn("currentBudgetData?.budgetEok || currentPurchasePower?.budgetEok", funding_severity_body)
        self.assertIn("Math.abs(value) / purchaseCeiling", funding_severity_body)
        self.assertIn("shortageRatio <= .01", funding_severity_body)
        self.assertIn("shortageRatio <= .03", funding_severity_body)
        self.assertIn("shortageRatio <= .10", funding_severity_body)
        self.assertIn('scenario?.type === "latest_deal"', funding_body)
        self.assertIn('scenario?.type === "recent3_average"', funding_body)
        self.assertIn("최근 실거래 기준 ${readableGapMoney(Math.abs(latestGap))} 조정 시 가능", funding_body)
        self.assertIn("3개월 평균 기준 ${readableGapMoney(Math.abs(recentAverageGap))} 조정 필요", funding_body)
        self.assertIn('severity === "near"', funding_body)
        self.assertIn('severity === "negotiate"', funding_body)
        self.assertIn('severity === "burden"', funding_body)
        self.assertIn('severity === "high"', funding_body)
        self.assertIn("매수 상한과 거의 맞음", funding_body)
        self.assertIn("가격 협상 필요", funding_body)
        self.assertIn("가격 부담 있음", funding_body)
        self.assertIn("가격 부담 큼", funding_body)
        self.assertIn("주담대 상한 영향", funding_body)
        self.assertNotIn("소득 기준 대출한도 영향", funding_body)
        self.assertIn("LTV 한도 영향", funding_body)
        self.assertIn("DSR 기준 예상 대출 한도", html)
        self.assertLess(
            cost_body.index('item.policyImpact?.status === "restricted"'),
            cost_body.index("cash?.gap < 0"),
        )
        self.assertLess(cost_body.index("cash?.gap < 0"), cost_body.index("ageDays != null && ageDays > 120"))
        self.assertIn('item.policyImpact?.status === "short" || cash?.gap < 0', cost_body)
        self.assertIn("candidateChoiceFundingCost(item)", cost_body)
        self.assertIn("거래 표본이 적어 적정 가격 판단은 어려워요", cost_body)
        self.assertIn("가격은 최근 2년 고점과 거의 비슷해요", cost_body)
        self.assertNotIn("가격 메리트는 크지 않아요", cost_body)
        self.assertIn("candidateChoiceRelativeCost(item)", cost_body)
        self.assertIn("candidateDealAgeDays(item.latestDealDate)", html)
        self.assertIn("candidateDealAgeDays(item.roneEstimate?.latestTrade?.dealDate)", html)
        self.assertIn("Math.min(...ages)", html)
        self.assertIn("candidateChoiceCatalystSubject(item)", summary_lines_body)
        self.assertIn("candidateChoiceCompactText(cost)", summary_lines_body)
        self.assertIn('["near", "negotiate"].includes(fundingSeverity)', summary_lines_body)
        self.assertIn('`${gains.join(" · ")} · ${candidateChoiceCompactText(cost)}`', summary_lines_body)
        self.assertIn('[/상승 흐름은 더 지켜봐야 해요$/, "상승 흐름 확인 필요"]', html)
        self.assertNotIn('"상승 상승 흐름"', html)
        self.assertIn("const trendSummary = candidateTrendSummary(item);", summary_lines_body)
        self.assertIn('lines.push(`${gainObject} 얻는 대신 ${candidateChoiceCompactText(cost)}`);', summary_lines_body)
        self.assertIn('lines.push(`${catalystSubject} 긍정 변수`);', summary_lines_body)
        self.assertIn("lines.push(candidateChoiceCompactText(trendMessage))", summary_lines_body)
        self.assertIn("...new Set(lines)", summary_lines_body)
        self.assertIn('row?.scope === "complex"', html)
        self.assertIn('row?.status === "confirmed"', html)
        self.assertIn('row?.scope === "area"', html)
        self.assertIn('row?.status === "nearby"', html)
        self.assertIn("인근 정비사업", html)
        self.assertIn("row?.eventLabel", html)
        self.assertIn("다른 후보보다 뚜렷한 강점은 아직 없음", summary_lines_body)
        self.assertIn('<span class="insight-kicker">핵심 요약</span>', html)
        self.assertIn('<div class="insight-summary">', html)
        self.assertIn(".insight-trend { margin:14px 0 0; border:0; border-radius:0; padding:0; background:transparent }", html)
        self.assertIn("font-size:11px", html)
        self.assertIn(".budget-sparkline-legend { position:relative; display:flex; align-items:center; flex-wrap:wrap; gap:6px 12px; color:#8b95a1; font-size:13px", html)
        self.assertIn(".spark-basis { flex-basis:100%; color:#8b95a1; font-size:13px", html)
        self.assertNotIn("이 단지는 이런 선택이에요", html)
        self.assertIn('<ul class="insight-title">${lines.map(line => `<li>${esc(line)}</li>`).join("")}</ul>', html)
        self.assertIn("font-size:15px; font-weight:700", html)
        self.assertIn("${candidateTrendInsightHtml(item, options)}", verdict_body)
        self.assertIn("${candidateRelatedNewsHtml(item)}", verdict_body)
        self.assertLess(
            verdict_body.index("${candidateRelatedNewsHtml(item)}"),
            verdict_body.index("${candidateTrendInsightHtml(item, options)}"),
        )
        self.assertIn('data-trend-toggle data-trend-action="toggle"', html)
        self.assertIn("차트보기", html)
        self.assertIn('border:1px solid #dfe3e8; border-radius:10px', html)
        self.assertIn('color:#3182f6; font-size:15px; font-weight:800', html)
        self.assertIn('.trend-toggle[data-trend-toggle]::after', html)
        self.assertIn('border-right:1.5px solid currentColor; border-bottom:1.5px solid currentColor', html)
        self.assertIn('max-width:100%; min-height:46px !important', html)
        self.assertIn('width:auto; min-height:48px !important', html)
        self.assertNotIn("차트로 확인", html)
        self.assertIn("candidateTrendPanelHtml(item, series)", trend_insight_body)
        self.assertNotIn("insight-section-label", trend_insight_body)
        self.assertIn('<div class="trend-status" data-trend-control>${controlHtml}</div>', trend_insight_body)
        self.assertIn('class="insight-news"', html)
        self.assertIn('class="insight-news-item"', html)
        self.assertNotIn("관련 변수", html)
        self.assertNotIn("insight-news-head", html)
        self.assertNotIn("현재 가격 흐름과 별도로 앞으로 확인할 뉴스예요.", html)
        self.assertNotIn("insight-news-context", html)
        self.assertIn("item.relatedNews", html)
        self.assertIn('"인근 교통·개발"', html)
        self.assertIn('status === "confirmed" && eventLabel', html)
        self.assertIn("news:Array.isArray(row.news) ? row.news : []", html)
        self.assertIn('getJson("/api/apartment-catalysts"', html)
        self.assertIn("enrichNewsCatalysts(rows);", html)
        self.assertIn("const CANDIDATE_PAGE_SIZE = 10;", html)
        self.assertIn("allSortedRows.slice(0, candidateVisibleCount)", html)
        self.assertIn("candidateLoadMoreHtml(rows.length, allSortedRows.length)", html)
        self.assertIn("data-candidate-load-more", html)
        self.assertIn("pending.slice(index, index + CANDIDATE_PAGE_SIZE)", html)
        self.assertIn("visibleCandidates: rows", html)
        self.assertNotIn('class="insight-tradeoff-label"', html)
        self.assertNotIn('class="insight-next-action"', html)
        self.assertNotIn('class="insight-action-label"', html)
        self.assertNotIn('class="insight-action"', html)
        self.assertNotIn(".insight-next-action {", html)
        self.assertNotIn(".insight-tradeoffs {", html)
        self.assertNotIn('class="insight-evidence-item"', html)
        self.assertIn("font-size:12px; font-weight:700", html)
        self.assertIn(".insight-trend .spark-summary-values em { font-size:inherit; font-weight:850 }", html)
        self.assertIn(".insight-trend .budget-sparkline {\n      margin:12px 0 2px; padding-top:12px;", html)
        self.assertNotIn("margin:12px 0 2px; border-top:1px solid #e5e5e7; padding-top:12px;", html)
        self.assertNotIn(".insight-kicker::before", html)
        self.assertIn("background:#f5f5f7", html)
        self.assertNotIn(".candidate-verdict:has(.insight-good)", html)

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
        self.assertIn("body.condition-stage-results .power-persistent { margin-top:8px }", html)
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
        self.assertIn('data-condition-summary-open="power"] { flex:0 0 auto }', html)
        self.assertIn("flex:1 1 0; min-width:0; overflow:hidden", html)
        self.assertIn('<span class="power-persistent-label">금액</span>', html)
        self.assertIn('<span class="power-persistent-label">지역</span>', html)
        self.assertIn('>변경</button>', html)
        self.assertIn('{ label:"금액", value:budgetLabel', html)
        self.assertIn('{ label:"지역", value:regionLabel', html)

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
        self.assertIn("selectedItem.legalDong", result_match.group("body"))
        self.assertIn("selectedItem.jibun", result_match.group("body"))
        self.assertIn("item.legalDong", result_match.group("body"))
        self.assertIn("item.jibun", result_match.group("body"))
        self.assertIn("...exactSelectedItems[0]", result_match.group("body"))
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
        self.assertIn('<span data-candidate-signal-label>리포트 보기</span>', html)
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
        self.assertIn("최근 가격·거래 흐름 ${esc(score)}점", html)
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
        self.assertIn("마지막 거래 기준 가격·거래 흐름", html)
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
        self.assertIn("geocodeCandidate(geocoder, kakao, mapItem)", focus_body)
        self.assertIn("appendCandidateMapEntry(mapItem, position)", focus_body)
        self.assertIn("selectCandidateMapItem(entry.item)", focus_body)
        self.assertIn("aptSearchInput.value = name;", navigation_body)
        self.assertIn('candidateViewMode === "map" && candidateMap', navigation_body)
        self.assertIn("await focusCandidateMapLeader(name, region);", navigation_body)
        self.assertIn("await runApartmentResultSearch({ name, region });", navigation_body)

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

    def test_policy_impact_appends_manual_naver_asking_price_check(self):
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
        self.assertIn("askingPriceCheckHtml(item)", body)
        self.assertIn("확인한 매물가", html)
        self.assertIn('data-asking-price-form', html)
        self.assertIn('name="asking_price_eok"', html)
        self.assertIn('.asking-price-input-shell input[type="number"]::-webkit-inner-spin-button', html)
        self.assertIn('-moz-appearance:textfield', html)
        self.assertIn('getJson("/api/asking-price-financing"', html)
        self.assertIn('budgetResultEl.addEventListener("submit"', html)
        self.assertIn('check.classList.add("is-ready")', html)
        self.assertIn('class="policy-metric policy-cash-scenario-result"', html)
        self.assertNotIn('policy-cash-scenario-copy">입력 매물가', html)
        self.assertIn('<small class="policy-required-label">자기자금</small>', body)
        self.assertIn("${policyMoney(scenario.requiredCashEok)} 필요", body)
        self.assertIn(".policy-required-line .policy-required-label", html)

    def test_direct_apartment_search_appends_manual_asking_price_check(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r"async function runAptSearch\b(?P<body>.*?)"
            r"\n    async function runApartmentResultSearch",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("${askingPriceCheckHtml(item)}", body)
        self.assertIn('aptSearchResults.addEventListener("submit"', html)
        self.assertIn('aptSearchResults.addEventListener("input"', html)
        self.assertIn("void calculateAskingPrice(form);", html)

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
        self.assertIn("realEstateSearch.budgetCandidates.v21", html)

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
        self.assertIn('const count = completed ? "3/3 완료"', progress_body)
        self.assertIn('const state = completed || index < safeStage ? "done"', progress_body)
        self.assertIn("모든 후보 카드가 준비되면 한 번에 보여드릴게요.", progress_body)

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
        self.assertIn("enrichMarketInsights(rows);", body)
        self.assertLess(
            body.index("mountCandidateMapPortal();"),
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
        self.assertIn('class="compare-toggle"', body)
        self.assertIn('class="candidate-secondary-actions"', body)
        self.assertIn('data-compare-name="${esc(item.name)}"', body)
        self.assertIn('aria-pressed="${selectedCandidateNames.has(item.name)}"', body)
        self.assertIn('"비교에서 빼기" : "비교 담기"', body)
        self.assertIn('grid-template-columns:minmax(0,1.65fr) minmax(0,1fr)', html)
        self.assertIn('border:1px solid #e1e5ea !important; border-radius:14px !important;', html)
        self.assertIn('background:#fff !important; color:#4e5968 !important; font-size:14px; font-weight:800', html)
        self.assertIn(
            ".candidate-primary-actions > .compare-toggle {\n"
            "      flex:0 0 auto; width:fit-content; min-width:max-content; max-width:100%; justify-self:start;",
            html,
        )
        self.assertNotIn("이 매물 계약 전 분석", body)
        self.assertIn('id="compareCart"', html)
        self.assertIn('id="compareCartBadge"', html)
        self.assertIn("compareCart.hidden = selected.length === 0", html)
        self.assertIn("compareCartBadge.textContent = String(selected.length)", html)
        self.assertIn('compareCart.addEventListener("click", openComparison);', html)
        self.assertIn('id="comparisonLimitToast"', html)
        self.assertIn("else showComparisonLimitToast();", html)
        self.assertIn('comparisonLimitToast.textContent = "비교는 최대 3건까지 담을 수 있어요."', html)
        self.assertNotIn('id="compareDock"', html)
        self.assertNotIn("compare-dock", html)

    def test_candidate_comparison_uses_report_highlights_without_auto_summary(self):
        html = APP_HTML.read_text(encoding="utf-8")

        self.assertIn('<h2 id="comparisonTitle">내 후보 비교</h2>', html)
        self.assertIn('<p class="comparison-mobile-subtitle">웹으로 보는 게 좋아요</p>', html)
        self.assertIn('.comparison-mobile-subtitle { display:none;', html)
        self.assertIn('.comparison-mobile-subtitle { display:block }', html)
        self.assertNotIn("어떤 차이가 있는지 볼게요", html)
        self.assertNotIn('class="comparison-summary"', html)
        self.assertIn('["핵심 요약", "summary"]', html)
        self.assertIn('["최근 가격·거래 흐름", "signal"]', html)
        self.assertIn("candidateChoiceSummaryLines(row)", html)
        self.assertIn("function comparisonSignalHtml(row)", html)

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
        self.assertNotIn('data-apt-area=""', render_match.group("body"))
        self.assertIn('event.target.closest("[data-apt-area]")', click_match.group("body"))
        self.assertIn("selectAptArea(card, area, `전용 ${label}`, area);", click_match.group("body"))
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
        self.assertIn("candidateVerdictHtml(candidate, { trendExpanded:loaded })", html)
        self.assertIn("await enrichAptLeaderEstimate(candidate);", html)
        self.assertLess(
            html.index("await enrichAptLeaderEstimate(candidate);"),
            html.index("renderAptCandidateResult(card, item, data, candidate, requestToken);"),
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
        self.assertIn("comparisonNotices", series_match.group("body"))
        self.assertIn("겹치는 기준월 없음", series_match.group("body"))
        self.assertIn('class="spark-compare-error"', html)
        self.assertIn("다시 검색하면 자동으로 재시도해요", html)

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
            r"\n    async function selectAptArea",
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
        self.assertIn("changeButton.textContent = buttonLabel;", render_body)
        self.assertIn("data.areaFallback && Number(data.requestedMinArea || 0)", affordability_body)
        self.assertIn("가장 가까운 실제 거래 평형 자동 선택", affordability_body)

    def test_apartment_search_chart_is_open_by_default_and_keeps_user_choice(self):
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
            "candidateVerdictHtml(candidate, { trendExpanded:candidate.aptSearchTrendExpanded !== false })",
            affordability_match.group("body"),
        )
        self.assertIn(
            'const trendExpanded = card.dataset.aptTrendExpanded !== "false";',
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
            '".candidate-detail-sheet:not([hidden]), .apt-report-sheet:not([hidden]), .listing-review-sheet:not([hidden])"',
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
        self.assertNotIn("candidateViewSwitchHtml()", render_match.group("body"))
        self.assertNotIn("candidate-map-view-switch-row", map_match.group("body"))
        self.assertIn('data-candidate-view="map"', html)
        self.assertIn('aria-label="지도에서 후보 보기"', html)
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
        self.assertIn('preview?.dataset.mobileState === "collapsed" ? preview : null', pointer_match.group("body"))
        self.assertIn(
            '.candidate-map-preview[data-mobile-state="collapsed"] .candidate-price-comparison',
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

    def test_naver_property_actions_open_in_a_safe_new_tab(self):
        html = APP_HTML.read_text(encoding="utf-8")
        match = re.search(
            r"function candidateNaverPropertyActionHtml\b(?P<body>.*?)"
            r"\n    function candidateListMetaHtml",
            html,
            re.DOTALL,
        )

        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn('target="_blank"', body)
        self.assertIn('rel="noopener noreferrer"', body)
        self.assertNotIn("뒤로가기로 결과에 복귀", html)
        self.assertNotIn("뒤로가기로 지도에 복귀", html)

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
            "구매력 상한 근접순",
            "최근 실거래가 낮은순",
            "신축순",
            "세대수 많은순",
            "동일 면적 거래 많은순",
        ):
            self.assertIn(label, sort_body)
        for removed in (
            "최근 가격·거래 흐름 점수 높은순",
            "최근 가격·거래 흐름 점수 낮은순",
            "마지막 동일 면적 거래가 3개월 이내",
            "데이터 신뢰도가 보통 이상",
            "최근 거래순",
            "추가 자금 적은순",
        ):
            self.assertNotIn(removed, sort_body)
        for label in (
            "1개월 이내 거래",
            "3개월 이내 거래",
            "신뢰도 보통 이상",
            "추가 자금 +5%까지",
        ):
            self.assertIn(label, html)
        self.assertIn('let includeAdditionalFundingCandidates = true;', html)
        self.assertIn('candidateTradeAgeFilter === "1m" ? "" : "1m"', html)
        self.assertIn('candidateTradeAgeFilter === "3m" ? "" : "3m"', html)
        self.assertIn("filterSourceRows.filter(candidateMatchesActiveFilters)", html)
        self.assertIn("function candidateSameAreaTradeAgeDays", html)
        self.assertIn('data-candidate-filter="${value}"', html)
        self.assertIn('`매수 후보 <span class="title-count">${esc(resultCount)}단지</span>`', html)
        self.assertNotIn('조건에 맞는 주요 단지 <span class="title-count">', html)
        self.assertIn(
            "min-height:38px; border:1px solid #e5e8eb; border-radius:11px; padding:0 14px;",
            html,
        )
        self.assertIn(
            '.candidate-filter-chip[aria-pressed="true"] { border:2px solid #3182f6; '
            "background:#fff; color:#3182f6; font-weight:850 }",
            html,
        )
        self.assertNotIn(".condition-stage-results .candidate-filter-chip {", html)
        self.assertIn('.condition-stage-results .budget-title { font-size:21px; line-height:1.38 }', html)
        self.assertIn('grid-template-columns:minmax(0,1fr); align-items:stretch; gap:10px;', html)
        self.assertIn('width:100%; align-self:stretch; justify-content:flex-end; margin-left:0', html)

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
