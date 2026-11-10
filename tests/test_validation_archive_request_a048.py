import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ariyan_trading import validation_archive_request
from ariyan_trading.validation_plan import freeze_plan
from test_binance_archive_a010 import ms
from test_validation_plan_a036 import HOUR, specification


class ValidationArchiveRequestTests(unittest.TestCase):
    def setUp(self):
        self.spec = specification()
        self.spec["market"]["input_format"] = "canonical"
        self.spec["window"] = {"start_ms": ms(2026, 12), "end_ms": ms(2027, 3)}
        self.plan = freeze_plan(self.spec, created_at_ms=0)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.path = root / "plan.json"
        self.path.write_text(json.dumps(self.plan), encoding="utf-8")
        self.snapshot = root / "snapshot"

    def test_derives_exact_p001_months_and_cutoff(self):
        request = validation_archive_request.archive_request_from_plan(self.plan)
        self.assertEqual(request.symbol, "BTCUSDT")
        self.assertEqual(request.interval, "1h")
        self.assertEqual(request.start_month, "2026-12")
        self.assertEqual(request.end_month, "2027-02")
        self.assertEqual(request.as_of_ms, self.spec["window"]["end_ms"])

    def test_rejects_partial_month_noncanonical_and_unsupported_interval(self):
        for section, field, value in (
            ("window", "start_ms", ms(2026, 12) + HOUR),
            ("window", "end_ms", ms(2027, 3) - HOUR),
            ("market", "input_format", "binance-spot"),
            ("market", "interval_ms", 2_700_000),
        ):
            with self.subTest(field=field, value=value):
                spec = {**self.spec, section: {**self.spec[section], field: value}}
                with self.assertRaises(ValueError):
                    validation_archive_request.archive_request_from_plan(
                        freeze_plan(spec, created_at_ms=0),
                    )

    def test_dry_run_and_open_window_make_no_fetch(self):
        end_ns = self.spec["window"]["end_ms"] * 1_000_000
        args = ["--plan", str(self.path)]
        with patch.object(validation_archive_request, "acquire_snapshot") as acquire:
            for now, closed in ((end_ns - 1, False), (end_ns, True)):
                with patch.object(validation_archive_request.time, "time_ns", return_value=now):
                    with redirect_stdout(io.StringIO()) as stdout:
                        self.assertEqual(validation_archive_request.main(args), 0)
                    self.assertIs(json.loads(stdout.getvalue())["window_closed_by_local_clock"], closed)
            with patch.object(validation_archive_request.time, "time_ns", return_value=end_ns - 1):
                with redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit) as error:
                    validation_archive_request.main([*args, "--fetch-output", str(self.snapshot)])
                self.assertEqual(error.exception.code, 2)
                self.assertIn("still open", stderr.getvalue())
            acquire.assert_not_called()

    def test_explicit_fetch_after_close_uses_derived_request(self):
        end_ns = self.spec["window"]["end_ms"] * 1_000_000
        with patch.object(validation_archive_request.time, "time_ns", return_value=end_ns), \
                patch.object(validation_archive_request, "acquire_snapshot", return_value={
                    "dataset": {"raw_sha256": "a" * 64},
                }) as acquire, redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(validation_archive_request.main([
                "--plan", str(self.path), "--fetch-output", str(self.snapshot),
            ]), 0)
        acquire.assert_called_once_with(
            validation_archive_request.archive_request_from_plan(self.plan), self.snapshot,
        )
        self.assertEqual(json.loads(stdout.getvalue())["snapshot_candle_sha256"], "a" * 64)
