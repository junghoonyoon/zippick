import tempfile
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import paid_access
import report_store


class ReportStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store_dir = Path(self.temp_dir.name)
        self.owner_token = "owner-token-long-enough"
        self.report = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "asOf": "2026-07-20",
            "apartment": {"name": "테스트아파트", "region": "성남분당구"},
            "pricing": {"askingPriceEok": 9.2},
            "verdict": {"label": "가격 협상 권장"},
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_owner_and_share_token_can_open_saved_report(self):
        saved = report_store.save(
            self.report,
            self.owner_token,
            store_dir=self.store_dir,
        )

        self.assertEqual(
            report_store.get(
                self.report["id"],
                owner_token=self.owner_token,
                store_dir=self.store_dir,
            ),
            self.report,
        )
        self.assertEqual(
            report_store.get(
                self.report["id"],
                share_token=saved["shareToken"],
                store_dir=self.store_dir,
            ),
            self.report,
        )

    def test_wrong_token_is_rejected(self):
        report_store.save(self.report, self.owner_token, store_dir=self.store_dir)

        with self.assertRaises(PermissionError):
            report_store.get(
                self.report["id"],
                share_token="wrong-token",
                store_dir=self.store_dir,
            )

    def test_owner_can_rotate_share_token(self):
        first = report_store.save(
            self.report,
            self.owner_token,
            store_dir=self.store_dir,
        )

        second = report_store.create_share(
            self.report["id"],
            self.owner_token,
            store_dir=self.store_dir,
        )

        self.assertNotEqual(first["shareToken"], second["shareToken"])
        with self.assertRaises(PermissionError):
            report_store.get(
                self.report["id"],
                share_token=first["shareToken"],
                store_dir=self.store_dir,
            )
        self.assertEqual(
            report_store.get(
                self.report["id"],
                share_token=second["shareToken"],
                store_dir=self.store_dir,
            ),
            self.report,
        )

    def test_lists_only_owned_reports(self):
        report_store.save(self.report, self.owner_token, store_dir=self.store_dir)

        rows = report_store.list_owned(self.owner_token, store_dir=self.store_dir)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "테스트아파트")
        self.assertEqual(
            report_store.list_owned("another-owner-long-enough", store_dir=self.store_dir),
            [],
        )


class PaidAccessTest(unittest.TestCase):
    def test_local_preview_is_allowed_by_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            allowed, status = paid_access.authorize("")

        self.assertTrue(allowed)
        self.assertTrue(status["localPreview"])

    def test_required_access_rejects_wrong_token(self):
        environment = {
            "REPORT_PAYMENT_REQUIRED": "1",
            "REPORT_ACCESS_TOKEN": "paid-token",
            "REPORT_CHECKOUT_URL": "https://example.com/checkout",
        }
        with mock.patch.dict("os.environ", environment, clear=True):
            allowed, payload = paid_access.authorize("wrong")

        self.assertFalse(allowed)
        self.assertEqual(payload["code"], "payment_required")
        self.assertEqual(payload["checkoutUrl"], environment["REPORT_CHECKOUT_URL"])


if __name__ == "__main__":
    unittest.main()
