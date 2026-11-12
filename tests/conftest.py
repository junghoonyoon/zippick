"""Unit tests keep production shared facts separate from test fixtures."""
import os
import copy
import json
from pathlib import Path

import pytest

os.environ.setdefault("ZIPPICK_DATA_MODE", "isolated")


@pytest.fixture
def living_area_geocodes(tmp_path, monkeypatch):
    """Freeze only address coordinates; plan dates and scoring stay real."""
    import kakao_station_distances as stations
    import living_area_metro as metro
    rows = json.loads((Path(__file__).parent / 'fixtures/living_area_geocodes.json').read_text())['rows']

    def lookup(target):
        row = next((row for row in rows if all(target.get(k) == v
                    for k, v in row['identity'].items())), None)
        if row is None:
            raise AssertionError(f"Missing address fixture: {target}")
        return {**copy.deepcopy(row['point']), 'coordinateBasis': 'address_geocode'}

    monkeypatch.setattr(stations, 'cached_record', lambda _: None)
    monkeypatch.setattr(metro, 'AUDITED_CENTER_PATH', tmp_path / 'audited.json')
    monkeypatch.setattr(metro, 'CENTER_PATH', tmp_path / 'centers.json')
    monkeypatch.setattr(metro, 'exact_point', lookup)
