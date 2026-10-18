import copy
import unittest
from unittest.mock import Mock, patch

import typesafe_jev as jev


class OccupancyEvidenceReviewTest(unittest.TestCase):
    def test_private_identity_stays_local_and_review_cannot_remove_boundaries(self):
        rows = [{"zoneId": "local-id", "zoneName": "local-name", "roadAddress": "local-address",
                 "latitude": 37.5, "kaptCode": "local-kapt", "evidence": "입주 기간 진행 중"}]
        before = copy.deepcopy(rows)
        response = Mock()
        response.json.return_value = {"answers": {"record_0": {
            "choice": "ongoing", "confidence": .9, "probabilities": {"ongoing": .95}}}}
        with patch.object(jev, "configured", return_value=True), patch.object(jev.requests, "post", return_value=response) as post:
            result = jev.review_occupancy_evidence(rows, "2026-10-16")
        self.assertEqual(post.call_args.kwargs["json"]["state"]["records"], [{"evidence": "입주 기간 진행 중"}])
        self.assertEqual(rows, before)
        self.assertFalse(result["automaticRemovalAllowed"])
        self.assertEqual(result["reviews"][0]["zoneId"], "local-id")

    def test_missing_answer_is_unavailable(self):
        response = Mock()
        response.json.return_value = {"answers": {}}
        with patch.object(jev, "configured", return_value=True), patch.object(jev.requests, "post", return_value=response):
            result = jev.review_occupancy_evidence([{"evidence": "준공"}], "2026-10-16")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reviews"], [])

    def test_missing_credentials_never_calls_network(self):
        with patch.object(jev, "configured", return_value=False), patch.object(jev.requests, "post") as post:
            result = jev.review_occupancy_evidence([{}], "2026-10-16")
        post.assert_not_called()
        self.assertEqual(result["reason"], "not_configured")
