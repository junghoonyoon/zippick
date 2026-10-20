#!/usr/bin/env python3
"""Convert an official Seoul ZIP without smoothing/repairing its boundaries.

Usage: PYTHONPATH=pipeline python scripts/import-map-zone-boundaries.py source.zip --date 2026-09-10
Requires pyshp and pyproj. Download provenance and code definitions are retained.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def definitions(content):
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(content)) as book:
        strings = [''.join(e.itertext()) for e in ET.fromstring(book.read('xl/sharedStrings.xml')).findall('s:si', ns)]
        types, stages = {}, {}
        for name in book.namelist():
            if not re.fullmatch(r'xl/worksheets/sheet\d+.xml', name):
                continue
            for row in ET.fromstring(book.read(name)).findall('.//s:row', ns):
                cells = {}
                for c in row.findall('s:c', ns):
                    v = c.find('s:v', ns)
                    text = v.text if v is not None else ''
                    cells[re.sub(r'\d', '', c.get('r'))] = (strings[int(text)] if c.get('t') == 's' and text else text).strip()
                if re.fullmatch(r'BZ\d+', cells.get('E', '')):
                    types[cells['E']] = cells['D']
                values = list(cells.values())
                for i, value in enumerate(values[:-1]):
                    if re.fullmatch(r'PP\d+', value):
                        stages[value] = values[i+1]
        return types, stages


def convert(path, published):
    import shapefile
    from shapely.geometry import shape, mapping
    from shapely.ops import transform
    from pyproj import CRS, Transformer
    with zipfile.ZipFile(path) as archive:
        files = archive.namelist()
        read = lambda ext: archive.read(next(n for n in files if n.lower().endswith(ext)))
        types, stages = definitions(read('.xlsx'))
        projection = read('.prj').decode()
        convert_xy = Transformer.from_crs(CRS.from_wkt(projection), 4326, always_xy=True).transform
        reader = shapefile.Reader(**{ext: io.BytesIO(read('.'+ext)) for ext in ('shp', 'shx', 'dbf')}, encoding='cp949')
        features = []
        for record in reader.iterShapeRecords():
            raw = record.record.as_dict()
            raw_type, raw_stage = raw['SCLAS_CL'], raw['PROPEL_CD']
            geometry = mapping(transform(convert_xy, shape(record.shape.__geo_interface__)))
            props = {'id': raw['PRESENT_SN'], 'name': raw['DGM_NM'],
                     'projectType': types.get(raw_type, '사업 종류 미확인'),
                     'stage': stages.get(raw_stage, '진행 단계 미확인'),
                     'districtCode': raw['SIGNGU_SE'], 'areaSqm': raw['DGM_AR'],
                     'source': '서울시 도시계획사업 현황(서울플랜+) 공간정보 '+published,
                     'sourceDate': published, 'sourceDataset': 'OA-22712',
                     'sourceNote': '법적 효력이 없는 참고자료', 'rawTypeCode': raw_type,
                     'rawStageCode': raw_stage, 'rawMajorTypeCode': raw['LCLAS_CL']}
            features.append({'type':'Feature', 'id':props['id'], 'properties':props, 'geometry':geometry})
        if len({f['id'] for f in features}) != len(features):
            raise ValueError('Duplicate official boundary IDs; no promotion')
        if not features:
            raise ValueError('Empty official download; no promotion')
        return {'type':'FeatureCollection', 'name':'서울시 도시계획사업 현황(서울플랜+) 공간정보',
                'sourceDate':published, 'sourceUrl':'https://data.seoul.go.kr/dataList/OA-22712/S/1/datasetView.do',
                'sourceArchiveSha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                'sourceCRS':projection, 'codeDefinitions':{'types':types,'stages':stages},
                'geometryProcessing':'CRS conversion only; no repair, simplification or boundary changes',
                'features':features}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive')
    parser.add_argument('--date', required=True)
    parser.add_argument('--output', default=str(ROOT/'data/redevelopment_zones.geojson'))
    args = parser.parse_args()
    data = convert(args.archive, args.date)
    out = Path(args.output)
    temp = out.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':'))+'\n')
    temp.replace(out)
    print(json.dumps({'count':len(data['features']),'sourceDate':data['sourceDate'],'output':str(out)}))
