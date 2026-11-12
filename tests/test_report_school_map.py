import subprocess
from pathlib import Path


def test_school_map_uses_matching_school_and_keeps_station_in_bounds():
    html = (Path(__file__).parents[1] / '앱화면/real-estate-search.html').read_text()
    school_fn = html.split('    async function mountZippickReportSchoolDistance(', 1)[1].split('\n    function setZippickReportZoneState', 1)[0]
    script = r'''
const assert = require('assert');
const overlays = [], lines = [], boundsSet = [];
const document = {createElement: () => ({setAttribute() {}})};
let rows = [];
class LatLng { constructor(lat, lng) { this.lat=lat; this.lng=lng; } }
class LatLngBounds { constructor() { this.points=[]; } extend(p) { this.points.push(p); } }
class Places { keywordSearch(name, callback) { callback(rows, 'OK'); } }
const kakao = {maps:{LatLng, LatLngBounds, services:{Places, Status:{OK:'OK'}, SortBy:{DISTANCE:'distance'}},
 Polyline:class { constructor(opts) {lines.push(opts)} setZIndex() {} },
 CustomOverlay:class { constructor(opts) {overlays.push(opts)} setZIndex() {} }}};
const map = {setBounds(b) {boundsSet.push(b.points)}};
const element = {isConnected:true, dataset:{zprMapState:'ready'}};
const apartment = new LatLng(37.5,127), station = new LatLng(37.501,127.001);
const item = {educationEnvironment:{elementarySchoolNames:['가나다초등학교'], elementaryDistanceMeters:325}};
async function mountZippickReportSchoolDistance(''' + school_fn + r'''
(async () => {
 rows = [{place_name:'다른초등학교', category_name:'학교 > 초등학교', x:'127.01', y:'37.5', distance:'325'},
         {place_name:'가나다초등학교', category_name:'학교 > 초등학교', x:'127.002', y:'37.501', distance:'320'}];
 await mountZippickReportSchoolDistance(element,map,kakao,item,apartment,station);
 assert.equal(overlays.length,1); assert.equal(overlays[0].content.textContent,'가나다초등학교 · 직선 325m');
 assert.deepEqual(boundsSet[0],[apartment,station,overlays[0].position]);
 assert.deepEqual(lines[0].path,[apartment,overlays[0].position]);
 rows = [{place_name:'가나다초등학교', category_name:'학교 > 초등학교', x:'127.1', y:'37.6', distance:'4000'}];
 await mountZippickReportSchoolDistance(element,map,kakao,item,apartment,station);
 await mountZippickReportSchoolDistance(element,map,kakao,{educationEnvironment:{}},apartment,station);
 assert.equal(overlays.length,1);
})().catch(error => {console.error(error); process.exit(1)});
'''
    subprocess.run(['node', '-e', script], check=True)
