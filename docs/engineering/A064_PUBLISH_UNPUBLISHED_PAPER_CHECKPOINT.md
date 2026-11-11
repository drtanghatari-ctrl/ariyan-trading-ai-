# A064 publish a recovered paper checkpoint under FREEZE

Use the A062 evidence and the independently retained order fields described
in A063. Set the intent version and action to the `VERSION` and `ACTION`
from `ariyan_trading.paper_unpublished_checkpoint_publication`.
The operator signs the bytes from
`unpublished_checkpoint_publication_payload(intent)` with Ed25519.
Pass the signature, independently trusted operator public key, retained
FREEZE pin and checkpoint key to `publish_unpublished_paper_checkpoint`.

Publication takes the paper selector lock and a SQLite writer reservation.
It reinspects the previous authenticated anchor, checks the exact pending
evidence and signed order, and replays the journal balances. It checks
expiry against the local clock before using the native A006 anchor writer.

Successful publication authenticates the existing journal tip. It leaves the
pending marker, trade journal and FREEZE state in place. For marker removal,
reinspect the published tip and obtain a fresh A060 clearance signature.

If publication raises `PaperCheckpointPublicationUncertain`, inspect the
anchor and marker before deciding how to recover. If the anchor is visibly
advanced, the A065 clearance path syncs the authenticated anchor and its
directory before deleting the marker. The API has no automatic retries or
order resubmission.
