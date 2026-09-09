// Run with: node --test tests/test_chart_analysis.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../앱화면/real-estate-search.html'), 'utf8');
const extract = name => {
  const start = html.indexOf(`    function ${name}(`);
  assert.ok(start >= 0, name);
  const end = html.indexOf('\n    function ', start + 1);
  return html.slice(start, end);
};
const ctx = vm.createContext({
  sparklineLatestValue: values => values?.filter(Number.isFinite).at(-1),
  candidateSparklineTemperaturePeriod: () => '최근 2년',
});
for (const name of ['sparklineMonthOrdinal','readableSparklinePeriod','sparklineFinitePoints','trendSpanLabel','candidateTrendLongTerm','candidateTrendBenchmarks','candidateTrendTopLeader','candidateTrendGapDirection','candidateTrendComparisonLabel','candidateTrendReading']) vm.runInContext(extract(name),ctx);
const item = {region:'노원구',signals:{leaderRegion:'상계동',districtLeaderRegion:'노원구'}};
const fixture = () => ({complex:[100,101,102,103,104,105,106,107,108,112.1],region:[100,100,101,102,103,104,105,106,107,108],leader:[100,102,104,108,110,112,118,122,126,131],districtLeader:Array(10).fill(140),counts:Array(10).fill(2)});
test('all inline JavaScript parses',()=>{for(const match of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))new Function(match[1]);});
test('example uses two lines and local leader even when district grew more',()=>{
 const result=ctx.candidateTrendReading(item,fixture(),'rise_continuing');
 assert.equal(result.headline,'전반적인 상승 흐름');
 assert.equal(result.comparison,'최근 2년 가격 변화율 · 노원구 평균보다 높음 · 상계동 대장보다 낮음');
 assert.match(result.note,/상계동 대장과의 상승률 차이가 커졌어요/);
});
test('district leader fallback and absent comparisons',()=>{
 const series=fixture();series.leader=null;
 assert.match(ctx.candidateTrendReading(item,series,'flat').comparison,/노원구 대장보다 낮음/);
 series.districtLeader=null;series.region=null;
 assert.match(ctx.candidateTrendReading(item,series,'flat').comparison,/지역 평균 비교 자료 부족 · 대장 비교 자료 부족/);
});
test('sparse and stale data take priority over upbeat patterns',()=>{
 const series=fixture();series.counts=[1,1];
 assert.equal(ctx.candidateTrendReading(item,series,'surge').headline,'거래가 적어 흐름 판단 어려움');
 assert.equal(ctx.candidateTrendReading(item,series,'stale').headline,'최근 거래 뜸함');
 assert.equal(ctx.candidateTrendGapDirection(series,{values:series.leader}),'unknown');
});
test('all supported patterns have a short standard title',()=>{
 for(const kind of ['surge','fast_rise','sharp_drop','fast_fall','rise_continuing','rise','rise_slowing','rebound','downturn','fall_continuing','fall','fall_slowing','volatile','mixed','flat','high_flat','low_flat','near_high','near_low']) {
  const result=ctx.candidateTrendReading(item,fixture(),kind);
  assert.notEqual(result.headline,'흐름 판단 어려움');assert.ok(result.headline.length<=26,kind);
 }
});
test('comparison boundaries are symmetric, including falling markets',()=>{
 assert.equal(ctx.candidateTrendComparisonLabel(1.5,'평균'),'평균보다 높음');
 assert.equal(ctx.candidateTrendComparisonLabel(-1.5,'평균'),'평균보다 낮음');
 assert.equal(ctx.candidateTrendComparisonLabel(-1.49,'평균'),'평균과 비슷');
 const series=fixture();series.complex[9]=90;series.region[9]=85;
 assert.match(ctx.candidateTrendReading(item,series,'fall_continuing').comparison,/평균보다 높음/);
});
test('missing final comparison month is not compared to a different month',()=>{
 const series=fixture();series.leader[9]=null;
 assert.match(ctx.candidateTrendReading(item,series,'rise_continuing').comparison,/대장 비교 자료 부족/);
});
test('gap narrowing, stable and insufficient windows remain distinct',()=>{
 const series=fixture();
 const leader={values:Array(10).fill(120)};
 assert.equal(ctx.candidateTrendGapDirection(series,leader),'narrowing');
 leader.values=series.complex.map(value=>value+10);
 assert.equal(ctx.candidateTrendGapDirection(series,leader),'steady');
 leader.values=leader.values.map((value,index)=>index<3?null:value);
 assert.equal(ctx.candidateTrendGapDirection(series,leader),'unknown');
});

const longSeries = values => ({complex:values, counts:values.map(value => value === null ? 0 : 2), periods:values.map((_,index)=>{const month=2024*12+9+index;return `${Math.floor(month/12)}${String(month%12+1).padStart(2,'0')}`;})});
test('two year rise and pullback is not renamed rebound after one up tick',()=>{
 const values=[107,100,null,100.3,99,101,102,102,101,100.5,102,106,107,108,109,110,114,115,118,131,128.5,129.4];
 const series=longSeries(values);
 assert.equal(ctx.candidateTrendLongTerm(series).kind,'rise_pullback');
 assert.equal(ctx.candidateTrendReading(item,series,'rebound').headline,'크게 오른 뒤 고점 아래에서 등락 중');
 assert.match(ctx.candidateTrendReading(item,series,'rebound').note,/최근 2년간 전체 거래 흐름 기준/);
 series.complex[21]=128;
 assert.equal(ctx.candidateTrendLongTerm(series).kind,'rise_pullback');
 assert.notEqual(ctx.candidateTrendReading(item,series,'downturn').headline,'상승 후 하락');
});
test('long term shapes describe both the major move and current position',()=>{
 const cases=[
  [[100,105,110,118,125,130,125,130], 'rise_recovered'],
  [[100,105,110,118,125,130,130,130], 'rise_plateau'],
  [[100,102,106,112,120,125,128,130], 'rise_high'],
  [[130,128,120,115,108,100,105,110], 'fall_recovering'],
  [[130,128,120,110,100,110,125,130], 'fall_recovered'],
  [[130,128,120,115,108,100,100,100], 'fall_near_low'],
  [[100,100,101,100,102,101,100,101], 'flat'],
  [[100,105,110,118,125,130,119,118], 'rise_falling'],
  [[100,102,106,112,120,125,105,100], 'rise_then_fall'],
  [[100,102,106,112,120,125,100,106], 'rise_fall_recovery'],
  [[100,110,100,110,100,110,100,110], 'volatile'],
 ];
 for(const [values,expected] of cases) assert.equal(ctx.candidateTrendLongTerm(longSeries(values)).kind,expected,JSON.stringify(values));
});
test('short observation coverage is not described as a full two years',()=>{
 const short=longSeries([100,102,104,110,115]);
 assert.equal(ctx.candidateTrendLongTerm(short),null);
 const halfYear=longSeries([100,103,105,110,120,122]);
 assert.doesNotMatch(ctx.candidateTrendReading(item,halfYear,'rise').note,/최근 2년간/);
});
