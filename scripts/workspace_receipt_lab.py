"""Fictional single-owner SQLite receipt lab. NOT a production store or runner.

Only explicitly created lab fixtures can be opened. The caller supplies trusted
identity/time/policy facts; authentication, clock authority, physical power-loss,
external effects and distributed failover are intentionally outside this model.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterator

APPLICATION_ID = 0x57534C42
SCHEMA = """
PRAGMA application_id=1465076802;
CREATE TABLE work (
 scope TEXT NOT NULL, id TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 0, epoch INTEGER NOT NULL DEFAULT 1,
 policy INTEGER NOT NULL DEFAULT 1, revoked INTEGER NOT NULL DEFAULT 0,
 fence INTEGER NOT NULL DEFAULT 0, holder TEXT, until_ms INTEGER,
 state TEXT NOT NULL DEFAULT 'ready', human_state TEXT NOT NULL DEFAULT 'open',
 result_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(scope,id)
);
CREATE TABLE receipts (
 scope TEXT NOT NULL, op_key TEXT NOT NULL, work_id TEXT NOT NULL,
 digest TEXT NOT NULL, receipt TEXT NOT NULL,
 PRIMARY KEY(scope,op_key), FOREIGN KEY(scope,work_id) REFERENCES work(scope,id)
);
CREATE TABLE outbox (
 event_id TEXT PRIMARY KEY, scope TEXT NOT NULL, work_id TEXT NOT NULL,
 payload TEXT NOT NULL, FOREIGN KEY(scope,work_id) REFERENCES work(scope,id)
);
"""


class Conflict(ValueError):
    """A known rejected operation, not an uncertain transport failure."""


class InjectedFailure(RuntimeError):
    """Synthetic fault; not a power-loss or filesystem-durability claim."""


def _text(value: str) -> None:
    if (not isinstance(value, str) or not 1 <= len(value) <= 128
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('identity must be 1..128 characters without controls')


def _integer(value: int, minimum: int = 0) -> None:
    if type(value) is not int or not minimum <= value < 2**63:
        raise ValueError('expected a bounded integer, not a bool or float')


class ReceiptLab:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=rw',
                                  uri=True, isolation_level=None, timeout=2)
        self.db.row_factory = sqlite3.Row
        if self.db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
            self.db.close()
            raise ValueError('not a workspace receipt lab fixture')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA synchronous=FULL')

    @classmethod
    def create_fixture(cls, path: Path) -> ReceiptLab:
        """Explicit write-once fixture creation; existing paths are never replaced."""
        path = Path(path)
        with path.open('xb'):
            pass
        db = sqlite3.connect(path, isolation_level=None)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)
        finally:
            db.close()
        return cls(path)

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def _write(self) -> Iterator[None]:
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise

    def _row(self, scope: str, work: str) -> sqlite3.Row:
        row = self.db.execute('SELECT * FROM work WHERE scope=? AND id=?',
                              (scope, work)).fetchone()
        if row is None:
            raise Conflict('not-found')
        return row

    def seed(self, scope: str, work: str) -> None:
        _text(scope)
        _text(work)
        with self._write():
            self.db.execute('INSERT INTO work(scope,id) VALUES(?,?)', (scope, work))

    def claim(self, scope: str, work: str, actor: str, *, now: int, until: int) -> int:
        for value in (scope, work, actor):
            _text(value)
        for value in (now, until):
            _integer(value)
        if until <= now:
            raise ValueError('lease must expire in the future')
        with self._write():
            row = self._row(scope, work)
            if row['revoked']:
                raise Conflict('revoked')
            if row['state'] not in ('ready', 'leased'):
                raise Conflict('state')
            if row['state'] == 'leased' and row['until_ms'] > now:
                raise Conflict('busy')
            fence = row['fence'] + 1
            _integer(fence, 1)
            self.db.execute("UPDATE work SET fence=?,holder=?,until_ms=?,state='leased' "
                            'WHERE scope=? AND id=?', (fence, actor, until, scope, work))
            return fence

    def accept(self, *, scope: str, work: str, actor: str, key: str, revision: int,
               epoch: int, policy: int, fence: int, result_digest: str, now: int,
               fault: str | None = None) -> dict:
        """Record one result, receipt and notification obligation atomically.

        Current scope/epoch/policy checks precede deduplication. Exact authorized
        replays may recover their receipt after the original lease expires.
        Human completion and actual outbox delivery are never performed here.
        """
        for value in (scope, work, actor, key):
            _text(value)
        for value in (revision, now):
            _integer(value)
        for value in (epoch, policy, fence):
            _integer(value, 1)
        if not isinstance(result_digest, str) or not re.fullmatch('[0-9a-f]{64}', result_digest):
            raise ValueError('result_digest must be lowercase SHA-256 hex')
        if fault not in (None, 'before_commit', 'after_commit'):
            raise ValueError('unknown fault')
        command = dict(scope=scope, work=work, actor=actor, key=key, revision=revision,
                       epoch=epoch, policy=policy, fence=fence, result_digest=result_digest)
        canonical = json.dumps(command, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        with self._write():
            row = self._row(scope, work)
            if row['revoked']:
                raise Conflict('revoked')
            if row['epoch'] != epoch:
                raise Conflict('epoch')
            if row['policy'] != policy:
                raise Conflict('policy')
            saved = self.db.execute('SELECT digest,receipt FROM receipts WHERE scope=? AND op_key=?',
                                    (scope, key)).fetchone()
            if saved is not None:
                if saved['digest'] != digest:
                    raise Conflict('key-reused')
                return json.loads(saved['receipt'])
            if row['state'] != 'leased':
                raise Conflict('state')
            if row['fence'] != fence or row['holder'] != actor or row['until_ms'] <= now:
                raise Conflict('lease')
            if row['revision'] != revision:
                raise Conflict('revision')
            next_revision = revision + 1
            _integer(next_revision)
            rid = hashlib.sha256((scope + '\x00' + key).encode('utf-8')).hexdigest()
            receipt = dict(id=rid, scope=scope, work=work, revision=next_revision,
                           result_digest=result_digest, human_state='open')
            encoded = json.dumps(receipt, sort_keys=True, separators=(',', ':'))
            self.db.execute("UPDATE work SET revision=?,result_count=result_count+1,"
                            "state='result-recorded',holder=NULL,until_ms=NULL WHERE scope=? AND id=?",
                            (next_revision, scope, work))
            self.db.execute('INSERT INTO receipts VALUES(?,?,?,?,?)',
                            (scope, key, work, digest, encoded))
            self.db.execute('INSERT INTO outbox VALUES(?,?,?,?)', (rid, scope, work, encoded))
            if fault == 'before_commit':
                raise InjectedFailure('before commit')
        if fault == 'after_commit':
            raise InjectedFailure('lost acknowledgement after commit')
        return receipt

    def counts(self, scope: str, work: str) -> tuple[int, int, int]:
        """Fixture introspection only, not an authorized application query API."""
        row = self.db.execute('SELECT result_count,'
                              '(SELECT COUNT(*) FROM receipts WHERE scope=? AND work_id=?),'
                              '(SELECT COUNT(*) FROM outbox WHERE scope=? AND work_id=?) '
                              'FROM work WHERE scope=? AND id=?',
                              (scope, work, scope, work, scope, work)).fetchone()
        return tuple(row)
