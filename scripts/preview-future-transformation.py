#!/usr/bin/env python3
"""Build a local QA page with the actual report renderer. Uses real pilot facts and isolated fictional fixtures."""
import copy
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))
import future_transformation as future
import kakao_station_distances


def main():
    html = (ROOT / '앱화면/real-estate-search.html').read_text()
    css = re.search(r'<style>(.*?)</style>', html, re.S).group(1)
    names = ['zippickFutureSourceLink', 'zippickFutureReferenceProjects', 'zippickLifestyleProjectInsight', 'zippickLifestyleChangeHtml', 'zippickReportMapHtml']
    functions = '\n'.join(re.search(r'    function ' + name + r'\([^\n]*\) \{.*?\n    \}', html, re.S).group() for name in names)
    sites = re.search(r'    const ZIPPICK_REPORT_PROJECT_SITES = \{.*?\n    \};', html, re.S).group()
    items = []
    for document in json.loads(future.PILOT_PATH.read_text()):
        entity = future.registry_entity(document['apartmentId'])
        location = kakao_station_distances.cached_station(entity) or {}
        row = {**entity, **{k: location[k] for k in ('latitude', 'longitude') if k in location}}
        items.append({'name': entity['name'], 'futureTransformation': future.analyze(row, entity)})
    fixture = json.loads((ROOT / 'tests/fixtures/future_transformation_ready.json').read_text())
    day = datetime.date.fromisoformat(fixture['asOfDate'])
    items.append({'name': '가상 테스트 · 분석 완료', 'futureTransformation': future.evaluate(fixture['apartmentId'], fixture, as_of=day)})
    partial = copy.deepcopy(fixture)
    partial['measurements']['daily_access'] = None
    items.append({'name': '가상 테스트 · 일부 확인', 'futureTransformation': future.evaluate(fixture['apartmentId'], partial, as_of=day)})
    for state in ('insufficient_data', 'error'):
        result = future.evaluate('fixture-only', as_of=day)
        result['status'] = state
        items.append({'name': '가상 테스트 · ' + state, 'futureTransformation': result})
    js = "const esc = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('\\\"','&quot;');\n"
    js += "const candidateDisplayName = item => item.name || '이 단지'; const candidateMapAddress = item => item.address || '';\n"
    js += sites + '\n' + functions + '\nconst items=' + json.dumps(items) + ';console.log(items.map(item=>`<h2>${esc(item.name)}</h2><div class="zippick-report">${zippickLifestyleChangeHtml(item)}</div>`).join(""));'
    rendered = subprocess.run(['node'], input=js, text=True, capture_output=True, check=True).stdout
    output = ROOT / 'outputs/future-transformation/review.html'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>생활권 변화 검증</title><style>' + css
                      + 'body{background:#fff;padding:24px;max-width:900px;margin:auto}h2{margin:32px 0 16px}.zippick-report{margin-bottom:60px}</style><body><p>로컬 검증 화면 · 실제 공식 자료와 가상 테스트 상태를 구분해 표시합니다.</p>' + rendered + '</body></html>')
    print(output)


if __name__ == '__main__':
    main()
