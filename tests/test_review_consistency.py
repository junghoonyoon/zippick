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
    run_functions(["ensureZippickReportPeers"], """
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


def test_market_reversals_name_both_time_windows_and_missing_is_not_down():
    run_functions(["zpNum", "zpPct", "zippickMarketVerdict", "zippickMarketEvidenceText"], """
      const rebound={signals:{momentumPct:-2.7,recent3Pct:4.1,turnoverRatio:1.67}};
      assert.match(zippickMarketVerdict(rebound).heading,/6개월.*하락.*3개월.*반등/);
      assert.match(zippickMarketEvidenceText(rebound),/2.7% 내렸.*3개월.*4.1% 올랐/);
      assert.match(zippickMarketVerdict({signals:{momentumPct:4,recent3Pct:-2,turnoverRatio:1.1}}).heading,/6개월.*상승.*3개월.*하락/);
      assert.match(zippickMarketVerdict({signals:{momentumPct:-4,recent3Pct:null,turnoverRatio:1}}).heading,/6개월.*그 전 6개월/);
      assert.match(zippickMarketVerdict({signals:{momentumPct:null,turnoverRatio:1}}).heading,/판단할 수 없어요/);
    """)


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
      refreshAptSearchTrendCandidate({...selected,locationScore:{score:81}});
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
    run_functions(["zpNum", "zippickPriceAssessment", "zippickPricePeerListHtml"], """
      const esc=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
      const transactionMoney=value=>`${value}억`;
      const zippickHasPriceComparison=()=>true;
      const comparison={status:'reference',position:'high',averagePriceEok:9,peerAveragePriceEok:8,
        differencePct:12.5,periodMonths:6,throughMonth:'2026-08',selectionMethod:'expanded',areaLabel:'59㎡',region:'강서구',
        peers:[{name:'<A>',legalDong:'화곡동',averagePriceEok:8,transactionCount:5,
          distanceMeters:850,similarities:['같은 동네','비슷한 면적'],differences:['8년 더 오래됨','100세대 적음']} ]};
      const assessment=zippickPriceAssessment({priceComparison:comparison});
      assert.equal(assessment.heading,'강서구 비교 단지 1곳보다 평균 실거래가가 12.5% 높아요.');
      assert.equal(zippickPriceAssessment({priceComparison:{...comparison,status:'ready',differencePct:-4}}).heading,'강서구 비교 단지 1곳보다 평균 실거래가가 4.0% 낮아요.');
      assert.match(zippickPriceAssessment({priceComparison:{...comparison,differencePct:0}}).heading,/평균 실거래가가 같아요/);
      assert.doesNotMatch(assessment.heading,/아쉬워요|참고 비교에서|시세가/);
      const html=zippickPricePeerListHtml(assessment);
      assert.match(html,/<table.*비교단지 선정 이유와 가격/s);
      assert.match(html,/주변 단지 가격 참고 1곳/);
      assert.match(html,/2026.08까지 6개월/);
      assert.match(html,/화곡동 · 59㎡/);
      assert.match(html,/직선 850m · 8년 더 오래됨 · 100세대 적음/);
      assert.doesNotMatch(html,/비슷한 면적<|다른 동네|<td>[^<]*<small>/);
      assert.match(html,/8년 더 오래됨 · 100세대 적음/);
      assert.match(html,/8억.*5건/s);
      assert.match(html,/&lt;A&gt;/);
      assert.doesNotMatch(html,/<A>|59㎡㎡/);
      assert.match(html,/<details.*비교단지를 고른 기준/s);
      const old=zippickPricePeerListHtml({comparisonPeers:[{name:'이름만 확인된 단지'}]});
      assert.match(old,/거리 미확인 · 연식 미확인 · 세대수 미확인/);
      assert.doesNotMatch(old,/같은 동네|비슷한 면적|같은 준공/);
      const uniform=zippickPricePeerListHtml({comparisonPeers:[
        {name:'동일 조건',distanceMeters:2839,similarities:['같은 세대수','같은 준공연도']},
        {name:'연식 누락',distanceMeters:500,differences:['1,000세대 많음']},
        {name:'거리 누락',differences:['146세대 적음','1년 더 새 건물']},
      ]});
      assert.match(uniform,/직선 2,839m · 같은 준공연도 · 같은 세대수/);
      assert.match(uniform,/직선 500m · 연식 미확인 · 1,000세대 많음/);
      assert.match(uniform,/거리 미확인 · 1년 더 새 건물 · 146세대 적음/);
      const criteriaOnly=zippickPricePeerListHtml({comparisonCriteria:{region:'강서구',householdsMin:500,householdsMax:750,ageMin:23,ageMax:33}});
      assert.match(criteriaOnly,/선정 기준: 강서구 · 500~750세대 · 23~33년차/);
      assert.doesNotMatch(criteriaOnly,/<table/);
      assert.equal(zippickPricePeerListHtml({}), '');
    """)


def test_peer_price_gaps_use_own_same_period_average_and_explicit_signs():
    run_functions(["zpNum", "zippickPricePeerListHtml"], r"""
      const esc=String;
      const assessment={comparisonOwnName:'초록',comparisonOwnAveragePriceEok:10,
        comparisonPeers:[{name:'높은 단지',averagePriceEok:11},{name:'낮은 단지',averagePriceEok:9},{name:'같은 단지',averagePriceEok:10}]};
      const html=zippickPricePeerListHtml(assessment);
      assert.match(html,/초록 평균 대비 \+높음 \/ −낮음/);
      assert.match(html,/class="zpr-peer-gap is-higher"[^>]*>\+10.0%<\/span>/);
      assert.match(html,/class="zpr-peer-gap is-lower"[^>]*>−10.0%<\/span>/);
      assert.match(html,/class="zpr-peer-gap is-equal"[^>]*>0.0%<\/span>/);
      assert.match(html,/aria-label="초록 평균 대비 −10.0% 낮음"/);
      const missing=zippickPricePeerListHtml({...assessment,comparisonOwnAveragePriceEok:null});
      assert.doesNotMatch(missing,/zpr-peer-gap|평균 대비/);
      const missingPeer=zippickPricePeerListHtml({...assessment,comparisonPeers:[{name:'미확인',averagePriceEok:null}]});
      assert.doesNotMatch(missingPeer,/class="zpr-peer-gap/);
      const tiny=zippickPricePeerListHtml({...assessment,comparisonPeers:[{name:'거의 같음',averagePriceEok:9.999}]});
      assert.match(tiny,/is-equal[^>]*>0.0%/);
      assert.doesNotMatch(tiny,/−0.0%|is-lower/);
    """)


def test_missing_nearby_peers_never_looks_like_cheap_or_neutral_price():
    run_functions(["zpNum", "zippickPriceAssessment", "zippickSectionRatingData", "zippickPricePeerListHtml"], """
      const esc=String,transactionMoney=value=>`${value}억`;
      const zippickHasPriceComparison=()=>false;
      const candidateHeadlinePrice=()=>({priceEok:8.5,label:'평균 실거래'});
      const criteria={region:'강서구',maxDistanceMeters:1000,householdsMin:500,householdsMax:750,ageMin:23,ageMax:33};
      for(const reasonCode of ['insufficient_nearby_peers','missing_comparison_coordinates','missing_building_criteria']) {
        const item={priceComparison:{status:'unavailable',reasonCode,reason:'가까운 비교단지가 부족해요.',selectionCriteria:criteria}};
        const assessment=zippickPriceAssessment(item);
        assert.match(assessment.heading,/가격 비교는 보류/);
        assert.doesNotMatch(assessment.heading,/보통|낮아요|싸요/);
        assert.equal(zippickSectionRatingData(item,'가격 비교'),null);
        assert.match(zippickPricePeerListHtml(assessment),/반경 1,000m.*500~750세대/);
      }
    """)


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
    run_functions(['zpNum', 'zippickComparisonFactsHtml', 'zippickAlternativeDifferenceHtml'], '''
      const esc = value => String(value);
      assert.match(zippickComparisonFactsHtml({}), /거래 건수 미확인/);
      assert.doesNotMatch(zippickComparisonFactsHtml({}), /3개월 0건/);
      const item={buildingAge:28,households:625};
      assert.match(zippickAlternativeDifferenceHtml(item,{buildingAge:25,households:500}), /3년 더 새 건물.*125세대 적음/);
      assert.match(zippickAlternativeDifferenceHtml(item,{}), /연식 미확인.*세대수 미확인/);
      const facts=zippickComparisonFactsHtml({...item,commuteProfile:{station:'우장산',walkMinutes:6,estimated:true},signals:{recent3DealCount:3,comparisonBasis:{recent3Start:'2026-07',recent3End:'2026-09'}}});
      assert.match(facts,/도보 약 6분 · 추정/);
      assert.match(facts,/3개월 3건/);
    ''')
