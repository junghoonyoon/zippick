import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_HTML = ROOT / "앱화면" / "real-estate-search.html"


class ReportPriceCheckTest(unittest.TestCase):
    def test_asking_price_uses_fresh_same_area_trade_basis(self):
        html = APP_HTML.read_text(encoding="utf-8")
        start = html.index("    function zippickPriceCheckBasis(item) {")
        end = html.index("    function zippickPriceCheckHtml(item) {", start)
        functions = html[start:end]
        script = """
          function zpNum(value) { return value == null || value === '' ? NaN : Number(value); }
          function transactionMoney(value) { return `${value}억`; }
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
          item.statsThrough = '2020-01-01';
          if (zippickPriceCheckBasis(item).price !== 12) process.exit(2);
          item.latestDealPriceEok = 0;
          if (!zippickPriceCheckText(zippickPriceCheckBasis(item), '12').includes('실거래를 확인')) process.exit(3);
        """
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
