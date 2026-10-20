#!/usr/bin/env python3
"""Refresh the official Seoul stage code dictionary; do not change boundary values."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://urban.seoul.go.kr/bsns/getPropelCdByCd.json'
PAGE = 'https://urban.seoul.go.kr/view/html/PMNU1100000001?bsnsCd=BZ101'
FIELDS = ('propelCd', 'propelCdNm', 'bsnsTypeLList', 'propelGrpCd', 'propelGrpNm')


def snapshot(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError('Official stage codes must be a nonempty list')
    codes = [{key: row.get(key) for key in FIELDS} for row in rows]
    if any(not row['propelCd'] or not row['propelCdNm'] for row in codes):
        raise ValueError('Missing stage code or label')
    if len({row['propelCd'] for row in codes}) != len(codes):
        raise ValueError('Duplicate stage code: review source before replacing')
    encoded = json.dumps(codes, ensure_ascii=False, sort_keys=True).encode()
    return {'checkedAt': dt.date.today().isoformat(), 'sourceUrl': URL, 'pageUrl': PAGE,
            'request': {'method': 'POST', 'json': {'propelCd': ''}},
            'recordsSha256': hashlib.sha256(encoded).hexdigest(),
            'note': 'Official code descriptions only; does not update individual project status dates.',
            'codes': codes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/map_zone_stage_codes.json')
    args = parser.parse_args()
    response = requests.post(URL, json={'propelCd': ''}, timeout=30)
    response.raise_for_status()
    result = snapshot(response.json())
    temporary = args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    temporary.replace(args.output)
    print(f"공식 단계 코드 {len(result['codes'])}개 갱신")


if __name__ == '__main__':
    main()
