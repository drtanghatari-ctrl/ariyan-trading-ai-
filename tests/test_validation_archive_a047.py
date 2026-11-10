import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ariyan_trading import binance_archive, validation_evaluation
from ariyan_trading.validation_plan import freeze_plan
from test_binance_archive_a010 import fixture, ms
from test_validation_plan_a036 import specification


class ValidationArchiveTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.snapshot = self.root / "snapshot"
        self.start = ms(2025, 1)
        self.end = ms(2025, 2)
        spec = specification()
        spec["market"].update(interval_ms=86_400_000, input_format="canonical")
        spec["window"].update(start_ms=self.start, end_ms=self.end)
        self.spec = spec
        self.plan = freeze_plan(spec, created_at_ms=0)
        request = binance_archive.BinanceSpotRequest("BTCUSDT", "1d", "2025-01", "2025-01", self.end)
        downloads, _ = fixture("BTCUSDT", "2025-01")
        with patch.object(binance_archive, "_download", side_effect=lambda url, limit: downloads[url]):
            self.manifest = binance_archive.acquire_snapshot(request, self.snapshot)

    def evaluate(self, plan=None):
        return validation_evaluation.evaluate_plan(
            self.plan if plan is None else plan, None, as_of_ms=self.end,
            binance_snapshot=self.snapshot,
        )

    def test_archive_report_reproduces_with_timestamp_record(self):
        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        output = self.root / "report.json"
        timestamp = {"receipt_sha256": "b" * 64}
        args = [
            "--plan", str(plan_path), "--binance-snapshot", str(self.snapshot),
            "--timestamp-receipt", "receipt.tsr", "--timestamp-ca-file", "ca.pem",
            "--expected-timestamp-ca-sha256", "a" * 64,
        ]
        with patch.object(validation_evaluation, "verify_timestamp", return_value=timestamp), \
                patch.object(binance_archive, "_download", side_effect=AssertionError("Offline")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(validation_evaluation.main([*args, "--output", str(output)]), 0)
            self.assertEqual(validation_evaluation.main([
                *args, "--verify-report", str(output),
                "--expected-plan-sha256", self.plan["plan_sha256"],
            ]), 0)

        report = json.loads(output.read_bytes())
        self.assertEqual(report["version"], "ARIYAN-A047-VALIDATION-EVALUATION-V1")
        self.assertEqual(report["plan_timestamp_check"], timestamp)
        archive = report["archive_snapshot_check"]
        canonical = json.dumps(self.manifest, sort_keys=True, separators=(",", ":")).encode("ascii")
        self.assertEqual(archive["manifest_sha256"], hashlib.sha256(canonical).hexdigest())
        self.assertEqual(archive["candle_csv_sha256"], report["evaluation"]["dataset"]["raw_sha256"])
        self.assertFalse(archive["source_independently_authenticated"])

    def test_rejects_wrong_market_and_window_before_replay(self):
        with patch.object(validation_evaluation, "evaluate_periods") as replay:
            for section, field, value in (
                ("market", "symbol", "ETHUSDT"), ("window", "start_ms", ms(2025, 1, 2)),
            ):
                with self.subTest(field=field):
                    spec = {**self.spec, section: {**self.spec[section], field: value}}
                    with self.assertRaisesRegex(ValueError, "market or coverage differs"):
                        self.evaluate(freeze_plan(spec, created_at_ms=0))
            replay.assert_not_called()

    def test_rejects_changed_candle_bytes_after_snapshot_verification(self):
        canonical = self.snapshot / "candles.csv"

        def verify_then_change(path):
            result = binance_archive.verify_snapshot(path)
            canonical.write_bytes(canonical.read_bytes().replace(b",105,", b",104,"))
            return result

        with patch.object(validation_evaluation, "verify_snapshot", side_effect=verify_then_change), \
                patch.object(validation_evaluation, "evaluate_periods") as replay:
            with self.assertRaisesRegex(ValueError, "Candle bytes differ"):
                self.evaluate()
            replay.assert_not_called()
