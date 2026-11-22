"""One-off: record in the experiment registry that A044 already evaluated the full EURUSD D1 sample.

Usage: PYTHONPATH=app python research/register_eurusd_disclosure.py REGISTRY.jsonl
Safe to run once; refuses if the disclosure is already present.
"""
import sys

from ariyan_trading.research_controls import ExperimentRegistry

SHA = 'b91fd22f64bc5af3fa21c01bf4b1e04795b80f7f8abd29ee6420b81e307bf037'


def main(path):
    reg = ExperimentRegistry(path)
    if any(r['dataset_sha256'] == SHA and r['kind'] in ('DISCLOSURE', 'LEGACY_FULL_SAMPLE') for r in reg.records()):
        raise SystemExit('already registered')
    reg.log('LEGACY_FULL_SAMPLE', 'eurusd_d1_textbook', SHA,
            {'symbol': 'EURUSD', 'study': 'A044', 'n_trials': 64, 'contaminated_holdout': True,
             'detail': '14 fixed strategies x 2 swap scenarios are reported; 50 walk-forward candidates'},
            None, 'A044 evaluated the whole 2018-11-13..2026-11-12 sample before any holdout was locked.')
    reg.log('DISCLOSURE', 'eurusd_d1_textbook', SHA,
            {'symbol': 'EURUSD', 'contaminated_holdout': True},
            None, 'The last 12 months of EURUSD are NOT a clean holdout. Its true final test is forward paper trading.')


if __name__ == '__main__':
    main(sys.argv[1])
