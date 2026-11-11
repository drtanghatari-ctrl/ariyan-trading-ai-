# A066 inspect paper checkpoint recovery status

After an uncertain publication or clearance, run the paper checkpoint
diagnostic with `--recovery-status` and the existing database, anchor,
selector, independently retained FREEZE pin and checkpoint key arguments.
This mode reads one SQLite snapshot under the selector lock.

| Status | Observation |
| --- | --- |
| `NO_PENDING_VERIFIED_TIP` | The marker is absent, the authenticated anchor matches the journal tip, and balances replay successfully. |
| `PENDING_AT_PUBLISHED_TIP` | The marker exists and the authenticated anchor matches the journal tip. |
| `PENDING_AT_PREVIOUS_TIP` | The marker exists and the authenticated anchor matches the immediately preceding tip. |
| `PENDING_WITH_DIVERGENT_ANCHOR` | The marker exists and the authenticated anchor matches neither expected tip. |

A missing marker with a mismatched anchor, a malformed marker, or failed
authentication causes an inspection error. The result describes the state
at inspection time and grants no permission to publish, clear or trade.
