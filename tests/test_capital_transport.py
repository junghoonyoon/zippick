"""Transport-plan references must be traceable and never imply direct benefit."""
import capital_transport
import planned_rail


def test_official_inventory_is_complete_historical_snapshot():
    data = capital_transport.inventory()
    assert data['period'] == '2021-2025'
    assert {key: len(rows) for key, rows in data['categories'].items()} == {
        'rail': 29, 'road': 7, 'brt': 8, 'transfer': 32}
    assert data['currentStatus'] == '사업별 2026년 진행 상태 미검증'
    transfer = capital_transport.transfer_plan()
    assert len(transfer['projects']) == 35
    assert {row[3] for row in transfer['projects']} == {'신규', '계속', '추가검토'}
    brt = capital_transport.brt_plan()
    assert len(brt['projects']) == 11
    assert {row[2] for row in brt['projects']} == {'신규', '계속'}
    road = capital_transport.road_plan()
    assert len(road['projects']) == 5
    assert sum(not item['scopes'] for item in road['projects']) == 1


def test_every_capital_province_has_coverage_envelope_without_fake_distance():
    for province, city, district in (
        ('서울특별시', '', '동대문구'), ('경기도', '성남시', '성남수정구'),
        ('인천광역시', '', '서구')):
        report = capital_transport.for_complex({
            'province': province, 'city': city, 'district': district,
            'address': f'{province} {city or district} 시험동 1'})
        assert report['status'] == 'partial'
        assert report['inventory']['counts']['rail'] == 29
        assert all('distanceMeters' not in project and project['relation']
                   and project['sourceUrl'].startswith('https://') for project in report['matchedPlans'])


def test_existing_reviewed_rail_is_only_current_reference_source():
    sample = {'province': '서울특별시', 'district': '동대문구', 'address': '서울특별시 동대문구 이문동 1'}
    report = capital_transport.for_complex(sample)
    assert report['matchedPlans']
    assert {item['id'] for item in report['matchedPlans'] if item['category'] == 'rail'} == {
        item['id'] for item in planned_rail.planned_rail_for_candidate(sample)}
    assert any(item['name'] == '청량리역 환승센터' for item in report['matchedPlans'])
    assert any(item['name'] == '검암역 복합환승센터' for item in capital_transport.for_complex({
        'province':'인천광역시', 'district':'서구'})['matchedPlans'])
    assert any(item['name'] == '성남 BRT(1·2단계)' for item in capital_transport.for_complex({
        'province':'경기도', 'city':'성남시'})['matchedPlans'])
    assert any(item['name'] == '중봉터널 민간투자사업' for item in capital_transport.for_complex({
        'province':'인천광역시', 'district':'서구'})['matchedPlans'])
    assert not any(item['name'] == '문학IC~공단고가교 도로 건설사업' for item in
                   capital_transport.for_complex({'province':'인천광역시', 'district':'서구'})['matchedPlans'])
    assert capital_transport.for_complex({'province': '부산광역시'})['status'] == 'out_of_scope'


def test_wirye_sinsa_is_shared_regional_reference_without_invented_station():
    reports = [
        {'province':'경기도', 'city':'성남시', 'district':'성남수정구'},
        {'province':'경기도', 'district':'성남수정구'},
        {'address':'경기도 성남시 수정구 산성동 1336'},
        {'province':'서울특별시', 'district':'송파구'},
        {'province':'서울특별시', 'district':'강남구'},
    ]
    for identity in reports:
        line = next(p for p in capital_transport.for_complex(identity)['matchedPlans']
                    if p['id'] == 'wirye-sinsa')
        assert line['stageCode'] == 'planning'
        assert line['regionalReference'] is True
        assert line['stations'] == []
        assert '예비타당성조사 통과' in line['stage']
        assert 'distanceMeters' not in line
        assert line['sourceUrl'].startswith('https://www.seoul.go.kr/')
    for identity in ({'province':'경기도', 'city':'성남시', 'district':'성남중원구'},
                     {'province':'서울특별시', 'district':'서초구'}):
        assert not any(p['id'] == 'wirye-sinsa' for p in capital_transport.for_complex(identity)['matchedPlans'])
