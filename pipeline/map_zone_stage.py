"""Explain missing stages and supplement code descriptions from official evidence."""
import json
from functools import lru_cache
import config

PATH = config.ROOT / 'data/map_zone_stage_codes.json'
MISSING = {'', '진행 단계 미확인', '단계 확인 필요', '미확인'}


def revision():
    return PATH.stat().st_mtime_ns if PATH.exists() else None


@lru_cache(maxsize=2)
def _codes(modified):
    return json.loads(PATH.read_text()) if modified else {}


def definition(properties):
    # Never replace a described source stage or infer a code from the name.
    if properties.get('stage', '') not in MISSING:
        return None
    bundle = _codes(revision())
    matches = [row for row in bundle.get('codes', [])
               if row['propelCd'] == properties.get('rawStageCode')
               and properties.get('rawTypeCode') in (row.get('bsnsTypeLList') or '').split(',')]
    if len(matches) != 1 or not matches[0].get('propelCdNm'):
        return None
    return {'code': matches[0]['propelCd'], 'label': matches[0]['propelCdNm'],
            'sourceUrl': bundle['sourceUrl'], 'pageUrl': bundle['pageUrl'],
            'checkedAt': bundle['checkedAt'], 'method': 'official_code_definition'}


def explanation(row, project, conflict, selected, normalized):
    if conflict:
        return {'stageStatus': 'conflict', 'stageReasonCode': 'official_sources_disagree',
                'stageReason': '경계 자료와 사업목록의 단계가 달라 확인 중이에요.'}
    label = selected.get('stageLabel') or ''
    if label not in MISSING:
        return {'stageStatus': 'source_value' if normalized != 'unknown' else 'source_detail',
                'stageReasonCode': 'official_code_supplement' if selected.get('stageDefinition') else 'official_source',
                'stageReason': ('원본에 빠진 코드 설명을 서울플랜 공식 코드표로 확인했어요.'
                                if selected.get('stageDefinition') else ''),
                'stageDefinition': selected.get('stageDefinition')}
    if row.get('sourceId') == 'seoul-plan-boundary' and row.get('rawStageCode'):
        return {'stageStatus': 'unverified', 'stageReasonCode': 'undocumented_source_code',
                'stageReason': '원본에 단계 코드만 있고 뜻을 확인할 설명이 없어요.'}
    return {'stageStatus': 'unverified',
            'stageReasonCode': 'project_stage_missing' if project else 'boundary_has_no_stage_and_no_verified_project',
            'stageReason': ('연결한 공식 사업목록에 단계가 없어요.' if project else
                            '경계 자료에는 단계가 없어요. 같은 사업인지 확인된 사업목록도 아직 연결되지 않았어요.')}
