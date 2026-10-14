import json
import unittest
from tests import test_v150 as fixtures
from backend.service import Service, ident
from backend.store import load_user, save_user

class AccountFreezeTests(unittest.TestCase):
    setUp=fixtures.Release150Tests.setUp
    tearDown=fixtures.Release150Tests.tearDown
    call=fixtures.Release150Tests.call
    add=fixtures.Release150Tests.add

    def freeze(self,uid=200,balance=True,withdrawal=True):
        return self.call(100,'admin-freeze',dict(userId=uid,balanceFrozen=balance,withdrawalFrozen=withdrawal,reason='Проверка'))

    def deposit(self,uid=200):
        request=self.call(uid,'deposit',dict(itemId='garama'))['result']['requestId']
        self.call(100,'admin-transfer',dict(requestId=request,decision='approve'))
        return request

    def pending(self,uid=200,kind='withdraw'):
        request=ident()
        with self.s.store.tx() as db:
            if kind=='withdraw':
                _,state=load_user(db,uid)
                entry=dict(uid=ident(),itemId='garama')
                data=dict(entries=[entry],value=self.s.items['garama']['value'])
            else:
                data=dict(value=5)
                db.execute('UPDATE partners SET claimed=claimed+500 WHERE user_id=?',(uid,))
            db.execute('INSERT INTO transfers VALUES(?,?,?,?,?,?)',(request,uid,kind,'pending',json.dumps(data),self.now))
        return request

    def test_requested_accounts_are_frozen_once_and_survive_restart(self):
        for uid in (7221165756,6263182915):
            self.s.login(dict(id=uid,first_name='Hold'))
            state=self.s.state(uid)
            self.assertTrue(state['balanceFrozen'] and state['withdrawalFrozen'])
        self.freeze(7221165756,False,False)
        restarted=Service('/virtual/release150.db',admins=(100,),clock=lambda:self.now)
        self.assertFalse(restarted.state(7221165756)['balanceFrozen'])
        self.assertTrue(restarted.state(6263182915)['withdrawalFrozen'])
        self.assertFalse(restarted.state(200)['balanceFrozen'])

    def test_freeze_blocks_financial_actions_even_without_browser(self):
        self.freeze()
        before=self.s.state(200)
        for action,body in [('case',dict(caseId='plant')),('upgrade',{}),('slots',{}),('mines-start',{}),('rocket-bet',{}),('sale',{}),('sale-all',{}),('withdraw',{}),('partner-withdraw',{}),('partner-claim',{}),('cashback-claim',{}),('quest-claim',{}),('promo',dict(code='MIAMI')),('deposit',dict(itemId='garama'))]:
            with self.subTest(action=action):
                with self.assertRaisesRegex(ValueError,'заморожен'):self.call(200,action,body)
        after=self.s.state(200)
        self.assertEqual((before['balance'],before['inventory']),(after['balance'],after['inventory']))

    def test_withdraw_only_lock_allows_games_but_blocks_existing_issue(self):
        request=self.pending()
        self.freeze(balance=False)
        self.call(200,'case',dict(caseId='plant'))
        with self.assertRaisesRegex(ValueError,'заморожен'):
            self.call(100,'admin-transfer',dict(requestId=request,decision='approve'))
        self.call(200,'withdraw-cancel',dict(requestId=request))
        self.assertTrue(any(e['itemId']=='garama' for e in self.s.state(200)['inventory']))

    def test_balance_only_freeze_blocks_admin_issue(self):
        request=self.pending()
        self.freeze(withdrawal=False)
        with self.assertRaisesRegex(ValueError,'заморожен'):
            self.call(100,'admin-transfer',dict(requestId=request,decision='approve'))
        self.call(100,'admin-transfer',dict(requestId=request,decision='reject'))

    def test_reverse_deducts_bonus_cashback_and_revokes_eligibility(self):
        before=self.s.state(200)['balance']
        request=self.deposit()
        total=self.s.state(200)['balance']-before
        self.assertGreater(total,self.s.items['garama']['value'])
        self.call(200,'giveaway-enter')
        self.call(200,'cashback-claim')
        withdraw=self.pending()
        commission=self.pending(kind='partner-withdraw')
        response=self.call(100,'admin-deposit-reverse',dict(requestId=request))['result']
        state=self.s.state(200)
        self.assertAlmostEqual(state['balance'],before)
        self.assertAlmostEqual(response['reversed'],total)
        self.assertTrue(state['balanceFrozen'] and state['withdrawalFrozen'])
        self.assertEqual(state['bonuses']['cashback'],0)
        self.assertEqual(state['bonuses']['giveaway']['myTickets'],0)
        self.assertEqual(state['bonuses']['giveaway']['participants'],0)
        self.assertEqual(self.s.state(100)['partner']['depositCount'],0)
        statuses={t['id']:t['status'] for t in state['transfers']}
        self.assertEqual([statuses[r] for r in (request,withdraw,commission)],['reversed','cancelled','cancelled'])
        with self.s.store.tx() as db:
            self.assertEqual(db.execute('SELECT active FROM funding_bonuses WHERE id=?',(request,)).fetchone()[0],0)
            self.assertEqual(db.execute('SELECT claimed FROM partners WHERE user_id=200').fetchone()[0],0)
        with self.assertRaises(ValueError):self.call(100,'admin-deposit-reverse',dict(requestId=request))

    def test_reverse_spent_credit_creates_debt_instead_of_negative_balance(self):
        request=self.deposit()
        with self.s.store.tx() as db:
            _,state=load_user(db,200);state['balance']=100;save_user(db,200,state)
            data=json.loads(db.execute('SELECT data FROM transfers WHERE id=?',(request,)).fetchone()[0])
        total=data['value']+data['bonus']/100
        state=self.call(100,'admin-deposit-reverse',dict(requestId=request))['result']
        self.assertEqual(state['deducted'],1)
        self.assertAlmostEqual(state['debt'],total-1)
        self.assertEqual(self.s.state(200)['balance'],0)

    def test_reversal_is_idempotent_and_permissions_are_enforced(self):
        request=self.deposit();key=ident()
        with self.assertRaises(PermissionError):self.call(300,'admin-freeze',dict(userId=200,balanceFrozen=True,withdrawalFrozen=True))
        with self.assertRaises(PermissionError):self.call(300,'admin-deposit-reverse',dict(requestId=request))
        first=self.call(100,'admin-deposit-reverse',dict(requestId=request),key)
        self.assertEqual(first,self.call(100,'admin-deposit-reverse',dict(requestId=request),key))
        self.assertEqual(len([h for h in self.s.state(200)['history'] if h['title']=='Отмена подтверждения депозита']),1)

    def test_invalid_reversal_does_not_change_pending_deposit(self):
        request=self.call(200,'deposit',dict(itemId='garama'))['result']['requestId']
        before=self.s.state(200)['balance']
        with self.assertRaises(ValueError):self.call(100,'admin-deposit-reverse',dict(requestId=request))
        self.assertEqual(self.s.state(200)['balance'],before)
        self.assertFalse(self.s.state(200)['balanceFrozen'])

    def test_admin_can_reverse_own_deposit_without_losing_mutations(self):
        request=self.deposit(100)
        before=self.s.state(100)['balance']
        with self.s.store.tx() as db:
            data=json.loads(db.execute('SELECT data FROM transfers WHERE id=?',(request,)).fetchone()[0])
        self.call(100,'admin-deposit-reverse',dict(requestId=request))
        self.assertAlmostEqual(self.s.state(100)['balance'],before-data['value'])
        self.assertTrue(self.s.state(100)['balanceFrozen'])

    def test_existing_mines_can_cash_out_while_balance_stays_locked(self):
        self.call(200,'mines-start',dict(uids=self.add(['67']),bombCount=3))
        with self.s.store.tx() as db:
            _,state=load_user(db,200);safe=next(i for i in range(25) if i not in state['mines']['bombs'])
        self.call(200,'mines-reveal',dict(index=safe))
        self.freeze()
        result=self.call(200,'mines-cash')['state']
        self.assertEqual(result['mines']['status'],'won')
        self.assertTrue(result['balanceFrozen'])

    def test_lock_flags_are_strict_and_unknown_user_is_not_created(self):
        for body in [dict(userId=200,balanceFrozen='false',withdrawalFrozen=True),dict(userId=999,balanceFrozen=True,withdrawalFrozen=True)]:
            with self.assertRaises(ValueError):self.call(100,'admin-freeze',body)
        self.assertFalse(self.s.state(200)['balanceFrozen'])
