# A065 sync the authenticated anchor before paper marker clearance

An anchor can be visible at the journal tip after the native writer replaces
the file and before the directory sync completes. The A060 signed clearance
API now verifies the opened anchor against the approved tip and syncs the
file and its parent directory before removing the pending marker.

The selector lock and SQLite writer reservation cover inspection, sync and
clearance. If either sync fails, the marker stays in place. A changed anchor
file or parent directory identity aborts clearance, and the signature must
still be current after sync. The existing checkpoint verification runs
before the SQLite commit.

The path requires filesystem support for file and directory sync, as does
native A006 anchor publication. Tests exercise sync failures and replacement
during sync. They do not simulate a physical power cut.
