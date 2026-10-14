import json
import unittest
from datetime import datetime, timezone
from tests import test_v150 as fixtures
from backend.service import ident
from backend.store import load_user, save_user
from backend.economy import distribution
from backend.fair import commitment

class Bonus160Tests(unittest.TestCase):
    setUp=fixtures.Release150Tests.setUp
    tearDown=fixtures.Release150Tests.tearDown
    call=fixtures.Release150Tests.call
    add=fixtures.Release150Tests.add

    def at(self,day,hour,minute=0):
        # October 17, 2026 is Saturday. Moscow is UTC+3.
        self.now=datetime(2026,10,day,hour-3,minute,tzinfo=timezone.utc).timestamp()

    def deposit(self,value,uid=200):
        with self.s.store.tx() as db:
            funding_id=ident()
            db.execute('INSERT INTO transfers VALUES(?,?,?,?,?,?)',(funding_id,uid,'deposit','approved',json.dumps(dict(value=value)),self.now))
            self.s.register_funding(db,uid,funding_id,round(value*100))
        return funding_id

    def test_deposit_case_expected_value(self):
        def ev(case):
            return sum(self.s.items[d['itemId']]['value']*d['chance'] for d in distribution(case,self.s.items))
        self.assertAlmostEqual(ev(self.s.cases['deposit']),ev(self.s.cases['referral'])*1.5)
        self.assertAlmostEqual(sum(d['baseChance'] for d in self.s.cases['deposit']['drops']),1)

    def test_all_or_nothing(self):
        case=self.s.cases['allornothing']
        self.assertEqual(case['price'],400)
        self.assertEqual({d['itemId']:d['chance'] for d in distribution(case,self.s.items)},{'garama':.7,'dragon':.3})

    def test_case_requires_confirmed_deposit_and_consumes_once(self):
        self.deposit(99)
        with self.assertRaises(ValueError):self.call(200,'case',dict(caseId='deposit'))
        self.deposit(100)
        key=ident()
        first=self.call(200,'case',dict(caseId='deposit'),key)
        second=self.call(200,'case',dict(caseId='deposit'),key)
        self.assertEqual(first['result'],second['result'])
        self.assertEqual(first['state']['bonuses']['depositCases'],0)
        with self.assertRaises(ValueError):self.call(200,'case',dict(caseId='deposit'))

    def test_one_case_per_qualifying_deposit(self):
        self.deposit(300)
        self.call(200,'case',dict(caseId='deposit'))
        with self.assertRaises(ValueError):self.call(200,'case',dict(caseId='deposit'))
        self.deposit(100)
        self.call(200,'case',dict(caseId='deposit'))

    def test_pending_deposit_does_not_award(self):
        response=self.call(200,'deposit',dict(itemId='dragon'))
        self.assertEqual(response['state']['bonuses']['depositCases'],0)
        self.call(100,'admin-transfer',dict(requestId=response['result']['requestId'],decision='approve'))
        self.assertEqual(self.s.state(200)['bonuses']['depositCases'],1)

    def test_giveaway_tickets_threshold_and_idempotency(self):
        self.deposit(49)
        with self.assertRaises(ValueError):self.call(200,'giveaway-enter')
        self.deposit(50);key=ident()
        self.call(200,'giveaway-enter',key=key)
        state=self.call(200,'giveaway-enter',key=key)['state']
        self.assertEqual(state['bonuses']['giveaway']['myTickets'],1)
        with self.assertRaises(ValueError):self.call(200,'giveaway-enter')

    def test_daily_draw_awards_once_and_persists(self):
        self.at(16,12)
        # Runtime rounds are now prepared at startup; anchor this legacy daily scenario to Friday.
        with self.s.store.tx() as db:
            db.execute("DELETE FROM controls WHERE name='giveaway_weekly_from'")
        self.s=type(self.s)('/virtual/release150.db',admins=(100,),clock=lambda:self.now)
        self.deposit(50);self.call(200,'giveaway-enter')
        before=self.s.state(200);server_hash=before['bonuses']['giveaway']['serverHash']
        initial=len(before['inventory']);self.at(17,3)
        after=self.s.state(200)
        self.assertEqual(len(after['inventory']),initial+1)
        self.assertEqual(after['inventory'][-1]['itemId'],'casaboo')
        last=after['bonuses']['giveaway']['last']
        self.assertEqual(commitment(last['serverSeed']),server_hash)
        self.assertEqual(len(self.s.state(200)['inventory']),initial+1)
        self.assertEqual(self.s.state(200)['bonuses']['giveaway']['myTickets'],0)

    def test_cashback_principal_once_per_week(self):
        self.deposit(100)
        first=self.call(200,'cashback-claim')
        self.assertEqual(first['result']['reward'],10)
        self.deposit(200)
        with self.assertRaises(ValueError):self.call(200,'cashback-claim')
        self.assertEqual(self.s.state(200)['bonuses']['cashback'],20)
        self.now+=7*86400
        self.assertEqual(self.call(200,'cashback-claim')['result']['reward'],20)

    def test_saturday_window_boundaries(self):
        self.deposit(100)
        for day,hour,minute,allowed in [(16,12,0,False),(17,9,59,False),(17,10,0,True),(17,19,59,True),(17,20,0,False),(18,12,0,False)]:
            self.at(day,hour,minute)
            self.assertEqual(self.s.state(200)['bonuses']['claimOpen'],allowed)
            if not allowed:
                with self.assertRaises(ValueError):self.call(200,'cashback-claim')

    def test_referral_claim_window_and_weekly_limit(self):
        with self.s.store.tx() as db:
            db.execute("INSERT INTO transfers VALUES(?,?,?,?,?,?)",(ident(),200,'deposit','approved','{\"value\":1000}',self.now))
            db.execute('INSERT INTO referral_ledger(event_id,invitee,net,stake,payout,created) VALUES(?,?,?,?,?,?)',(ident(),200,10000,10000,0,self.now))
        self.at(16,12)
        with self.assertRaises(ValueError):self.call(100,'partner-claim')
        self.at(17,10)
        first=self.call(100,'partner-claim')
        self.assertTrue(first['state']['bonuses']['partnerClaimed'])
        self.assertEqual(first['state']['partner']['depositCount'],1)
        self.assertEqual(first['state']['partner']['count'],1)
        with self.assertRaises(ValueError):self.call(100,'partner-claim')

    def test_refund_revokes_unused_rewards_and_cashback(self):
        funding=self.deposit(100)
        before=self.s.state(200)['balance']
        self.call(200,'cashback-claim')
        with self.s.store.tx() as db:
            _,state=load_user(db,200)
            self.s.revoke_funding(db,200,funding,state);save_user(db,200,state)
        state=self.s.state(200)
        self.assertEqual(state['balance'],before)
        self.assertEqual(state['bonuses']['cashback'],0)
        self.assertEqual(state['bonuses']['depositCases'],0)
        self.assertEqual(state['bonuses']['giveaway']['eligible'],0)

    def test_restart_keeps_tickets_and_claims(self):
        self.deposit(100);self.call(200,'giveaway-enter');self.call(200,'cashback-claim')
        from backend.service import Service
        fresh=Service('/virtual/release150.db',admins=(100,),clock=lambda:self.now)
        state=fresh.state(200)
        self.assertEqual(state['bonuses']['giveaway']['myTickets'],1)
        self.assertTrue(state['bonuses']['cashbackClaimed'])

if __name__=='__main__':unittest.main()
