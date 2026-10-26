import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import living_area_context as context


def report():
    station={'lineId':'dongbuk','name':'월계역 · 동북선','lineName':'동북선',
             'stage':'construction','stageLabel':'공사 중','distanceMeters':607}
    return {'modelVersion':'living-area-v2-beta','status':'insufficient_data',
        'displayProjects':[{'id':'housing','name':'시험 정비사업','projectType':'redevelopment',
                            'stage':'construction','distanceMeters':900}],
        'planRating':{'version':'living-area-plan-v8-beta','status':'ready','score':3.4,
            'subScores':{'housing':3.4,'transport':0},'weights':{'housing':1,'transport':.2},
            'transportCoverage':{'nearbyPlannedStations':[station]},
            'components':{'housing':{'selectedProjectId':'housing'},'transport':{
                'inputs':[],'noUsefulPlannedStation':True,'excludedStations':[station]}}}}


@pytest.mark.parametrize('housing',[3.4,3.6,2.0])
def test_distance_exclusion_does_not_mean_construction_plan_is_unconfirmed(housing):
    model=report()
    model['planRating']['score']=housing
    model['planRating']['subScores']['housing']=housing
    result=context.conclude(model,{'name':'삼호4'})
    brief=result['briefing']
    text=' '.join([brief['reason'],*brief['weaknesses'],*brief['unknowns']])
    assert '교통 계획은 확인되지' not in text
    assert '철도 계획은 없어요' not in text
    assert '거리 기준상 가점' in text
    assert model['planRating']['subScores']['transport']==0


@pytest.mark.skipif(not shutil.which('node'),reason='Node required')
def test_compact_report_shows_construction_and_why_no_bonus():
    html=(Path(__file__).resolve().parents[1]/'앱화면/real-estate-search.html').read_text()
    functions='\n'.join(re.search(r'    function '+name+r'\(.*?\n    \}',html,re.S).group()
        for name in ['zippickRailUnderReview','zippickLifestyleChangeHtml'])
    model=context.conclude(report(),{'name':'삼호4'})
    farther=copy.deepcopy(model['planRating']['components']['transport']['excludedStations'][0])
    farther.update(name='하계역 · 동북선',distanceMeters=1206)
    model['planRating']['components']['transport']['excludedStations'].insert(0,farther)
    script=r'''
const assert=require('node:assert/strict');
const esc=value=>String(value??'');
const zippickLifestyleChangeRatingData=item=>item.futureTransformation.planRating.score;
const zippickLifestylePlanRating=analysis=>analysis.planRating;
const zippickFutureSourceIsOfficial=()=>false;
const zippickReportMapHtml=()=>'';
const zippickReviewRailReferences=()=>[];
const zippickLivingTransportHtml=()=>'';
const zippickFutureSourceLink=()=>'';
const zippickLivingProjectSourceUrl=()=>'';
'''+functions+'\nconst model='+json.dumps(model,ensure_ascii=False)+r''';
const output=zippickLifestyleChangeHtml({futureTransformation:model});
const facts=output.split('aria-label="생활권 변화 근거"')[1].split('집픽 브리핑')[0];
assert.match(facts,/동북선 · 공사 중 · 직선 607m · 기존 역보다 멀어 가점 제외/);
assert.equal((facts.match(/동북선/g)||[]).length,1);
assert.match(facts,/\+0\.0/);
assert.doesNotMatch(output,/새 교통 계획은 확인되지|새로 탈 만한 예정역 없음/);
// A second line may already contribute points; keep the unscored line visible.
model.planRating.components.transport.inputs=[{lineId:'gtx-c',name:'광운대역 · GTX-C',distanceMeters:369,contributionScore:3.8}];
model.planRating.subScores.transport=3.8;
assert.match(zippickLifestyleChangeHtml({futureTransformation:model}),/동북선 · 공사 중 · 직선 607m · 기존 역보다 멀어 가점 제외/);
'''
    result=subprocess.run(['node'],input=script,text=True,capture_output=True)
    assert result.returncode==0,result.stderr


@pytest.mark.skipif(not shutil.which('node'),reason='Node required')
def test_report_map_uses_nearest_station_per_line_without_changing_source_data():
    html=(Path(__file__).resolve().parents[1]/'앱화면/real-estate-search.html').read_text()
    function=re.search(r'    function zippickLivingRepresentativeStations\(.*?\n    \}',html,re.S).group()
    script="const assert=require('node:assert/strict');\n"+function+r'''
const stop=(id,lineId,distanceMeters,more={})=>({id,lineId,distanceMeters,
  name:'같은 역 이름',latitude:37.62,longitude:127.06,serviceStatus:'planned',...more});
const input=[stop('d1','dongbuk',1870),stop('d2','dongbuk',1206),stop('d3','dongbuk',607),
 stop('g1','gtx-c',369),stop('d4','dongbuk',1217),stop('outside','other',2001),
 stop('invalid','dongbuk',100,{latitude:null}),stop('negative','other',-1)];
const before=JSON.stringify(input);
assert.deepEqual(zippickLivingRepresentativeStations(input).map(s=>s.id),['d3','g1']);
assert.equal(JSON.stringify(input),before);
assert.deepEqual(zippickLivingRepresentativeStations([...input].reverse()).map(s=>s.id).sort(),['d3','g1']);
// Existing stops and a new extension are different facts; one of each may appear.
assert.equal(zippickLivingRepresentativeStations([stop('p','one',500),stop('o','one',300,{serviceStatus:'operating'})]).length,2);
// Same names on different lines must not merge. Unknown line identities stay distinct.
assert.equal(zippickLivingRepresentativeStations([stop('a','one',500),stop('b','two',300)]).length,2);
assert.equal(zippickLivingRepresentativeStations([stop('a',null,500),stop('b',null,300)]).length,2);
assert.deepEqual(zippickLivingRepresentativeStations([stop('b','one',500),stop('a','one',500)]).map(s=>s.id),['a']);
'''
    result=subprocess.run(['node'],input=script,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
