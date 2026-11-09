"""Card/report consistency, explicit time windows and collapsed input behavior."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest


HTML = Path(__file__).resolve().parents[1] / "앱화면" / "real-estate-search.html"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="Node required")


def run_functions(names, script):
    source = HTML.read_text()
    functions = []
    for name in names:
        match = re.search(r"^    (?:async )?function " + name + r"\(.*?^    \}", source, re.M | re.S)
        assert match, name
        functions.append(match.group())
    result = subprocess.run(
        ["node"], input="const assert = require('node:assert/strict');\n" + "\n".join(functions) + "\n" + script,
        text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_peer_enrichment_cannot_replace_selected_area_score_or_price():
    run_functions(["zpNum", "zippickTradeAreaScope", "zippickAreaContains", "zippickLatestTradeDetails",
                   "zippickValuationMatchesTrade", "zippickReportAreaKey", "zippickRefreshReportLocation", "ensureZippickReportPeers"], """
      const score = {status:'ok',score:73};
      const item = {name:'잠실엘스',region:'송파구',displayAreaLabel:'전용 59.96㎡',
        locationScore:score,latestDealPriceEok:29.4,signals:{score:55}};
      const fetchAptReport = async () => ({report:{locationScore:{status:'ok',score:84},
        latestDealPriceEok:40,signals:{score:90},peers:[{name:'비교 단지'}],priceComparison:{status:'reference'}}});
      (async () => {
        await ensureZippickReportPeers(item);
        assert.strictEqual(item.locationScore, score);
        assert.equal(item.latestDealPriceEok,29.4);
        assert.equal(item.signals.score,55);
        assert.equal(item.peers[0].name,'비교 단지');
        assert.equal(item.reportPeerState,'ready');
      })().catch(error=>{console.error(error);process.exitCode=1;});
    """)


def test_chart_legend_and_card_compare_the_same_month_with_missing_trades():
    run_functions(["candidateTrendSummary"], """
      const candidateDisplayName = row => row.name;
      const candidateTrendPattern = () => ({comparable:true,message:''});
      const candidateTrendComparison = () => '';
      const readableSparklinePeriod = String;
      const series={complex:[100,120,null],region:[100,125,110],
        leader:[100,null,130],districtLeader:null,periods:['202607','202608','202609'],anchorPeriod:'202607'};
      const summary=candidateTrendSummary({name:'단지',region:'송파구'},series);
      assert.equal(summary.comparisonPeriod,'202608');
      assert.equal(summary.complexValue,120);
      assert.equal(summary.regionValue,125); // the card correctly says below the region
      assert.equal(summary.leaderValue,null); // no stale leader rate in the legend
      series.complex=[null,null,null];
      assert.equal(candidateTrendSummary({name:'단지'},series),null);
    """)


PRICE_FUNCTIONS = ['zpNum', 'zippickHasPriceComparison', 'zippickPriceSelectionTier',
                   'zippickPricePeerLabel', 'zippickPriceHeading', 'zippickPriceGapSentence',
                   'zippickPriceAssessment', 'zippickPriceComparisonHtml', 'zippickPriceEvidenceHtml']
PRICE_SETUP = r'''
const esc=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const candidateDisplayName=item=>item.name || '';
const render=item=>zippickPriceEvidenceHtml(item);
const simple=peers=>({name:'초록',latestDealPriceEok:99,priceComparison:{status:'ready',method:'simple',
 position:'similar',averagePriceEok:10,differencePct:0,periodMonths:6,areaLabel:'59㎡',region:'강서구',peers}});
'''


def test_market_reversals_name_both_time_windows_and_missing_is_not_down():
    run_functions(['zpNum', 'zpPct', 'zippickMarketVerdict', 'zippickMarketEvidenceText',
                   'zippickSignalBarsHtml', 'zippickSignalBarReason', 'zippickTradeCountText'], r'''
      const zippickBarHtml=(label,points,max,reason)=>`<p>${label}: ${reason}</p>`;
      const rebound={signals:{momentumPct:-2.7,recent3Pct:4.1,turnoverRatio:1.67,
        comparisonBasis:{areaLabel:'59㎡'},scoreBreakdown:{
          priceMomentum:{label:'6개월 가격 변화',value:-2.7,points:0,maxPoints:40},
          recentPersistence:{label:'최근 3개월 지속성',value:4.1,points:15,maxPoints:15}}}};
      assert.match(zippickMarketVerdict(rebound).heading,/6개월.*하락.*3개월.*반등/);
      // The summary names the area; the actual detail rows own the numeric evidence.
      assert.match(zippickMarketEvidenceText(rebound),/59㎡ 실거래 기준/);
      const detail=zippickSignalBarsHtml(rebound);
      assert.match(detail,/최근 6개월.*2.7% 내렸/);
      assert.match(detail,/최근 3개월.*직전 3개월보다 4.1% 올랐/);
      assert.match(zippickMarketVerdict({signals:{momentumPct:4,recent3Pct:-2,turnoverRatio:1.1}}).heading,/6개월.*상승.*3개월.*하락/);
      assert.match(zippickMarketVerdict({signals:{momentumPct:-4,recent3Pct:null,turnoverRatio:1}}).heading,/6개월.*그 전 6개월/);
      assert.match(zippickMarketVerdict({signals:{momentumPct:null,turnoverRatio:1}}).heading,/판단할 수 없어요/);
      assert.match(zippickSignalBarReason({value:null},'priceMomentum'),/실거래가 부족.*판단하기는 어려워요/);
      assert.doesNotMatch(zippickSignalBarReason({value:null},'priceMomentum'),/0%|내렸어요/);
    ''')


def test_collapsing_details_never_discards_custom_rate_term_or_type():
    run_functions(["purchasePowerHasCustomDetails", "purchasePowerParams"], """
      const field = value => ({value});
      const policyPurchaseRegion=field('seoul'),policyHomeOwnership=field('no_home'),policyFirstTime=field('true');
      const policyCash=field('5'),policyReserveCash=field('0.2'),policyAnnualIncome=field('8000'),policyMonthlyDebt=field('20');
      const policyCoBorrower=field('false'),policySpouseIncome=field(''),policySpouseDebt=field('');
      const policyCreditScore=field(''),policyMortgageRate=field('4.2'),policyLoanTerm=field('30'),policyRateType=field('periodic');
      const estimatedMortgageRate=()=>({rate:4.2});
      let mortgageRateManuallyEdited=false;
      assert.equal(purchasePowerParams('approximate').get('mortgage_rate'),'');
      assert.equal(purchasePowerParams('approximate').get('reserve_cash_eok'),'0.2');
      policyMortgageRate.value='5.1';mortgageRateManuallyEdited=true;policyLoanTerm.value='20';
      const collapsed=purchasePowerParams('approximate');
      assert.equal(collapsed.get('mortgage_rate'),'5.1');
      assert.equal(collapsed.get('loan_term_years'),'20');
      assert.equal(collapsed.toString(),purchasePowerParams('exact').toString());
      mortgageRateManuallyEdited=false;policyMortgageRate.value='4.2';policyLoanTerm.value='30';policyRateType.value='variable';
      assert.equal(purchasePowerHasCustomDetails(),true);
      assert.equal(purchasePowerParams('approximate').get('rate_type'),'variable');
    """)


def test_late_chart_update_does_not_replace_a_new_area_selection():
    run_functions(["refreshAptSearchTrendCandidate"], """
      const candidateIdentityKey = item => `${item.apartmentId}:${item.areaLabel}`;
      const selected={name:'같은 이름',apartmentId:'A',areaLabel:'84',locationScore:{score:80}};
      const aptCandidateResults=new Map([[0,selected]]),currentAptSearchItems=[selected];
      const aptSearchResults={querySelector:()=>null};
      const candidateMapOrigin='none';
      refreshAptSearchTrendCandidate({name:'같은 이름',apartmentId:'A',areaLabel:'59',locationScore:{score:50}});
      assert.equal(aptCandidateResults.get(0).locationScore.score,80);
      assert.strictEqual(aptCandidateResults.get(0),selected);
      selected.locationScore = {score:81};
      refreshAptSearchTrendCandidate(selected);
      assert.strictEqual(currentAptSearchItems[0],selected);
      assert.equal(selected.locationScore.score,81);
    """)



def test_conditional_verdict_names_strength_and_limitation_without_price_instructions():
    source = HTML.read_text()
    matrix = "const ZIPPICK_MATRIX = " + source.split("const ZIPPICK_MATRIX = ", 1)[1].split(";", 1)[0] + ";"
    run_functions(["zpNum", "zpPct", "zippickMatrixVerdict", "zippickMarketVerdict", "zippickVerdictTitle"], matrix + """
      const transactionMoney=value=>`${value}억`;
      const zippickPriceCheckBasis=item=>item.basis;
      const zippickLatestTradeDetails=()=>({price:10});
      const zippickBuyBandTradeMatchesArea=item=>item.areaMatches !== false;
      const zippickBuyBandTier=(value,low,high)=>value<low ? 0 : value>high ? 2 : 1;
      const zippickWeakestPart=item=>item.weakest;
      const zpPartRatio=part=>part.points == null ? NaN : part.points/part.maxPoints;
      const item={locationScore:{score:78},signals:{score:55,momentumPct:-2.7,recent3Pct:4.1,turnoverRatio:1.67},
        valuation:{status:'ready',floorComparison:{status:'matched'}},basis:{low:9,high:11},
        weakest:{key:'market',points:6.4,maxPoints:10}};
      const title=(changes={},override={})=>{
        const selected={...item,...changes};
        return zippickVerdictTitle(selected,{...zippickMatrixVerdict(selected.locationScore.score,selected.signals.score),...override});
      };
      assert.equal(zippickMatrixVerdict(78,55).tone,'conditional');
      assert.match(title(),/단지 조건은 좋지만 최근 시장 흐름은 아직 부족해요/);
      assert.doesNotMatch(title(),/하락기|거래가 뜸|거래가 적|매도가 어려/);
      // 가장 낮은 상대 점수가 아니라 판정을 만든 시장 점수로 제약을 설명한다.
      assert.match(title({buildingAge:28,weakest:{key:'product',points:4,maxPoints:10}}),/최근 시장 흐름은 아직 부족/);
      assert.match(title({valuation:{status:'insufficient'}}),/최근 시장 흐름은 아직 부족/);
      const strongSignals={score:83,momentumPct:10,recent3Pct:5,turnoverRatio:1.3};
      const older={locationScore:{score:63},signals:strongSignals,buildingAge:28,weakest:{key:'product',points:4,maxPoints:10}};
      assert.match(title(older),/최근 흐름은 좋지만 오래된 연식은 약점이에요/);
      assert.match(title({...older,weakest:{key:'demand',points:12,maxPoints:30}}),/최근 흐름은 좋지만 입지·교육 조건은 아쉬워요/);
      assert.match(title({...older,weakest:{key:'demand',points:null,maxPoints:30,status:'missing'}}),/자료가 부족해 판단할 수 없어요/);
      assert.match(title({}, {partial:true}),/단지 조건은 좋지만 거래가 적어 최근 흐름은 판단할 수 없어요/);
      assert.match(title({}, {peakGuard:{atPeak:true}}),/좋지만 고점권 가격은 부담/);
      assert.match(title({}, {peakGuard:{atPeak:false}}),/좋지만 빠르게 오른 가격은 부담/);
      assert.match(title({signals:strongSignals}),/우선 검토/);
      for(const [changes,override] of [[{},{}],[older,{}],[{areaMatches:false},{}],[{}, {partial:true}],[{}, {peakGuard:{atPeak:true}}]]) {
        assert.doesNotMatch(title(changes,override),/[0-9]|만원|이하 매물|수리비|계산할 수 있는 상태|확인하세요|감안하세요/);
      }
    """)

def test_compact_peer_table_preserves_selection_metadata_and_unknowns():
    run_functions(PRICE_FUNCTIONS, PRICE_SETUP + r'''
      const item={name:'기준단지',legalDong:'화곡동',households:625,buildYear:2015,
       priceComparison:{status:'ready',method:'usual_gap',position:'high',averagePriceEok:9,
        currentGapPct:12.5,usualGapPct:5,shiftPp:7.5,periodMonths:6,throughMonth:'2026-08',
        areaLabel:'59㎡',region:'강서구',scope:'district',conditionsRelaxed:true,lowData:true,
        peers:[{name:'<A>',legalDong:'화곡동',households:500,approvalYear:2007,tier:2,
          averagePriceEok:8,transactionCount:5,lowData:true,distanceMeters:850,currentRatio:112.5,usualRatio:105,shiftPp:7.5}]}};
      const before=JSON.stringify(item),html=render(item);
      assert.match(html,/<table.*aria-label="비교 단지 시세"/s);
      assert.match(html,/59㎡ 최근 6개월/);
      assert.match(html,/화곡동 · 500세대 · 2007년 준공 · 직선 850m · 최근 5건/);
      assert.match(html,/&lt;A&gt;/);assert.doesNotMatch(html,/<A>|59㎡㎡/);
      assert.match(html,/최근 평균 가격은 강서구 단지 1곳과의 평소 가격 차이를 감안하면 비싸요/);
      assert.match(html,/세대수가 이 단지의 30% 이상, 준공연도 차이 15년 이내/);
      assert.match(html,/가까운 곳에 비교할 단지가 부족해 강서구로 넓혔어요/);
      assert.match(html,/세대수나 연식 차이가 큰 단지도 포함/);
      assert.match(html,/<details.*계산 근거 보기/s);
      assert.equal(JSON.stringify(item),before);
      const unknown=render(simple([{name:'이름만 확인된 단지',averagePriceEok:null,currentRatio:null,usualRatio:null}]));
      assert.match(unknown,/세대수 미확인/);assert.match(unknown,/준공연도 미확인/);
      assert.match(unknown,/거리 자료 없음/);assert.match(unknown,/자료 없음/);
      assert.doesNotMatch(unknown,/NaN|undefined|같은 준공|직선 0m|0세대|0년 준공/);
    ''')


def test_peer_price_gaps_use_own_same_period_average_and_explicit_signs():
    run_functions(PRICE_FUNCTIONS, PRICE_SETUP + r'''
      // The table now states how expensive the SELECTED complex is relative to each peer.
      // Ratios must use the same-period averages (10), never the latest single trade (99).
      const item=simple([{name:'높은 단지',averagePriceEok:11,currentRatio:10/11*100},
        {name:'낮은 단지',averagePriceEok:9,currentRatio:10/9*100},
        {name:'같은 단지',averagePriceEok:10,currentRatio:100}]);
      const html=render(item), row=name=>html.match(new RegExp(`<tr><th[^>]*>${name}[\\s\\S]*?</tr>`))[0];
      assert.match(html,/이 단지가 지금/);
      assert.match(html,/<tr class="is-own">.*초록.*10억/s);
      assert.match(row('높은 단지'),/11억.*9% 쌈/s);
      assert.match(row('낮은 단지'),/9억.*11% 비쌈/s);
      assert.match(row('같은 단지'),/10억.*비슷/s);
      assert.doesNotMatch(html,/99억/);
      const missingOwn=render({...item,priceComparison:{...item.priceComparison,averagePriceEok:null}});
      assert.doesNotMatch(missingOwn,/<table|NaN|0억/);
      const missingPeer=render(simple([{name:'미확인',averagePriceEok:null,currentRatio:null,diffPct:null}]));
      assert.match(missingPeer,/자료 없음/);assert.doesNotMatch(missingPeer,/NaN|Infinity|<td>0억|>0% 비쌈/);
      assert.match(render(simple([{name:'거의 같음',averagePriceEok:9.999,currentRatio:100.01}])),/거의 같음.*비슷/s);
      const history={...item,priceComparison:{...item.priceComparison,method:'usual_gap',shiftPp:10,
        currentGapPct:10,usualGapPct:-10,peers:[{name:'방향 전환',averagePriceEok:9,currentRatio:110,usualRatio:90,shiftPp:20}]}};
      assert.match(render(history),/10% 쌈 → 10% 비쌈/);
      history.priceComparison.peers[0].usualRatio=null;
      assert.match(render(history),/자료 없음 → 10% 비쌈/);
      assert.doesNotMatch(render(history),/NaN|Infinity/);
      // Missing historical/current values must not become zero-price or zero-height chart evidence.
      history.priceComparison.usualGapPct=null;
      history.priceComparison.currentGapPct=null;
      history.priceComparison.yearlyGaps=[{year:2024,gapPct:null},{year:2025,gapPct:0}];
      history.priceComparison.peers[0].shiftPp=null;
      const partial=render(history);
      assert.doesNotMatch(partial,/NaN|Infinity|zpr-price-years-usual|점선 평소|24년/);
      assert.match(partial,/25년 비슷/);
      assert.match(partial,/<td>자료 없음<\/td>/);
      for(const invalid of [null,undefined,'',NaN,Infinity,-100,-101]) {
        const unavailable=render(simple([{name:'비율 미확인',averagePriceEok:9,currentRatio:null,diffPct:invalid}]));
        assert.doesNotMatch(unavailable,/NaN|Infinity|% 쌈|% 비쌈/);
        assert.match(unavailable,/<td>자료 없음<\/td>/);
      }
      // Legacy current-only data has the opposite numerator, so invert it when forming this-complex wording.
      assert.match(render(simple([{name:'낮은 단지',averagePriceEok:9,diffPct:-10}])),/11% 비쌈/);

    ''')


def test_missing_nearby_peers_never_looks_like_cheap_or_neutral_price():
    run_functions([*PRICE_FUNCTIONS,'zippickSectionRatingData'], PRICE_SETUP + r'''
      for(const reasonCode of ['insufficient_nearby_peers','missing_comparison_coordinates','missing_building_criteria']) {
        const item={priceComparison:{status:'unavailable',reasonCode,reason:'가까운 비교단지가 부족해요.'}};
        const assessment=zippickPriceAssessment(item),html=render(item);
        assert.match(assessment.heading,/자료가 부족해 판단할 수 없어요/);
        assert.doesNotMatch(assessment.heading,/보통|저렴|싸요|적정/);
        assert.equal(zippickSectionRatingData(item,'가격 비교'),null);
        assert.match(html,/가까운 비교단지가 부족해요/);
        assert.doesNotMatch(html,/<table|NaN|0억/);
      }
      const currentOnly=simple([{name:'비교단지',averagePriceEok:10,currentRatio:100}]);
      assert.equal(zippickSectionRatingData(currentOnly,'가격 비교'),null,'simple comparisons must not acquire stars');
    ''')


def test_alternatives_never_expand_price_or_accept_unknown_area():
    run_functions(['zpNum', 'zippickReportPeers'], '''
      const candidateHeadlinePrice = () => ({priceEok:10});
      const candidateRowsForLookup = () => [];
      const peer = {name:'대안',apartmentId:'p',region:'강서구',latestDealDate:'2026-10-01',latestDealPriceEok:10,latestDealExclusiveArea:59};
      const item = {name:'기준',apartmentId:'s',region:'강서구',displayAreaLabel:'59㎡',peers:[peer]};
      assert.equal(zippickReportPeers(item).length,1);
      item.peers = [{...peer,latestDealPriceEok:13}];
      assert.equal(zippickReportPeers(item).length,0);
      item.peers = [{...peer,latestDealExclusiveArea:null}];
      assert.equal(zippickReportPeers(item).length,0);
      item.peers = [{...peer,latestDealExclusiveArea:84}];
      assert.equal(zippickReportPeers(item).length,0);
    ''')


def test_comparison_facts_and_differences_do_not_invent_missing_values():
    run_functions(['zpNum','zippickAlternativeDifferenceHtml','zippickTradeCountText',
                   'zippickSignalBarReason','zippickCommuteHtml'], r'''
      const esc=String,zippickCommuteGrade=()=> 'fair',zippickCommuteHeading=()=>'',zippickCommuteInsight=()=>'';
      const item={buildingAge:28,households:625};
      assert.match(zippickAlternativeDifferenceHtml(item,{buildingAge:25,households:500}),/3년 더 새 건물.*125세대 적음/);
      assert.match(zippickAlternativeDifferenceHtml(item,{}),/연식 미확인.*세대수 미확인/);
      for(const missing of [null,undefined,'']) {
        const signals={recentDealCount:missing,priorDealCount:10};
        assert.equal(zippickTradeCountText(signals),'');
        assert.doesNotMatch(zippickSignalBarReason({value:null},'turnover',signals),/0건/);
      }
      assert.match(zippickTradeCountText({recentDealCount:0,priorDealCount:10}),/최근 6개월 거래는 0건/);
      assert.match(zippickTradeCountText({recentDealCount:3,priorDealCount:10}),/최근 6개월 거래는 3건.*그 전 6개월 10건/);
      const commute=zippickCommuteHtml({commuteProfile:{station:'우장산',walkMinutes:6,estimated:true,hubs:{여의도:{totalMinutes:30}}}});
      assert.match(commute,/우장산역.*도보 6분/);assert.match(commute,/도보 포함.*추정/);
    ''')


def test_report_refreshes_collected_location_without_changing_price_cohort():
    run_functions(["zippickRefreshReportLocation"], """
      const price={key:'price',score:30,maxPoints:30,coverage:1};
      const oldDemand={key:'demand',score:null,maxPoints:30,coverage:0};
      const product={key:'product',score:60,maxPoints:10,coverage:1};
      const item={apartmentId:'exact',name:'동일이름',region:'마포구',latestDealPriceEok:17,
        locationScore:{score:38,parts:[price,oldDemand,product]},signals:{score:55}};
      const demand={key:'demand',score:90,maxPoints:30,coverage:1,details:[
        {key:'station',status:'ok',score:100,reason:'공덕역 · 직선 159m'},
        {key:'education',status:'ok',score:80,reason:'주변 학교'}]};
      const report={apartmentId:'exact',locationScore:{score:99,parts:[{...price,score:99},demand]},
        latestDealPriceEok:20,signals:{score:99},nearestStationDistance:159.1,
        educationEnvironment:{status:'ok',elementaryDistanceMeters:250,basis:'nearby_school_access'}};
      zippickRefreshReportLocation(item,report);
      assert.strictEqual(item.locationScore.parts[0],price);
      assert.strictEqual(item.locationScore.parts[2],product);
      assert.strictEqual(item.locationScore.parts[1],demand);
      assert.equal(item.locationScore.score,60);
      assert.equal(item.locationScore.coverage,1);
      assert.equal(item.latestDealPriceEok,17);assert.equal(item.signals.score,55);
      assert.equal(item.nearestStationDistance,159.1);
      assert.equal(item.educationEnvironment.elementaryDistanceMeters,250);
      const saved=item.locationScore;
      zippickRefreshReportLocation(item,{...report,apartmentId:'different'});
      assert.strictEqual(item.locationScore,saved);
      const noId={...item,apartmentId:''};
      zippickRefreshReportLocation(noId,{...report,apartmentId:''});
      assert.strictEqual(noId.locationScore,saved);
    """)


def test_distance_refresh_keeps_the_buyers_existing_commute_metric():
    run_functions(["zippickRefreshReportLocation"], """
      const commute={key:'commute',score:20,maxPoints:8,status:'ok',reason:'입력한 직장권'};
      const item={apartmentId:'same',locationScore:{parts:[{key:'demand',score:20,maxPoints:30,coverage:1,details:[commute]}]}};
      const fresh={apartmentId:'same',locationScore:{parts:[{key:'demand',score:100,maxPoints:30,details:[
        {key:'commute',score:100,maxPoints:8,status:'ok'},
        {key:'station',score:100,maxPoints:5,status:'ok'},
        {key:'education',score:100,maxPoints:4,status:'ok'}]}]}};
      zippickRefreshReportLocation(item,fresh);
      const part=item.locationScore.parts[0];
      assert.strictEqual(part.details[0],commute);
      assert.equal(part.score,62);assert.equal(part.points,18.6);
      assert.equal(item.locationScore.score,62);
    """)
