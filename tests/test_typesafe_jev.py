import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import typesafe_jev  # noqa: E402


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class TypeSafeJevTest(unittest.TestCase):
    def setUp(self):
        typesafe_jev._CACHE.clear()
        self.query = {
            "name": "홍은동 현대",
            "region": "서대문구",
            "legalDong": "홍은동",
        }
        self.candidates = [
            {
                "name": "현대(1,2차)",
                "aliases": ["홍은동 현대"],
                "district": "서대문구",
                "legalDong": "홍은동",
                "jibun": "202-5",
            },
            {
                "name": "현대하이츠",
                "district": "서대문구",
                "legalDong": "홍은동",
                "jibun": "413-38",
            },
        ]

    def test_choice_returns_only_a_high_confidence_candidate(self):
        response = _Response({
            "answers": {
                "apartment_identity": {
                    "type": "choice",
                    "choice": "candidate_0",
                    "probabilities": {
                        "candidate_0": 0.94,
                        "candidate_1": 0.04,
                        "no_match": 0.02,
                    },
                    "confidence": 0.91,
                },
            },
        })
        with mock.patch.object(typesafe_jev.config, "TYPESAFE_API_KEY", "test-key"), mock.patch.object(
            typesafe_jev.requests,
            "post",
            return_value=response,
        ) as post:
            result = typesafe_jev.choose_apartment_identity(self.query, self.candidates)

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["selectedIndex"], 0)
        request_json = post.call_args.kwargs["json"]
        criteria = request_json["questions"]["apartment_identity"]["criteria"]
        self.assertIn("no_match", criteria)
        self.assertEqual(
            request_json["state"]["candidate_apartments"][0]["jibun"],
            "202-5",
        )

    def test_low_confidence_choice_is_not_accepted(self):
        response = _Response({
            "answers": {
                "apartment_identity": {
                    "type": "choice",
                    "choice": "candidate_0",
                    "probabilities": {
                        "candidate_0": 0.67,
                        "candidate_1": 0.25,
                        "no_match": 0.08,
                    },
                    "confidence": 0.59,
                },
            },
        })
        with mock.patch.object(typesafe_jev.config, "TYPESAFE_API_KEY", "test-key"), mock.patch.object(
            typesafe_jev.requests,
            "post",
            return_value=response,
        ):
            result = typesafe_jev.choose_apartment_identity(self.query, self.candidates)

        self.assertEqual(result["status"], "review")
        self.assertIsNone(result["selectedIndex"])

    def test_missing_key_never_calls_remote_service(self):
        with mock.patch.object(typesafe_jev.config, "TYPESAFE_API_KEY", ""), mock.patch.object(
            typesafe_jev.requests,
            "post",
        ) as post:
            result = typesafe_jev.choose_apartment_identity(self.query, self.candidates)

        self.assertEqual(result["status"], "unavailable")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
