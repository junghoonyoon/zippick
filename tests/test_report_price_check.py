import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_HTML = ROOT / "앱화면" / "real-estate-search.html"


class ReportPriceCheckTest(unittest.TestCase):
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
          if (!numericRangeBand.includes('최근 실거래 9.8억') || !numericRangeBand.includes('2026-08-31 · 전용 59.49㎡ · 14층')) process.exit(105);
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
          if (!directBand.includes('최근 실거래 9.8억') || !directBand.includes('2026-08-31 · 전용 59.49㎡ · 14층')) process.exit(108);
          const roneReport={...base,areaLabel:'전용 84㎡',displayAreaLabel:'전용 84㎡',
            roneEstimate:{latestTrade:{dealAmountEok:11.2,dealDate:'2026-09-12',exclusiveArea:84.89,floor:'8'}},
            valuation:{...base.valuation,areaLabel:'전용 84㎡'}};
          const roneBand=zippickBuyBandHtml(roneReport,{});
          if (!roneBand.includes('최근 실거래 11.2억') || !roneBand.includes('2026-09-12 · 전용 84.89㎡ · 8층')) process.exit(109);

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
        script = """
          function zpNum(value) { return value == null || value === '' ? NaN : Number(value); }
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
        """ + average_functions + rating_functions + functions + """
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
          if (!modelBand.includes('집픽이 지키는 3가지') || !modelBand.includes('부르는 값은 계산에 넣지 않아요')) process.exit(18);
          if (!modelBand.includes('최근 2년 가격 흐름') || !modelBand.includes('data-reused-price-chart')) process.exit(39);
          const holdBand = zippickBuyBandHtml({...item, valuation:{status:'unavailable', reason:'비슷한 면적의 거래가 3건 미만이라 가격 판단을 보류했어요.'}}, {});
          if (!holdBand.includes('억지로 답을 만들지 않아요') || holdBand.includes('<input')) process.exit(19);
          if (!modelBand.includes('적정가격보다 비싸요') || modelBand.includes('<em>비쌈</em>')) process.exit(11);
          if (!modelBand.includes('이 가격은 어떻게 계산했나요?') || !modelBand.includes('주변 시장 흐름을 +1.2% 반영했어요.')) process.exit(12);
          item.valuation.marketAdjustmentPct = 0;
          const recentTradeBand = zippickBuyBandHtml(item, {});
          if (!recentTradeBand.includes('최근 거래가 30일 이내라 지역 시세 변화는 따로 더하지 않았어요.')) process.exit(15);
          item.valuation.marketAdjustmentPct = 1.8;
          item.valuation.indexAdjustment = {status:'applied', region:'서울 종로구', asOf:'2026-09-28', centerChangePct:1.8};
          const indexBand = zippickBuyBandHtml(item, {});
          if (!indexBand.includes('지난 실거래에 <b>한국부동산원 서울 종로구 주간 시세</b>를 반영해 적정가격을 <mark>1.8% 올렸어요</mark>. (9월 28일 기준)')) process.exit(20);
          if (indexBand.includes('주변 시장 흐름을')) process.exit(21);
          // 계산 근거는 기본 접힘 상태의 '더보기' 안에 둔다.
          if (!indexBand.includes('<details class="zpr-buy-band-basis"><summary>') || !indexBand.includes('이 가격은 어떻게 계산했나요?')) process.exit(28);
          if (indexBand.includes('<details class="zpr-buy-band-basis" open')) process.exit(34);
          if (indexBand.includes('부르는 값이 아니라')) process.exit(22);
          // 같은 내용을 알림 줄이나 근거 목록에서 되풀이하지 않는다.
          if (indexBand.includes('zpr-buy-band-index') || (indexBand.match(/올렸어요/g) || []).length !== 1) process.exit(23);
          if (indexBand.indexOf('<mark>') > indexBand.indexOf('zpr-buy-band-result')) process.exit(24);
          item.valuation.marketAdjustmentPct = -2.04;
          if (!zippickBuyBandHtml(item, {}).includes('적정가격을 <mark>2.0% 내렸어요</mark>.')) process.exit(25);
          item.valuation.marketAdjustmentPct = 0;
          if (!zippickBuyBandHtml(item, {}).includes('<mark>적정가격도 그대로예요</mark>. (9월 28일 기준)')) process.exit(29);
          if (!indexBand.includes('집픽이 지키는 4가지') || !indexBand.includes('<b>한국부동산원 주간 시세</b>로 최근 기준에 맞춰요')) process.exit(26);
          if (!modelBand.includes('부르는 값이 아니라') || modelBand.includes('zpr-buy-band-index')) process.exit(27);
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
          if (!unmatchedFloorBand.includes('최근 실거래 · 9억') || unmatchedFloorBand.includes('<em>') || unmatchedFloorBand.includes('층 비교 부족')) process.exit(41);
          if (!unmatchedFloorBand.includes('zpr-buy-band-chart is-reference') || !unmatchedFloorBand.includes('zpr-buy-band-marker')) process.exit(42);
          if (!unmatchedFloorBand.includes('<strong>쌈</strong>') || !unmatchedFloorBand.includes('<strong>적정</strong>') || !unmatchedFloorBand.includes('<strong>비쌈</strong>')) process.exit(45);
          if (!unmatchedFloorBand.includes('is-cheap is-current') || unmatchedFloorBand.includes('<small>싼지·비싼지 판단 보류</small>') || !unmatchedFloorBand.includes('여러 층 거래 기준이에요. 싸게 거래된 이유가 있는지')) process.exit(46);
          if (!unmatchedFloorBand.includes('참고 가격대를 <mark>2.0% 내렸어요</mark>') || unmatchedFloorBand.includes('적정가격을 <mark>')) process.exit(43);
          if (zippickPriceCheckBasis(item).label !== '여러 층 거래 참고 가격') process.exit(44);
          if (!zippickSectionRatingHtml(item, '가격 비교').includes('가격 비교 임시 점수') || !zippickSectionRatingHtml(item, '가격 비교').includes('3.0/5')) process.exit(47);
          item.testQuarterStats = {currentCount:5, currentAverage:10.2, stale:false};
          const rankDetail = {key:'price_rank', status:'ok', reason:'지역 후보 3/4위 · 가격 부담 낮은 편',
            comparisonPeerCount:3, comparisonPeers:[
              {name:'산성역 포레스티아', legalDong:'신흥동', areaLabel:'전용 59.8㎡'},
              {name:'산성역자이푸르지오 1단지', legalDong:'신흥동', areaLabel:'전용 60㎡'},
              {name:'삼부', legalDong:'수진동', areaLabel:'전용 59.8㎡'},
            ]};
          item.testPricePart = {key:'price', points:24.6, maxPoints:30, details:[rankDetail]};
          item.priceComparison = {status:'loading'};
          if (zippickPriceAssessment(item).heading !== '가격은 보통으로 임시 표시했어요. 주변 단지 거래를 확인하고 있어요.') process.exit(60);
          if (!zippickSectionRatingHtml(item, '가격 비교').includes('3.0/5')) process.exit(65);
          item.priceComparison = {status:'unavailable', reason:'비교할 거래가 부족해요.'};
          if (zippickSectionRatingData(item, '가격 비교').stars !== '3.0') process.exit(66);
          item.priceComparison = {status:'ready', region:'도봉구', areaLabel:'84.5', periodMonths:6,
            averagePriceEok:9.6487, peerAveragePriceEok:10.0469, differencePct:-4.0, position:'similar',
            peers:[
              {name:'동아청솔', legalDong:'창동', averagePriceEok:10.727, transactionCount:10},
              {name:'삼성아파트', legalDong:'창동', averagePriceEok:9.3136, transactionCount:22},
              {name:'주공19단지', legalDong:'창동', averagePriceEok:10.1, transactionCount:3},
            ]};
          if (zippickPriceAssessment(item).heading !== '가격은 보통이에요. 시세가 도봉구 비교 단지 3곳보다 4.0% 낮아요.') process.exit(57);
          if (!zippickSectionRatingHtml(item, '가격 비교').includes('가격 비교 점수 3.0/5')) process.exit(67);
          if (zippickPriceAssessment(item).subheading !== '최근 6개월 평균 실거래가 · 이 단지 9.6487억 · 비교 단지 10.0469억') process.exit(58);
          if (JSON.stringify(zippickPriceAssessment(item).comparisonPeers[0]) !== JSON.stringify({name:'동아청솔',legalDong:'창동',averagePriceEok:10.727,transactionCount:10})) process.exit(59);
          if (zippickPriceAssessment(item).peerReason !== '같은 구에서 비슷한 조건의 단지를 골랐어요.') process.exit(63);
          item.priceComparison.status = 'reference';
          item.priceComparison.reason = '비교 단지의 조건 차이가 있어 이번 가격 차이는 종합 점수에 넣지 않았어요.';
          if (!zippickPriceAssessment(item).heading.startsWith('가격은 보통이에요. 참고 비교에서 시세가 도봉구 비교 단지 3곳보다 4.0% 낮아요.')) process.exit(68);
          if (!zippickPriceAssessment(item).peerReason.includes('참고 별점은 이 가격 차이로 계산했어요.')) process.exit(69);
          if (!zippickSectionRatingHtml(item, '가격 비교').includes('가격 비교 참고점수 3.0/5')) process.exit(70);
          item.priceComparison.position = 'high';
          item.priceComparison.differencePct = 16.2;
          if (zippickSectionRatingData(item, '가격 비교').stars !== '2.0' || !zippickPriceAssessment(item).heading.startsWith('가격은 아쉬워요.')) process.exit(74);
          item.priceComparison.position = 'similar';
          item.priceComparison.differencePct = -4.0;
          item.priceComparison.peers = item.priceComparison.peers.slice(0, 1);
          if (!zippickPriceAssessment(item).heading.includes('비교 단지 1곳보다') || zippickSectionRatingData(item, '가격 비교').stars !== '3.0') process.exit(73);
          item.priceComparison.peers = [
            {name:'동아청솔', legalDong:'창동', averagePriceEok:10.727, transactionCount:10},
            {name:'삼성아파트', legalDong:'창동', averagePriceEok:9.3136, transactionCount:22},
            {name:'주공19단지', legalDong:'창동', averagePriceEok:10.1, transactionCount:3},
          ];
          item.priceComparison.status = 'ready';
          item.priceComparison.position = 'low';
          item.priceComparison.differencePct = -7.0;
          if (!zippickPriceAssessment(item).heading.startsWith('가격은 좋아요. 시세가 도봉구 비교 단지 3곳보다 7.0% 낮아요.')) process.exit(61);
          if (zippickSectionRatingData(item, '가격 비교').stars !== '4.0') process.exit(71);
          item.priceComparison.position = 'high';
          item.priceComparison.differencePct = 7.0;
          if (!zippickPriceAssessment(item).heading.startsWith('가격은 아쉬워요. 시세가 도봉구 비교 단지 3곳보다 7.0% 높아요.')) process.exit(62);
          if (zippickSectionRatingData(item, '가격 비교').stars !== '2.0') process.exit(72);
          delete item.priceComparison;
          const averagePriceTitle = zippickPriceAssessment(item).heading;
          if (averagePriceTitle !== '시세가 낮은 편이에요. 성남수정구의 다른 단지 3곳과 비교한 결과예요.') process.exit(48);
          if (zippickPriceAssessment(item).subheading !== '이 아파트의 최근 3개월 평균 실거래가는 10.2억이에요.') process.exit(64);
          if (JSON.stringify(zippickPriceAssessment(item).comparisonPeers) !== JSON.stringify(rankDetail.comparisonPeers)) process.exit(54);
          item.latestDealPriceEok = 12;
          item.valuation.floorComparison = {status:'matched', targetFloor:14, sampleCount:8};
          item.latestDealFloor = '14';
          if (zippickPriceAssessment(item).heading !== averagePriceTitle) process.exit(49);
          item.testQuarterStats = {currentCount:1, currentAverage:9, stale:false};
          item.recentAveragePriceEok = 10.5;
          item.tradeLookbackMonths = 6;
          if (!zippickPriceAssessment(item).subheading.includes('최근 6개월 평균 실거래가는 10.5억이에요.') || zippickPriceAssessment(item).heading.includes('14층')) process.exit(53);
          item.testQuarterStats = {currentCount:5, currentAverage:10.2, stale:false};
          item.testPricePart.details[0].reason = '지역 후보 1/4위 · 가격 부담 높음';
          if (zippickPriceAssessment(item).heading !== '시세가 비싼 편이에요. 성남수정구의 다른 단지 3곳과 비교한 결과예요.') process.exit(50);
          item.testPricePart.details[0].reason = '지역 후보 2/4위 · 중간 가격대';
          if (!zippickPriceAssessment(item).heading.startsWith('시세가 보통이에요.')) process.exit(51);
          item.testPricePart.details = [];
          if (!zippickPriceAssessment(item).heading.startsWith('가격은 보통으로 임시 표시했어요.')) process.exit(52);
          item.testPricePart.details = [{...rankDetail}];
          item.testPricePart.details[0].comparisonPeers = [];
          if (zippickPriceAssessment(item).heading.startsWith('시세가 낮은 편이에요.')) process.exit(55);
          item.testPricePart.details[0] = rankDetail;
          item.region = '';
          if (zippickPriceAssessment(item).heading.startsWith('시세가 낮은 편이에요.')) process.exit(56);
          item.region = '성남수정구';
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
