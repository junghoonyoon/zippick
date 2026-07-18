import datetime as dt
import sys
import unittest
from pathlib import Path


PIPELINE_DIR = Path(__file__).resolve().parents[1] / "pipeline"
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

import build_presale_supplement as supplement  # noqa: E402


class BuildPresaleSupplementTests(unittest.TestCase):
    def test_clean_complex_name_removes_announcement_round_but_keeps_block(self):
        self.assertEqual(
            supplement.clean_complex_name(
                "남양주왕숙 A-24블록 신혼희망타운(공공분양)(본청약)"
            ),
            "남양주왕숙 A-24블록 신혼희망타운(공공분양)",
        )

    def test_different_planning_blocks_are_not_merged(self):
        first = supplement.blank_candidate()
        first.update({
            "대표단지명": "남양주왕숙 A-24블록",
            "법정동코드": "41360",
            "법정동": "진접읍",
            "_aliases": {"남양주왕숙 A-24블록"},
            "_source_keys": {"청약홈 APT 분양정보"},
            "_priority": 2,
        })
        second = supplement.blank_candidate()
        second.update({
            "대표단지명": "남양주왕숙 B-17블록",
            "법정동코드": "41360",
            "법정동": "진접읍",
            "_aliases": {"남양주왕숙 B-17블록"},
            "_source_keys": {"청약홈 APT 분양정보"},
            "_priority": 2,
        })

        self.assertEqual(len(supplement.merge_candidates([first, second])), 2)

    def test_deal_cutoff_uses_whole_month_boundary(self):
        self.assertEqual(
            supplement.deal_date_cutoff(dt.date(2026, 7, 17), 12),
            "2025-07-01",
        )

    def test_clean_lh_title_removes_revision_and_recruitment_suffix(self):
        self.assertEqual(
            supplement.clean_lh_title(
                "[정정공고][정정공고]고양창릉 S-4블록 공공분양주택 "
                "입주자모집공고 1일전"
            ),
            "고양창릉 S-4블록 공공분양주택",
        )


if __name__ == "__main__":
    unittest.main()
