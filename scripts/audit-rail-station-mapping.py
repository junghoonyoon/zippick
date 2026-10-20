"""Write a reviewable station coverage report from the shared registry."""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
b = json.loads((ROOT/'data/rail_station_mapping.json').read_text())
rows = []
for line in b['lines']:
    stations = [s for s in b['stations'] if s['lineId'] == line['id']]
    rows.append({k:line.get(k) for k in ('id','name','stage','stageCode','listedStations',
        'stationLocationCount','landmarkReferences','unlocatedStations','scoringStations',
        'mappingComplete','stationListComplete','unresolvedReason','sourceUrl','stationsSourceUrl')}
        | {'unresolvedStations':[s.get('stationName') or s['name'] for s in stations if s['locationStatus']!='located'],
           'referenceOnlyStations':[s.get('stationName') or s['name'] for s in stations if s.get('referenceOnly')]})
audit = dict(checkedAt=b['checkedAt'],scope=b['scope'],coverage=b['coverage'],lines=rows,
    limitations=['같은 환승역도 노선마다 따로 센 노선-역 연결 건수입니다.',
                 '좌표는 정거장 부지·예정역 장소·기존 환승역의 대표점입니다. 출입구나 도보 경로가 아닙니다.',
                 '주변 시설 참고점은 역 위치 확인 건수와 교통 점수에서 제외합니다.',
                 '미확인 역의 위치를 추측하지 않았으며, 전체 정거장 목록이 미확인인 노선도 남아 있습니다.',
                 'VWorld 정거장 공간정보는 현재 설정된 키의 인증 오류로 수집하지 못했습니다.'],
    sourceMethods=['국가철도공단 사업 현황·공식 노선도','국토교통부·지자체 승인 자료',
                   '토지이음 실시계획 고시의 정거장별 부지 주소','서울시 2026년 도시철도망 승인 보고서',
                   '경기도 공개 GIS·수도권 교통계획 대조','카카오 주소·예정역 검색의 이름 및 지역 일치 검증'])
(ROOT/'docs/rail-station-mapping-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
e = html.escape
body=[]
for r in rows:
    state='개통 구간 제외' if r['stageCode']=='completed' else '목록·위치 확인' if r['mappingComplete'] else '일부 확인'
    gaps=' · '.join(r['unresolvedStations']) or r.get('unresolvedReason') or '—'
    if not r['stationListComplete'] and r['stageCode']!='completed':gaps+=' / 전체 역 목록 추가 확인 필요'
    body.append(f'<tr><th>{e(r["name"])}<small>{e(r["stage"])} · {state}</small></th><td>{r["listedStations"]}</td><td>{r["stationLocationCount"]}</td><td>{r["landmarkReferences"]}</td><td>{r["scoringStations"]}</td><td>{e(gaps)}<p><a href="{e(r["stationsSourceUrl"])}">역 목록 출처</a> · <a href="{e(r["sourceUrl"])}">사업 단계 출처</a></p></td></tr>')
c=b['coverage']
page=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>철도 예정역 확인 현황</title><style>body{{font:16px/1.6 system-ui;max-width:1200px;margin:32px auto;padding:0 20px;color:#182230}}h1{{font-size:28px}}strong{{color:#195bb5}}table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;padding:14px;border-bottom:1px solid #dce2eb;vertical-align:top}}thead{{background:#f0f5fd}}small{{display:block;color:#65748a}}a{{color:#195bb5}}.scroll{{overflow:auto}}input{{font:inherit;padding:12px;width:min(90%,420px);margin:12px 0}}td:last-child{{min-width:260px}}th{{min-width:160px}}</style><h1>철도 예정역 확인 현황</h1><p>확인일 {e(b['checkedAt'])}. <strong>{c['lineCount']}개 노선에서 역 위치 {c['stationLocationCount']}건</strong>을 연결했습니다. 주변 시설 참고점 {c['landmarkReferences']}건은 따로 표시했습니다.</p><p>등록한 노선-역 연결 {c['listedStations']}건 중 좌표 미확인 {c['unlocatedStations']}건이 남아 있습니다. 전체 역 목록까지 확인한 노선은 {c['completeLines']}개입니다.</p><p>{e(b['scope'])}</p><ul>{''.join('<li>'+e(x)+'</li>' for x in audit['limitations'])}</ul><input id="filter" aria-label="노선 검색" placeholder="노선 이름으로 찾기"><div class="scroll"><table><thead><tr><th>노선</th><th>목록</th><th>역 위치</th><th>주변 시설</th><th>점수 반영</th><th>남은 확인과 출처</th></tr></thead><tbody>{''.join(body)}</tbody></table></div><script>document.querySelector('#filter').addEventListener('input',e=>document.querySelectorAll('tbody tr').forEach(r=>r.hidden=!r.textContent.includes(e.target.value)));</script></html>'''
(ROOT/'docs/rail-station-mapping-audit.html').write_text(page)
print(json.dumps(c,ensure_ascii=False))
