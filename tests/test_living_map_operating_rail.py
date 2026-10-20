"""Rail names appear by default, including planned stops and crowded maps."""
import re
import subprocess
from pathlib import Path


def test_operating_rail_label_and_connection_survive_neighbourhood_cards():
    html = (Path(__file__).parents[1] / '앱화면/real-estate-search.html').read_text()
    basis = re.search(r'    function zippickLivingStationBasis\(station\) \{.*?\n    \}', html, re.S).group()
    basis = re.search(r'    function zippickRailUnderReview\(project = \{\}\) \{.*?\n    \}', html, re.S).group() + basis
    declutter = html.split('      const declutter = () => {', 1)[1].split('      kakao.maps.event.addListener(map,"idle",declutter);', 1)[0]
    script = basis + r'''
const assert = require('node:assert/strict');
assert.equal(zippickLivingStationBasis({serviceStatus:'operating',scoringEligible:false}),'운행 중');
assert.match(zippickLivingStationBasis({serviceStatus:'planned',scoringEligible:false}),/지도 참고점/);
for (const width of [300, 700]) {
  const height=430, center={lat:0,lng:0};
  const closestRailStation={latitude:10,longitude:11,serviceStatus:'operating'};
  const stations=[closestRailStation,
    {latitude:10,longitude:11,serviceStatus:'planned',name:'창동역 · GTX-C'},
    {latitude:11,longitude:12,serviceStatus:'planned',name:'지도 가장자리 역'},
    {latitude:12,longitude:13,serviceStatus:'planned',name:'화면 밖 역'}];
  const stationPoint={lat:10,lng:11};
  const xy={x:width/2-40,y:height/2-30};
  const map={getLevel:()=>4,getProjection:()=>({containerPointFromCoords:p=>p.lat===10 ? xy
    : p.lat===11 ? {x:width-2,y:2} : p.lat===12 ? {x:width+40,y:200} : {x:width/2,y:height/2}})};
  const mapElement={clientWidth:width,clientHeight:height,getBoundingClientRect:()=>({left:0,top:0}),querySelector:()=>null};
  const layer=()=>({map:null,setMap(value){this.map=value;},setPosition(){}});
  const item=layer(), distanceLine=layer();
  const label={offsetWidth:175,offsetHeight:50,style:{}};
  const overlays=[{item,label,project:closestRailStation,distanceLine,keepDistanceLine:true},
    ...stations.slice(1).map(project=>({item:layer(),label:{offsetWidth:175,offsetHeight:50,style:{}},
      project,distanceLine:layer()}))];
  const dongOverlays=[{item:layer(),card:{style:{}},positions:[stationPoint],rowCount:2}];
  const routes=[], points=[];
  const kakao={maps:{LatLng:class {constructor(lat,lng){this.lat=lat;this.lng=lng;}}}};
''' + 'const declutter = () => {' + declutter + r'''
  declutter();
  assert.equal(item.map,map,'가까운 GTX 역 이름을 동네 카드보다 먼저 배치해야 한다');
  assert.equal(distanceLine.map,map,'단지에서 GTX 역까지 연결선을 유지해야 한다');
  for (const entry of overlays.slice(0,3)) {
    assert.equal(entry.item.map,map,'화면 안 모든 철도역은 누르기 전부터 이름 태그를 보여야 한다');
    assert.equal(entry.distanceLine.map,map);
    assert.ok(entry.label.style.transform);
  }
  assert.equal(overlays[3].item.map,null,'화면 밖 역은 억지로 화면 안으로 가져오지 않는다');
  assert.ok(label.style.transform,'단지 이름과 겹치지 않도록 역 이름을 옮겨야 한다');
}
'''
    result = subprocess.run(['node'], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_report_map_only_exposes_stations_within_two_kilometers():
    html = (Path(__file__).parents[1] / '앱화면/real-estate-search.html').read_text()
    selection = re.search(r'      const stations = \(data.stations.*?;', html, re.S).group()
    script = r'''
const assert = require('node:assert/strict');
const data={stations:[0,703,933,2000,2001,2255,2975,null,undefined,-1,NaN,Infinity]
  .map(distanceMeters=>({distanceMeters}))};
''' + selection + r'''
assert.deepEqual(stations.map(station=>station.distanceMeters),[0,703,933,2000]);
'''
    result = subprocess.run(['node'], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
