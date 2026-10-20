"""Reference boundaries are opt-in and cannot reappear after a delayed response."""
import re
import subprocess
from pathlib import Path


HTML = Path(__file__).parents[1] / '앱화면/real-estate-search.html'


def test_candidate_reference_visibility_and_pending_requests():
    html = HTML.read_text()
    names = ('mapZoneIsVisible', 'redevelopmentZoneLegendHtml',
             'setCandidateMapZoneVisibility', 'candidateMapRedevelopmentBbox',
             'clearCandidateMapRedevelopmentLabels', 'clearCandidateMapRedevelopmentLayers',
             'renderCandidateMapRedevelopmentZones')
    functions = '\n'.join(re.search(
        r'    (?:async )?function ' + name + r'\([^\n]*\) \{.*?\n    \}',
        html, re.S).group() for name in names)
    defaults = '\n'.join(re.search(r'    let ' + name + r' = .*?;', html).group()
                         for name in ('candidateMapRedevelopmentEnabled', 'candidateMapReferenceEnabled'))
    script = defaults + functions + '''
const assert = require('node:assert/strict');
const candidateMap = {getLevel:()=>4};
const candidateMapKakao = {};
const candidateMapContainer = {setAttribute(){}};
let candidateMapPresentationMode = 'markers';
let candidateMapRedevelopmentRequestSeq = 0, candidateMapRedevelopmentLastBbox = '';
let candidateMapRedevelopmentTimer = null, candidateMapRedevelopmentFocus = null;
let candidateMapRedevelopmentLayers = [];
const CANDIDATE_MAP_REDEVELOPMENT_LABEL_LEVEL = 6;
const CANDIDATE_MAP_REDEVELOPMENT_REQUEST_LIMIT = 3000;
const controls = new Map([
  ['.candidate-map-zone-legend', {}],
  ['[data-candidate-map-redevelopment-toggle]', {}],
  ['[data-candidate-map-reference-toggle]', {}],
]);
const candidateMapQuery = selector => controls.get(selector);
const candidateMapBoundsBbox = () => '126.9,37.5,127.1,37.7';
function scheduleCandidateMapRedevelopmentZones() {}
function syncCandidateMapRedevelopmentNameLabels() {}
function showCandidateMapFocusedRedevelopmentZone() {return false;}
function setCandidateMapCaption() {}
function redevelopmentZoneRings() {return [[[1,2,3]]];}
function redevelopmentZonePolygonStyle() {return {clickable:false};}
let resolveResponse;
function getJson() {return new Promise(resolve => {resolveResponse = resolve;});}
const kakao = {maps:{Polygon:class {
  constructor(options) {this.map=options.map;}
  setMap(map) {this.map=map;}
}}};
const zones = ['renewal','reference','unknown'].map(kind => ({id:kind,zoneKind:kind}));
const visibleKinds = () => candidateMapRedevelopmentLayers.map(layer => layer.zone.zoneKind);
(async () => {
  assert.equal(candidateMapRedevelopmentEnabled,true);
  assert.equal(candidateMapReferenceEnabled,false);
  assert.doesNotMatch(redevelopmentZoneLegendHtml(), /파랑/);
  let pending = renderCandidateMapRedevelopmentZones(kakao);
  resolveResponse({zones}); await pending;
  assert.deepEqual(visibleKinds(), ['renewal','unknown']);

  setCandidateMapZoneVisibility({reference:true});
  assert.match(controls.get('.candidate-map-zone-legend').innerHTML,/파랑/);
  pending = renderCandidateMapRedevelopmentZones(kakao);
  resolveResponse({zones}); await pending;
  assert.deepEqual(visibleKinds(), ['renewal','reference','unknown']);

  // A reference-only map works independently of the renewal switch.
  setCandidateMapZoneVisibility({renewal:false});
  assert.ok(candidateMapRedevelopmentBbox());
  pending = renderCandidateMapRedevelopmentZones(kakao);
  resolveResponse({zones}); await pending;
  assert.deepEqual(visibleKinds(), ['reference']);

  // Switching off clears polygons and popups immediately; stale requests lose.
  const detachedLayers = candidateMapRedevelopmentLayers;
  const popup = {map:candidateMap,setMap(map){this.map=map;}};
  const nameLabel = {map:candidateMap,setMap(map){this.map=map;}};
  detachedLayers[0].label = popup;
  detachedLayers[0].nameLabel = nameLabel;
  setCandidateMapZoneVisibility({renewal:true});
  assert.ok(detachedLayers.every(layer => layer.polygon.map === null));
  assert.equal(popup.map,null);
  assert.equal(nameLabel.map,null);
  pending = renderCandidateMapRedevelopmentZones(kakao);
  setCandidateMapZoneVisibility({reference:false});
  resolveResponse({zones}); await pending;
  assert.deepEqual(visibleKinds(), []);
  pending = renderCandidateMapRedevelopmentZones(kakao);
  resolveResponse({zones}); await pending;
  assert.deepEqual(visibleKinds(), ['renewal','unknown']);

  setCandidateMapZoneVisibility({renewal:false});
  assert.equal(candidateMapRedevelopmentBbox(),'');
  assert.equal(controls.get('.candidate-map-zone-legend').hidden,true);
  assert.deepEqual(visibleKinds(), []);
})().catch(error => {console.error(error); process.exit(1);});
'''
    result = subprocess.run(['node'], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
