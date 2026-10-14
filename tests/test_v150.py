import json
import math
import sqlite3
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend import service as module
from backend.economy import distribution, landing, legacy_landing
from backend.fair import FairRandom, commitment
from backend.service import Service, ident
from backend.store import Store, load_user, save_user
from backend.verify import verify_document

CATALOG_SOURCE=globals().get('CATALOG_SOURCE') or Path(module.__file__).with_name('catalog.json').read_text(encoding='utf-8')


class Release150Tests(unittest.TestCase):
    def setUp(self):
        self.connections={}
        connections=self.connections
        class MemoryStore(Store):
            def __init__(self,path):
                key=str(path)
                if key not in connections:
                    connections[key]=sqlite3.connect(':memory:',isolation_level=None,check_same_thread=False)
                    connections[key].row_factory=sqlite3.Row
                self.conn=connections[key]
                super().__init__(path)
            @contextmanager
            def tx(self):
                self.conn.execute('BEGIN IMMEDIATE')
                try:
                    yield self.conn
                    self.conn.commit()
                except BaseException:
                    self.conn.rollback()
                    raise
        @contextmanager
        def read(store):
            store.conn.execute('PRAGMA query_only=ON')
            store.conn.execute('BEGIN')
            try: yield store.conn
            finally:
                store.conn.rollback()
                store.conn.execute('PRAGMA query_only=OFF')
        MemoryStore.read=read
        self.now=datetime(2026,10,17,13,tzinfo=timezone.utc).timestamp()
        self.patches=[patch.object(module,'Store',MemoryStore),patch.object(Path,'mkdir',lambda *a,**k:None),patch.object(Path,'read_text',lambda *a,**k:CATALOG_SOURCE),patch.object(Path,'is_file',lambda *a,**k:True)]
        for p in self.patches:p.start()
        self.s=Service('/virtual/release150.db',admins=(100,),starting_balance=50000,clock=lambda:self.now)
        self.s.login(dict(id=100,first_name='Owner'))
        self.s.login(dict(id=200,first_name='Player @BrainrotFreebie'),'ref_u100')
        self.s.login(dict(id=300,first_name='Other'))

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        for db in self.connections.values():db.close()

    def call(self,uid,action,body=None,key=None):
        return self.s.mutate(uid,action,body or {},key or ident())

    def add(self,items,uid=200):
        with self.s.store.tx() as db:
            _,state=load_user(db,uid)
            entries=[self.s.add_item(state,item) for item in items]
            save_user(db,uid,state)
        return entries

    def test_case_catalog_probability_budget(self):
        for case in self.s.cases.values():
            drops=distribution(case,self.s.items)
            self.assertAlmostEqual(sum(d['chance'] for d in drops),1)
            if case.get('free'):continue
            if case['id']=='allornothing':
                self.assertEqual({d['itemId']:d['chance'] for d in drops},{'garama':.7,'dragon':.3})
                continue
            losses=[d for d in drops if self.s.items[d['itemId']]['value']<case['price']]
            self.assertEqual(len(losses),2)
            self.assertAlmostEqual(losses[0]['chance'],losses[1]['chance'])
            self.assertLessEqual(sum(d['chance']*self.s.items[d['itemId']]['value'] for d in drops),.8*case['price']+1e-9)

    def test_three_cases_are_atomic_and_idempotent(self):
        body=dict(caseId='plant',count=3);key=ident()
        first=self.call(200,'case',body,key)
        self.assertEqual(first,self.call(200,'case',body,key))
        self.assertEqual(len(first['result']['drops']),3)
        self.assertEqual(len(self.s.state(200)['inventory']),3)
        self.assertEqual(self.s.state(200)['stats']['opened'],3)
        self.assertEqual(self.s.state(200)['balance'],50000-self.s.cases['plant']['price']*3)
        with self.s.store.tx() as db:
            _,state=load_user(db,300);state['balance']=10000;save_user(db,300,state)
        with self.assertRaises(ValueError):self.call(300,'case',body)
        state=self.s.state(300)
        self.assertEqual((state['balance'],state['inventory'],state['stats']['opened']),(100,[],0))
        for count in (0,2,4,True):
            with self.assertRaises(ValueError):self.call(200,'case',dict(caseId='plant',count=count))

    def test_subscription_and_nickname_repeat_after_24_hours(self):
        start=self.now
        for case in ('subscribe','nickname'):
            body=dict(caseId=case,_subscribed=True)
            self.call(200,'case',body)
            with self.assertRaises(ValueError):self.call(200,'case',body)
            with self.assertRaises(ValueError):self.call(300,'case',dict(body,count=3))
        self.call(200,'case',dict(caseId='referral'))
        self.now=start+86399
        for case in ('subscribe','nickname'):
            with self.assertRaises(ValueError):self.call(200,'case',dict(caseId=case,_subscribed=True))
        self.now=start+86400
        with self.assertRaises(ValueError):self.call(200,'case',dict(caseId='subscribe',_subscribed=False))
        self.call(200,'case',dict(caseId='subscribe',_subscribed=True))
        self.s.login(dict(id=200,first_name='Player'))
        with self.assertRaises(ValueError):self.call(200,'case',dict(caseId='nickname'))
        self.s.login(dict(id=200,first_name='Player @BrainrotFreebie'))
        self.call(200,'case',dict(caseId='nickname'))
        with self.assertRaises(ValueError):self.call(200,'case',dict(caseId='referral'))

    def test_large_item_stakes_and_full_mines_payout(self):
        items=self.add(['dragon','dragon'])
        self.call(200,'upgrade',dict(uids=items,targetId='lovebear'))
        self.call(200,'slots',dict(uid=self.add(['lovebear'])[0]))
        many=self.add(['67']*101)
        self.call(200,'upgrade',dict(uids=many,targetId='lovebear'))
        self.call(200,'mines-start',dict(uids=self.add(['lovebear']),bombCount=3))
        with self.s.store.tx() as db:
            _,state=load_user(db,200);bombs=state['mines']['bombs']
        for cell in range(25):
            if cell not in bombs:self.call(200,'mines-reveal',dict(index=cell))
        game=self.s.state(200)['mines']
        self.assertEqual(game['status'],'won')
        self.assertEqual(len(game['opened']),22)
        self.assertGreater(game['payout'],10000)

    def test_rocket_balance_stake_and_round_total_are_not_capped(self):
        public=self.s.state(200)['round']
        with self.s.store.tx() as db:
            row=db.execute('SELECT data FROM rounds WHERE id=?',(public['id'],)).fetchone()
            game=json.loads(row['data']);game.update(crash=100,capped=True,startAt=(self.now+10)*1000,endAt=(self.now+100)*1000)
            db.execute('UPDATE rounds SET data=? WHERE id=?',(json.dumps(game),public['id']))
        for uid,amount in ((200,1234.56),(300,2345.67)):
            result=self.call(uid,'rocket-bet',dict(roundId=public['id'],amount=amount,autoCash=1.01))
            self.assertAlmostEqual(result['state']['balance'],50000-amount)
            self.assertEqual(result['state']['rocket']['stakeCount'],0)
        self.now+=11
        for uid in (200,300):self.assertEqual(self.s.state(uid)['rocket']['status'],'won')

    def test_rocket_invalid_or_unfunded_amount_does_not_charge(self):
        round_id=self.s.state(200)['round']['id']
        for amount in (0,.000000001,1.001,50001,True,float('inf')):
            before=self.s.state(200)['balance']
            with self.assertRaises(ValueError):self.call(200,'rocket-bet',dict(roundId=round_id,amount=amount))
            self.assertEqual(self.s.state(200)['balance'],before)

    def test_withdrawal_caps_still_apply(self):
        items=self.add(['dragon']*11)
        with self.assertRaises(ValueError):self.call(200,'withdraw',dict(uids=items))
        self.assertEqual(len(self.s.state(200)['inventory']),11)

    def test_arrow_tip_matches_outcome_and_probability(self):
        class Draw:
            def __init__(self,unit):self.values=iter((.37,unit))
            def draw(self):return next(self.values)
        for chance in (.01,.05,.2,.5,.8,.95):
            wins=0
            for n in range(2000):
                result=landing(chance,Draw((n+.5)/2000))
                angle=math.radians(result['angle'])
                self.assertAlmostEqual(result['y'],120-math.cos(angle)*104)
                self.assertEqual(result['win'],result['y']>=result['level'])
                wins+=result['win']
            self.assertAlmostEqual(wins/2000,chance,places=3)

    def test_old_and_new_upgrade_proofs_remain_verifiable(self):
        for geometry,fn in ((None,legacy_landing),('arrow',landing)):
            seed='test-seed';client='client';chance=.2
            proof=dict(serverSeed=seed,serverHash=commitment(seed),clientSeed=client,nonce=1,game='upgrade',chance=chance,outcome=fn(chance,FairRandom(seed,client,1)))
            if geometry:proof['geometry']=geometry
            self.assertTrue(verify_document(proof)['valid'])

    def test_quest_rewards_grow_with_difficulty(self):
        variants={}
        for day in range(15):
            self.now=datetime(2026,10,1,12,tzinfo=timezone.utc).timestamp()+day*86400
            for quest in self.s.state(200)['quests']['items']:
                variants.setdefault(quest['kind'],{})[quest['goal']]=quest['reward']
        self.assertEqual(len(variants),5)
        for rewards in variants.values():
            values=[reward for _,reward in sorted(rewards.items())]
            self.assertGreater(values[-1],values[0])

    def test_deposit_notification_has_no_dialogue_button(self):
        rid=self.call(200,'deposit',dict(itemId='garama'))['result']['requestId']
        with self.s.store.tx() as db:row=db.execute('SELECT * FROM outbox WHERE id=?',(rid,)).fetchone()
        self.assertIn('@BrainrotFreebie_deposit_bot',row['message'])
        self.assertIsNone(row['payload'])


    def test_old_deposit_dialogues_and_queued_buttons_are_disabled(self):
        with self.s.store.tx() as db:
            db.execute('PRAGMA user_version=7')
            db.execute("INSERT INTO bot_dialogs VALUES(200,'old-deposit',0)")
            db.execute("INSERT INTO outbox(id,message,method,payload) VALUES('chat-message-old','','sendMessage',?)",(json.dumps(dict(chat_id=100,text='Old relay')),))
            payload=dict(chat_id=100,text='Новый депозит\nНажми «Ответить», чтобы выбрать этот диалог.',reply_markup=dict(inline_keyboard=[[dict(text='Ответить',callback_data='dep:reply:old-deposit')]]))
            db.execute("INSERT INTO outbox(id,message,method,payload) VALUES('old-owner-notice','','sendMessage',?)",(json.dumps(payload),))
        Service('/virtual/release150.db',admins=(100,),clock=lambda:self.now)
        with self.s.store.tx() as db:
            self.assertFalse(db.execute('SELECT * FROM bot_dialogs').fetchall())
            self.assertEqual(db.execute("SELECT sent FROM outbox WHERE id='chat-message-old'").fetchone()[0],1)
            payload=json.loads(db.execute("SELECT payload FROM outbox WHERE id='old-owner-notice'").fetchone()[0])
            self.assertNotIn('reply_markup',payload)
            self.assertIn('@BrainrotFreebie_deposit_bot',payload['text'])


if __name__=='__main__':unittest.main()
