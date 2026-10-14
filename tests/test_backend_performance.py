import json
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_v150 as fixtures
from backend import service as module
from backend.service import Service,ident
from backend.security import RateLimited
from backend.store import Store,load_user,save_user

class BackendPerformanceTests(unittest.TestCase):
    setUp=fixtures.Release150Tests.setUp
    tearDown=fixtures.Release150Tests.tearDown
    call=fixtures.Release150Tests.call
    add=fixtures.Release150Tests.add

    def test_polling_and_authentication_do_not_write(self):
        token=self.s.login(dict(id=200,first_name='Player'))
        db=self.s.store.conn;before=db.total_changes
        for _ in range(10):
            self.assertEqual(self.s.authenticate(token),200)
            self.s.maintenance()
            self.s.state(200)
        self.assertEqual(db.total_changes,before)

    def test_read_snapshot_cannot_change_database(self):
        with self.s.store.read() as db:
            self.s.snapshot(db,200,readonly=True)
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("UPDATE users SET nonce=nonce+1 WHERE id=200")
        self.call(200,'case',dict(caseId='plant'))

    def test_tick_does_not_decode_a_thousand_idle_profiles(self):
        with self.s.store.tx() as db:
            original=db.execute('SELECT profile,state,seed,client FROM users WHERE id=300').fetchone()
            idle=json.dumps(dict(json.loads(original['state']),idle_marker='DO_NOT_DECODE'))
            db.executemany('INSERT INTO users(id,profile,state,seed,client) VALUES(?,?,?,?,?)',[(uid,original['profile'],idle,original['seed'],original['client']) for uid in range(1000,2000)])
        self.call(200,'mines-start',dict(uids=self.add(['67']),bombCount=3))
        self.now+=60
        original_loads=json.loads
        def guarded(value,*args,**kwargs):
            if isinstance(value,str) and 'DO_NOT_DECODE' in value: raise AssertionError('Idle state was decoded by tick')
            return original_loads(value,*args,**kwargs)
        with patch.object(module.json,'loads',guarded):
            with self.s.store.tx() as db:self.s.tick(db)
        self.assertEqual(self.s.state(200)['mines']['status'],'lost')
        with self.s.store.read() as db:
            self.assertIsNone(db.execute('SELECT next_tick FROM users WHERE id=200').fetchone()[0])
            plan=db.execute('EXPLAIN QUERY PLAN SELECT id,state FROM users WHERE next_tick<=?',(self.now,)).fetchall()
            self.assertTrue(any('users_due' in r['detail'] for r in plan))

    def test_automatic_rocket_settlement_survives_restart(self):
        public=self.s.state(200)['round']
        with self.s.store.tx() as db:
            row=db.execute('SELECT data FROM rounds WHERE id=?',(public['id'],)).fetchone()
            game=json.loads(row['data']);game['crash']=5;game['endAt']=game['startAt']+math.log(5)/.24*1000
            db.execute('UPDATE rounds SET data=? WHERE id=?',(json.dumps(game),game['id']))
        self.call(200,'rocket-bet',dict(roundId=game['id'],amount=10,autoCash=2))
        self.now=game['startAt']/1000+math.log(2)/.24+.001
        self.s=Service('/virtual/release150.db',admins=(100,),clock=lambda:self.now)
        state=self.s.state(200)
        self.assertEqual(state['rocket']['status'],'won')
        self.assertEqual(state['rocket']['payout'],20)
        self.assertEqual(state['balance'],50010)
        self.assertEqual(self.s.state(200)['balance'],50010)

    def test_rate_limit_is_persistent_and_refills(self):
        for _ in range(2):
            with self.s.store.tx() as db:self.s.consume_rate(db,200,'test',capacity=2,seconds=10)
        with self.assertRaises(RateLimited):
            with self.s.store.tx() as db:self.s.consume_rate(db,200,'test',capacity=2,seconds=10)
        self.s=Service('/virtual/release150.db',admins=(100,),clock=lambda:self.now)
        with self.assertRaises(RateLimited):
            with self.s.store.tx() as db:self.s.consume_rate(db,200,'test',capacity=2,seconds=10)
        self.now+=5
        with self.s.store.tx() as db:self.s.consume_rate(db,200,'test',capacity=2,seconds=10)

    def test_compact_retry_does_not_replay_old_balance_or_unfreeze(self):
        key=ident();body=dict(caseId='plant')
        first=self.call(200,'case',body,key)
        self.call(100,'admin-freeze',dict(userId=200,balanceFrozen=True,withdrawalFrozen=True))
        with self.s.store.tx() as db:
            db.execute("UPDATE account_rates SET tokens=0 WHERE user_id=200 AND kind='action'")
            stored=json.loads(db.execute('SELECT response FROM requests WHERE user_id=200 AND key=?',(key,)).fetchone()[0])
        self.assertNotIn('state',stored)
        retry=self.call(200,'case',body,key)
        self.assertEqual(retry['result'],first['result'])
        self.assertTrue(retry['state']['balanceFrozen'])
        self.assertEqual(retry['state']['balance'],first['state']['balance'])
        self.assertEqual(len(retry['state']['inventory']),1)

    def test_legacy_receipts_are_compacted_without_losing_retry_identity(self):
        key=ident();body=dict(caseId='plant')
        first=self.call(200,'case',body,key)
        legacy=json.dumps(first)
        self.assertGreater(len(legacy),2048)
        with self.s.store.tx() as db:
            db.execute('UPDATE requests SET response=? WHERE user_id=200 AND key=?',(legacy,key))
        self.now+=301
        self.s.refresh_runtime()
        with self.s.store.read() as db:
            saved=json.loads(db.execute('SELECT response FROM requests WHERE user_id=200 AND key=?',(key,)).fetchone()[0])
        self.assertNotIn('state',saved)
        self.assertEqual(saved['result'],first['result'])
        retry=self.call(200,'case',body,key)
        self.assertEqual(retry['result'],first['result'])
        self.assertEqual(retry['state']['balance'],first['state']['balance'])
        self.assertEqual(len(retry['state']['inventory']),1)

    def test_top_drop_uses_index_and_resets_at_moscow_midnight(self):
        with self.s.store.tx() as db:
            self.s.drop(db,200,'67');self.s.drop(db,200,'dragon');self.s.drop(db,300,'garama')
        self.assertEqual(self.s.state(200)['topDrop']['itemId'],'dragon')
        self.now=self.s.bonus_calendar(self.now)['dayEnd']
        self.assertIsNone(self.s.state(200)['topDrop'])

    def test_giveaway_aggregate_matches_verified_sources(self):
        round_id=self.s.state(200)['bonuses']['giveaway']['day']
        for index,(kind,status,amount,wrong_user) in enumerate([
            ('deposit','approved',50,False),('deposit','pending',50,False),
            ('deposit','approved',49,False),('deposit','approved',60,True),
            ('stars','paid',50,False),('stars','pending',50,False)]):
            with self.s.store.tx() as db:
                fid='ticket-'+str(index);uid=300 if wrong_user else 200
                if kind=='deposit':
                    db.execute('INSERT INTO transfers VALUES(?,?,?,?,?,?)',(fid,uid,kind,status,json.dumps(dict(value=amount)),self.now))
                else:
                    db.execute('INSERT INTO invoices(id,user_id,stars,status,charge,created) VALUES(?,?,?,?,?,?)',(fid,uid,amount,status,'charge-'+fid if status=='paid' else None,self.now))
                self.s.register_funding(db,200,fid,5000 if kind=='deposit' else amount*150)
                db.execute('UPDATE funding_bonuses SET giveaway_day=? WHERE id=?',(round_id,fid))
        with self.s.store.read() as db:
            verified=self.s.funded_bonus_rows(db,minimum=5000,round_id=round_id)
            counts=self.s.giveaway_counts(db,round_id,200)
        self.assertEqual(counts,(len(verified),len(verified),len({r['user_id'] for r in verified})))
        self.assertEqual(counts,(2,2,1))


class StoreConcurrencyTests(unittest.TestCase):
    def test_real_wal_reader_does_not_block_writer_and_pool_is_readonly(self):
        with tempfile.TemporaryDirectory(prefix='freebie-wal-qa-') as folder:
            store=Store(Path(folder)/'test.sqlite')
            try:
                with store.tx() as db:db.execute("INSERT INTO controls VALUES('qa',0)")
                with store.read() as reader:
                    self.assertEqual(reader.execute("SELECT value FROM controls WHERE name='qa'").fetchone()[0],0)
                    with store.tx() as writer:writer.execute("UPDATE controls SET value=1 WHERE name='qa'")
                    self.assertEqual(reader.execute("SELECT value FROM controls WHERE name='qa'").fetchone()[0],0)
                    with self.assertRaises(sqlite3.OperationalError):reader.execute('DELETE FROM controls')
                with store.read() as reader:self.assertEqual(reader.execute("SELECT value FROM controls WHERE name='qa'").fetchone()[0],1)
            finally:store.close()
