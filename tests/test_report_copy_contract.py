"""Conclusions must be clear without changing their comparison basis or data state."""
from pathlib import Path
import re
import subprocess

HTML = Path(__file__).resolve().parents[1] / '앱화면/real-estate-search.html'

def run(names, script, extra=''):
    html = HTML.read_text()
    functions = '\n'.join(re.search(r'    function '+name+r'\([^\n]*\) \{.*?\n    \}', html, re.S).group() for name in names)
    result = subprocess.run(['node'],input="const assert=require('node:assert/strict');\n"+functions+'\n'+extra+'\n'+script,text=True,capture_output=True)
    assert result.returncode == 0, result.stderr


def test_conditional_stamp_uses_one_label_and_keeps_reasons_in_headline():
    run(['zippickOverallRatingHtml'], r'''
const esc=String;
const reason='입지는 좋지만 가격은 부담돼요.';
for(const label of ['조건부 검토','매수는 신중히 검토하세요.']) {
 const verdict={common:true,tone:'conditional',label,reviewHeadline:reason+' 매수는 신중히 검토하세요.'};
 const before=JSON.stringify(verdict),html=zippickOverallRatingHtml(verdict,label);
 assert.match(html,/zpr-verdict-tag is-conditional">조건부 검토<\/span>/);
 assert.ok(html.includes(`<h3 class="zpr-overall-opinion">${reason}</h3>`));
 assert.equal(JSON.stringify(verdict),before);
}
for(const [tone,label] of [['yes','매수 검토'],['hold','매수 보류'],['risk','다른 후보 우선'],['missing','판단 보류']]) {
 const html=zippickOverallRatingHtml({common:true,tone,label,reviewHeadline:reason},label);
 assert.ok(html.includes(`zpr-verdict-tag is-${tone}">${label}</span>`));
}
''')


def test_price_band_all_positions_and_data_limits():
    html = HTML.read_text()
    block = html[html.index('    function zippickPriceCheckBasis(item) {'):html.index('    function zippickReportFinance(item) {')]
    run(['zpNum'], r'''
const esc=String, transactionMoney=v=>`${v}억`, candidateTrendPanelHtml=()=>'', zippickBandTradeHistoryHtml=()=>'';
const base={displayAreaLabel:'전용 59㎡',latestDealExclusiveArea:59.34,latestDealDate:'2026-10-20',latestDealFloor:2,
 valuation:{status:'ready',latestTradeExcluded:true,fairPrice:{lowEok:8,centerEok:9,highEok:10},
 floorComparison:{status:'matched'},dataQuality:{sampleCount:5,level:'medium',periodMonths:6}}};
for (const [price,meaning] of [[7,'저렴한 편이에요'],[8,'적정해요'],[9,'적정해요'],[10,'적정해요'],[11,'비싸게 거래됐어요']]) {
 for (const referenceOnly of [true,false]) for (const floor of ['matched','insufficient']) {
  const item={...base,latestDealPriceEok:price,valuation:{...base.valuation,referenceOnly,floorComparison:{status:floor}}};
  const before=JSON.stringify(item), rendered=zippickBuyBandHtml(item,{});
  const headline=price>10 ? `${price}억으로 이 단지의 최근 시세보다 ${meaning}` : price<8 ? `최근 거래 ${price}억은 이 단지에서 ${meaning}` : `최근 거래 ${price}억은 같은 단지의 비슷한 집 거래와 비교하면 적정한 가격에 거래됐어요`;
  assert.ok(rendered.includes(headline));
  assert.doesNotMatch(rendered,/<h4>[^<]*(가격대 안|범위 안)/);
  assert.equal(JSON.stringify(item),before);
 }
}
const historical={...base,latestDealPriceEok:9,valuation:{...base.valuation,referenceOnly:true,dataQuality:{sampleCount:3,periodMonths:24,periodWidened:true}}};
assert.match(zippickBuyBandHtml(historical,{}),/과거 거래 기준으로 적정해요.*현재 시세는 판단하기 어려워요/);
assert.match(zippickBuyBandHtml({...base,latestDealPriceEok:9},{peakGuard:{atPeak:true}}),/적정한 가격에 거래됐어요.*다만.*2년/);
assert.doesNotMatch(zippickBuyBandHtml({...base,latestDealPriceEok:9,latestDealExclusiveArea:84},{}),/<h4>[^<]*(저렴한 편이에요|적정한 가격에 거래됐어요|비싸게 거래됐어요)/);
''',block)



