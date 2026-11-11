# A067 verify the independently retained paper checkpoint after clearance

Before clearance, retain the journal sequence and digest from the published
tip inspection independently of the ledger and anchor files. For example,
retain them with the operator record for that clearance.

Run the A066 diagnostic with the usual database, anchor, selector, FREEZE
pin and key arguments, plus `--recovery-status`,
`--expected-cleared-sequence SEQUENCE` and
`--expected-cleared-digest SHA256`. A matching result includes
`expected_cleared_tip_verified: true`.

The check requires an absent marker, authenticated anchor, successful
balance replay and an exact match to the retained journal tip. A mismatch
or a remaining marker returns an error. This comparison can detect a
coherent rollback to an earlier tip when the independently retained values
are current. It grants no authority to modify the ledger or leave FREEZE.
