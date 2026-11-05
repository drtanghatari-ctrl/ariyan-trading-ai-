"""Intake rejects malformed prices, chronology, units and incomplete bars."""

import hashlib
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from ariyan_trading.market_data import Candle, HEADER, load_candles


class MarketDataA007Tests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "candles.csv"
        self.rows = ["0,100,110,90,105,1", "60000,105,110,100,106,2"]

    def write(self, rows=None, header=None):
        self.path.write_text(
            (",".join(HEADER) if header is None else header) + "\n"
            + "\n".join(self.rows if rows is None else rows) + "\n",
            encoding="utf-8",
        )

    def load(self, **kwargs):
        options = dict(symbol="BTCUSDT", interval_ms=60000,
                       source="synthetic unit-test fixture", as_of_ms=120000)
        options.update(kwargs)
        return load_candles(self.path, **options)

    def test_valid_snapshot_and_byte_hash(self):
        self.write()
        result = self.load()
        self.assertEqual(len(result.candles), 2)
        self.assertEqual(result.candles[0].close, Decimal("105"))
        self.assertEqual(result.raw_sha256, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_rejects_wrong_header_and_extra_fields(self):
        for header, rows in [("time,open,high,low,close,volume", self.rows),
                             (",".join(HEADER), [self.rows[0] + ",extra", self.rows[1]])]:
            with self.subTest(header=header, rows=rows):
                self.write(rows, header)
                with self.assertRaises(ValueError):
                    self.load()

    def test_rejects_bad_prices_and_volume(self):
        for index, value in [(1,"0"), (2,"99"), (3,"106"), (4,"NaN"),
                             (4,"Infinity"), (1,"-1"), (5,"-1"),
                             (1,"1e100"), (1,"1e-20"), (1,""), (1,"True")]:
            with self.subTest(index=index, value=value):
                fields = self.rows[0].split(",")
                fields[index] = value
                self.write([",".join(fields), self.rows[1]])
                with self.assertRaises((ValueError, ArithmeticError)):
                    self.load()

    def test_zero_volume_is_valid_data(self):
        self.write([self.rows[0][:-1] + "0", self.rows[1]])
        self.assertEqual(self.load().candles[0].volume, 0)

    def test_duplicate_reverse_gap_and_misalignment(self):
        for timestamp in ("0", "-60000", "120000", "60001", "60000.0", "6e4"):
            with self.subTest(timestamp=timestamp):
                self.write([self.rows[0], timestamp + ",105,110,100,106,2"])
                with self.assertRaises(ValueError):
                    self.load(as_of_ms=300000)
        self.write(list(reversed(self.rows)))
        with self.assertRaises(ValueError):
            self.load()

    def test_incomplete_bar_and_invalid_metadata(self):
        self.write()
        for kwargs in [dict(as_of_ms=119999), dict(interval_ms=True),
                       dict(interval_ms=0), dict(source=""), dict(symbol="bad symbol"),
                       dict(as_of_ms=True), dict(input_format="guess"),
                       dict(timestamp_unit="guess"), dict(timestamp_unit="us")]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.load(**kwargs)

    def test_empty_short_blank_and_malformed_csv(self):
        for rows in ([], self.rows[:1], ["", self.rows[0]], ['"unclosed', self.rows[0]]):
            self.write(rows)
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.load()

    def test_bounds_on_bytes_and_rows(self):
        self.write()
        with patch("ariyan_trading.market_data.MAX_BYTES", 20):
            with self.assertRaises(ValueError):
                self.load()
        with patch("ariyan_trading.market_data.MAX_ROWS", 1):
            with self.assertRaises(ValueError):
                self.load()

    def test_binance_ms_and_us_are_equivalent(self):
        results = []
        for unit, scale in [("ms", 1), ("us", 1000)]:
            lines = []
            for index in range(2):
                start = index * 60000 * scale
                end = start + 60000 * scale - 1
                lines.append(f"{start},100,110,90,105,1,{end},0,1,0,0,0")
            self.path.write_text("\n".join(lines) + "\n")
            results.append(self.load(input_format="binance-spot", timestamp_unit=unit))
        self.assertEqual(results[0].candles, results[1].candles)
        with self.assertRaises(ValueError):
            self.load(input_format="binance-spot", timestamp_unit="ms")

    def test_binance_close_time_and_us_fraction_rejected(self):
        for line in ["0,100,110,90,105,1,100,0,1,0,0,0",
                     "1,100,110,90,105,1,60000000,0,1,0,0,0"]:
            self.path.write_text(line + "\n" + line + "\n")
            with self.assertRaises(ValueError):
                self.load(input_format="binance-spot", timestamp_unit="us")

    def test_dataset_direct_construction_validates(self):
        self.write()
        dataset = self.load()
        for kwargs in [dict(candles=list(dataset.candles)), dict(raw_sha256="bad"),
                       dict(candles=(dataset.candles[0], dataset.candles[0])),
                       dict(as_of_ms=0), dict(candles=(object(), object()))]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(dataset, **kwargs)
        with self.assertRaises(ValueError):
            Candle(0, 100.0, Decimal("110"), Decimal("90"), Decimal("100"), Decimal("1"))


if __name__ == "__main__":
    unittest.main()
