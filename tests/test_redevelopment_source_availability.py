"""An audited absence is different from unavailable or excluded source data."""
import json

import pytest
import redevelopment_analysis as redevelopment


@pytest.mark.parametrize("source,geometry,expected", [
    (None, True, "ok"),
    ("OA-22712", True, "data_unavailable"),
    (None, False, "data_unavailable"),
])
def test_completed_only_source_does_not_hide_unavailable_data(tmp_path, monkeypatch,
                                                            source, geometry, expected):
    feature = {
        "type": "Feature", "id": "completed-fixture",
        "properties": {"name": "완료된 가상구역", "projectType": "재건축",
                       "stage": "준공", "sourceDataset": source},
        "geometry": {"type": "Polygon", "coordinates": [[
            [127, 37.5], [127.001, 37.5], [127.001, 37.501],
            [127, 37.501], [127, 37.5],
        ]]} if geometry else None,
    }
    path = tmp_path / "zones.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}))
    monkeypatch.setattr(redevelopment, "DATA_PATH", path)
    monkeypatch.setattr(redevelopment, "_CACHE", {"mtime": None, "projects": [], "loadOk": False})
    projects, status = redevelopment.nearby_projects(
        {"latitude": 37.5, "longitude": 127}, {"province": "서울특별시"})
    assert projects == []
    assert status == expected
