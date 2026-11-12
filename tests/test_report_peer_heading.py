"""Completed peer comparisons must not be described as missing comparisons."""
import json
from pathlib import Path

import pytest

from test_common_purchase_verdict import run


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/dmc_peer_comparison_20261111.json').read_text())


def test_dmc_report_uses_completed_comparison_in_heading_and_table():
    run('const item=' + json.dumps(FIXTURE['report'], ensure_ascii=False) + r''';
const result=verdict(item);
assert.equal(item.apartmentId,'11410120327177');
assert.equal(item.priceComparison.peers.length,2);
assert.deepEqual(item.priceComparison.peers.map(p=>p.transactionCount),[3,2]);
assert.equal(result.priceSource,'usual_gap');
assert.equal(result.price,'similar');
assert.equal(result.scores.price,3);
assert.equal(result.stars,3);
assert.equal(result.priceRatingCapped,true);
assert.equal(result.reviewHeadline,'단지 조건은 좋고 비교 가격은 평소 수준이지만, 비교 단지의 거래가 적어요. 매수는 신중히 검토하세요.');
assert.match(result.priceTitle,/서대문구 내 비슷한 단지와 비교하면 평소 수준/);
assert.doesNotMatch(result.reviewHeadline,/비교할 단지가 부족|판단할 수 없/);
assert.match(result.basis,/서대문구 내 다른 단지까지 비교/);
assert.match(result.basis,/자료 적음/);
const esc=String, candidateDisplayName=item=>item.displayName||item.name;
const html=zippickPriceComparisonHtml(item,result.peerPriceAssessment);
for(const value of ['힐스테이트 신촌','홍제역 해링턴플레이스','최근 3건','최근 2건','9% → 17% 쌈','5% → 10% 비쌈'])
  assert.ok(html.includes(value),value);
assert.match(html,/최근 거래가 있는 2곳/);
const header=zippickOverallRatingHtml(result,result.label);
const heading=header.match(/<h3 class="zpr-overall-opinion">(.*?)<\/h3>/s)[1];
assert.equal(heading.replace(/<[^>]+>/g,''),result.reviewHeadline.replace(' 매수는 신중히 검토하세요.',''));
assert.match(header,/zpr-verdict-tag is-conditional/);
''', ['zippickPriceComparisonHtml', 'zippickPriceSelectionTier', 'zippickOverallRatingHtml'])


@pytest.mark.parametrize('region', ['서대문구', '강서구', '남양주시'])
@pytest.mark.parametrize('shift,meaning', [(-4, '평소보다 낮지만'), (0, '평소 수준이지만'), (4, '비싸요')])
def test_completed_district_comparisons_keep_price_conclusion_and_actual_limits(region, shift, meaning):
    run(f'''
const item=base();
Object.assign(item.priceComparison,{{scope:'district',region:'{region}',shiftPp:{shift},lowData:true,
 peers:[3,2].map(transactionCount=>({{tier:1,transactionCount,lowData:true,
 yearlyRatios:{{'2024':95,'2025':98}}}}))}});
const result=verdict(item);
assert.equal(result.priceSource,'usual_gap');
assert.equal(result.stars,3);
assert.ok(result.reason.includes('{meaning}'));
assert.doesNotMatch(result.reviewHeadline,/비교할 단지가 부족|가격을 판단할.*부족/);
assert.match(result.basis,/다른 단지의 거래가 적어요/);
assert.ok(result.priceTitle.includes('{region} 내 비슷한 단지'));
assert.match(result.basis,/자료 적음/);
''')


def test_history_limit_is_distinct_from_missing_peers_and_scope_only():
    run('''
const item=base();Object.assign(item.priceComparison,{scope:'district',shiftPp:0,
 peers:[0,1].map(tier=>({tier,transactionCount:8,yearlyRatios:{'2025':95}}))});
let result=verdict(item);
assert.equal(result.stars,3);
assert.match(result.reviewHeadline,/과거 가격 차이 자료가 적어요/);
assert.doesNotMatch(result.reviewHeadline,/비교할 단지가 부족/);
for(const peer of item.priceComparison.peers)peer.yearlyRatios['2024']=98;
result=verdict(item);
assert.equal(result.stars,4);
assert.equal(result.priceRatingCapped,false);
assert.match(result.basis,/자료 적음/);
assert.match(result.basis,/다른 단지까지 비교/);
item.priceComparison={status:'unavailable',reasonCode:'insufficient_peers'};
result=verdict(item);
assert.equal(result.stars,null);
assert.equal(result.scores.price,null);
assert.match(result.reason,/자료가 부족/);
assert.doesNotMatch(result.reviewHeadline,/비교 가격은 평소 수준/);
''')
