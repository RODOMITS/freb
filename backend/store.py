import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, profile TEXT NOT NULL, state TEXT NOT NULL, seed TEXT NOT NULL, client TEXT NOT NULL, nonce INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, type TEXT NOT NULL, status TEXT NOT NULL, delta INTEGER NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL, proof TEXT);
CREATE TABLE IF NOT EXISTS requests(user_id INTEGER NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL, response TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(user_id,key));
CREATE TABLE IF NOT EXISTS promos(code TEXT PRIMARY KEY, reward INTEGER NOT NULL, max_uses INTEGER NOT NULL, uses INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS redemptions(user_id INTEGER NOT NULL, code TEXT NOT NULL, PRIMARY KEY(user_id,code));
CREATE TABLE IF NOT EXISTS claims(user_id INTEGER NOT NULL, case_id TEXT NOT NULL, claimed REAL NOT NULL, PRIMARY KEY(user_id,case_id));
CREATE TABLE IF NOT EXISTS seeds(hash TEXT PRIMARY KEY, seed TEXT NOT NULL, user_id INTEGER NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS rounds(id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS transfers(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS invoices(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, stars INTEGER NOT NULL, status TEXT NOT NULL, charge TEXT UNIQUE, created REAL NOT NULL, checkout TEXT);
CREATE TABLE IF NOT EXISTS updates(id INTEGER PRIMARY KEY, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, message TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, actor INTEGER NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS bonus_spend(day TEXT PRIMARY KEY, spent INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS refund_jobs(invoice_id TEXT PRIMARY KEY, status TEXT NOT NULL, actor INTEGER NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS controls(name TEXT PRIMARY KEY, value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS partners(user_id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, claimed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS referral_codes(code TEXT PRIMARY KEY, user_id INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS referrals(invitee INTEGER PRIMARY KEY, inviter INTEGER NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS referral_ledger(event_id TEXT PRIMARY KEY, invitee INTEGER NOT NULL, net INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS quest_claims(user_id INTEGER NOT NULL, day TEXT NOT NULL, quest_id TEXT NOT NULL, claimed REAL NOT NULL, PRIMARY KEY(user_id,day,quest_id));
CREATE INDEX IF NOT EXISTS operations_user ON operations(user_id,created DESC);
'''


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.tx() as db:
            db.executescript(SCHEMA)
            if 'checkout' not in {r['name'] for r in db.execute('PRAGMA table_info(invoices)')}:
                db.execute('ALTER TABLE invoices ADD COLUMN checkout TEXT')
            if 'held_until' not in {r['name'] for r in db.execute('PRAGMA table_info(invoices)')}:
                db.execute('ALTER TABLE invoices ADD COLUMN held_until REAL NOT NULL DEFAULT 0')
                # Existing paid balances receive the announced conservative withdrawal hold.
                db.execute("UPDATE invoices SET held_until=created+504*3600 WHERE status='paid'")
            if 'bonus' not in {r['name'] for r in db.execute('PRAGMA table_info(invoices)')}:
                db.execute('ALTER TABLE invoices ADD COLUMN bonus INTEGER NOT NULL DEFAULT 0')
            ledger_columns={r['name'] for r in db.execute('PRAGMA table_info(referral_ledger)')}
            for name,kind in [('stake','INTEGER'),('payout','INTEGER'),('created','REAL')]:
                if name not in ledger_columns:
                    db.execute(f'ALTER TABLE referral_ledger ADD COLUMN {name} {kind}')
            db.execute('PRAGMA user_version=5')

    def backup(self, directory):
        from datetime import datetime, timezone
        directory=Path(directory).resolve()
        directory.mkdir(parents=True,exist_ok=True)
        destination=directory/f'freebie-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.sqlite3'
        source=sqlite3.connect(self.path,timeout=15)
        target=sqlite3.connect(str(destination))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        for old in sorted(directory.glob('freebie-*.sqlite3'),reverse=True)[7:]:
            if old.resolve().parent!=directory:
                raise ValueError('Backup path outside target directory')
            old.unlink()
        return destination

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()


def load_user(db, uid):
    row = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not row:
        raise ValueError('Пользователь не найден')
    return row, json.loads(row['state'])


def save_user(db, uid, state):
    db.execute('UPDATE users SET state=? WHERE id=?', (json.dumps(state),uid))
