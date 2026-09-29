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

    def test_asking_price_uses_fresh_same_area_trade_basis(self):
        html = APP_HTML.read_text(encoding="utf-8")
        start = html.index("    function zippickPriceCheckBasis(item) {")
        end = html.index("    function zippickPriceCheckHtml(item) {", start)
        functions = html[start:end]
        script = """
          function zpNum(value) { return value == null || value === '' ? NaN : Number(value); }
          function transactionMoney(value) { return `${value}억`; }
          function esc(value) { return String(value); }
          function candidateIdentityKey() { return 'sample'; }
          const zippickEnteredPrices = new Map();
        """ + functions + """
          const fresh = new Date().toISOString().slice(0, 10);
          const item = {
            statsThrough: fresh,
            recent3AdjustedTradeCount: 5,
            recent3AdjustedAveragePriceEok: 10,
            recent3TradeCount: 6,
            recent3AveragePriceEok: 11,
            latestDealPriceEok: 12,
            latestDealDate: fresh,
          };
          const basis = zippickPriceCheckBasis(item);
          if (basis.price !== 10 || !zippickPriceCheckText(basis, '12').includes('2억 높습니다')) process.exit(1);
          item.valuation = {
            status: 'ready', modelVersion: 'zippick-current-value-v1', asOf: fresh,
            fairPrice: {lowEok: 9.4, centerEok: 10.1, highEok: 10.8, method: 'test'},
            dataQuality: {sampleCount: 8, level: 'medium'},
          };
          const modelBasis = zippickPriceCheckBasis(item);
          if (modelBasis.low !== 9.4 || modelBasis.price !== 10.1 || modelBasis.high !== 10.8) process.exit(4);
          if (!zippickPriceCheckText(modelBasis, '9').includes('싼 구간')) process.exit(5);
          if (!zippickPriceCheckText(modelBasis, '10').includes('적정 구간')) process.exit(6);
          if (!zippickPriceCheckText(modelBasis, '11').includes('비싼 구간')) process.exit(7);
          const band = zippickBuyBandResultHtml(9.4, 10.1, 10.8, 10, true, '11');
          if (!band.includes('<strong>쌈</strong>') || !band.includes('<strong>적정</strong>') || !band.includes('<strong>비쌈</strong>')) process.exit(8);
          if (band.includes('가격 좋음') || band.includes('협상 필요')) process.exit(9);
          if (!band.includes('zpr-buy-band-chart has-asking') || !band.includes('--zpr-band-position:')) process.exit(13);
          if (!band.includes('최근 실거래 10억') || !band.includes('입력한 매물 11억')) process.exit(14);
          item.latestDealExclusiveArea = 84;
          item.displayAreaLabel = '전용 84㎡';
          item.valuation.reasons = ['이전 실거래 8건을 사용했어요.', '평가할 최근 거래는 기준가격에서 뺐어요.'];
          item.valuation.limitations = ['층·향·수리 상태는 반영하지 못했어요.'];
          item.valuation.marketAdjustmentPct = 1.2;
          item.valuation.macro = {message:'기준금리는 향후 시장 위험으로 확인해요.'};
          const modelBand = zippickBuyBandHtml(item, {});
          if (!modelBand.includes('매수 판단 밴드') || modelBand.includes('집픽 현재 적정가격')) process.exit(10);
          if (!modelBand.includes('적정가격보다 비싸요') || !modelBand.includes('<em>비쌈</em>')) process.exit(11);
          if (!modelBand.includes('이 가격은 어떻게 계산했나요?') || !modelBand.includes('주변 시장 흐름을 +1.2% 반영했어요.')) process.exit(12);
          delete item.valuation;
          item.statsThrough = '2020-01-01';
          if (zippickPriceCheckBasis(item).price !== 12) process.exit(2);
          item.latestDealPriceEok = 0;
          if (!zippickPriceCheckText(zippickPriceCheckBasis(item), '12').includes('실거래를 확인')) process.exit(3);
        """
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
