import json,unittest,sqlite3,hashlib
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
from backend import service as module
from backend.service import Service,ident
from backend.store import Store,load_user,save_user
from backend.economy import landing
from backend.fair import FairRandom

CATALOG_SOURCE = globals().get('CATALOG_SOURCE') or Path(module.__file__).with_name('catalog.json').read_text(encoding='utf-8')

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.connections={}
        connections=self.connections
        class MemoryStore(Store):
            def __init__(self,path):
                key=str(path)
                if key not in connections:
                    connections[key]=sqlite3.connect(':memory:',isolation_level=None)
                    connections[key].row_factory=sqlite3.Row
                self.conn=connections[key]
                super().__init__(path)
            @contextmanager
            def tx(self):
                self.conn.execute('BEGIN IMMEDIATE')
                try:yield self.conn;self.conn.commit()
                except BaseException:self.conn.rollback();raise
        self.now=datetime(2026,10,17,13,tzinfo=timezone.utc).timestamp()
        self.patches=[patch.object(module,'Store',MemoryStore),patch.object(Path,'mkdir',lambda *a,**k:None),patch.object(Path,'read_text',lambda *a,**k:CATALOG_SOURCE),patch.object(Path,'is_file',lambda *a,**k:True)]
        for p in self.patches:p.start()
        self.s=Service('/virtual/test.db',admins=(100,),clock=lambda:self.now)
        self.s.login(dict(id=100,first_name='Owner'))
        self.s.login(dict(id=200,first_name='Player'),'ref_u100')
        self.s.login(dict(id=300,first_name='Other'))
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        for c in self.connections.values():c.close()
    def call(self,uid,action,body=None,key=None):
        return self.s.mutate(uid,action,body or {},key or ident())
    def items(self,*names):
        ids=[]
        with self.s.store.tx() as db:
            _,s=load_user(db,200)
            for name in names:ids.append(self.s.add_item(s,name))
            save_user(db,200,s)
        return ids
    def deposit(self,item='garama'):
        rid=self.call(200,'deposit',dict(itemId=item))['result']['requestId']
        self.call(100,'admin-transfer',dict(requestId=rid,decision='approve'))
    def test_deposit_whitelist(self):
        for item in ('eviledon','queenbee','digi','tictac'):
            with self.assertRaises(ValueError):self.call(200,'deposit',dict(itemId=item))
        for item in ('garama','boppin','globa','bunny','kraken'):self.deposit(item)
        self.assertEqual(self.s.state(100)['partner']['depositCount'],5)
    def test_tiers_and_stats(self):
        self.deposit()
        with self.s.store.tx() as db:
            self.s.referral_result(db,200,'event',20,4)
            self.s.referral_result(db,200,'event',20,4)
        p=self.s.state(100)['partner']
        self.assertEqual((p['revShare'],p['earned'],p['turnover'],p['payouts'],p['games'],p['deposits']),(40,6.4,20,4,1,72))
        for count,rate,earned in [(25,45,7.2),(50,50,8),(100,55,8.8)]:
            current=self.s.state(100)['partner']['count']
            for n in range(current,count):self.s.login(dict(id=1000+n,first_name='Friend'),'ref_u100')
            p=self.s.state(100)['partner'];self.assertEqual((p['count'],p['revShare'],p['earned']),(count,rate,earned))
    def test_legacy_turnover_is_not_invented(self):
        self.deposit()
        with self.s.store.tx() as db:db.execute("INSERT INTO referral_ledger(event_id,invitee,net) VALUES('old',200,1000)")
        p=self.s.state(100)['partner']
        self.assertFalse(p['historyComplete']);self.assertEqual(p['turnover'],0);self.assertEqual(p['earned'],4)
    def test_quest_rewards_and_moscow_reset(self):
        with self.s.store.tx() as db:
            for kind in ('case','upgrade'):
                for n in range(5):self.s.operation(db,200,kind,'Test')
        key=ident()
        self.call(200,'quest-claim',dict(questId='cases5'),key)
        self.call(200,'quest-claim',dict(questId='cases5'),key)
        self.call(200,'quest-claim',dict(questId='upgrades5'))
        self.assertEqual(self.s.state(200)['balance'],15)
        with self.assertRaises(ValueError):self.call(200,'quest-claim',dict(questId='cases5'))
        with self.assertRaises(ValueError):self.call(300,'quest-claim',dict(questId='cases5',progress=999))
        self.now=datetime(2026,10,17,21,tzinfo=timezone.utc).timestamp()
        q=self.s.state(200)['quests']
        self.assertEqual(q['day'],'2026-10-18')
        self.assertTrue(all(i['progress']==0 and not i['claimed'] for i in q['items']))
    def test_sale_all_keeps_locked_items_and_is_atomic(self):
        a,b,c=self.items('67','garama','dragon')
        rid=self.call(200,'withdraw',dict(uids=[c]))['result']['requestId']
        before=self.s.state(200);old_hash=before['inventoryHash']
        self.items('esok')
        with self.assertRaises(ValueError):self.call(200,'sale-all',dict(inventoryHash=old_hash))
        before=self.s.state(200);key=ident();body=dict(inventoryHash=before['inventoryHash'])
        self.call(200,'sale-all',body,key);self.call(200,'sale-all',body,key)
        after=self.s.state(200)
        self.assertEqual(after['balance'],90);self.assertEqual(after['inventory'],[]);self.assertEqual(len(after['pendingInventory']),1)
        with self.assertRaises(ValueError):self.call(300,'sale-all',body)
        self.call(200,'withdraw-cancel',dict(requestId=rid))
        self.assertEqual(self.s.state(200)['inventory'][0]['itemId'],'dragon')
    def test_maintenance_and_player_state_survive_restart(self):
        self.items('garama')
        with self.s.store.tx() as db:
            _,s=load_user(db,200);s['balance']=12345;save_user(db,200,s)
        self.call(100,'admin-maintenance',dict(enabled=True))
        reopened=Service('/virtual/test.db',admins=(100,),clock=lambda:self.now)
        self.assertTrue(reopened.maintenance())
        self.assertEqual(reopened.state(200)['balance'],123.45)
        self.assertEqual(len(reopened.state(200)['inventory']),1)
        with self.assertRaises(PermissionError):reopened.mutate(200,'quest-claim',dict(questId='cases5'),ident())
        reopened.mutate(100,'admin-maintenance',dict(enabled=False),ident())
        self.assertFalse(reopened.maintenance())
    def test_upgrade_position_matches_verdict(self):
        for chance in (.001,.02,.2,.5,.8,.95):
            for n in range(100):
                p=landing(chance,FairRandom('test','client',n))
                self.assertEqual(p['win'],p['y']>=p['level'])
                self.assertLessEqual((p['x']-120)**2+(p['y']-120)**2,104**2+1e-7)
        uid=self.items('67')[0]
        result=self.call(200,'upgrade',dict(uids=[uid],targetId='lagrand'))['result']
        self.assertAlmostEqual(result['chance'],.8*3/7)
        self.assertEqual(result['landing']['win'],result['landing']['y']>=result['landing']['level'])

if __name__=='__main__':unittest.main()
