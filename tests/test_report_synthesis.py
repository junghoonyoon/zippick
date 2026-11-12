"""Headline facts retain their source state and do not change purchase ratings."""
from test_common_purchase_verdict import run


def test_summary_keeps_age_caution_and_both_price_judgments():
    run("""
const item=base();item.buildingAge=28;item.locationScore.parts[1].details[1].score=25;
item.households=2231;
const [station, school]=item.locationScore.parts[0].details;
station.reason='창동역 4호선 · 직선 500m';school.reason='서울자운초등학교 · 156m 거리';
item.locationScore.parts[1].details[0].score=90;
item.commuteProfile={hubs:{강남:{totalMinutes:19}}};
let v=verdict(item);
assert.equal(v.summary,'2,231세대 대단지이고, 창동역까지 직선 500m, 서울자운초등학교까지 직선 156m로 역과 학교가 가까워요. 다만 28년차 연식은 약점이에요');
assert.doesNotMatch(v.summary,/19분/);
assert.deepEqual(v.summaryFactors.map(f=>f.key),['location','age']);
assert.ok(v.title.startsWith(v.priceTitle+'. '));
assert.ok(v.title.endsWith(v.summary));
item.signals={status:'ok',momentumPct:12,turnoverRatio:.2,recentDealCount:3,priorDealCount:15};
assert.match(verdict(item).tradeEvidence,/최근 6개월 거래가 직전 6개월 15건에서 3건으로 줄었어요/);
assert.match(verdict(item).summary,/28년차 연식은 약점이에요/);
item.locationScore.parts[0].details[0]={key:'station',score:100,status:'missing'};
assert.doesNotMatch(verdict(item).summary,/창동역|역과 학교가 가까|역 접근성이 좋/);
""")


def test_liquidity_uses_the_same_monthly_history_and_ignores_unavailable_states():
    run("""
const item=base();delete item.signals;
for(const metric of item.locationScore.parts[0].details.slice(0,2)) metric.score=70;
const history=count=>({status:'ready',months:Array.from({length:12},(_,i)=>({period:`2025-${String(i+1).padStart(2,'0')}`,price:i<6?10:8,count:i<6?10:count}))});
item.liquidityHistory=history(10);
assert.equal(zippickLiquidityStat(item).band,'strong');
assert.match(verdict(item).summary,/과거 하락기에도 거래가 유지/);
item.liquidityHistory=history(2);
assert.equal(zippickLiquidityStat(item).band,'weak');
assert.match(verdict(item).summary,/과거 하락기에는 거래가 평소의 40% 미만/);
for(const status of ['error','unavailable','pending']) {
 item.liquidityHistory.status=status;
 assert.doesNotMatch(verdict(item).summary,/하락기/);
}
""")


def test_development_requires_matching_identity_official_evidence_and_known_stage():
    run("""
const item=base();item.apartmentId='a';delete item.signals;
for(const metric of item.locationScore.parts[0].details.slice(0,2)) metric.score=70;
const project={stage:'construction',contributionScore:2,sourceUrl:'https://www.molit.go.kr/news?id=1'};
item.futureTransformation={apartmentId:'a',modelVersion:'living-area-v2-beta',status:'ready',
 planRating:{version:'living-area-plan-v9-beta',status:'ready',score:4,components:{transport:{inputs:[project]}}}};
const before=verdict(item);
assert.match(before.summary,/교통 개선 공사가 진행 중/);
assert.doesNotMatch(before.summary,/개통됐|집값.*오르/);
item.futureTransformation.apartmentId='b';assert.doesNotMatch(verdict(item).summary,/교통 개선/);
item.futureTransformation.apartmentId='a';project.sourceUrl='https://blog.example.com/rumor';
assert.doesNotMatch(verdict(item).summary,/교통 개선/);
project.sourceUrl='https://www.molit.go.kr/news?id=1';project.stage='planning';
assert.match(verdict(item).summary,/계획은 아직 초기 단계/);
item.futureTransformation.status='stale';assert.doesNotMatch(verdict(item).summary,/개선 공사|초기 단계/);
const after=verdict(item);assert.equal(after.stars,before.stars);assert.equal(after.reason,before.reason);assert.equal(after.priceTitle,before.priceTitle);
""")


def test_fixed_hub_access_and_missing_market_data_are_not_personal_or_negative_guesses():
    run("""
const item=base();delete item.signals;
for(const metric of item.locationScore.parts[0].details.slice(0,2)) metric.score=70;
item.commuteProfile={hubs:{강남:{totalMinutes:18},여의도:{totalMinutes:40},광화문:{totalMinutes:50}}};
assert.match(verdict(item).summary,/강남까지 예상 18분/);
const original=verdict(item);
item.policyImpact={requiredCashEok:50};item.commuteAccessScore=0;
assert.equal(verdict(item).title,original.title);
item.commuteProfile.hubs={강남:{totalMinutes:65},여의도:{totalMinutes:70},광화문:{totalMinutes:85}};
assert.match(verdict(item).summary,/주요 업무지구까지 예상 1시간/);
delete item.commuteProfile;
item.signals={status:'error',momentumPct:10,turnoverRatio:.1,recentDealCount:2,priorDealCount:20};
assert.doesNotMatch(verdict(item).summary,/거래.*줄|가격은 올/);
""")


def test_summary_distinguishes_uneven_station_and_school_access():
    run("""
const item=base();
const [station, school]=item.locationScore.parts[0].details;
item.households=180;
station.reason='창신역 6호선 · 직선 326m';
Object.assign(school,{score:40,reason:'서울명신초등학교 · 1,120m 거리'});
assert.equal(verdict(item).summary,'180세대 소단지이고, 창신역까지 직선 326m로 가까워요. 다만 서울명신초등학교까지 직선 1,120m로 학교와 거리가 있어요');
delete item.households;
item.locationScore.parts[1].details[0].reason='919세대 · 500~999세대 구간';
Object.assign(school,{score:80,reason:'서울명신초등학교 · 264m 거리'});
Object.assign(station,{score:30,reason:'창신역 6호선 · 직선 1,137m'});
assert.equal(verdict(item).summary,'919세대 중간 규모 단지이고, 서울명신초등학교까지 직선 264m로 가까워요. 다만 창신역까지 직선 1,137m로 역이 먼 편이에요');
station.score=55;
station.reason='창신역 6호선 · 직선 869m';
assert.match(verdict(item).summary,/역 접근성은 보통이에요/);
station.status='missing';
assert.doesNotMatch(verdict(item).summary,/창신역|역은 멀어요|역과 학교가 가까워요/);
item.locationScore.parts[1].details[0].status='missing';
assert.match(verdict(item).summary,/^세대수는 확인되지 않았고, 서울명신초등학교까지 직선 264m로 가까워요/);
school.reason='서울명신초등학교 · 1,120m 거리';
assert.doesNotMatch(verdict(item).summary,/초등학교.*가까워요/);
""")
