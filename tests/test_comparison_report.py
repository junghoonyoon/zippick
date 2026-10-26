"""Behavior checks for the comparison report's financial and relative claims."""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / '앱화면' / 'real-estate-search.html'


@unittest.skipUnless(shutil.which('node'), 'Node.js is required')
class ComparisonReportTest(unittest.TestCase):
    def run_js(self, names, body):
        html = HTML.read_text()
        helpers = '\n'.join(re.search(r'    function ' + name + r'\(.*?\n    \}', html, re.S).group() for name in names)
        script = "const assert = require('node:assert/strict');\n" + helpers + '\n' + body
        result = subprocess.run(['node'], input=script, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_price_headroom_never_overrides_cash_shortage(self):
        self.run_js(['comparisonNumber', 'comparisonFundingState', 'comparisonRequiredCashText', 'comparisonPriceGapText', 'comparisonValue'], r"""
          const esc = value => String(value);
          const readableGapMoney = value => `${Math.round(value * 10000)}만원`;
          const policyMoney = value => `${value}억`;
          const row = {budgetGapEok:.65, fitStatus:'예산 안', policyImpact:{cashGapEok:-.17,requiredCashEok:4.17}};
          assert.equal(comparisonFundingState(row).kind, 'short');
          assert.match(comparisonValue(row,'fit'), /1700만원 필요/);
          assert.match(comparisonValue(row,'policyCash'), /1700만원 필요/);
          assert.equal(comparisonValue(row,'gap'), '검토 기준선보다 6500만원 낮음');
          for (const key of ['fit','gap','policyCash']) assert.doesNotMatch(comparisonValue(row,key), /구매 가능|예산 안/);
          assert.equal(comparisonPriceGapText({}), '검토 기준선 확인 필요');
          assert.equal(comparisonPriceGapText({budgetGapEok:0}), '검토 기준선과 같음');
          assert.match(comparisonPriceGapText({budgetGapEok:-.1}), /높음/);
        """)

    def test_cash_scenarios_missing_zero_and_loan_restrictions(self):
        self.run_js(['comparisonNumber', 'comparisonFundingState', 'comparisonRequiredCashText'], r"""
          const readableGapMoney = value => `${Math.round(value * 10000)}만원`;
          const policyMoney = value => `${value}억`;
          const row = {policyImpact:{cashGapEok:.2,requiredCashEok:3.8,cashScenarios:[
            {cashGapEok:.2,requiredCashEok:3.8},{cashGapEok:-.4,requiredCashEok:4.4}
          ]}};
          assert.equal(comparisonFundingState(row).gap, -.4);
          assert.equal(comparisonFundingState(row).shortage, .4);
          assert.equal(comparisonRequiredCashText(row), '4.4억');
          for (const cashGapEok of [null,undefined,'',NaN]) {
            assert.equal(comparisonFundingState({policyImpact:{cashGapEok}}).kind,'unknown');
          }
          assert.equal(comparisonFundingState({policyImpact:{cashGapEok:0}}).text,'추가 자기자금 없음');
          assert.equal(comparisonFundingState({policyImpact:{cashGapEok:.1}}).kind,'within');
          assert.equal(comparisonFundingState({policyImpact:{status:'restricted',cashGapEok:.1}}).text,'대출 제한 확인 필요');
          assert.match(comparisonFundingState({policyImpact:{status:'restricted',cashGapEok:-.1}}).text,/추가 자기자금/);
        """)

    def test_reasons_compare_real_metrics_and_show_tradeoff(self):
        self.run_js(['comparisonNumber', 'comparisonPreferenceWeights', 'comparisonRecommendationDifferences', 'comparisonDecisionReasonsHtml'], r"""
          const comparisonPreference = {type:'stable',period:'long',priority:'education'};
          const comparisonMetricScore = (row,key) => row[key] ?? null;
          const candidateDisplayName = row => row.name;
          const esc = value => String(value);
          const row = {name:'가단지',total:85,flow:65,education:90};
          const runnerUp = {name:'나단지',total:70,flow:80,education:75};
          const html = comparisonDecisionReasonsHtml([row,runnerUp],{row,runnerUp});
          assert.match(html,/나단지보다 단지·입지 종합점수가 15점 높아요/);
          assert.match(html,/나단지보다 교육환경 점수가 15점 높아요/);
          assert.match(html,/최근 시장 신호는 나단지보다 15점 낮아요/);
          const missing = comparisonDecisionReasonsHtml([],{row:{name:'가'},runnerUp:{name:'나'}});
          assert.match(missing,/뚜렷한 강점을 가리기 어려워요/);
          assert.doesNotMatch(missing,/더 좋아요|가장|높아요/);
        """)

    def test_consultant_summary_uses_real_prices_and_separate_trade_windows(self):
        self.run_js(['comparisonNumber', 'comparisonConsultationSummary'], r"""
          const comparisonPreference = {priority:'growth'};
          const candidateDisplayName = row => row.name;
          const comparisonRecommendationDifferences = () => [{key:'flow',label:'최근 시장 신호',value:99,other:91,difference:8}];
          const row = {name:'삼호4',buildingAge:39,signals:{recent3Pct:4.6,recentDealCount:13,priorDealCount:5,recoveryPct:95}};
          const recommendation = {row,runnerUp:{name:'한신',buildingAge:29},leadGap:5};
          const summary = comparisonConsultationSummary(recommendation);
          assert.match(summary.title,/삼호4부터 보겠습니다/);
          assert.match(summary.reason,/최근 3개월 가격은 4.6% 올랐습니다/);
          assert.match(summary.reason,/이전 6개월 5건에서 최근 6개월 13건/);
          assert.match(summary.reason,/한신보다 최근 시장 신호가 8점/);
          assert.match(summary.reason,/가격 상승과 거래 증가가 함께/);
          assert.match(summary.caution,/고점에 가까운/);
          row.signals = {recent3Pct:-3,recentDealCount:2,priorDealCount:4};
          const down = comparisonConsultationSummary(recommendation);
          assert.match(down.reason,/3% 내렸습니다/);
          assert.match(down.reason,/줄었습니다/);
          assert.doesNotMatch(down.reason,/가격 상승과 거래 증가가 함께/);
          assert.match(down.caution,/2건뿐/);
        """)

    def test_consultant_summary_follows_priority_and_does_not_invent_distance(self):
        self.run_js(['comparisonNumber', 'comparisonConsultationSummary'], r"""
          const comparisonPreference = {priority:'transport'};
          const candidateDisplayName = row => row.name;
          let differences = [{key:'transport',label:'교통 점수',value:100,other:90,difference:10}];
          const comparisonRecommendationDifferences = () => differences;
          const row = {name:'한신',nearestStationName:'중화역',nearestStationDistance:250,buildingAge:29};
          const recommendation = {row,runnerUp:{name:'삼호4',buildingAge:39},leadGap:1};
          const summary = comparisonConsultationSummary(recommendation);
          assert.match(summary.title,/교통을 우선하면 한신부터/);
          assert.match(summary.reason,/중화역까지 직선거리 약 250m/);
          assert.match(summary.reason,/실제 걷는 길과 출근 시간은 따로/);
          assert.match(summary.caution,/판단 차이는 작습니다/);
          row.nearestStationDistance = null;
          assert.doesNotMatch(comparisonConsultationSummary(recommendation).reason,/0m|250m/);
          differences = [];
          assert.match(comparisonConsultationSummary(recommendation).title,/자신 있게 권하기 어렵습니다/);
        """)

    def test_consultation_and_funding_are_separate_in_verdict(self):
        self.run_js(['comparisonPreferenceVerdictHtml'], r"""
          const esc = value => String(value);
          const comparisonFundingState = () => ({text:'추가 자기자금 1700만원 필요',kind:'short',shortage:.17});
          const comparisonPreferenceHighlightsHtml = () => '<ul>선택 기준</ul>';
          const comparisonConsultationSummary = () => ({title:'삼호4부터 보겠습니다',reason:'거래가 늘었습니다.',caution:'고점에 가깝습니다.'});
          const html = comparisonPreferenceVerdictHtml([], {row:{name:'삼호4'},leadGap:1,reasonParts:[]});
          assert.match(html,/삼호4부터 보겠습니다/);
          assert.match(html,/거래가 늘었습니다/);
          assert.match(html,/고점에 가깝습니다/);
          assert.match(html,/추가 자기자금 1700만원 필요/);
          assert.ok(html.indexOf('거래가 늘었습니다') < html.indexOf('자금 확인'));
          assert.doesNotMatch(html,/구매 가능|아래에서 자금과 후보 간 차이를 확인하세요/);
        """)
