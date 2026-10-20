"""Versioned map display policy. Unknown is never a reference classification.

Colors describe the source's area category, not approval, profitability or stage.
Keep broader planning areas separate from individual renewal areas.
"""
VERSION = '2026-10-19.1'
RENEWAL_TYPES = frozenset({
    '재개발(주택정비형)', '재개발(도시정비형)', '재건축(공동)', '재건축(단독)',
    '가로주택정비사업', '소규모재건축사업', '소규모재개발사업', '자율주택정비사업',
    '신속통합기획', '모아타운', '재정비촉진구역', '시장정비사업',
    '주거환경개선(정비형)', '주거환경개선(관리형)',
})
REFERENCE_TYPES = frozenset({
    '공공주택지구조성사업', '청년안심주택', '도시재생활성화지역', '리모델링활성화구역',
    '존치관리구역', '장기전세주택', '역세권 활성화', '재정비촉진지구', '도시개발사업',
    '도심 공공주택 복합사업', '미리내집', '존치정비구역', '사전협상제',
})
# Codes are checked together with the official GIS layer. "기타" is unresolved.
GG_KINDS = {(12, 'UDR100'): 'renewal', (13, 'UDT100'): 'renewal',
            (14, 'UDA100'): 'reference', (15, 'UDS100'): 'renewal'}
LABELS = {'renewal': '정비사업', 'reference': '참고 구역', 'unknown': '확인 중'}


def classify(row, project=None):
    kind, reason = 'unknown', 'unmapped_source_type'
    if row.get('sourceId') == 'seoul-plan-boundary':
        value = row.get('projectTypeLabel')
        if value in RENEWAL_TYPES:
            kind, reason = 'renewal', 'official_seoul_project_type'
        elif value in REFERENCE_TYPES:
            kind, reason = 'reference', 'official_seoul_reference_type'
    elif row.get('sourceId') == 'gg-plan-boundary':
        kind = GG_KINDS.get((row.get('sourceLayer'), row.get('useCode')), 'unknown')
        reason = 'official_gg_layer_and_code' if kind != 'unknown' else 'unmapped_gg_code'
    # A project join cannot silently turn a broad reference area into a project.
    if project and kind == 'reference' and project.get('projectType') in ('redevelopment', 'reconstruction'):
        kind, reason = 'unknown', 'boundary_project_category_conflict'
    if project and kind == 'renewal':
        label = row.get('projectTypeLabel') or ''
        expected = 'reconstruction' if '재건축' in label else 'redevelopment' if '재개발' in label else None
        actual = project.get('projectType')
        if expected and actual in ('redevelopment', 'reconstruction') and expected != actual:
            kind, reason = 'unknown', 'boundary_project_subtype_conflict'
    return {'zoneKind': kind, 'zoneKindLabel': LABELS[kind],
            'classificationReason': reason, 'classificationVersion': VERSION}


def coverage():
    return {'scopeComplete': False, 'status': 'partial', 'classificationVersion': VERSION,
            'regions': {'서울특별시': 'partial', '경기도': 'partial', '인천광역시': 'missing'},
            'note': '공개 경계 자료 기준 · 수도권 전체 확인 중 · 인천 경계 미연결'}
