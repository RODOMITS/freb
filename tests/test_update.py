import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.service import Service, ident
from backend.store import load_user, save_user
from backend.economy import distribution, slots, landing, RTP
from backend.fair import FairRandom


class UpdateTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'data'
        root.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=root)
        self.now=datetime(2026,10,17,13,0,tzinfo=timezone.utc).timestamp()
        self.s=Service(Path(self.tmp.name)/'db.sqlite',admins=(100,),clock=lambda:self.now)
        self.s.login(dict(id=100,first_name='Owner'))
        self.s.login(dict(id=200,first_name='User @BrainrotFreebie'),'ref_u100')
        self.s.login(dict(id=300,first_name='Other'))

    def tearDown(self): self.tmp.cleanup()

    def call(self,uid,action,body=None,key=None):
        return self.s.mutate(uid,action,body or {},key or ident())

    def inventory(self,uid,item):
        with self.s.store.tx() as db:
            _,state=load_user(db,uid)
            entry=self.s.add_item(state,item)
            save_user(db,uid,state)
        return entry

    def test_cancel_ownership_lock_and_idempotency(self):
        item=self.inventory(200,'garama')
        response=self.call(200,'withdraw',dict(uids=[item]))
        request=response['result']['requestId']
        self.assertFalse(response['state']['inventory'])
        self.assertEqual(response['state']['pendingInventory'][0]['uid'],item)
        for action,body in [('sale',dict(uid=item)),('upgrade',dict(uids=[item],targetId='dragon')),('withdraw-cancel',dict(requestId=request))]:
            with self.assertRaises(ValueError): self.call(300 if action=='withdraw-cancel' else 200,action,body)
        self.now+=86400
        key=ident()
        self.call(200,'withdraw-cancel',dict(requestId=request),key)
        self.call(200,'withdraw-cancel',dict(requestId=request),key)
        self.assertEqual(len(self.s.state(200)['inventory']),1)
        with self.assertRaises(ValueError):self.call(100,'admin-transfer',dict(requestId=request,decision='approve'))

    def test_window_boundaries_and_admin(self):
        start=self.now
        for offset,allowed in [(-1,False),(0,True),(3599,True),(3600,False),(86400,False)]:
            self.assertEqual(self.s.withdrawal_open(start+offset),allowed)
        item=self.inventory(200,'garama')
        request=self.call(200,'withdraw',dict(uids=[item]))['result']['requestId']
        self.now=start+3600
        with self.assertRaises(ValueError):self.call(100,'admin-transfer',dict(requestId=request,decision='approve'))
        self.now=start
        self.call(100,'admin-transfer',dict(requestId=request,decision='approve'))
        with self.assertRaises(ValueError):self.call(200,'withdraw-cancel',dict(requestId=request))

    def test_deposit_threshold_and_exclusion(self):
        for item in ('ketupat','lavadorito','eviledon'):
            with self.assertRaises(ValueError):self.call(200,'deposit',dict(itemId=item))
        self.call(200,'deposit',dict(itemId='garama'))

    def test_referrals_net_losses_funding_and_repeat_claim(self):
        with self.s.store.tx() as db:
            self.s.referral_result(db,200,'free-farming',100,0)
        self.assertEqual(self.s.state(100)['partner']['available'],0)
        req=self.call(200,'deposit',dict(itemId='garama'))['result']['requestId']
        self.call(100,'admin-transfer',dict(requestId=req,decision='approve'))
        with self.s.store.tx() as db:
            self.s.referral_result(db,200,'loss',50,0)
            self.s.referral_result(db,200,'loss',50,0)
            self.s.referral_result(db,200,'win',10,30)
        self.assertEqual(self.s.state(100)['partner']['available'],12)
        self.call(100,'partner-claim')
        self.assertEqual(self.s.state(100)['balance'],12)
        with self.assertRaises(ValueError):self.call(100,'partner-claim')
        with self.s.store.tx() as db:self.s.referral_result(db,200,'another-loss',1000,0)
        self.assertEqual(self.s.state(100)['partner']['available'],16.8)
        self.now+=86400
        req=self.call(100,'partner-withdraw')['result']['requestId']
        self.call(100,'withdraw-cancel',dict(requestId=req))
        self.assertEqual(self.s.state(100)['partner']['available'],16.8)

    def test_codes_immutable_attribution_and_free_cases(self):
        self.call(100,'partner-code',dict(code='my_code'))
        with self.assertRaises(ValueError):self.call(300,'partner-code',dict(code='my_code'))
        self.s.login(dict(id=200,first_name='User @BrainrotFreebie'),'ref_u300')
        self.assertEqual(self.s.state(100)['partner']['count'],1)
        self.call(200,'case',dict(caseId='referral'))
        self.call(200,'case',dict(caseId='nickname'))
        for uid,case in [(200,'referral'),(200,'nickname'),(300,'nickname'),(300,'referral')]:
            with self.assertRaises(ValueError):self.call(uid,'case',dict(caseId=case))

    def test_case_rtp_and_slot_bands(self):
        for case in self.s.cases.values():
            d=distribution(case,self.s.items)
            self.assertAlmostEqual(sum(x['chance'] for x in d),1)
            if not case.get('free'):
                self.assertAlmostEqual(sum(self.s.items[x['itemId']]['value']*x['chance'] for x in d),{'sahur':18.4,'feast':308,'burrow':272}.get(case['id'],.8*case['price']))
        class Rng:
            def __init__(self,u):self.u=u
            def draw(self):return self.u
            def pick(self,pool):return pool.pop(0)
        for u,m in [(0,5),(.029999,5),(.03,2),(.354999,2),(.355,0),(.999,0)]:
            self.assertEqual(slots(10,list(self.s.items),Rng(u))['multiplier'],m)
        self.assertAlmostEqual(.03*5+.325*2,RTP)

    def test_top_drop_moscow_day(self):
        with self.s.store.tx() as db:self.s.drop(db,200,'dragon')
        self.assertEqual(self.s.state(100)['topDrop']['itemId'],'dragon')
        self.now+=86400
        self.assertIsNone(self.s.state(100)['topDrop'])

if __name__=='__main__':unittest.main()
