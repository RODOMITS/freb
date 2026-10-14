import json
import math
import queue
import sqlite3
import threading
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
CREATE TABLE IF NOT EXISTS account_locks(user_id INTEGER PRIMARY KEY, balance_frozen INTEGER NOT NULL DEFAULT 0, withdrawal_frozen INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '', actor INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS partners(user_id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, claimed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS referral_codes(code TEXT PRIMARY KEY, user_id INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS referrals(invitee INTEGER PRIMARY KEY, inviter INTEGER NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS referral_ledger(event_id TEXT PRIMARY KEY, invitee INTEGER NOT NULL, net INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS quest_claims(user_id INTEGER NOT NULL, day TEXT NOT NULL, quest_id TEXT NOT NULL, claimed REAL NOT NULL, PRIMARY KEY(user_id,day,quest_id));
CREATE TABLE IF NOT EXISTS bot_dialogs(actor INTEGER PRIMARY KEY, request_id TEXT NOT NULL, last_sent REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS funding_bonuses(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, amount INTEGER NOT NULL, created REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1, case_used INTEGER NOT NULL DEFAULT 0, giveaway_day TEXT, cashback_paid INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS weekly_bonus_claims(user_id INTEGER NOT NULL, kind TEXT NOT NULL, week TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(user_id,kind,week));
CREATE TABLE IF NOT EXISTS giveaway_rounds(day TEXT PRIMARY KEY, seed TEXT NOT NULL, commitment TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS giveaway_draws(day TEXT PRIMARY KEY, winner INTEGER, ticket_id TEXT, participants INTEGER NOT NULL, seed TEXT NOT NULL, commitment TEXT NOT NULL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS funding_user ON funding_bonuses(user_id,created);
CREATE INDEX IF NOT EXISTS operations_user ON operations(user_id,created DESC);
'''


class Store:
    def __init__(self, path):
        self.path = str(path)
        self.write_lock=threading.Lock()
        self.read_pool=queue.LifoQueue(maxsize=12)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.tx() as db:
            db.executescript(SCHEMA)
            db.execute('PRAGMA journal_mode=WAL')
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
            if 'completed' not in {r['name'] for r in db.execute('PRAGMA table_info(operations)')}:
                db.execute('ALTER TABLE operations ADD COLUMN completed REAL')
            outbox_columns={r['name'] for r in db.execute('PRAGMA table_info(outbox)')}
            for name,kind in [('method','TEXT'),('payload','TEXT'),('retry_at','REAL NOT NULL DEFAULT 0')]:
                if name not in outbox_columns:
                    db.execute(f'ALTER TABLE outbox ADD COLUMN {name} {kind}')
            if db.execute('PRAGMA user_version').fetchone()[0]<8:
                db.execute('DELETE FROM bot_dialogs')
                db.execute("UPDATE outbox SET sent=1 WHERE sent=0 AND id LIKE 'chat-%'")
                for row in db.execute('SELECT id,payload FROM outbox WHERE sent=0 AND payload IS NOT NULL').fetchall():
                    payload=json.loads(row['payload'])
                    buttons=payload.get('reply_markup',{}).get('inline_keyboard',[])
                    if any(str(button.get('callback_data','')).startswith('dep:') for line in buttons for button in line):
                        payload.pop('reply_markup',None)
                        payload['text']=payload.get('text','').split('\nНажми «Ответить»')[0]+'\nИгрок направлен в @BrainrotFreebie_deposit_bot.'
                        db.execute('UPDATE outbox SET payload=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),row['id']))
            giveaway_columns={r['name'] for r in db.execute('PRAGMA table_info(giveaway_rounds)')}
            for name,kind in [('period',"TEXT NOT NULL DEFAULT 'daily'"),('start_at','REAL'),('end_at','REAL')]:
                if name not in giveaway_columns:
                    db.execute(f'ALTER TABLE giveaway_rounds ADD COLUMN {name} {kind}')
            db.execute("UPDATE giveaway_rounds SET end_at=CAST(strftime('%s',day,'+1 day','-3 hours') AS INTEGER),start_at=CAST(strftime('%s',day,'-3 hours') AS INTEGER) WHERE end_at IS NULL AND day GLOB '????-??-??'")
            # Apply the requested incident hold once; later admin unfreezes survive restarts.
            if not db.execute("SELECT 1 FROM controls WHERE name='incident_hold_20261014'").fetchone():
                for uid in (7221165756,6263182915):
                    db.execute("INSERT INTO account_locks(user_id,balance_frozen,withdrawal_frozen,reason) VALUES(?,1,1,'Проверка депозита') ON CONFLICT(user_id) DO UPDATE SET balance_frozen=1,withdrawal_frozen=1,reason=excluded.reason",(uid,))
                db.execute("INSERT INTO controls VALUES('incident_hold_20261014',1)")
            if 'next_tick' not in {r['name'] for r in db.execute('PRAGMA table_info(users)')}:
                db.execute('ALTER TABLE users ADD COLUMN next_tick REAL')
                for row in db.execute("SELECT id,state FROM users WHERE json_extract(state,'$.mines.status')='active' OR json_extract(state,'$.rocket.status')='active'").fetchall():
                    db.execute('UPDATE users SET next_tick=? WHERE id=?',(next_tick(json.loads(row['state'])),row['id']))
            audit_columns={r['name'] for r in db.execute('PRAGMA table_info(audit)')}
            for name,kind in [('drop_day','TEXT'),('drop_value','REAL')]:
                if name not in audit_columns: db.execute(f'ALTER TABLE audit ADD COLUMN {name} {kind}')
            if 'invoice_url' not in {r['name'] for r in db.execute('PRAGMA table_info(invoices)')}:
                db.execute('ALTER TABLE invoices ADD COLUMN invoice_url TEXT')
            db.execute('CREATE TABLE IF NOT EXISTS account_rates(user_id INTEGER NOT NULL,kind TEXT NOT NULL,tokens REAL NOT NULL,updated REAL NOT NULL,PRIMARY KEY(user_id,kind))')
            db.executescript("""
CREATE INDEX IF NOT EXISTS users_due ON users(next_tick) WHERE next_tick IS NOT NULL;
CREATE INDEX IF NOT EXISTS sessions_expires ON sessions(expires);
CREATE INDEX IF NOT EXISTS transfers_user_status ON transfers(user_id,kind,status,created);
CREATE INDEX IF NOT EXISTS transfers_created ON transfers(created DESC);
CREATE INDEX IF NOT EXISTS invoices_user_status ON invoices(user_id,status,held_until);
CREATE INDEX IF NOT EXISTS invoices_created ON invoices(created DESC);
CREATE INDEX IF NOT EXISTS referrals_inviter ON referrals(inviter,created DESC);
CREATE INDEX IF NOT EXISTS referral_results ON referral_ledger(invitee);
CREATE INDEX IF NOT EXISTS bonus_round ON funding_bonuses(giveaway_day,active,amount);
CREATE INDEX IF NOT EXISTS giveaway_deadlines ON giveaway_rounds(end_at);
CREATE INDEX IF NOT EXISTS audit_feed ON audit(id DESC) WHERE action='drop';
CREATE INDEX IF NOT EXISTS audit_day_top ON audit(drop_day,drop_value DESC,created,id) WHERE action='drop';
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(retry_at) WHERE sent=0 AND attempts<10;
CREATE INDEX IF NOT EXISTS legacy_request_size ON requests(created) WHERE length(response)>2048;
CREATE INDEX IF NOT EXISTS operations_quests ON operations(user_id,coalesce(completed,created),type) WHERE status!='pending';
""")
            db.execute("INSERT OR IGNORE INTO partners(user_id,code) SELECT id,'u'||id FROM users")
            db.execute('INSERT OR IGNORE INTO referral_codes(code,user_id) SELECT code,user_id FROM partners')
            db.execute('PRAGMA user_version=12')


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

    def connect(self, readonly=False):
        target=Path(self.path).resolve().as_uri()+'?mode=ro' if readonly else self.path
        db=sqlite3.connect(target,timeout=2,isolation_level=None,uri=readonly,check_same_thread=False)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=2000')
        if readonly: db.execute('PRAGMA query_only=ON')
        else: db.execute('PRAGMA synchronous=FULL')
        return db

    @contextmanager
    def read(self):
        try: db=self.read_pool.get_nowait()
        except queue.Empty: db=self.connect(readonly=True)
        try:
            db.execute('BEGIN')
            yield db
        finally:
            db.rollback()
            try: self.read_pool.put_nowait(db)
            except queue.Full: db.close()

    def close(self):
        while True:
            try: self.read_pool.get_nowait().close()
            except queue.Empty: break

    @contextmanager
    def tx(self):
        if not self.write_lock.acquire(timeout=2):
            raise sqlite3.OperationalError('database is locked')
        db=None
        try:
            db=self.connect()
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            if db is not None: db.rollback()
            raise
        finally:
            if db is not None: db.close()
            self.write_lock.release()


def load_user(db, uid):
    row = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not row:
        raise ValueError('Пользователь не найден')
    return row, json.loads(row['state'])


def next_tick(state):
    deadlines=[]
    mines=state.get('mines')
    if mines and mines.get('status')=='active': deadlines.append(mines['expiresAt']/1000)
    rocket=state.get('rocket')
    if rocket and rocket.get('status')=='active':
        deadline=rocket['endAt']/1000
        target=rocket.get('autoCash')
        if target and target<=rocket['crash']: deadline=min(deadline,rocket['startAt']/1000+math.log(target)/.24)
        deadlines.append(deadline)
    return min(deadlines) if deadlines else None


def save_user(db, uid, state):
    db.execute('UPDATE users SET state=?,next_tick=? WHERE id=?', (json.dumps(state),next_tick(state),uid))
