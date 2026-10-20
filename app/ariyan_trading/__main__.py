"""Offline demonstration only. No broker connectivity."""

from pathlib import Path
from tempfile import TemporaryDirectory

from .engine import PaperEngine, signal


def main():
    prices = [100, 101, 102, 103, 104, 105]
    decision = signal(prices)

    with TemporaryDirectory() as folder:
        engine = PaperEngine(Path(folder) / "demo.sqlite")
        result = engine.execute(decision, prices[-1])

        print("ARIYAN TRADING AI — A001")
        print("MODE: OFFLINE PAPER TRADING")
        print("Signal:", decision)
        print("Execution:", result)
        print("Remaining cash:", round(engine.cash, 2))
        print("Position units:", round(engine.units, 6))
        print("NO LIVE FINANCIAL ACTIONS")


if __name__ == "__main__":
    main()
