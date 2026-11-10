"""Assess current validation evidence for new exposure in offline ATAI."""
import argparse
import json
from pathlib import Path

from .review_inspector import inspect_review

VERSION = 'ARIYAN-A027-PREDICTABILITY-GATE-V1'
INSPECTION_ERRORS = (
    OSError, ValueError, TypeError, KeyError, IndexError, ArithmeticError, RecursionError,
)


def assess_new_exposure(review_directory=None):
    """Return an offline NO_TRADE decision for every currently supported input.

    A025 reviews can explain the decision. A027 has no accepted prospective
    validation format and provides no path to positive admission.
    """
    result = {
        'version': VERSION,
        'scope': 'NEW_EXPOSURE_ONLY',
        'decision': 'NO_TRADE',
        'reason': 'MISSING_VALIDATION_EVIDENCE',
        'prospective_validation_established': False,
        'source_authenticity_established': False,
        'live_authorized': False,
        'review_batch_sha256': None,
        'review_job_count': None,
    }
    if review_directory is None:
        return result

    try:
        review = inspect_review(review_directory)
    except INSPECTION_ERRORS:
        # Paths and parser errors can contain caller-supplied data. Keep the
        # decision stable. The separate A025 command is available for diagnosis.
        result['reason'] = 'UNVERIFIABLE_REVIEW_EVIDENCE'
        return result

    result['reason'] = 'DEVELOPMENT_REVIEW_ONLY'
    result['review_batch_sha256'] = review['batch_sha256']
    result['review_job_count'] = review['job_count']
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path, help='Optional saved A024 review directory')
    args = parser.parse_args(argv)
    print(json.dumps(assess_new_exposure(args.review), indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
