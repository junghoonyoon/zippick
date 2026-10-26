#!/usr/bin/env python3
"""Extract only public project facts from saved official source documents.

XLSX read-only extracts are produced with the bundled runtime, not rewritten.
No representative names/contact details or arbitrary source scripts are saved.
"""
import argparse
import datetime as dt
import hashlib
import html
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SEOUL = 'https://cleanup.seoul.go.kr/cleanup/bsnssttus/lscrMainIndx.do?cpage=1&pageSize=2000'
NOWON = 'https://www.nowon.kr/www/redevelop/main.do'
INCHEON = 'https://renewal.incheon.go.kr/ires/program/0000-0020-0037/program/board/board_inscr.do?bbs_id=BBSMSTR_000000000001&ntt_id=1317'


def clean(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', str(value or '')))).strip()


def key(*values):
    return hashlib.sha256('|'.join(str(v) for v in values).encode()).hexdigest()[:20]


def seoul_projects(path, checked):
    rows, ordinals = [], []
    text = Path(path).read_text()
    for tr in re.findall(r'<tr\b.*?</tr>', text, re.S|re.I):
        cells = [clean(td) for td in re.findall(r'<td\b.*?</td>', tr, re.S|re.I)]
        if len(cells) < 6 or not cells[0].isdigit():
            continue
        ordinals.append(int(cells[0]))
        slug = re.search(r"cafeOpenPopup\('([^']+)'", tr)
        source_url = ('https://cleanup.seoul.go.kr/cafe/mainIndx.do?cafeUrl=' + slug[1]) if slug else SEOUL
        rows.append({'id':'cleanup:' + (slug[1] if slug else key(cells[1:6])),
            'name':cells[3], 'province':'서울특별시', 'district':cells[1], 'address':cells[4],
            'projectTypeLabel':cells[2], 'stageLabel':cells[5], 'sourceId':'cleanup-business',
            'sourceUrl':source_url, 'inventoryUrl':SEOUL, 'sourceDate':None,
            'checkedAt':checked, 'sourcePriority':100})
    if not rows or len(rows) != max(ordinals) or len(set(ordinals)) != len(rows):
        raise ValueError('partial Seoul business list')
    return rows


def nowon_projects(path, checked):
    text = Path(path).read_text()
    rows = json.JSONDecoder().raw_decode(text.split('var redevelopSites =',1)[1].lstrip())[0]
    result = []
    for row in rows:
        if row['categoryNm'] != '재건축' and not re.search(r'재개발|재건축|가로주택', row['siteName'] + row['typeNm']):
            continue
        result.append({'id':'nowon:' + str(row['siteNo']), 'name':row['siteName'],
            'province':'서울특별시', 'district':'노원구', 'legalDong':row['dongNm'],
            'address':row['location'], 'projectTypeLabel':'재건축' if row['categoryNm']=='재건축' else row['typeNm'],
            'stageLabel':row['currentStepName'] or row['typeNm'], 'sourceAsOfMonth':row['baseDate'],
            'sourceId':'nowon-business', 'sourceUrl':f"https://www.nowon.kr/www/redevelop/detail.do?siteNo={row['siteNo']}",
            'inventoryUrl':NOWON, 'sourceDate':None, 'checkedAt':checked, 'sourcePriority':90})
    return result


def incheon_projects(paths, checked):
    result = []
    aliases = {'제물포구':['중구','동구'], '서해구':['서구'], '검단구':['서구']}
    for kind, path in enumerate(paths):
        sheets = json.loads(Path(path).read_text())
        rows = next(iter(sheets.values()))
        count = 0
        for number, row in enumerate(rows,1):
            if not isinstance(row[0], (int,float)) or isinstance(row[0], bool):
                continue
            if kind == 0:
                district, name, address, project_type, stage = row[1],row[2],row[3],row[5],row[14]
            else:
                district, name, address, project_type, stage = row[1],row[3],row[6],row[2],row[10]
            if not all((district,name,address,project_type)):
                continue
            count += 1
            result.append({'id':'incheon:' + key(kind,name,address), 'name':name,
                'province':'인천광역시', 'district':district, 'districtAliases':aliases.get(district,[]),
                'districtAliasBasis':'2026 행정구역 개편 전 검색 원본과 법정동·지번을 함께 대조',
                'address':address, 'projectTypeLabel':project_type, 'stageLabel':clean(stage),
                'sourceId':'incheon-renewal-202609' if kind==0 else 'incheon-small-renewal-202609',
                'sourceUrl':INCHEON, 'sourceDate':'2026-09-30', 'publishedAt':'2026-10-08',
                'checkedAt':checked, 'sourcePriority':90, 'sourceSheet':next(iter(sheets)), 'sourceRow':number})
        if count != (169 if kind==0 else 112):
            raise ValueError(f'Incheon source count mismatch: {kind}: {count}')
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--seoul-html',required=True)
    parser.add_argument('--nowon-html',required=True)
    parser.add_argument('--incheon-json',nargs=2,required=True)
    parser.add_argument('--checked-at',default=dt.date.today().isoformat())
    parser.add_argument('--output',default=str(ROOT/'data/apartment_development_sources.json'))
    args=parser.parse_args()
    rows = seoul_projects(args.seoul_html,args.checked_at) + nowon_projects(args.nowon_html,args.checked_at)
    rows += incheon_projects(args.incheon_json,args.checked_at)
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('duplicate official project id')
    sources = [args.seoul_html,args.nowon_html,*args.incheon_json]
    result={'version':1,'checkedAt':args.checked_at,'useContext':'noncommercial_reference',
        'scopeComplete':False, 'sources':[{'url':u,'checkedAt':args.checked_at} for u in (SEOUL,NOWON,INCHEON)],
        'inputHashes':[hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sources],
        'projects':rows}
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    from collections import Counter
    print(json.dumps({'projects':len(rows),'sourceCounts':dict(Counter(r['sourceId'] for r in rows))},ensure_ascii=False))


if __name__=='__main__':main()
