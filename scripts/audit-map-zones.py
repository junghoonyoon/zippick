#!/usr/bin/env python3
"""Reconcile every stored boundary with the shared map output; no network writes."""
import collections
import datetime as dt
import hashlib
import html
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'pipeline'))
import living_area_metro as metro
import map_zone_policy as policy
import redevelopment_occupancy as occupancy
import search_server
from shapely.geometry import shape
from shapely.validation import explain_validity


def run():
    source=json.loads((ROOT/'data/redevelopment_zones.geojson').read_text())
    raw=[(f['properties']['id'],'서울',f,f['properties']) for f in source['features']]
    raw += [('gg-zone:'+str(f['properties']['sourceLayer'])+':'+str(f['properties']['OBJECTID']),'경기',f,f['properties'])
            for f in metro.catalog()['ggBoundaries']]
    zones=metro.spatial({'latitude':37.5,'longitude':127},metro.catalog()['projects'],dt.date.today(),
                       bbox=(124,33,132,39),include_routes=False)['zones']
    byid={z['id']:z for z in zones}
    assert len(raw)==len({r[0] for r in raw}), 'duplicate source IDs'
    assert len(zones)==len(byid), 'duplicate display IDs'
    api=search_server._redevelopment_zones_payload({'bbox':['124,33,132,39'],'limit':['3000']})
    assert not api['limited'], 'API truncation: partition the audit viewport'
    api_byid={z['id']:z for z in api['zones']}
    assert byid.keys()==api_byid.keys(), 'report/viewport boundary set mismatch'
    for id,z in byid.items():
        for key in ('geometry','name','stageLabel','zoneKind','classificationReason','projectId','sourceDate','sourceUrl'):
            assert z[key]==api_byid[id][key], (id,key)
    rows=[]
    for id,region,f,p in raw:
        z=byid.get(id)
        geometry=shape(f['geometry'])
        excluded=None
        if not z:
            if region=='서울' and occupancy.occupancy_evidence({**p,'id':id}):excluded='입주 확인'
            elif region=='서울' and metro.stage(p.get('stage'))=='completed':excluded='공식 완료 단계'
            elif not geometry.is_valid or geometry.is_empty:excluded='원본 도형 오류'
            else:excluded='연결된 공식 사업 완료'
        row={k:z.get(k) for k in ('name','projectId','projectTypeLabel','zoneKind','zoneKindLabel',
            'classificationReason','businessNameConfirmed','matchMethod','stageLabel','stage','stageMismatch',
            'boundaryStageLabel','projectStageLabel','stageStatus','stageReasonCode','stageReason','stageDefinition','stageSourceUrl','stageSourceDate','sourceUrl','sourceDate','nameSourceUrl','nameSourceDate') } if z else {}
        row.update(id=id,region=region,displayed=bool(z),excludedReason=excluded,
                   rawName=p.get('name') or p.get('ALIAS') or p.get('REMARK') or '사업명 미확인',
                   rawType=p.get('projectType') or p.get('USE_CD'),
                   rawStage=p.get('stage'),districtCode=p.get('districtCode') or p.get('STD_SGGCD'),
                   geometryValid=geometry.is_valid,geometryIssue=None if geometry.is_valid else explain_validity(geometry))
        rows.append(row)
    counters={region:dict(collections.Counter(r.get('zoneKind') if r['displayed'] else 'excluded' for r in rows if r['region']==region)) for region in ('서울','경기')}
    result={'checkedAt':dt.datetime.now().astimezone().isoformat(),'classificationVersion':policy.VERSION,
        'coverage':policy.coverage(),'rawCount':len(raw),'displayedCount':len(zones),'countsByRegion':counters,
        'excluded':dict(collections.Counter(r['excludedReason'] for r in rows if not r['displayed'])),
        'unknownClassification':sum(z['zoneKind']=='unknown' for z in zones),
        'unknownNames':sum(not z['businessNameConfirmed'] for z in zones),
        'unknownStages':sum(z['stage']=='unknown' for z in zones),
        'stageDisagreements':sum(z['stageMismatch'] for z in zones),
        'missingStageLabels':sum(z['stageLabel']=='진행 단계 미확인' for z in zones),
        'stageReasons':dict(collections.Counter(z.get('stageReasonCode') for z in zones)),
        'stageStatuses':dict(collections.Counter(z.get('stageStatus') for z in zones)),
        'invalidGeometry':sum(not r['geometryValid'] for r in rows),
        'apiParity':{'checkedBoundaries':len(zones),'mismatches':0,'truncated':api['limited']},
        'dataHashes':{name:hashlib.sha256((ROOT/'data'/name).read_bytes()).hexdigest() for name in ('redevelopment_zones.geojson','living_area_metro_catalog.json')},
        'sourceChecks':json.loads((ROOT/'docs/map-zone-source-check.json').read_text()),
        'validation':json.loads((ROOT/'docs/map-zone-validation.json').read_text()) if (ROOT/'docs/map-zone-validation.json').exists() else {},'rows':rows}
    assert result['rawCount']==result['displayedCount']+sum(result['excluded'].values())
    (ROOT/'docs/map-zone-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    render(result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','sourceChecks','dataHashes')},ensure_ascii=False,indent=2))


