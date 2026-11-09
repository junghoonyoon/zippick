import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_HTML = ROOT / "앱화면" / "real-estate-search.html"


class ReportPriceCheckTest(unittest.TestCase):
    def test_missing_location_data_is_not_replaced_with_price_rank_copy(self):
        html = APP_HTML.read_text(encoding="utf-8")
        start = html.index("    function zippickDemandScoreReason(part) {")
        end = html.index("    function zippickMarketScoreReason(item) {", start)
        demand = html[start:end]
        self.assertIn("역·학교 자료를 불러오지 못해 판단할 수 없어요.", demand)
        self.assertNotIn("zippickDetailReasons(part", demand)
        self.assertNotIn("지역 후보", demand)
        self.assertNotIn("도보", demand)

    def test_report_summary_appears_before_buy_band(self):
        html = APP_HTML.read_text(encoding="utf-8")
        start = html.index("    function zippickDecisionHtml(item, verdict) {")
        end = html.index("    function zippickLocationEvidenceText", start)
        decision = html[start:end]

        self.assertLess(
            decision.index('<div class="zpr-summary is-verdict">'),
            decision.index("${zippickBuyBandHtml(item, verdict)}"),
        )
        self.assertNotIn("다음에 볼 것", decision)
        self.assertNotIn("같은 면적·비슷한 층의 매물이 위 가격 기준에 맞는지 확인하세요", decision)
        report_start = html.index("    function candidateZippickReportHtml(item) {")
        report_end = html.index("    function candidateDisplayName(item) {", report_start)
        report = html[report_start:report_end]
        self.assertNotIn('data-zpr-step="매물 가격 비교"', report)
        self.assertNotIn("zippickPriceCheckHtml(item)", report)
        self.assertNotIn('data-zpr-asking-price', html)


    def test_all_report_shapes_keep_latest_trade_marker_for_matching_area(self):
        html = APP_HTML.read_text(encoding="utf-8")
        functions = html[html.index("    function zippickPriceCheckBasis(item) {"):
                         html.index("    function zippickReportFinance(item) {")]
        report_renderer = html[html.index("    function candidateZippickReportHtml(item) {"):
                               html.index("    function candidateDisplayName(item) {")]
        decision_renderer = html[html.index("    function zippickDecisionHtml(item, verdict) {"):
                                 html.index("    function zippickLocationEvidenceText(item, verdict) {")]
        self.assertIn("${zippickDecisionHtml(item, verdict)}", report_renderer)
        self.assertIn("${zippickBuyBandHtml(item, verdict)}", decision_renderer)
        script = """
          function zpNum(value) { return value == null || value === '' ? NaN : Number(value); }
          function transactionMoney(value) { return `${value}억`; }
          function esc(value) { return String(value); }
          function candidateTrendPanelHtml() { return ''; }
          const base = {valuation:{status:'ready',fairPrice:{lowEok:8.35,centerEok:9.52,highEok:10},
            floorComparison:{status:'matched'},dataQuality:{sampleCount:6,level:'medium'}}};
        """ + functions + """
          const samho = {...base, name:'삼호4', areaLabel:'전용 50~59㎡', displayAreaLabel:'전용 50㎡',
            areaMin:50, areaMax:59, latestDealPriceEok:9.8, latestDealDate:'2026-08-31',
            latestDealExclusiveArea:59.49, latestDealFloor:'14',
            valuation:{...base.valuation, areaLabel:'전용 50㎡',
              fairPrice:{lowEok:8.35,centerEok:9.52,highEok:10}}};
          const samhoBand = zippickBuyBandHtml(samho, {});
          if (!samhoBand.includes('zpr-buy-band-marker') || !samhoBand.includes('최근 실거래 9.8억')) process.exit(100);
          if (!samhoBand.includes('2026-08-31 · 14층') || !samhoBand.includes('최근 실거래는 적정가격 안에 있어요')) process.exit(101);
          if (samhoBand.includes('위치를 확인할 수 없어요') || samhoBand.includes('zpr-buy-band-limit')) process.exit(102);
          for (const area of [50,59,59.49,59.99]) {
            if (!zippickBuyBandTradeMatchesArea({...samho,latestDealExclusiveArea:area})) process.exit(103);
          }
          for (const area of [49.99,60,84]) {
            const different = zippickBuyBandHtml({...samho,latestDealExclusiveArea:area}, {});
            if (different.includes('zpr-buy-band-marker') || !different.includes('선택한 면적 범위와 달라')) process.exit(104);
          }
          const numericRange={...samho,areaLabel:'',displayAreaLabel:'50㎡',latestDealPriceEok:null,
            latestDealDate:'',latestDealExclusiveArea:null,latestDealFloor:'',
            latestTrade:{dealAmountEok:9.8,dealDate:'2026-08-31',exclusiveArea:59.49,floor:'14'},
            valuation:{...samho.valuation,areaLabel:''}};
          const numericRangeBand=zippickBuyBandHtml(numericRange,{});
          if (!numericRangeBand.includes('최근 실거래 9.8억') || !numericRangeBand.includes('2026-08-31 · 14층')) process.exit(105);
          const exactArea={...samho,areaLabel:'전용 84㎡',displayAreaLabel:'84㎡',areaMin:84,areaMax:84,
            valuation:{...samho.valuation,areaLabel:'84㎡'}};
          if (zippickBuyBandHtml(exactArea,{}).includes('zpr-buy-band-marker')) process.exit(106);

          const noPrice = zippickBuyBandHtml({...samho, latestDealPriceEok:null}, {});
          if (noPrice.includes('zpr-buy-band-marker') || noPrice.includes('NaN%')) process.exit(107);

          // 직접 단지 리포트와 R-ONE 보강 리포트는 최신 거래가 중첩 객체로 올 수 있다.
          const directReport={...base,areaLabel:'전용 59㎡',displayAreaLabel:'전용 59㎡',
            latestTrade:{dealAmountEok:9.8,dealDate:'2026-08-31',exclusiveArea:59.49,floor:'14'},
            valuation:{...base.valuation,areaLabel:'전용 59㎡'}};
          const directBand=zippickBuyBandHtml(directReport,{});
          if (!directBand.includes('최근 실거래 9.8억') || !directBand.includes('2026-08-31 · 14층')) process.exit(108);
          const roneReport={...base,areaLabel:'전용 84㎡',displayAreaLabel:'전용 84㎡',
            roneEstimate:{latestTrade:{dealAmountEok:11.2,dealDate:'2026-09-12',exclusiveArea:84.89,floor:'8'}},
            valuation:{...base.valuation,areaLabel:'전용 84㎡'}};
          const roneBand=zippickBuyBandHtml(roneReport,{});
          if (!roneBand.includes('최근 실거래 11.2억') || !roneBand.includes('2026-09-12 · 8층')) process.exit(109);

        """
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_read_only_band_uses_fresh_same_area_trade_basis(self):
        html = APP_HTML.read_text(encoding="utf-8")
        start = html.index("    function zippickPriceCheckBasis(item) {")
        end = html.index("    function zippickReportFinance(item) {", start)
        functions = html[start:end]
        rating_start = html.index("    function zippickSectionRatingData(item, label) {")
        rating_end = html.index("    function zippickOverallRatingHtml", rating_start)
        rating_functions = html[rating_start:rating_end]
        average_start = html.index("    function candidateHeadlinePrice(item) {")
        average_end = html.index("    function candidateHeadlinePriceHtml(item) {", average_start)
        average_functions = html[average_start:average_end]
        section_start = html.index("    function zippickPriceComparisonHtml(item, assessment) {")
        section_end = html.index("    function zippickPersonalFundingHtml(item) {", section_start)
        section_functions = html[section_start:section_end]
        script = """
          function zpNum(value) { return value == null || value === '' ? NaN : Number(value); }
          function candidateDisplayName(item) { return item.name || '테스트단지'; }
          function zippickReportTable(headers, rows) { return headers.join('|') + rows.map(row => row.join('|')).join('\\n'); }
          function zpScoredParts(item) { return [item.testPricePart || {key:'price', points:24.6, maxPoints:30}]; }
          function zpPartRatio(part) { return part ? part.points / part.maxPoints : NaN; }
          const ZP_PEAK_RECOVERY_PCT = 98;
          const HEADLINE_MIN_QUARTER_TRADES = 5;
          function transactionMoney(value) { return `${value}억`; }
          function policyMoney(value) { return `${value}억`; }
          function recentQuarterStats(item) { return item.testQuarterStats || null; }
          function esc(value) { return String(value); }
          function candidateTrendPanelHtml(_item, _series, options = {}) {
            return options.compact === true ? '<div data-reused-price-chart>chart</div>' : '';
          }
        """ + average_functions + rating_functions + functions + section_functions + """
          const fresh = new Date().toISOString().slice(0, 10);
          const item = {
            region: '성남수정구',
            statsThrough: fresh,
            recent3AdjustedTradeCount: 5,
            recent3AdjustedAveragePriceEok: 10,
            recent3TradeCount: 6,
            recent3AveragePriceEok: 11,
            latestDealPriceEok: 12,
            latestDealDate: fresh,
          };
          const basis = zippickPriceCheckBasis(item);
          if (basis.price !== 10) process.exit(1);
          item.valuation = {
            status: 'ready', modelVersion: 'zippick-current-value-v1', asOf: fresh,
            fairPrice: {lowEok: 9.4, centerEok: 10.1, highEok: 10.8, method: 'test'},
            dataQuality: {sampleCount: 8, level: 'medium', latestTradeAgeDays: 19},
            floorComparison: {status: 'matched', targetFloor: 10, sampleCount: 8},
            market: {status: 'available'},
          };
          const modelBasis = zippickPriceCheckBasis(item);
          if (modelBasis.low !== 9.4 || modelBasis.price !== 10.1 || modelBasis.high !== 10.8) process.exit(4);
          if (zippickBuyBandTier(9, 9.4, 10.8) !== 0) process.exit(5);
          if (zippickBuyBandTier(10, 9.4, 10.8) !== 1) process.exit(6);
          if (zippickBuyBandTier(11, 9.4, 10.8) !== 2) process.exit(7);
          const band = zippickBuyBandResultHtml(9.4, 10.8, 10, true);
          if (!band.includes('<strong>쌈</strong>') || !band.includes('<strong>적정</strong>') || !band.includes('<strong>비쌈</strong>')) process.exit(8);
          if (band.includes('가격 좋음') || band.includes('협상 필요')) process.exit(9);
          if (!band.includes('zpr-buy-band-chart') || !band.includes('--zpr-band-position:')) process.exit(13);
          if (!band.includes('최근 실거래 10억') || band.includes('입력한 매물')) process.exit(14);
          item.latestDealExclusiveArea = 84;
          item.displayAreaLabel = '전용 84㎡';
          item.valuation.reasons = ['이전 실거래 8건을 사용했어요.', '평가할 최근 거래는 기준가격에서 뺐어요.'];
          item.valuation.limitations = ['층·향·수리 상태는 반영하지 못했어요.'];
          item.valuation.marketAdjustmentPct = 1.2;
          item.valuation.macro = {message:'기준금리는 향후 시장 위험으로 확인해요.'};
          const modelBand = zippickBuyBandHtml(item, {});
          if (!modelBand.includes('집픽 밴드') || modelBand.includes('집픽 현재 적정가격')) process.exit(10);
          if (modelBand.includes('<input') || modelBand.includes('입력한 매물')) process.exit(16);
          if (modelBand.includes('집픽이 지키는') || !modelBand.includes('부르는 값(호가)은 쓰지 않아요') || !modelBand.includes('<b>평가할 최근 거래는 빼고</b>')) process.exit(18);
          // 판정 근거는 비교 대상·범위·최근 거래 위치를 한 문단으로 말한다.
          if (!modelBand.includes('같은 단지·비슷한 면적·비슷한 층의 다른 실거래 <b>8건</b>') || !modelBand.includes('<b>9.4억~10.8억</b>') || !modelBand.includes('<mark>약 11% 높아요</mark>')) process.exit(48);
          // 마커와 근거 목록에 있는 거래 정보·한계 문구를 별도 줄로 되풀이하지 않는다.
          if (modelBand.includes('zpr-buy-band-meta') || modelBand.includes('국토교통부 신고 거래') || (modelBand.match(/반영하지 못했어요/g) || []).length !== 1) process.exit(49);
          if (!modelBand.includes('최근 2년 가격 흐름') || !modelBand.includes('data-reused-price-chart')) process.exit(39);
          const holdBand = zippickBuyBandHtml({...item, valuation:{status:'unavailable', reason:'비슷한 면적의 거래가 3건 미만이라 가격 판단을 보류했어요.'}}, {});
          if (!holdBand.includes('억지로 답을 만들지 않아요') || holdBand.includes('<input')) process.exit(19);
          if (!modelBand.includes('적정가격보다 비싸요') || modelBand.includes('<em>비쌈</em>')) process.exit(11);
          if (!modelBand.includes('왜 이렇게 판단했나요?') || !modelBand.includes('주변 시장 흐름을 +1.2% 반영했어요.')) process.exit(12);
          item.valuation.marketAdjustmentPct = 0;
          const recentTradeBand = zippickBuyBandHtml(item, {});
          if (!recentTradeBand.includes('최근 거래가 30일 이내라 지역 시세 변화는 따로 더하지 않았어요.')) process.exit(15);
          item.valuation.marketAdjustmentPct = 1.8;
          item.valuation.indexAdjustment = {status:'applied', region:'서울 종로구', asOf:'2026-09-28', centerChangePct:1.8};
          const indexBand = zippickBuyBandHtml(item, {});
          if (!indexBand.includes('한국부동산원 서울 종로구 주간 시세로 오늘 기준에 맞춰 보니') || !indexBand.includes('<b>한국부동산원 서울 종로구 주간 시세</b>로 9월 28일 기준에 맞췄어요. 그 결과 적정가격을 1.8% 올렸어요.')) process.exit(20);
          if (indexBand.includes('주변 시장 흐름을')) process.exit(21);
          // 계산 근거는 기본 접힘 상태의 '더보기' 안에 둔다.
          if (!indexBand.includes('<details class="zpr-buy-band-basis"><summary>') || !indexBand.includes('왜 이렇게 판단했나요?')) process.exit(28);
          if (indexBand.includes('<details class="zpr-buy-band-basis" open')) process.exit(34);
          if (indexBand.includes('부르는 값이 아니라')) process.exit(22);
          // 같은 내용을 알림 줄이나 근거 목록에서 되풀이하지 않는다.
          if (indexBand.includes('zpr-buy-band-index') || (indexBand.match(/올렸어요/g) || []).length !== 1) process.exit(23);
          if (indexBand.indexOf('<mark>') > indexBand.indexOf('zpr-buy-band-result')) process.exit(24);
          item.valuation.marketAdjustmentPct = -2.04;
          if (!zippickBuyBandHtml(item, {}).includes('적정가격을 2.0% 내렸어요.')) process.exit(25);
          item.valuation.marketAdjustmentPct = 0;
          if (!zippickBuyBandHtml(item, {}).includes('9월 28일 기준에 맞췄어요. 시세 변화가 거의 없어 그대로예요.')) process.exit(29);
          if (indexBand.includes('집픽이 지키는') || (indexBand.match(/주간 시세로/g) || []).length !== 1) process.exit(26);
          if (!modelBand.includes('최근 시장 흐름을 반영해 보니') || modelBand.includes('zpr-buy-band-index')) process.exit(27);
          // 타이틀이 '가격 주의'인 단지는 밴드도 같은 방향으로 말한다.
          item.latestDealPriceEok = 10;
          const calmBand = zippickBuyBandHtml(item, {});
          if (!calmBand.includes('최근 실거래는 적정가격 안에 있어요') || calmBand.includes('<em>적정</em>')) process.exit(30);
          const peakBand = zippickBuyBandHtml(item, {peakGuard:{atPeak:true}});
          if (!peakBand.includes('요즘 시세와 비슷하게 거래됐어요. 다만 요즘 시세가 2년 중 가장 높은 구간이에요.')) process.exit(31);
          if (peakBand.includes('<em>') || peakBand.includes('적정가격 안에 있어요')) process.exit(32);
          if (!peakBand.includes('요즘 시세대로 사도 2년 중 가장 높은 구간의 값에 사는 거예요. 다음 거래를 지켜보세요.')) process.exit(33);
          const surgeBand = zippickBuyBandHtml(item, {peakGuard:{atPeak:false, surge:true}});
          if (!surgeBand.includes('다만 요즘 시세가 최근 석 달 새 빠르게 올랐어요.') || surgeBand.includes('<em>')) process.exit(35);
          item.latestDealPriceEok = 9;
          const cheapPeakBand = zippickBuyBandHtml(item, {peakGuard:{atPeak:true}});
          if (!cheapPeakBand.includes('요즘 시세보다 싸게 거래됐어요. 다만 요즘 시세가 2년 중 가장 높은 구간이에요.') || cheapPeakBand.includes('<em>')) process.exit(36);
          item.valuation.floorComparison = {status:'insufficient', targetFloor:1, sampleCount:0};
          item.valuation.marketAdjustmentPct = -2.04;
          item.latestDealFloor = '1';
          const unmatchedFloorBand = zippickBuyBandHtml(item, {peakGuard:{atPeak:false, surge:true}});
          if (!unmatchedFloorBand.includes('요즘 시세보다 싸게 거래됐어요. 다만 요즘 시세가 최근 석 달 새 빠르게 올랐어요.')) process.exit(40);
          if (!unmatchedFloorBand.includes('최근 실거래 9억') || !unmatchedFloorBand.includes('같은 단지·비슷한 면적(여러 층)') || unmatchedFloorBand.includes('<em>') || unmatchedFloorBand.includes('층 비교 부족')) process.exit(41);
          if (!unmatchedFloorBand.includes('zpr-buy-band-chart is-reference') || !unmatchedFloorBand.includes('zpr-buy-band-marker')) process.exit(42);
          if (!unmatchedFloorBand.includes('<strong>쌈</strong>') || !unmatchedFloorBand.includes('<strong>적정</strong>') || !unmatchedFloorBand.includes('<strong>비쌈</strong>')) process.exit(45);
          if (!unmatchedFloorBand.includes('is-cheap is-current') || unmatchedFloorBand.includes('<small>싼지·비싼지 판단 보류</small>') || !unmatchedFloorBand.includes('여러 층 거래 기준이에요. 싸게 거래된 이유가 있는지')) process.exit(46);
          if (!unmatchedFloorBand.includes('참고 가격대를 2.0% 내렸어요') || unmatchedFloorBand.includes('적정가격을')) process.exit(43);
          if (zippickPriceCheckBasis(item).label !== '여러 층 거래 참고 가격') process.exit(44);
          // 비교 단지와 비교하지 못하면 임시 별점을 붙이지 않는다.
          if (zippickSectionRatingData(item, '가격 비교') !== null) process.exit(47);
          item.testQuarterStats = {currentCount:5, currentAverage:10.2, stale:false};
          const rankDetail = {key:'price_rank', status:'ok', reason:'지역 후보 3/4위 · 가격 부담 낮은 편',
            comparisonPeerCount:3, comparisonPeers:[
              {name:'산성역 포레스티아', legalDong:'신흥동', areaLabel:'전용 59.8㎡'},
              {name:'산성역자이푸르지오 1단지', legalDong:'신흥동', areaLabel:'전용 60㎡'},
              {name:'삼부', legalDong:'수진동', areaLabel:'전용 59.8㎡'},
            ]};
          item.testPricePart = {key:'price', points:24.6, maxPoints:30, details:[rankDetail]};
          item.priceComparison = {status:'loading'};
          if (zippickPriceAssessment(item).heading !== '비교 단지 거래를 확인하고 있어요') process.exit(60);
          if (zippickSectionRatingData(item, '가격 비교') !== null) process.exit(65);
          item.priceComparison = {status:'unavailable', reason:'비교할 거래가 부족해요.'};
          if (zippickPriceAssessment(item).heading !== '비교할 단지 자료가 부족해 판단할 수 없어요') process.exit(66);
          if (zippickPriceAssessment(item).subheading !== '비교할 거래가 부족해요.') process.exit(63);
          // 원래 10% 싼 단지가 지금 11% 싸면 평소 수준(적정)이다. 단순 가격 차이로 싸다고 하지 않는다.
          item.priceComparison = {status:'ready', region:'송파구', areaLabel:'전용 84㎡', scope:'district',
            averagePriceEok:28.5, transactionCount:31, peerAveragePriceEok:32.28, differencePct:-11.7,
            usualGapPct:-12.2, currentGapPct:-11.2, shiftPp:1, position:'similar', lowData:false,
            yearlyGaps:[{year:2022, gapPct:-12.8, lowData:false}, {year:2023, gapPct:-11.5, lowData:false}, {year:2024, gapPct:-11, lowData:false}, {year:2025, gapPct:-14.1, lowData:true}],
            selectionCriteria:{householdsMin:2853, approvalYearGap:10},
            peers:[
              {name:'파크리오', legalDong:'신천동', averagePriceEok:29, transactionCount:36, diffPct:1.8, usualRatio:98.3, currentRatio:98.3, shiftPp:0},
              {name:'잠실엘스', legalDong:'잠실동', averagePriceEok:33.5, transactionCount:40, diffPct:17.5, usualRatio:86.1, currentRatio:85.1, shiftPp:-1},
            ]};
          const fair = zippickPriceAssessment(item);
          if (fair.heading !== '송파구 비슷한 단지 2곳과 비교하면 평소 수준이에요') process.exit(57);
          if (fair.subheading !== '해마다 비교 단지보다 11~14% 쌌고, 지금도 11% 싸요.') process.exit(58);
          if (!zippickSectionRatingHtml(item, '가격 비교').includes('가격 비교 점수 3.0/5')) process.exit(67);
          const fairHtml = zippickPriceEvidenceHtml(item);
          // 해마다 비교 단지보다 얼마나 쌌는지와 지금을 한 차트로 보여준다. %p 표현은 쓰지 않는다.
          if (!fairHtml.includes('zpr-price-years is-similar') || !fairHtml.includes('↓ 비교 단지보다 쌈') || !fairHtml.includes('실선 비교 단지 평균') || fairHtml.includes('주변 평균') || !fairHtml.includes('22년') || !fairHtml.includes('25년') || !fairHtml.includes('지금') || !fairHtml.includes('is-thin') || !fairHtml.includes('거래가 적은 해') || fairHtml.includes('%p') || !fairHtml.includes('가까운 곳에 비교할 단지가 부족해 송파구로 넓혔어요.')) process.exit(59);
          if (fairHtml.includes('zpr-buy-band-zone')) process.exit(75);
          if (!fairHtml.includes('14% → 15% 쌈') || !fairHtml.includes('이 단지가 평소 → 지금') || fairHtml.includes('자료 적음')) process.exit(68);
          // 비교 단지를 어떤 기준으로 골랐는지 실제 단계와 단지별 사실을 보여준다.
          if (!fairHtml.includes('비교 단지는 이렇게 골랐어요') || !fairHtml.includes('송파구에서 세대수 차이 50% 이내, 준공연도 차이 10년 이내') || !fairHtml.includes('가격은 보지 않았어요')) process.exit(82);
          const factsHtml = (() => { const saved = item.priceComparison; item.priceComparison = {...saved, peers:[{...saved.peers[0], households:6864, approvalYear:2008, distanceMeters:2561, tier:3}, saved.peers[1]]}; const html = zippickPriceEvidenceHtml(item); item.priceComparison = saved; return html; })();
          if (!factsHtml.includes('6,864세대 · 2008년 준공 · 2,561m') || !factsHtml.includes('송파구에서 100세대 이상')) process.exit(83);
          if (fairHtml.includes('zpr-comparison-facts') || fairHtml.includes('비교할 후보') || fairHtml.includes('확인하세요')) process.exit(69);
          item.priceComparison = {...item.priceComparison, shiftPp:4.1, currentGapPct:-6, position:'high', lowData:true,
            peers:item.priceComparison.peers.map(peer => ({...peer, transactionCount:4, lowData:true}))};
          const high = zippickPriceAssessment(item);
          if (high.heading !== '송파구 비슷한 단지 2곳과 비교하면 평소보다 7% 비싸졌어요' || high.subheading !== '해마다 비교 단지보다 11~14% 쌌는데, 지금은 6% 싸요. 평소 12%보다 차이가 줄었어요.') process.exit(74);
          if (zippickSectionRatingData(item, '가격 비교').stars !== '2.0') process.exit(72);
          const highHtml = zippickPriceEvidenceHtml(item);
          if (!highHtml.includes('자료 적음') || !highHtml.includes('최근 4건') || !highHtml.includes('zpr-price-years is-high') || !highHtml.includes('6%')) process.exit(70);
          // 평소 차이를 모르면 지금 가격만 비교했다고 밝히고 별점을 붙이지 않는다.
          const beforeSimple = item.priceComparison;
          item.priceComparison = {...beforeSimple, method:'simple', shiftPp:null, usualGapPct:null, currentGapPct:null,
            differencePct:-8, position:'low', lowData:true, scope:'district', conditionsRelaxed:true, areaAdjusted:true};
          const simple = zippickPriceAssessment(item);
          if (simple.heading !== '송파구 비슷한 단지 2곳보다 8% 싸요' || !simple.subheading.includes('동네 차이는 감안하지 못했어요')) process.exit(77);
          if (zippickSectionRatingData(item, '가격 비교') !== null) process.exit(78);
          const simpleHtml = zippickPriceEvidenceHtml(item);
          if (!simpleHtml.includes('8%') || simpleHtml.includes('zpr-price-years') || !simpleHtml.includes('이 단지가 지금') || !simpleHtml.includes('자료 적음')) process.exit(79);
          if (!simpleHtml.includes('송파구로 넓혔어요') || !simpleHtml.includes('세대수나 연식 차이가 큰 단지도 포함했어요') || !simpleHtml.includes('같은 면적 가격으로 환산했어요')) process.exit(80);
          if (simpleHtml.includes('평소 가격 차이로 감안했어요') || simpleHtml.includes('NaN')) process.exit(81);
          // 세대수·연식 조건까지 넓히면 '비슷한'이라고 하지 않고 구 이름과 단지 수를 쓴다.
          const widenedPeers = beforeSimple.peers.map(peer => ({...peer, tier:2}));
          item.priceComparison = {...beforeSimple, peers:widenedPeers};
          if (zippickPriceAssessment(item).heading !== '송파구 단지 2곳과 비교하면 평소보다 7% 비싸졌어요') process.exit(84);
          item.priceComparison = {...beforeSimple, peers:widenedPeers, position:'similar'};
          if (zippickPriceAssessment(item).heading !== '송파구 단지 2곳과 비교하면 평소 수준이에요') process.exit(85);
          item.priceComparison = {...beforeSimple, peers:widenedPeers, method:'simple', position:'similar', differencePct:1};
          if (zippickPriceAssessment(item).heading !== '송파구 단지 2곳과 가격이 비슷해요') process.exit(86);
          item.priceComparison = {...beforeSimple, peers:widenedPeers, method:'simple', position:'high', differencePct:8};
          if (zippickPriceAssessment(item).heading !== '송파구 단지 2곳보다 8% 비싸요') process.exit(87);
          item.priceComparison = {...beforeSimple, usualGapPct:-12, currentGapPct:-16, position:'low'};
          if (zippickPriceAssessment(item).heading !== '송파구 비슷한 단지 2곳과 비교하면 평소보다 5% 싸졌어요') process.exit(88);
          // 대표값과 판정의 방향이 다르면 틀린 숫자를 쓰지 않는다.
          item.priceComparison = {...beforeSimple, usualGapPct:-12, currentGapPct:-6, position:'low'};
          if (zippickPriceAssessment(item).heading !== '송파구 비슷한 단지 2곳과 비교하면 평소보다 싸졌어요') process.exit(89);
          item.priceComparison = beforeSimple;
          item.priceComparison = {...item.priceComparison, periodMonths:12, periodWidened:true};
          const widenedHtml = zippickPriceEvidenceHtml(item);
          if (!widenedHtml.includes('이 단지의 최근 6개월 거래가 적어 최근 12개월로 봤어요.') || !widenedHtml.includes('최근 12개월</th>')) process.exit(76);
          item.priceComparison = {...item.priceComparison, periodMonths:6, periodWidened:false, shiftPp:-6.5, position:'low', lowData:false};
          if (!zippickPriceAssessment(item).subheading.endsWith('평소 12%보다 차이가 커졌어요.')) process.exit(61);
          if (zippickSectionRatingData(item, '가격 비교').stars !== '5.0') process.exit(71);
          item.priceComparison = {...item.priceComparison, peers:item.priceComparison.peers.slice(0, 1)};
          // 비교 단지 1곳이어도 평소 차이를 계산했으면 판정을 보여준다.
          if (zippickSectionRatingData(item, '가격 비교') === null) process.exit(73);
          delete item.priceComparison;
          if (zippickPriceAssessment(item).heading !== '비교할 단지 자료가 부족해 판단할 수 없어요') process.exit(48);
          item.latestDealPriceEok = 12;
          item.valuation.floorComparison = {status:'matched', targetFloor:14, sampleCount:8};
          item.latestDealFloor = '14';
          const expensivePeakBand = zippickBuyBandHtml(item, {peakGuard:{atPeak:true}});
          if (!expensivePeakBand.includes('최근 실거래는 적정가격보다 비싸요') || expensivePeakBand.includes('<em>')) process.exit(37);
          const tradeAtPeak = zippickBuyBandResultHtml(9.4, 10.8, 10, true, 'peak');
          if (!tradeAtPeak.includes('요즘 시세대로 사도 2년 중 가장 높은 구간의 값에 사는 거예요.')) process.exit(38);
          delete item.valuation;
          item.statsThrough = '2020-01-01';
          if (zippickPriceCheckBasis(item).price !== 12) process.exit(2);
          item.latestDealPriceEok = 0;
          if (zippickPriceCheckBasis(item) !== null) process.exit(3);
        """
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