def test_price_band_plots_prior_same_area_trades_at_reported_prices():
    html = HTML.read_text()
    block = html[html.index('    function zippickPriceCheckBasis(item) {'):html.index('    function zippickReportFinance(item) {')]
    run(['zpNum'], r"""
const esc=String, transactionMoney=v=>`${v}억`, candidateTrendPanelHtml=()=>'', zippickBandTradeHistoryHtml=()=>'';
const trade=(date,price,area=59.87,floor='8')=>({dealDate:date,originalPriceEok:price,adjustedPriceEok:price+3,exclusiveArea:area,floor});
const item={priceIdentityVerified:true,displayAreaLabel:'전용 59.87㎡',
 latestDealExclusiveArea:59.87,latestDealDate:'2026-10-20',latestDealFloor:'9',latestDealPriceEok:9.3,
 valuation:{status:'ready',latestTradeExcluded:true,areaScope:{minSqm:58.87,maxSqm:60.87,upperInclusive:true},
  evaluatedTrade:{exclusiveArea:59.87,dealDate:'2026-10-20',floor:'9',dealAmountEok:9.3},
  fairPrice:{lowEok:9.1,centerEok:9.15,highEok:9.2},dataQuality:{sampleCount:3,periodMonths:6},
  comparisonTrades:[trade('2026-09-19',9.16)]},
 roneEstimate:{adjustedTransactions:[
  trade('2026-10-02',9.19),trade('2026-10-20',9.3),trade('2026-10-19',8.9,84.95),
  trade('2026-10-03',9.19,59.87,'5'),trade('2026-09-12',9.19),trade('2026-09-08',9.19),
  trade('2026-09-07',9.19),trade('2026-09-06',9.19),trade('2026-09-05',9.19),
  trade('2026-09-04',9.19),trade('2026-09-03',9.19),trade('2026-09-02',9.19),
 ]}};
const before=JSON.stringify(item), rendered=zippickBuyBandHtml(item,{});
assert.doesNotMatch(rendered,/zpr-buy-band-prior-list/);
assert.match(rendered,/<h4>직전 거래는 9.19억이었어요\. 이번에는 9.3억으로 이 단지의 최근 시세보다 비싸게 거래됐어요<\/h4>/);
assert.doesNotMatch(zippickBuyBandHtml({...item,roneEstimate:null},{}),/<h4>직전 거래는/);
assert.match(rendered,/aria-label="이전 실거래 6건\. 1번 · 계약 당시 9.19억 · 2026-10-03 · 5층/);
assert.match(rendered,/최근 실거래 9.3억<small>2026-10-20 · 9층/);
assert.match(rendered,/9.19억<\/strong><small>2026-10-03 · 5층/);
assert.match(rendered,/2026-09-04/);
assert.doesNotMatch(rendered,/12.19억|2026-10-19|2026-09-03|2026-09-02/);
assert.equal((rendered.match(/class="zpr-buy-band-prior-trade"/g)||[]).length,8);
const pins=[...rendered.matchAll(/zpr-buy-band-prior-pin" style="--zpr-band-position:([\d.]+)%;--zpr-prior-lane:(\d)"/g)];
assert.equal(pins.length,3);
assert.ok(pins.every(pin=>Number(pin[1])>100/3 && Number(pin[1])<200/3));
assert.deepEqual(pins.map(pin=>pin[2]),['0','1','2']);
assert.equal(JSON.stringify(item),before);
assert.match(zippickBuyBandHtml({...item,roneEstimate:null},{}),/가격대 계산에 쓴 이전 실거래 1번 · 계약 당시 9.16억/);
assert.doesNotMatch(zippickBuyBandHtml({...item,displayAreaLabel:'전용 84㎡'},{}),/zpr-buy-band-prior-pin/);
""",block)


def test_peer_price_comparison_does_not_confuse_cheap_with_less_cheap():
    run(['zpNum','zippickPriceHeading'],r'''
const zippickPricePeerLabel=()=> '비교 단지 2곳';
for (const [position,meaning] of [['low','저렴해요'],['similar','적정해요'],['high','비싸요']]) {
 const title=zippickPriceHeading({method:'usual_gap',currentGapPct:-6,usualGapPct:-12},position);
 assert.equal(title,`최근 평균 가격은 비교 단지 2곳과의 평소 가격 차이를 감안하면 ${meaning}`);
 assert.doesNotMatch(title,/비교 단지 2곳보다.*비싸/);
}
assert.equal(zippickPriceHeading({method:'simple',differencePct:-8},'low'),'비교 단지 2곳보다 8% 싸요');
''')


