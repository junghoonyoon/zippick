#!/usr/bin/env python3
"""Audit every searchable physical apartment through the production resolver."""
import collections
import datetime as dt
import html
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'pipeline'))
import apartment_development as development
import real_estate_search as search
from future_transformation import apartment_key


def run():
    day=dt.date.today()
    registry=development.index()
    seen=set();rows=[];models=[];failures=[]
    for entity in search.APARTMENT_MASTER:
        if entity.get('aggregate'):continue
        apartment_id=apartment_key(entity)
        signature=(apartment_id,entity.get('province'),entity.get('district'),entity.get('legalDong'),entity.get('jibun'))
        if signature in seen:continue
        seen.add(signature)
        item={**entity,'apartmentId':apartment_id}
        result=development.for_apartment(item,day=day,registry=registry)
        if result['status']=='confirmed':
            for p in result['projects']:
                if p['matchedSubjectApartmentId'] != apartment_id or not p['matchMethod']:
                    failures.append({'apartmentId':apartment_id,'reason':'missing_verified_identity'})
                if development.terminal(p.get('stageLabel')):
                    failures.append({'apartmentId':apartment_id,'reason':'completed_project_resurrected'})
            models.append({'name':entity['name'],'apartmentId':apartment_id,
                'province':entity.get('province'),'district':entity.get('district'),
                'legalDong':entity.get('legalDong'),'jibun':entity.get('jibun'),
                'approvedAt':entity.get('approvedAt'),'buildingAge':development._age(entity,day),
                'futureTransformation':{'apartmentId':apartment_id,'ownDevelopment':result}})
        rows.append({'apartmentId':apartment_id,**{k:entity.get(k) for k in
            ('name','province','district','legalDong','jibun')},'status':result['status'],
            'rating':result.get('rating'), 'projects':[{k:p.get(k) for k in
                ('id','name','address','stageLabel','sourceUrl','sourceDate','checkedAt','matchMethod')}
                for p in result['projects']], 'unresolvedProjects':result['unresolvedProjects']})
    matched=[r for r in rows if r['status']=='confirmed']
    report={'checkedAt':day.isoformat(),'version':development.VERSION,'scopeComplete':False,
        'scope':'검색 원본의 개별 단지 전체. 연결한 공식 자료를 전수 대조한 결과이며, 모든 추진위·비공식 움직임의 실시간 전수 확인을 뜻하지 않음.',
        'counts':{'apartments':len(rows),'confirmed':len(matched),
            'rated':sum(r.get('rating',{}).get('state')=='ready' for r in matched),
            'status':dict(collections.Counter(r['status'] for r in rows)),
            'sourceProjects':len(registry['rows'])},
        'byProvince':{province:dict(collections.Counter(r['status'] for r in rows if r['province']==province))
                      for province in sorted({r['province'] or '' for r in rows})},
        'failures':failures,'rows':rows}
    (ROOT/'docs/apartment-development-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    Path('/tmp/zippick-development-render-cases.json').write_text(json.dumps(models,ensure_ascii=False))
    esc=lambda v:html.escape(str(v or '—'))
    body=''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in (r['name'],r['district'],r['legalDong'],r['jibun'],
        ' / '.join(p['name'] for p in r['projects']),
        ' / '.join(p['stageLabel'] for p in r['projects']),r.get('rating',{}).get('scoreText')))
        +'<td>'+''.join(f'<a href="{esc(p["sourceUrl"])}">공식 자료</a> ' for p in r['projects'])+'</td></tr>' for r in matched)
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>단지 정비사업 연결 검증</title><style>body{font:16px/1.65 system-ui,sans-serif;max-width:1300px;margin:35px auto;padding:0 20px;color:#202b40}table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;border-bottom:1px solid #ddd;padding:10px;overflow-wrap:anywhere}a{color:#1769c2}.scroll{overflow:auto}</style>
<h1>단지 정비사업 연결 검증</h1><p>고유번호·지역·법정동·지번·공식 구역을 대조했어요. 확인된 자료가 없는 단지는 ‘사업 없음’으로 판정하지 않아요.</p>'''
    page+=f'<p>확인일 {day.isoformat()} · 검사 {len(rows):,}단지 · 연결 {len(matched):,}단지 · 별점 {report["counts"]["rated"]:,}단지</p>'
    page+='<p><strong>단계가 확인된 사업만 별점을 매겼어요.</strong> 이름·법정동·지번이 맞거나, 이름이 같은 공식 구역에 단지 위치가 확인돼야 연결해요. 공동 사업도 각 단지 고유번호는 따로 유지해요.</p>'
    page+='<p>서울 사업장 공개 현황, 노원구 현황, 경기도 2026년 2분기 현황, 인천 2026년 9월 말 현황과 공식 구역을 대조했어요. 사업장 현황과 옛 지도 단계가 다르면 사업장 현황을 먼저 써요. 같은 기준일의 단계가 충돌하면 별점을 보류해요.</p>'
    page+='<p>아래는 연결된 단지예요. 주소가 다르거나 자료가 부족한 경우도 <a href="apartment-development-audit.json">전체 단지 판정 기록</a>에 남겼어요. 모든 비공식 추진 움직임을 확인한 결과는 아니에요.</p>'
    page+='<div class="scroll"><table><thead><tr>'+''.join('<th>'+h+'</th>' for h in ['단지','지역','법정동','지번','공식 사업명','현재 단계','별점','출처'])+'</tr></thead><tbody>'+body+'</tbody></table></div></html>'
    (ROOT/'docs/apartment-development-audit.html').write_text(page)
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':
    result=run()
    raise SystemExit(bool(result['failures']))
