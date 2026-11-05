"""A007 bounded, offline candle intake. No network or trading operations."""

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .ledger_validation import bounded_decimal

MAX_ROWS = 100_000
MAX_BYTES = 32 * 1024 * 1024
MAX_VALUE = Decimal("1000000000000000")
HEADER = ["timestamp_ms", "open", "high", "low", "close", "volume"]


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def number(value, name, allow_zero=False):
    result = bounded_decimal(value)
    if result < 0 or (not allow_zero and result == 0) or result > MAX_VALUE:
        raise ValueError(f"{name} is outside the supported range")
    return result


@dataclass(frozen=True)
class Candle:
    timestamp_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self):
        integer(self.timestamp_ms, "timestamp_ms")
        # Catch accidental microseconds, while allowing dates through year 9999.
        if self.timestamp_ms > 253_402_300_799_000:
            raise ValueError("Timestamp outside millisecond date range")
        for name in ("open", "high", "low", "close", "volume"):
            value = getattr(self, name)
            if type(value) is not Decimal:
                raise ValueError("Candle numeric fields must be Decimal")
            number(value, name, allow_zero=(name == "volume"))
        if not (self.low <= self.open <= self.high
                and self.low <= self.close <= self.high):
            raise ValueError("Inconsistent OHLC bounds")


@dataclass(frozen=True)
class CandleDataset:
    candles: tuple
    symbol: str
    interval_ms: int
    source: str
    as_of_ms: int
    raw_sha256: str
    input_format: str
    timestamp_unit: str

    def __post_init__(self):
        integer(self.interval_ms, "interval_ms", 1)
        integer(self.as_of_ms, "as_of_ms")
        if not isinstance(self.symbol, str) or not re.fullmatch(
            r"[A-Z0-9][A-Z0-9_.:/-]{0,39}", self.symbol
        ):
            raise ValueError("Invalid symbol label")
        if (not isinstance(self.source, str) or not self.source.strip()
                or len(self.source) > 2048):
            raise ValueError("A nonempty source label is required")
        if not isinstance(self.raw_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.raw_sha256
        ):
            raise ValueError("Invalid input SHA256")
        if self.input_format not in ("canonical", "binance-spot"):
            raise ValueError("Unsupported input format")
        if self.timestamp_unit not in ("ms", "us"):
            raise ValueError("Timestamp unit must be ms or us")
        if self.input_format == "canonical" and self.timestamp_unit != "ms":
            raise ValueError("Canonical CSV requires millisecond timestamps")
        if type(self.candles) is not tuple or not 2 <= len(self.candles) <= MAX_ROWS:
            raise ValueError(f"Dataset requires 2..{MAX_ROWS} candles")
        previous = None
        for candle in self.candles:
            if type(candle) is not Candle:
                raise ValueError("Dataset contains a non-Candle object")
            if candle.timestamp_ms % self.interval_ms:
                raise ValueError("Candle is not aligned to the interval")
            if previous is not None and candle.timestamp_ms - previous != self.interval_ms:
                raise ValueError("Duplicate, unordered, or missing candle")
            if candle.timestamp_ms + self.interval_ms > self.as_of_ms:
                raise ValueError("Dataset includes an incomplete/future candle")
            previous = candle.timestamp_ms


def _timestamp(text):
    if not re.fullmatch(r"[0-9]{1,18}", text):
        raise ValueError("Timestamp must be a nonnegative integer")
    return int(text)


def load_candles(path, *, symbol, interval_ms, source, as_of_ms,
                 input_format="canonical", timestamp_unit="ms"):
    """Read one bounded CSV snapshot, reject gaps rather than repairing them.

    canonical: exact six-column header, timestamps in milliseconds.
    binance-spot: headerless twelve-column public-data klines, explicit unit.
    SHA256 identifies bytes; source/symbol labels are caller assertions.
    """
    integer(interval_ms, "interval_ms", 1)
    if input_format not in ("canonical", "binance-spot"):
        raise ValueError("Unsupported input format")
    if timestamp_unit not in ("ms", "us"):
        raise ValueError("Timestamp unit must be ms or us")
    if input_format == "canonical" and timestamp_unit != "ms":
        raise ValueError("Canonical CSV requires millisecond timestamps")
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("CSV exceeds the 32 MiB input limit")
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    if input_format == "canonical" and next(reader, None) != HEADER:
        raise ValueError("CSV header must be " + ",".join(HEADER))
    candles = []
    try:
        for row in reader:
            if len(candles) >= MAX_ROWS:
                raise ValueError("CSV exceeds the candle count limit")
            expected = 6 if input_format == "canonical" else 12
            if len(row) != expected:
                raise ValueError(f"Expected {expected} fields per row")
            fields = [field.strip() for field in row]
            opened = _timestamp(fields[0])
            scale = 1000 if timestamp_unit == "us" else 1
            if opened % scale:
                raise ValueError("Open timestamp is not an exact millisecond")
            if input_format == "binance-spot":
                closed = _timestamp(fields[6])
                if closed != opened + interval_ms * scale - 1:
                    raise ValueError("Binance close time does not match interval/unit")
            values = [number(value, name, allow_zero=(name == "volume"))
                      for value, name in zip(fields[1:6], HEADER[1:])]
            candles.append(Candle(opened // scale, *values))
    except (ValueError, TypeError, csv.Error) as exc:
        raise ValueError(f"CSV line {reader.line_num}: {exc}") from exc
    return CandleDataset(
        tuple(candles), symbol, interval_ms, source, as_of_ms,
        hashlib.sha256(raw).hexdigest(), input_format, timestamp_unit,
    )