def render(r):
    esc=lambda s:html.escape(str(s or '—'))
    counts=''.join('<tr><th>'+region+'</th>'+''.join('<td>'+str(r['countsByRegion'][region].get(kind,0))+'</td>' for kind in ('renewal','reference','unknown','excluded'))+'</tr>' for region in ('서울','경기'))
    exceptions=[x for x in r['rows'] if x.get('zoneKind')=='unknown' or not x['geometryValid']]
    detail=''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in (x['region'],x['id'],x.get('name') or x['rawName'],x['rawType'],x.get('classificationReason') or x['geometryIssue']))+'</tr>' for x in exceptions)
    types=''.join('<tr><th>'+label+'</th><td>'+esc(' · '.join(sorted(values)))+'</td></tr>' for label,values in [('주황 · 정비사업',policy.RENEWAL_TYPES),('파랑 · 참고 구역',policy.REFERENCE_TYPES)])
    page=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>수도권 구역 지도 검증 보고서</title>
<style>body{{font:16px/1.7 system-ui,sans-serif;color:#202b40;max-width:1080px;margin:40px auto;padding:0 20px;background:#f6f8fa}}section{{background:white;padding:24px;margin:20px 0;border:1px solid #dde3eb;border-radius:12px}}h1{{font-size:28px}}h2{{font-size:21px}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #e0e5ec;overflow-wrap:anywhere}}.scroll{{overflow:auto}}a{{color:#1769c2}}.note{{color:#526078}}strong{{font-weight:700}}.status{{border-left:5px solid #6b7280}}</style>
<h1>수도권 구역 지도 검증 보고서</h1><p><a href="map-zone-guide.md">단일 관리 문서 보기</a> · 이 보고서는 자동 생성 결과입니다.</p><p class="note">검증 시각 {esc(r['checkedAt'])} · 분류 기준 {policy.VERSION}</p>
<section class="status"><h2>서울·경기 자료를 수정했습니다. 수도권 전체 확인은 진행 중입니다.</h2><p><strong>원본 {r['rawCount']:,}개를 점검</strong>했습니다. 지도에 표시하는 {r['displayedCount']:,}개는 리포트와 매수 후보 지도에서 경계·이름·단계·색상 분류가 같습니다.</p><p>인천 공식 경계는 아직 연결하지 못했습니다. 자료가 없는 곳을 ‘정비사업 없음’으로 표시하지 않습니다. 이 검증은 공개 원본과 서비스의 일치 여부를 확인한 것이며, 개별 고시 전체를 대조한 법적 경계 검증은 아닙니다.</p></section>
<section><h2>무엇을 고쳤나</h2><ul><li>서울 2월 경계를 9월 10일 공개 원본으로 갱신: 새 경계 439개, 원본에서 빠진 경계 248개, 이름·단계·면적 변경 425개.</li><li>경기 경계 407개는 공식 서버와 모두 일치. 공식 사업목록 542건을 대조하고, 주거환경개선 44건을 재개발과 구분.</li><li>서울 공식 사업목록 830건의 고유번호·이름·단계 대조. 사업명이 비어 있어도 확인된 구역 유형으로 색상 결정.</li><li>이름을 연결할 때 주소·지역·면적을 함께 확인. 이름이 다른 사업을 구역 안에 있다는 이유만으로 연결하지 않음.</li><li>준공 예정·일부 준공은 완료로 처리하지 않음. 원본 도형은 임의 보정하지 않음.</li></ul></section>
<section><h2>지도 표시 결과</h2><table><tr><th>지역</th><th>주황 · 정비사업</th><th>파랑 · 참고 구역</th><th>회색 · 확인 중</th><th>지도 제외</th></tr>{counts}<tr><th>인천</th><td colspan="4">경계 원본 확인 중</td></tr></table><p>주황색은 사업 유형을 뜻합니다. 구역 지정·사업 승인·착공을 보장하는 색이 아닙니다.</p><p>지도 제외 사유: {esc(' · '.join(k+' '+str(v)+'개' for k,v in r['excluded'].items()))}.</p></section>
<section><h2>아직 확인이 필요한 항목</h2><ul><li>유형 확인 중 <strong>{r['unknownClassification']}개</strong>: 원본의 ‘기타’ 코드나 코드 설명 누락. 회색으로 표시.</li><li>사업명 미확인 <strong>{r['unknownNames']}개</strong>: 이름을 추정하지 않고 ‘사업명 미확인’ 표시. 유형이 확인된 정비구역은 주황색 유지.</li><li>진행 단계 원문 미확인 {r['missingStageLabels']}개. 원본에 단계가 없고 공식 사업목록 연결 근거가 부족합니다. 공통 단계 분류 미확인 {r['unknownStages']}개에는 원문 단계가 있는 건축심의 등도 포함됩니다.</li><li>경계 자료와 연결한 사업목록의 단계 분류 차이 {r['stageDisagreements']}개: 진행 단계를 확정하지 않고 ‘진행 단계 확인 중’으로 표시. 두 자료의 원문과 출처를 상세 화면에서 확인 가능.</li><li>원본 도형 오류 {r['invalidGeometry']}개: 정확한 경계를 그릴 수 없어 지도에서 제외. 원본 수정 자료 필요.</li></ul><p>인천 시청 공개 게시물의 사업 목록은 확인했으나, 확인한 지도 검색은 이미지 방식이어서 실제 경계 좌표로 사용하지 않았습니다.</p></section>
<section><h2>색상 기준</h2><table>{types}<tr><th>회색 · 확인 중</th><td>분류표에 없는 코드, 출처의 분류 충돌. 이름에 ‘재개발’이 들어 있다는 이유만으로 확정하지 않음.</td></tr></table><p>경기: 재개발구역 UDR100·정비구역 UDT100·주거환경개선지구 UDS100은 주황, 재정비촉진지구 UDA100은 파랑. 기타 코드는 회색.</p></section>
<section><h2>검사와 적용 범위</h2><p>기존 핵심 검사 59개·화면 지도 검사 22개·단계 분류 검사 21개에 더해 단계 보강 검사 5개를 통과했습니다. 실제 단지 리포트 API와 전체 지도 API도 대조했습니다. 데스크톱과 모바일 폭에서 지도 이동·확대·선택·카드 펼치기와 접기를 확인했습니다.</p><p>기존 지도 테스트 5개는 통과하지 못했습니다. 4개는 현재 단지 목록에 없는 과거 고유값, 1개는 직접 분석 호출의 좌표 누락 때문입니다. 전체 테스트가 통과했다고 주장하지 않습니다. <a href="map-zone-validation.json">검사 상세</a> · <a href="map-zone-api-smoke.json">실제 API 대조</a></p><p>적용: 현재 로컬 서버. 사용자의 요청으로 운영(exe.dev) 배포는 보류했습니다.</p></section>
<section><h2>출처와 이용 범위</h2><p><a href="https://data.seoul.go.kr/dataList/OA-22712/S/1/datasetView.do">서울 경계 OA-22712</a> · 2026-09-10 공개. 사이트 표기: 출처표시·상업적 이용금지·변경금지. 기존에 확인된 비상업용 표시 조건을 유지했습니다. 상업 서비스 제공 전에는 별도 이용 허락이나 이용 가능한 대체 원본이 필요합니다.</p><p><a href="https://data.seoul.go.kr/dataList/OA-23112/S/1/datasetView.do">서울 사업목록 OA-23112</a> · <a href="https://www.gg.go.kr/opendata/openDataContent.do?gg_content_idx=11673&amp;decodeIdx=5318">경기 사업목록</a> · 경기 목록 기준 2026-06-30. 조회 날짜와 자료 기준일은 다릅니다.</p><p><a href="https://gris.gg.go.kr:8888/grisgis/rest/services/bdsMap_Public/MapServer">경기 공식 공간정보</a> · 레이어 12~15. 전체 수신과 건수·속성·도형 일치 확인.</p><p>검증 상세: <a href="map-zone-audit.json">전체 {r['rawCount']:,}개 점검 결과</a> · <a href="map-zone-source-check.json">공식 원본 대조 결과</a></p></section>
<section><h2>유형 미확인·도형 오류 목록</h2><div class="scroll"><table><tr><th>지역</th><th>구역 고유값</th><th>원본명/표시명</th><th>원본 유형</th><th>확인 사유</th></tr>{detail}</table></div></section></html>'''
    (ROOT/'docs/map-zone-audit.html').write_text(page)


if __name__=='__main__':run()
