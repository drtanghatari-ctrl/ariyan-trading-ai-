"""Regression guard for the twelve legacy fixture connection-allocation paths."""
import sqlite3
import unittest
from unittest.mock import patch

CASES = (
    'test_durable_integrity.DurableIntegrityTests.test_missing_opening_balance_fails_closed',
    'test_durable_ledger.DurableLedgerTests.test_reject_corrupted_opening_balance',
    'test_durable_recovery.DurableRecoveryTests.test_reject_modified_cash_delta',
    'test_durable_recovery.DurableRecoveryTests.test_reject_modified_units_delta',
    'test_durable_recovery.DurableRecoveryTests.test_reject_sequence_gap',
    'test_durable_schema_integrity.DurableSchemaIntegrityTests.test_missing_journal_must_fail_closed',
    'test_journal_tampering_a005.JournalTamperingA005Tests.test_consistent_transaction_rewrite_is_rejected',
    'test_ledger_identity_a006.LedgerIdentityTests.test_invalid_identity_rejected_on_reopen',
    'test_ledger_identity_a006.LedgerIdentityTests.test_legacy_missing_identity_is_not_auto_enrolled',
    'test_process_crash_recovery.ProcessCrashRecoveryTests.test_uncommitted_transaction_is_rolled_back',
    'test_process_crash_recovery.ProcessCrashRecoveryTests.test_committed_transaction_survives_crash',
    'test_schema_constraints_a005.SchemaConstraintsA005Tests.test_existing_a004_database_reopens',
)


class SqliteCleanupA019Tests(unittest.TestCase):
    def test_legacy_fixture_connections_are_closed_after_their_tests(self):
        real_connect = sqlite3.connect
        connections = []
        custom_factories = []

        class TrackedConnection(sqlite3.Connection):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs)
                connections.append(self)

        def connect(*args,**kwargs):
            if len(args)>5 or 'factory' in kwargs:
                custom_factories.append(True)
            else:
                kwargs['factory'] = TrackedConnection
            return real_connect(*args,**kwargs)

        try:
            suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in CASES)
            result = unittest.TestResult()
            with patch('sqlite3.connect',side_effect=connect):
                suite.run(result)
            self.assertEqual(result.testsRun,len(CASES))
            self.assertEqual(result.errors,[])
            self.assertEqual(result.failures,[])
            self.assertEqual(custom_factories,[])
            self.assertGreaterEqual(len(connections),len(CASES))
            unclosed = []
            for index,connection in enumerate(connections):
                try:
                    connection.execute('SELECT 1')
                except sqlite3.ProgrammingError:
                    pass  # Closed connections reject even a trivial query.
                else:
                    unclosed.append(index)
            self.assertEqual(unclosed,[],f'Fixture connections remained open: {unclosed}')
        finally:
            # The guard owns strong references so it can inspect actual handles.
            # Cleanup occurs even when the regression assertion fails.
            for connection in connections:
                connection.close()


if __name__ == '__main__':
    unittest.main()
