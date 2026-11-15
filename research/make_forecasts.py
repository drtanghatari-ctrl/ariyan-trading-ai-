"""Write a forecast CSV (A046) for one daily dataset. Run on the machine that has the model installed.

  python make_forecasts.py DATA.csv SYMBOL OUT.csv --model naive
  python make_forecasts.py DATA.csv SYMBOL OUT.csv --model kronos  --start 2023-01-01 --draws 5
  python make_forecasts.py DATA.csv SYMBOL OUT.csv --model timesfm --start 2023-01-01

Needs PYTHONPATH=app (this project) plus the model's own packages. Each forecast uses ONLY candles up to and
including its decision bar. Resumable: rows already in OUT.csv are skipped, so you can stop and restart.
Use --limit 3 first to smoke-test a model. The kronos and timesfm adapters follow the projects' published
examples but have NOT been run by the author: expect to adjust them. Only the naive baseline is tested.
Do not forecast beyond the development period if you want a clean final test: use --end 2025-11-11.
"""
import argparse
import csv
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load_d1 import load  # noqa: E402
from ariyan_trading.forecast_signals import HEADER, naive_forecast  # noqa: E402


def adapter_naive(args):
    return 'naive', 'vol60-v1', lambda closes, candles: naive_forecast(closes)


def adapter_kronos(args):
    import pandas as pd
    import torch
    sys.path.insert(0, args.kronos_repo)               # a clone of github.com/shiyu-coder/Kronos
    from model import Kronos, KronosPredictor, KronosTokenizer
    tokenizer = KronosTokenizer.from_pretrained('NeoQuasar/Kronos-Tokenizer-base')
    model = Kronos.from_pretrained('NeoQuasar/Kronos-' + args.kronos_size)
    predictor = KronosPredictor(model, tokenizer, device='cuda:0' if torch.cuda.is_available() else 'cpu',
                                max_context=512)

    def forecast(closes, candles):
        window = candles[-min(len(candles), args.context):]
        frame = pd.DataFrame({'open': [float(c.open) for c in window], 'high': [float(c.high) for c in window],
                              'low': [float(c.low) for c in window], 'close': [float(c.close) for c in window],
                              'volume': [float(c.volume) for c in window]})
        x_ts = pd.Series(pd.to_datetime([c.timestamp_ms for c in window], unit='ms'))
        y_ts = pd.Series([x_ts.iloc[-1] + pd.Timedelta(days=1)])
        finals = sorted(float(predictor.predict(df=frame, x_timestamp=x_ts, y_timestamp=y_ts, pred_len=1, T=1.0,
                                                top_p=0.9, sample_count=1)['close'].iloc[-1])
                        for _ in range(args.draws))
        pick = lambda q: finals[min(len(finals) - 1, max(0, round(q * (len(finals) - 1))))]
        return pick(0.1), pick(0.5), pick(0.9)
    return 'kronos-' + args.kronos_size, 'NeoQuasar', forecast


def adapter_timesfm(args):
    import numpy as np
    from timesfm3 import ModelConfig, TimesFM3Evaluator      # per the project README; adjust to your version
    forecaster = TimesFM3Evaluator(ModelConfig(checkpoint_path='google/timesfm-3.0-pytorch', per_core_batch_size=1,
                                               device=args.device))

    def forecast(closes, candles):
        series = np.log(np.array([float(c) for c in closes[-args.context:]]))
        out = list(forecaster.predict_batch([series], horizon=1, return_quantiles=True,
                                            use_symmetric_averaging=False))[0]
        q = np.exp(out.quantiles[0])                          # nine deciles 0.1..0.9 of the log price
        return float(q[0]), float(q[4]), float(q[8])
    return 'timesfm-3.0', 'google/timesfm-3.0-pytorch', forecast


ADAPTERS = {'naive': adapter_naive, 'kronos': adapter_kronos, 'timesfm': adapter_timesfm}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('data'), ap.add_argument('symbol'), ap.add_argument('out')
    ap.add_argument('--model', choices=sorted(ADAPTERS), required=True)
    ap.add_argument('--start', default=None, help='first decision date YYYY-MM-DD')
    ap.add_argument('--end', default=None, help='last decision date YYYY-MM-DD (use the day before the holdout)')
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--context', type=int, default=400)
    ap.add_argument('--draws', type=int, default=5, help='kronos: sampled paths per forecast')
    ap.add_argument('--kronos-size', default='small')
    ap.add_argument('--kronos-repo', default='Kronos')
    ap.add_argument('--device', default='cpu')
    args = ap.parse_args()
    dataset, _ = load(args.data, args.symbol)
    name, version, forecast = ADAPTERS[args.model](args)
    day = lambda text: None if text is None else int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp() * 1000)
    start, end = day(args.start), day(args.end)
    done = set()
    if os.path.exists(args.out):
        with open(args.out, newline='') as stream:
            done = {int(r['decision_ts_ms']) for r in csv.DictReader(stream)}
    fresh = not os.path.exists(args.out)
    candles, written = dataset.candles, 0
    with open(args.out, 'a', newline='') as stream:
        writer = csv.writer(stream)
        if fresh:
            writer.writerow(HEADER)
        for i, candle in enumerate(candles):
            ts = candle.timestamp_ms
            if i < 61 or ts in done or (start and ts < start) or (end and ts > end):
                continue
            closes = [float(c.close) for c in candles[:i + 1]]
            q10, q50, q90 = forecast(closes, candles[:i + 1])
            writer.writerow([ts, args.symbol, 1, closes[-1], '%.10g' % q10, '%.10g' % q50, '%.10g' % q90, name,
                             version, ts])
            stream.flush()
            written += 1
            if args.limit and written >= args.limit:
                break
    print('wrote %d forecasts to %s' % (written, args.out))


if __name__ == '__main__':
    main()
