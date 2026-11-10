"""Create real symlink fixtures when the test host permits them."""

from unittest import SkipTest


def symlink_or_skip(link, target, *, target_is_directory=False):
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if getattr(exc, 'winerror', None) == 1314:
            raise SkipTest('Windows denied permission to create a symlink fixture (1314)') from exc
        raise