def test_market_summary_and_body_share_all_direction_combinations():
    run(['zpNum','zpPct','candidateSignalDataUnavailable', 'zippickMarketVerdict','zippickSignalHeading','zippickDecisionScoresHtml'],r'''
const zippickLocationHeading=()=> '단지 조건은 보통이에요',zippickLocationEvidenceText=()=>'',
 candidateLocationScoreBadgeHtml=()=>'',candidateFlowScoreBadgeHtml=()=>'',zippickMarketEvidenceText=()=>'',
 zippickHasVerifiedMixedCorridor=()=>false,esc=String;
for (const momentum of [-5,0,5]) for (const turnover of [.4,1,1.5]) for(const recent3 of [-2,0,2]) {
 const item={signals:{momentumPct:momentum,turnoverRatio:turnover,recent3Pct:recent3}};
 const title=zippickSignalHeading(item,{});
 assert.match(title,/최근 시장 흐름은 (좋아요|보통이에요|아쉬워요)\./);
 assert.ok(zippickDecisionScoresHtml(item,{}).includes(`<strong>${title}</strong>`));
}
for(const signals of [{},{momentumPct:null,turnoverRatio:1},{momentumPct:0,turnoverRatio:null}]) {
 assert.match(zippickSignalHeading({signals},{}),/판단할 수 없어요/);
}
const flat=zippickSignalHeading({signals:{momentumPct:0,turnoverRatio:1.5}},{});
assert.match(flat,/거래는 늘었지만 가격은 비슷/);
assert.doesNotMatch(flat,/가격과 거래가 크게 변하지/);
''')


def test_funding_is_scenario_specific_and_missing_is_not_bad():
    run(['zpNum','zippickFundingHtml'],r'''
const esc=String,transactionMoney=v=>`${v}억`,zpPct=v=>`${v}%`,zippickJeonsePeerStat=i=>i.peer;
for (const band of ['high','similar','low']) {
 const item={latestDealPriceEok:9,jeonseSalePriceBasisEok:10,latestJeonseDepositEok:4,jeonseRatioPct:40,
 peer:{band,total:5,median:50},policyImpact:{cashScenarios:[{priceEok:9,requiredCashEok:6}]}};
 const output=zippickFundingHtml(item),heading=output.match(/<h5>(.*?)<\/h5>/s)[1];
 assert.match(heading,/전세를 끼고.*내 돈 5억.*세금·중개비는 별도/);
 assert.doesNotMatch(heading,/자금 조건은 좋아요|자금 조건은 아쉬워요/);
 assert.match(output,/직접 들어가 산다면.*6억/);
}
assert.match(zippickFundingHtml({}),/계산할 수 없어요.*전세금 자료가 없어요/);
assert.doesNotMatch(zippickFundingHtml({jeonseRatioPct:40}),/<h5>[^<]*(좋아요|아쉬워요)/);
''')


def test_liquidity_unknown_states_have_no_negative_score_or_sale_promise():
    run(['zpNum','zippickLiquidityHtml','zippickSectionRatingData'],r'''
const esc=String,zippickLiquidityStat=i=>i.stat;
const base={windowMonths:60,downMonths:6,downDeals:18,downPerMonth:3,otherMonths:54,otherPerMonth:6,silentMonths:0};
for (const band of ['illiquid','no_downturn','unknown']) {
 const item={stat:{...base,band}};
 assert.match(zippickLiquidityHtml(item),/판단할 수 없어요/);
 assert.equal(zippickSectionRatingData(item,'하락기 거래'),null);
 assert.doesNotMatch(zippickLiquidityHtml(item),/팔리는 데 시간이 걸릴|매도가 어려워요/);
}
for(const [band,ratio,meaning] of [['strong',.7,'좋아요'],['fair',.5,'보통이에요'],['weak',.1,'아쉬워요']]) {
 const item={stat:{...base,band,ratio}};
 assert.ok(zippickLiquidityHtml(item).includes(`하락기 거래 유지는 ${meaning}`));
 assert.notEqual(zippickSectionRatingData(item,'하락기 거래'),null);
}
assert.match(zippickLiquidityHtml({}),/판단할 수 없어요/);
assert.match(zippickLiquidityHtml({reportPeerState:'loading'}),/불러오고 있어요/);
''')


def test_access_reason_never_calls_a_low_scoring_station_close():
    run(['zpNum','zippickDemandScoreReason'],r'''
const zippickDetailReasons=()=>[];
const item={points:25,maxPoints:30,details:[{key:'station',points:1,maxPoints:5,status:'ok',reason:'역 직선 1450m'},
 {key:'education',points:4,maxPoints:4,status:'ok',reason:'학교 250m'}]};
const output=zippickDemandScoreReason(item);
assert.match(output,/역 접근성은 아쉬워요.*학교 접근성은 좋아요/);
assert.doesNotMatch(output,/역과 학교가 가까워|역이 가까워/);
item.details[0].status='missing';
assert.doesNotMatch(zippickDemandScoreReason(item),/1450m|역 접근성은 아쉬워요/);
''')
