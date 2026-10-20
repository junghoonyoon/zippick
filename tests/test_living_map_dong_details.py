"""A neighbourhood tag opens only its own projects without blocking the map."""
import subprocess
import re
from pathlib import Path


def test_dong_tag_opens_exact_official_sources_and_keeps_map_open():
    html = (Path(__file__).parents[1] / '앱화면/real-estate-search.html').read_text()
    panel = html.split('      const createReferencePanel =', 1)[1].split('      const openProject =', 1)[0]
    cards = html.split('      const mountDongCards =', 1)[1].split('      const declutter =', 1)[0]
    sources = '\n'.join(re.search(r'    function ' + name + r'\([^\n]*\) \{.*?\n    \}', html, re.S).group()
                        for name in ('zippickFutureSourceIsOfficial', 'zippickOfficialDetailUrl',
                                     'zippickFutureSourceLink', 'zippickLivingProjectSourceUrl'))
    script = r'''
const assert = require('node:assert/strict');
class Node {
  constructor(tag) { this.tagName=tag; this.children=[]; this.dataset={}; this.style={}; this.listeners={}; }
  append(...nodes) { nodes.forEach(node => {this.children.push(node); node.parent=this;}); }
  appendChild(node) { this.append(node); }
  replaceChildren(...nodes) { this.children=[]; this.append(...nodes); }
  setAttribute(name,value) { this[name]=value; }
  addEventListener(name,fn) { this.listeners[name]=fn; }
  remove() { this.parent.children=this.parent.children.filter(node=>node!==this); }
  querySelector(selector) { return this.children.find(node=>'.'+node.className===selector) || null; }
  focus() { focused=this; }
  scrollIntoView() {}
  insertAdjacentHTML() {}
}
let focused=null, clearCount=0;
const document={createElement:tag=>new Node(tag),createTextNode:text=>({textContent:text})};
const mapHome=new Node('section');
const mapElement={isConnected:true, dataset:{}, closest:()=>null};
const zones=[
 {id:'zone-1',name:'같은 이름',projectType:'redevelopment',stageLabel:'조합 설립',latitude:37.65,longitude:127.03,distanceMeters:400,stageSourceUrl:'https://www.seoul.go.kr/notice?id=1',sourceUrl:'https://data.seoul.go.kr/dataset',sourceDate:'2026-10-01'},
 {id:'zone-2',name:'같은 이름',projectType:'reconstruction',stageLabel:'구역 지정',latitude:37.66,longitude:127.04,distanceMeters:700,sourceUrl:'https://www.seoul.go.kr/notice?id=2'},
 {id:'other-dong',name:'다른 동 사업',projectType:'redevelopment',latitude:37.67,longitude:127.05,distanceMeters:800},
];
const point={id:'point',name:'사업 대표점',projectType:'reconstruction',latitude:37.65,longitude:127.02,distanceMeters:500};
const nearbyRenewal=new Map([...zones,point].map(project=>[project.id,project]));
const renewalCount=nearbyRenewal.size, stations=[], dongOverlays=[], overlays=[];
const zippickLivingDongRegionCache=new Map();
const distanceText=m=>`직선 약 ${m}m`;
const stageText=p=>p.stageLabel || '진행 단계 미확인';
const validPoint=p=>Number.isFinite(p.latitude)&&Number.isFinite(p.longitude);
const esc=value=>String(value);
const mapZoneDevelopmentDetailHtml=()=>'';
const clearSelectedZoneTag=()=>{clearCount++;};
let selected=null, panned=null;
const map={panTo:position=>{panned=position;}};
const kakao={maps:{LatLng:class {constructor(lat,lng){this.latitude=lat;this.longitude=lng;}}, services:{
 Status:{OK:'OK'}, Geocoder:class {coord2RegionCode(lng,lat,callback){
   const other=lat===37.67;
   callback([{region_type:'B',code:other?'other':'banghak',region_3depth_name:other?'창동':'방학동'}],'OK');
 }}
}}};
const overlay=(position,node,anchor,clickable)=>{
 const item={position,node,clickable,setZIndex(){}}; overlays.push(item); return item;
};
const legend=new Node('div');
const declutter=()=>{};
''' + sources + '\nconst createReferencePanel =' + panel + r'''
const selectZone=(project,position,options)=>{
 selected=project; showReference(project,{...options,preserveSelectedTag:true});
};
''' + 'const mountDongCards =' + cards + r'''
function panelNode(){return mapHome.querySelector('.zpr-living-map-reference');}
function listButtons(){return panelNode().children.find(node=>node.tagName==='ul').children.map(row=>row.children[0]);}
function click(node){node.listeners.click({stopPropagation(){}});}
(async()=>{
 await mountDongCards();
 assert.equal(dongOverlays.length,2);
 const card=dongOverlays[0].card;
 assert.equal(card.tagName,'button');
 assert.equal(card.type,'button');
 assert.equal(overlays[0].clickable,true);
 click(card);
 assert.equal(panelNode()['aria-label'],'방학동 정비사업');
 assert.equal(focused,panelNode());
 let buttons=listButtons();
 assert.equal(buttons.length,3);
 assert.ok(buttons.every(button=>!button.children.some(node=>node.textContent==='다른 동 사업')));
 assert.match(buttons[0].children[1].textContent,/조합 설립.*400m/);
 assert.equal(buttons[0].tagName,'a');
 assert.equal(buttons[0].href,zones[0].stageSourceUrl);
 assert.equal(buttons[2].href,zones[1].sourceUrl); // Equal names retain each exact source.
 for (const link of [buttons[0],buttons[2]]) {
   assert.equal(link.target,'_blank');
   assert.equal(link.rel,'noopener noreferrer');
   assert.equal(link.listeners.click,undefined,'브라우저 링크로 열고 내부 상세 화면으로 전환하지 않는다');
   assert.equal(link.children[2].textContent,'사업 상세 보기 ↗');
 }
 assert.equal(buttons[1].tagName,'div');
 assert.equal(buttons[1].href,undefined);
 assert.equal(buttons[1].children[2].textContent,'개별 공식 자료 확인 중');
 assert.equal(panelNode()['aria-label'],'방학동 정비사업');
 assert.equal(selected,null);
 assert.equal(panned,null);
 assert.equal(zippickLivingProjectSourceUrl({sourceUrl:'javascript:alert(1)'}),'');
 assert.equal(zippickLivingProjectSourceUrl({sourceUrl:'https://www.seoul.go.kr.evil.com/'}),'');
 assert.equal(zippickLivingProjectSourceUrl({sourceUrl:'https://user:pass@www.seoul.go.kr/'}),'');
 assert.equal(zippickLivingProjectSourceUrl({stageSourceUrl:'invalid',nameSourceUrl:zones[1].sourceUrl}),zones[1].sourceUrl);
 for (const url of ['https://gris.gg.go.kr:8888/grisgis/rest/services/bdsMap_Monitoring/MapServer/7',
   'https://data.seoul.go.kr/dataList/OA-23112/S/1/datasetView.do',
   'https://www.gg.go.kr/opendata/openDataContent.do?gg_content_idx=11673',
   'https://cleanup.seoul.go.kr/', 'https://www.eum.go.kr/web/gs/gv/gvGosiList.jsp']) {
   assert.equal(zippickFutureSourceLink(url),'','데이터 목록이나 GIS API를 사용자 링크로 내보내지 않는다');
   assert.equal(zippickLivingProjectSourceUrl({officialDetailUrl:url,sourceUrl:url}),'');
 }
 const detail='https://cleanup.seoul.go.kr/cafe/mainIndx.do?cafeUrl=banghakzone3';
 assert.equal(zippickLivingProjectSourceUrl({officialDetailUrl:detail,sourceUrl:zones[1].sourceUrl}),detail);
 click(panelNode().querySelector('.zpr-living-map-reference-close'));
 assert.equal(panelNode(),null);
 assert.equal(focused,card);
 assert.ok(clearCount>0);
})().catch(error=>{console.error(error);process.exit(1);});
'''
    result = subprocess.run(['node'], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
