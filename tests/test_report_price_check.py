import unittest
from test_report_quality import run_js


class ReportPriceCheckTest(unittest.TestCase):
    def test_asking_price_uses_fresh_same_area_trade_basis(self):
        run_js("""
const item = sample([9,9.5,10,10.5,11]);
const basis = zippickPriceCheckBasis(item);
assert.equal(basis.price,10);
assert.match(zippickPriceCheckText(basis,'12'),/2억 높습니다/);
assert.match(zippickPriceCheckText(basis,'8'),/2억 낮습니다/);
assert.match(zippickPriceCheckText(basis,'-1'),/사이/);
item.roneEstimate.adjustedTransactions.forEach(row=>row.dealDate='2020-01-01');
assert.equal(zippickPriceCheckBasis(item),null);
assert.match(zippickPriceCheckText(null,'12'),/실거래를 확인/);
""")
