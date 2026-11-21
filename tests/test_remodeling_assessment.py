import datetime as dt

import pytest

import apartment_reconstruction
import remodeling_assessment


@pytest.mark.parametrize("apartment_id,district,dong,jibun,floors,coverage,estimated", [
    ("11710120099495", "송파구", "잠실동", "22", 33, 15.17, False),
    ("11110100000039", "종로구", "창신동", "702", 14, 22.63, True),
])
def test_audited_remodeling_evidence_is_scored_independently_of_reconstruction_register(
    monkeypatch, apartment_id, district, dong, jibun, floors, coverage, estimated
):
    entity = {"apartmentId": apartment_id, "province": "서울특별시",
              "district": district, "legalDong": dong, "jibun": jibun}
    day = dt.date(2026, 11, 21)
    monkeypatch.setattr(apartment_reconstruction, "_conditions",
                        lambda *args, **kwargs: {"status": "identity_unverified", "profile": {}})
    assessment = apartment_reconstruction.analyze(entity, {}, {}, day=day)["remodelingAssessment"]
    assert assessment["stars"] == 3
    assert assessment["highestResidentialFloors"]["value"] == floors
    assert assessment["buildingCoverage"]["value"] == coverage
    assert assessment["buildingCoverage"]["estimated"] is estimated
    assert remodeling_assessment.evaluate({**entity, "jibun": "999"}, {}, day=day)["stars"] is None


def test_snapshot_contains_all_audited_current_floor_counts():
    records = remodeling_assessment._read(remodeling_assessment.revision())
    assert sum("floor" in row for row in records.values()) == 19_250
