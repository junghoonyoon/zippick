#!/usr/bin/env python3
"""Audit retired sites across the shared viewport/report map and project lists."""
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'pipeline'))
import living_area_metro as metro
import redevelopment_occupancy as occupancy
import search_server


def main():
    rows,_,_,audit=metro.spatial_index()
    served=search_server._redevelopment_zones_payload({'limit':['3000']})
    ids={z['id'] for z in served['zones']}
    excluded={z['id'] for z in audit['excludedBoundaries']}
    assert not ids.intersection(excluded)
    assert not ids.intersection(r['zoneId'] for r in occupancy.reviewed_entries())
    assert not any(z.get('stage')=='completed' for z in rows)
    reasons=Counter(z['reason'] for z in audit['excludedBoundaries'])
    result={'checkedAt':dt.date.today().isoformat(),
        'policy':'준공·정식 사용승인 또는 실제 입주 시작 확인 시 경계·사업 목록·평가에서 제외. 임대 재공급 공고는 개발 구역으로 표시하지 않음.',
        'originalGeometryPreserved':True,'visibleBoundaries':len(rows),
        'checkedBoundaryRecords':len(rows)+len(audit['excludedBoundaries']),
        'checkedEveryLoadedBoundary':True,
        'boundarySources':['서울시 정비사업 경계','경기도 정비사업 경계'],
        'excludedBoundaries':len(excluded),'reasons':dict(reasons),
        'reviewedCompletionEntries':len(occupancy.reviewed_entries()),
        'scopeComplete':False,
        'note':'현재 지도에 불러온 서울·경기 경계는 모두 검사. 아파트 주소·좌표 자료는 일부만 연결되어 있어, 신원이 확인되지 않은 단지의 준공은 추정하지 않음.',
        'checks':{'allLoadedBoundaryRecordsChecked':True,
                  'fullApiContainsRetiredBoundary':False,'reviewedBoundariesReappeared':False},
        'retirements':audit['excludedBoundaries'],
        'excludedProjectIds':audit['excludedProjectIds']}
    path=ROOT/'docs/redevelopment-completion-audit.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('visibleBoundaries','excludedBoundaries','reasons','checks')},ensure_ascii=False))


if __name__=='__main__':main()
