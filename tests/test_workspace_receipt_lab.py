"""Deterministic storage probes, not product/runtime qualification."""
import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'workspace_receipt_lab.py'
spec = importlib.util.spec_from_file_location('workspace_receipt_lab', PATH)
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


class ReceiptLabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fictional.db'
        self.store = lab.ReceiptLab.create_fixture(self.path)
        self.addCleanup(self.store.close)
        self.store.seed('alpha', 'work')
        self.fence = self.store.claim('alpha', 'work', 'worker-a', now=100, until=200)

    def request(self, **changes):
        data = dict(scope='alpha', work='work', actor='worker-a', key='op-1',
                    revision=0, epoch=1, policy=1, fence=self.fence,
                    result_digest='a' * 64, now=150)
        return dict(data, **changes)

    def apply(self, **changes):
        return self.store.accept(**self.request(**changes))

    def counts(self):
        return self.store.counts('alpha', 'work')

    def alter(self, sql, params=()):
        self.store.db.execute(sql, params)

    def rejected(self, reason, **changes):
        before = self.counts()
        with self.assertRaisesRegex(lab.Conflict, reason):
            self.apply(**changes)
        self.assertEqual(before, self.counts())

    def test_accept_commits_result_receipt_and_outbox_but_not_human_completion(self):
        receipt = self.apply()
        self.assertEqual(receipt['revision'], 1)
        self.assertEqual(self.counts(), (1, 1, 1))
        row = self.store.db.execute('SELECT state,human_state FROM work').fetchone()
        self.assertEqual(tuple(row), ('result-recorded', 'open'))

    def test_same_request_replays_one_receipt(self):
        first = self.apply()
        self.assertEqual(first, self.apply(now=900))
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_changed_payload_under_same_key_is_a_conflict(self):
        self.apply()
        self.rejected('key-reused', result_digest='b' * 64)

    def test_changed_binding_under_same_key_is_a_conflict(self):
        self.apply()
        self.rejected('key-reused', revision=1)

    def test_expired_lease_cannot_write(self):
        self.rejected('lease', now=200)

    def test_replaced_holder_and_fence_cannot_write(self):
        next_fence = self.store.claim('alpha', 'work', 'worker-b', now=201, until=301)
        self.assertGreater(next_fence, self.fence)
        self.rejected('lease', now=220)
        self.apply(actor='worker-b', fence=next_fence, now=220)
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_unexpired_claim_is_not_stolen(self):
        with self.assertRaisesRegex(lab.Conflict, 'busy'):
            self.store.claim('alpha', 'work', 'worker-b', now=150, until=300)
        self.apply()

    def test_fence_is_checked_independently_of_holder(self):
        self.rejected('lease', fence=self.fence + 1)

    def test_holder_is_checked_independently_of_fence(self):
        self.rejected('lease', actor='worker-b')

    def test_revision_conflict_preserves_user_edit(self):
        self.alter("UPDATE work SET revision=1 WHERE scope='alpha'")
        self.rejected('revision')
        self.assertEqual(self.store.db.execute('SELECT revision FROM work').fetchone()[0], 1)

    def test_revocation_blocks_new_write(self):
        self.alter("UPDATE work SET revoked=1 WHERE scope='alpha'")
        self.rejected('revoked')

    def test_revocation_blocks_receipt_replay_disclosure(self):
        self.apply()
        self.alter("UPDATE work SET revoked=1 WHERE scope='alpha'")
        self.rejected('revoked')

    def test_policy_version_is_checked_independently(self):
        self.rejected('policy', policy=2)

    def test_restore_epoch_is_checked_independently(self):
        self.alter("UPDATE work SET epoch=2 WHERE scope='alpha'")
        self.rejected('epoch')

    def test_independent_restored_owners_accept_divergent_results_with_copied_fence(self):
        # SQLite backup copies committed WAL state into a separate database owner.
        clone_path = Path(self.tmp.name) / 'restored.db'
        destination = lab.sqlite3.connect(clone_path)
        try:
            self.store.db.backup(destination)
        finally:
            destination.close()
        clone = lab.ReceiptLab(clone_path)
        self.addCleanup(clone.close)
        identity_sql = 'SELECT revision,epoch,policy,fence,holder,until_ms FROM work'
        self.assertEqual(tuple(self.store.db.execute(identity_sql).fetchone()),
                         tuple(clone.db.execute(identity_sql).fetchone()))
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertEqual(clone.counts('alpha', 'work'), (0, 0, 0))

        original = self.apply(key='original-result', result_digest='a' * 64)
        restored = clone.accept(**self.request(key='restored-result', result_digest='b' * 64))
        self.assertNotEqual(original['id'], restored['id'])
        self.assertNotEqual(original['result_digest'], restored['result_digest'])
        self.assertEqual(self.counts(), (1, 1, 1))
        self.assertEqual(clone.counts('alpha', 'work'), (1, 1, 1))
        for store in (self.store, clone):
            self.assertEqual(tuple(store.db.execute(
                'SELECT epoch,fence,human_state FROM work').fetchone()),
                (1, self.fence, 'open'))
        # Two local acceptances are the counterexample, not a failover PASS.

    def test_cancelled_work_rejects_late_success(self):
        self.alter("UPDATE work SET state='cancelled' WHERE scope='alpha'")
        self.rejected('state')

    def test_different_scope_does_not_reveal_or_collide_with_receipt(self):
        alpha = self.apply()
        self.store.seed('beta', 'work')
        fence = self.store.claim('beta', 'work', 'worker-a', now=100, until=200)
        beta = self.apply(scope='beta', fence=fence)
        self.assertNotEqual(alpha['id'], beta['id'])
        self.assertEqual(self.store.counts('beta', 'work'), (1, 1, 1))

    def test_missing_scope_is_not_found_not_an_empty_success(self):
        self.rejected('not-found', scope='missing')

    def test_before_commit_failure_rolls_back_all_three_records(self):
        with self.assertRaises(lab.InjectedFailure):
            self.apply(fault='before_commit')
        self.assertEqual(self.counts(), (0, 0, 0))
        self.apply()
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_after_commit_lost_ack_is_recovered_after_reopen(self):
        with self.assertRaises(lab.InjectedFailure):
            self.apply(fault='after_commit')
        self.assertEqual(self.counts(), (1, 1, 1))
        self.store.close()
        self.store = lab.ReceiptLab(self.path)
        self.addCleanup(self.store.close)
        self.assertEqual(self.apply()['revision'], 1)
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_outbox_write_failure_rolls_back_effect_and_receipt(self):
        self.alter("CREATE TRIGGER fail_outbox BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'disk-like-failure'); END")
        with self.assertRaises(lab.sqlite3.IntegrityError):
            self.apply()
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_two_independent_connections_same_key_recover_one_result(self):
        self._race(same_key=True)

    def test_two_independent_connections_different_keys_accept_one_effect(self):
        self._race(same_key=False)

    def _race(self, same_key):
        barrier = threading.Barrier(2)
        def invoke(index):
            store = lab.ReceiptLab(self.path)
            try:
                barrier.wait(timeout=5)
                request = self.request(key='op-1' if same_key else f'op-{index}')
                try:
                    return ('ok', store.accept(**request))
                except lab.Conflict as exc:
                    return ('conflict', str(exc))
            finally:
                store.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(invoke, (1, 2)))
        self.assertEqual(sum(row[0] == 'ok' for row in results), 2 if same_key else 1)
        if same_key:
            self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_bad_boundary_values_rejected_before_writing(self):
        cases = [dict(revision=True), dict(now=float('nan')), dict(fence=0),
                 dict(epoch=-1), dict(key=''), dict(scope='bad\x00scope'),
                 dict(result_digest='not-a-digest'), dict(actor='x' * 129)]
        for change in cases:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.apply(**change)
                self.assertEqual(self.counts(), (0, 0, 0))

    def test_non_fixture_database_is_refused(self):
        path = Path(self.tmp.name) / 'other.db'
        connection = lab.sqlite3.connect(path)
        connection.execute('CREATE TABLE private(x)')
        connection.close()
        with self.assertRaisesRegex(ValueError, 'fixture'):
            lab.ReceiptLab(path)

    def test_create_never_overwrites_an_existing_path(self):
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            lab.ReceiptLab.create_fixture(self.path)
        self.assertEqual(before, self.path.read_bytes())


if __name__ == '__main__':
    unittest.main()
