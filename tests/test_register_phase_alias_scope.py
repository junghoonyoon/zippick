"""Actual census mismatches must not identify phases through a broad alias."""
import json
from pathlib import Path
import pytest
import apartment_reconstruction as r
import apartment_development as d

CASES=json.loads((Path(__file__).parent/'fixtures/register_phase_alias_scope_20261118.json').read_text())

@pytest.mark.parametrize('case',CASES,ids=[x['entity']['apartmentId'] for x in CASES])
def test_actual_register_without_phase_or_household_proof_stays_unverified(case):
    assert r.profile(case['entity'],case['entry'])['status']=='identity_unverified'


def test_named_phase_keeps_only_same_phase_aliases():
    e={'name':'테스트2단지','legalDong':'테스트동','aliases':['테스트아파트','테스트1단지','테스트2단지아파트']}
    assert d.entity_keys(e)==d.name_keys(e['name'],e['legalDong']) | d.name_keys('테스트2단지아파트',e['legalDong'])


def test_unphased_site_preserves_its_verified_name_aliases():
    e={'name':'테스트','legalDong':'테스트동','aliases':['새이름']}
    assert d.entity_keys(e)==d.name_keys('테스트','테스트동')|d.name_keys('새이름','테스트동')
