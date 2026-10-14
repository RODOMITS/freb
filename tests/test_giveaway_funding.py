import unittest,json
from tests import test_v150 as fixtures
from backend.service import Service,ident
from backend.store import load_user

class GiveawayFundingTests(unittest.TestCase):
    setUp=fixtures.Release150Tests.setUp
    tearDown=fixtures.Release150Tests.tearDown
    call=fixtures.Release150Tests.call

    def funding(self,uid=200,amount=50,source='deposit',status='approved',source_uid=None,source_amount=None):
        funding_id=ident()
        source_uid=uid if source_uid is None else source_uid
        source_amount=amount if source_amount is None else source_amount
        with self.s.store.tx() as db:
            if source=='deposit':
                db.execute('INSERT INTO transfers VALUES(?,?,?,?,?,?)',(funding_id,source_uid,'deposit',status,json.dumps(dict(value=source_amount)),self.now))
            elif source=='stars':
                db.execute('INSERT INTO invoices(id,user_id,stars,status,charge,created) VALUES(?,?,?,?,?,?)',(funding_id,source_uid,source_amount,status,'charge-'+funding_id if status=='paid' else None,self.now))
            self.s.register_funding(db,uid,funding_id,round(amount*100))
        return funding_id

    def attach(self,funding_id,round_id):
        with self.s.store.tx() as db:db.execute('UPDATE funding_bonuses SET giveaway_day=? WHERE id=?',(round_id,funding_id))

    def test_twelve_members_with_two_real_deposits_counts_two(self):
        g=self.s.state(200)['bonuses']['giveaway']
        for uid in (200,300):self.attach(self.funding(uid=uid),g['day'])
        for uid in range(1000,1010):
            self.s.login(dict(id=uid,first_name='Fake'))
            self.attach(self.funding(uid=uid,source='none'),g['day'])
        state=self.s.state(200)
        self.assertEqual(state['bonuses']['giveaway']['participants'],2)
        self.assertEqual(state['bonuses']['giveaway']['tickets'],2)
        checked=self.call(100,'admin-giveaway-check')
        self.assertEqual(checked['result']['removedCount'],10)
        with self.s.store.tx() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM funding_bonuses WHERE giveaway_day=?',(g['day'],)).fetchone()[0],2)

    def test_restart_removes_invalid_preserves_legitimate_round_and_balances(self):
        g=self.s.state(200)['bonuses']['giveaway']
        good=self.funding();bad=self.funding(uid=300,source='none')
        self.attach(good,g['day']);self.attach(bad,g['day'])
        before=self.s.state(200)['balance']
        self.s=Service('/virtual/release150.db',admins=(100,),clock=lambda:self.now)
        after=self.s.state(200)
        self.assertEqual(after['balance'],before)
        self.assertEqual(after['bonuses']['giveaway']['participants'],1)
        self.assertEqual(after['bonuses']['giveaway']['serverHash'],g['serverHash'])
        self.assertEqual(after['bonuses']['giveaway']['drawAt'],g['drawAt'])
        with self.s.store.tx() as db:
            self.assertIsNone(db.execute('SELECT giveaway_day FROM funding_bonuses WHERE id=?',(bad,)).fetchone()[0])
            self.assertEqual(db.execute('SELECT giveaway_day FROM funding_bonuses WHERE id=?',(good,)).fetchone()[0],g['day'])

    def test_orphan_pending_rejected_cannot_enter(self):
        for source,status in [('none','approved'),('deposit','pending'),('deposit','rejected'),('stars','pending'),('stars','refund_requested'),('stars','refunded')]:
            self.funding(source=source,status=status,source_amount=34 if source=='stars' else 50,amount=51 if source=='stars' else 50)
        self.assertEqual(self.s.state(200)['bonuses']['giveaway']['eligible'],0)
        with self.assertRaises(ValueError):self.call(200,'giveaway-enter')

    def test_paid_stars_qualify_and_consumed_once(self):
        self.funding(source='stars',status='paid',source_amount=34,amount=51)
        state=self.call(200,'giveaway-enter')['state']
        self.assertEqual(state['bonuses']['giveaway']['myTickets'],1)
        with self.assertRaises(ValueError):self.call(200,'giveaway-enter')

    def test_wrong_owner_and_inflated_amount_do_not_qualify(self):
        self.funding(source_uid=300)
        self.funding(source_amount=20,amount=50)
        self.funding(source='stars',status='paid',source_amount=1,amount=50)
        self.assertEqual(self.s.state(200)['bonuses']['giveaway']['eligible'],0)

    def test_invalid_ticket_cannot_win(self):
        g=self.s.state(200)['bonuses']['giveaway']
        bad=self.funding(uid=300,source='none');good=self.funding()
        self.attach(bad,g['day']);self.attach(good,g['day'])
        self.now=g['drawAt']/1000
        self.assertEqual(self.s.state(200)['bonuses']['giveaway']['last']['winnerId'],200)

    def test_orphan_cannot_claim_deposit_case_or_cashback(self):
        self.funding(amount=100,source='none')
        state=self.s.state(200)
        self.assertEqual(state['bonuses']['cashback'],0)
        self.assertEqual(state['bonuses']['depositCases'],0)
        with self.assertRaises(ValueError):self.call(200,'cashback-claim')
        with self.assertRaises(ValueError):self.call(200,'case',dict(caseId='deposit'))

    def test_admin_check_is_admin_only(self):
        with self.assertRaises(PermissionError):self.call(200,'admin-giveaway-check')

    def test_completed_draw_history_not_rewritten(self):
        day='2026-10-01';bad=self.funding(source='none');self.attach(bad,day)
        with self.s.store.tx() as db:
            db.execute('INSERT INTO giveaway_draws VALUES(?,?,?,?,?,?,?)',(day,200,bad,1,'old-seed','old-hash',self.now-86400))
        self.call(100,'admin-giveaway-check')
        with self.s.store.tx() as db:
            self.assertEqual(db.execute('SELECT giveaway_day FROM funding_bonuses WHERE id=?',(bad,)).fetchone()[0],day)

if __name__=='__main__':unittest.main()
