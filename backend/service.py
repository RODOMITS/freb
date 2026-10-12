import copy
import hashlib
import json
import math
import re
import secrets
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .economy import RTP, cents, crash_point, distribution, landing, mines_multiplier, roll_case, slots
from .fair import FairRandom, commitment, new_seed
from .store import Store, load_user, save_user
from .risk import Limits


def ident():
    return uuid.uuid4().hex


def integer(value, minimum=1, maximum=1000000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'Ожидается целое число от {minimum} до {maximum}')
    return value


class Service:
    def __init__(self, path, admins=(7613236278,1821268346), starting_balance=0, clock=time.time, limits=None):
        self.store, self.admins, self.clock = Store(path), set(admins), clock
        self.limits=limits or Limits()
        self.starting_balance = cents(starting_balance)
        catalog = json.loads(Path(__file__).with_name('catalog.json').read_text(encoding='utf-8'))
        self.items = {item['id']:item for item in catalog['items']}
        self.cases = {case['id']:case for case in catalog['cases']}
        for case_id, name, free, hue in [('daily','Бесплатный кейс','daily',0),('subscribe','Кейс за подписку','subscribe',0)]:
            self.cases[case_id] = dict(id=case_id,name=name,price=0,free=free,hue=hue,image='img/cases/daily.png' if case_id=='daily' else 'img/cases/subscribe.png',drops=[dict(itemId=i,baseChance=p) for i,p in ([('67',.94),('lagrand',.05),('bananito',.01)] if case_id=='daily' else [('67',.85),('lagrand',.10),('bananito',.04),('esok',.01)])])
        for case_id,name in [('referral','За приглашение'),('nickname','За ник')]:
            self.cases[case_id]=dict(id=case_id,name=name,price=0,free=case_id,theme='Бесплатные',hue=0,image='img/cases/'+case_id+'.png',drops=[dict(itemId=i,baseChance=p) for i,p in [('67',.85),('lagrand',.10),('bananito',.04),('esok',.01)]])
        for case in self.cases.values():
            distribution(case,self.items)

    def login(self, user, start_param=""):

        uid, now = user['id'], self.clock()
        with self.store.tx() as db:
            state = dict(version=1,balance=self.starting_balance,debt=0,inventory=[],stats=dict(opened=0,upgrades=0,wins=0),mines=None,rocket=None,slotResult=None)
            fresh=not db.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone()
            code='u'+str(uid)
            db.execute('INSERT OR IGNORE INTO partners(user_id,code) VALUES(?,?)',(uid,code))
            db.execute('INSERT OR IGNORE INTO referral_codes VALUES(?,?)',(code,uid))
            if fresh and start_param.startswith('ref_'):
                parent=db.execute('SELECT user_id FROM referral_codes WHERE code=?',(start_param[4:].lower(),)).fetchone()
                if parent and parent['user_id']!=uid:
                    db.execute('INSERT OR IGNORE INTO referrals VALUES(?,?,?)',(uid,parent['user_id'],now))
            db.execute('INSERT OR IGNORE INTO users(id,profile,state,seed,client) VALUES(?,?,?,?,?)', (uid,json.dumps(user),json.dumps(state),new_seed(),secrets.token_hex(16)))
            db.execute('UPDATE users SET profile=? WHERE id=?', (json.dumps(user),uid))
            token = secrets.token_urlsafe(32)
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,now+86400))
            db.execute('DELETE FROM sessions WHERE expires<?',(now,))
        return token

    @staticmethod
    def withdrawal_open(now):
        msk=datetime.fromtimestamp(now,timezone(timedelta(hours=3)))
        return msk.weekday()==5 and msk.hour==16

    def referral_result(self, db, uid, event_id, stake, payout):
        funded=db.execute("SELECT 1 FROM invoices WHERE user_id=? AND status='paid' UNION ALL SELECT 1 FROM transfers WHERE user_id=? AND kind='deposit' AND status='approved' LIMIT 1",(uid,uid)).fetchone()
        if funded and db.execute('SELECT 1 FROM referrals WHERE invitee=?',(uid,)).fetchone():
            db.execute('INSERT OR IGNORE INTO referral_ledger VALUES(?,?,?)',(event_id,uid,cents(stake)-cents(payout)))

    def partner(self, db, uid):
        account=db.execute('SELECT * FROM partners WHERE user_id=?',(uid,)).fetchone()
        if not account:
            code='u'+str(uid)
            db.execute('INSERT INTO partners(user_id,code) VALUES(?,?)',(uid,code))
            db.execute('INSERT OR IGNORE INTO referral_codes VALUES(?,?)',(code,uid))
            account=db.execute('SELECT * FROM partners WHERE user_id=?',(uid,)).fetchone()
        people=db.execute('SELECT invitee FROM referrals WHERE inviter=?',(uid,)).fetchall()
        net=0
        for person in people:
            who=person['invitee']
            paid=db.execute("SELECT coalesce(sum(stars),0)*150 FROM invoices WHERE user_id=? AND status='paid'",(who,)).fetchone()[0]
            paid+=sum(cents(json.loads(r['data'])['value']) for r in db.execute("SELECT data FROM transfers WHERE user_id=? AND kind='deposit' AND status='approved'",(who,)))
            loss=db.execute('SELECT coalesce(sum(net),0) FROM referral_ledger WHERE invitee=?',(who,)).fetchone()[0]
            # Carry wins forward and cap eligible losses by confirmed funding.
            net+=min(loss,paid)
        earned=max(0,net)*40//100
        available=max(0,earned-account['claimed'])
        return dict(code=account['code'],count=len(people),earned=earned/100,claimed=account['claimed']/100,available=available/100,availableCents=available)

    def authenticate(self, token):
        with self.store.tx() as db:
            row = db.execute('SELECT user_id FROM sessions WHERE token=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),self.clock())).fetchone()
        if not row:
            raise PermissionError('Сессия истекла. Открой приложение заново в Telegram.')
        return row['user_id']

    def operation(self, db, uid, kind, title, status='done', delta=0, detail='', proof=None, op_id=None):
        op_id = op_id or ident()
        db.execute('INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,delta=excluded.delta,detail=excluded.detail', (op_id,uid,kind,status,delta,title,detail,self.clock(),json.dumps(proof) if proof else None))
        return op_id

    def rng(self, db, uid, kind):
        row,_ = load_user(db,uid)
        nonce = row['nonce']
        db.execute('UPDATE users SET nonce=nonce+1 WHERE id=?',(uid,))
        proof = dict(serverHash=commitment(row['seed']),clientSeed=row['client'],nonce=nonce,game=kind,algorithm='HMAC-SHA256 / first 52 bits / clientSeed:nonce:cursor')
        return FairRandom(row['seed'],row['client'],nonce), proof

    def stake(self, state, uids):
        if not isinstance(uids,list) or not 1 <= len(uids) <= 100 or any(not isinstance(u,str) for u in uids) or len(set(uids)) != len(uids):
            raise ValueError('Выбери от 1 до 100 разных предметов')
        entries = [e for e in state['inventory'] if e['uid'] in uids]
        if len(entries) != len(uids):
            raise ValueError('Предмет недоступен или уже поставлен')
        state['inventory'] = [e for e in state['inventory'] if e['uid'] not in uids]
        return sum(self.items[e['itemId']]['value'] for e in entries), entries

    def credit(self, state, amount):
        covered=min(state.get('debt',0),amount)
        state['debt']=state.get('debt',0)-covered
        state['balance']+=amount-covered

    def check_risk(self, db, maximum):
        outstanding=0
        for row in db.execute('SELECT state FROM users'):
            state=json.loads(row['state'])
            for kind in ('mines','rocket'):
                game=state.get(kind)
                if game and game['status']=='active':
                    outstanding+=cents(game.get('riskMax',game['stakeValue']*100 if kind=='rocket' else self.limits.max_payout))
        if outstanding+cents(maximum)>cents(self.limits.max_open_risk):
            raise ValueError('Лимит активных ставок достигнут. Дождись завершения игр.')

    def withdraw_hold(self, db, uid):
        pending=db.execute("SELECT max(created) FROM invoices WHERE user_id=? AND status='refund_requested'",(uid,)).fetchone()[0]
        if pending is not None:
            return pending+315360000
        row=db.execute("SELECT max(held_until) FROM invoices WHERE user_id=? AND status IN ('paid','refund_requested')",(uid,)).fetchone()
        return row[0] or 0

    def apply_refund(self, db, invoice, charge):
        if invoice['status']=='refunded':
            return
        uid=invoice['user_id']
        _,state=load_user(db,uid)
        delta=invoice['stars']*150 if invoice['status'] in ('paid','refund_requested') else 0
        used=min(delta,state['balance'])
        state['balance']-=used
        state['debt']=state.get('debt',0)+delta-used
        # Pending withdrawals are reversible; completed trades need operator review.
        for transfer in db.execute("SELECT * FROM transfers WHERE user_id=? AND kind='withdraw' AND status='pending'",(uid,)).fetchall():
            state['inventory'].extend(json.loads(transfer['data'])['entries'])
            db.execute("UPDATE transfers SET status='rejected' WHERE id=?",(transfer['id'],))
            self.operation(db,uid,'withdraw','Вывод отменён','lose',detail='Возврат платежа Stars',op_id=transfer['id'])
        save_user(db,uid,state)
        db.execute("UPDATE invoices SET status='refunded',charge=? WHERE id=?",(charge,invoice['id']))
        db.execute("UPDATE refund_jobs SET status='done' WHERE invoice_id=?",(invoice['id'],))
        self.operation(db,uid,'refund','Возврат Stars',delta=-used,detail=f'{invoice["stars"]} Stars · долг {state["debt"]/100} BStars',op_id='refund-'+invoice['id'])
        self.audit(db,uid,'refund',dict(invoiceId=invoice['id'],debt=state['debt']))

    def add_item(self, state, item_id):
        entry = dict(uid=ident(),itemId=item_id)
        state['inventory'].append(entry)
        return entry['uid']

    def current_round(self, db):
        row = db.execute('SELECT data FROM rounds ORDER BY rowid DESC LIMIT 1').fetchone()
        game = json.loads(row['data']) if row else None
        if game is None or self.clock() >= game['endAt']/1000+3:
            seed, round_id = new_seed(), ident()
            crash = crash_point(FairRandom(seed,round_id,0).draw())
            start = (self.clock()+10)*1000
            game = dict(id=round_id,rtp=RTP,seed=seed,serverHash=commitment(seed),clientSeed=round_id,startAt=start,endAt=start+math.log(crash)/.24*1000,crash=crash,capped=crash>=100,maxTotalStake=self.limits.rocket_round_stake)
            db.execute('INSERT INTO rounds VALUES(?,?)',(round_id,json.dumps(game)))
        return game

    def tick(self, db):
        now = self.clock()*1000
        # Settle stored wagers before rotating the public round, including after restart.
        for row in db.execute('SELECT id,state FROM users').fetchall():
            state, changed = json.loads(row['state']), False
            mines = state.get('mines')
            if mines and mines['status']=='active' and now>=mines['expiresAt']:
                self.finish_mines(db,row['id'],state,bool(mines['opened']),'Истёк таймер')
                changed = True
            rocket = state.get('rocket')
            if rocket and rocket['status']=='active':
                target = rocket['autoCash']
                due = rocket['startAt'] + math.log(target)/.24*1000 if target else math.inf
                if target and target<=rocket['crash'] and now>=due:
                    self.finish_rocket(db,row['id'],state,target,True)
                    changed = True
                elif now >= rocket['endAt']:
                    self.finish_rocket(db,row['id'],state,100 if rocket['capped'] else 0,True)
                    changed = True
            if changed:
                save_user(db,row['id'],state)
        self.current_round(db)

    def finish_mines(self, db, uid, state, win, reason=''):
        game = state['mines']
        payout = cents(game['stakeValue']*mines_multiplier(game['bombCount'],len(game['opened']),game.get('rtp',.85))) if win else 0
        game.update(status='won' if win else 'lost',payout=payout/100)
        self.credit(state,payout)
        self.referral_result(db,uid,game['id'],game['stakeValue'],payout/100)
        self.operation(db,uid,'mines','Мины','win' if win else 'lose',payout,f'{reason} · ставка {game["stakeValue"]} · открыто {len(game["opened"])} · выплата {payout/100}',op_id=game['id'])

    def finish_rocket(self, db, uid, state, multiplier, automatic):
        game = state['rocket']
        payout = cents(game['stakeValue']*multiplier)
        game.update(status='won' if multiplier else 'lost',cashAt=multiplier,payout=payout/100,automatic=automatic)
        self.credit(state,payout)
        detail = f'{"Автозабор" if automatic else "Забор"} ×{multiplier:.2f} · ставка {game["stakeValue"]} · выплата {payout/100}' if multiplier else f'Взрыв ×{math.floor(game["crash"]*100)/100:.2f}'
        self.referral_result(db,uid,game['id'],game['stakeValue'],payout/100)
        self.operation(db,uid,'rocket','Ракетка','win' if multiplier else 'lose',payout,detail,op_id=game['id'])

    def snapshot(self, db, uid, history_limit=200):
        row, state = load_user(db,uid)
        result = copy.deepcopy(state)
        result['balance'] /= 100
        result['partner']=self.partner(db,uid)
        result['partner'].pop('availableCents',None)
        result['withdrawalOpen']=self.withdrawal_open(self.clock())
        result['pendingInventory']=[dict(e,requestId=r['id'],status='withdrawing') for r in db.execute("SELECT id,data FROM transfers WHERE user_id=? AND kind='withdraw' AND status='pending'",(uid,)) for e in json.loads(r['data'])['entries']]
        today=datetime.fromtimestamp(self.clock(),timezone(timedelta(hours=3))).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        drops=[dict(json.loads(r['detail']),created=r['created']) for r in db.execute("SELECT detail,created FROM audit WHERE action='drop' AND created>=?",(today,))]
        result['topDrop']=max(drops,key=lambda d:self.items.get(d['itemId'],{}).get('value',0)) if drops else None
        result['debt']=state.get('debt',0)/100
        result['withdrawHeldUntil']=self.withdraw_hold(db,uid)*1000
        result['refundReviewPending']=bool(db.execute("SELECT 1 FROM invoices WHERE user_id=? AND status='refund_requested'",(uid,)).fetchone())
        result['limits']=self.limits.public()
        control=db.execute("SELECT value FROM controls WHERE name='paused'").fetchone()
        result['gamesPaused']=bool(control and control['value'])
        result['isAdmin'] = uid in self.admins
        result['profile'] = json.loads(row['profile'])
        history = db.execute('SELECT * FROM operations WHERE user_id=? ORDER BY created DESC,rowid DESC LIMIT ?', (uid,history_limit)).fetchall()
        result['history'] = [dict(id=h['id'],type=h['type'],status=h['status'],delta=h['delta']/100,title=h['title'],detail=h['detail'],createdAt=datetime.fromtimestamp(h['created'],timezone.utc).isoformat(),proof=json.loads(h['proof']) if h['proof'] else None) for h in history]
        result['historyTotal'] = db.execute('SELECT count(*) FROM operations WHERE user_id=?',(uid,)).fetchone()[0]
        for operation in result['history']:
            if operation['type']=='mines' and operation['status']=='pending' and operation['proof']:
                operation['proof'].pop('outcome',None)
        result['fair'] = dict(serverHash=commitment(row['seed']),clientSeed=row['client'],nonce=row['nonce'])
        result['feed'] = [dict(itemId=json.loads(r['detail'])['itemId'],playerName=json.loads(r['detail'])['playerName']) for r in db.execute("SELECT detail FROM audit WHERE action='drop' ORDER BY id DESC LIMIT 12")]
        result['promos'] = [dict(code=p['code'],reward=p['reward']/100,limit=p['max_uses'],used=p['uses'],active=bool(p['active'])) for p in db.execute('SELECT * FROM promos')] if uid in self.admins else []
        result['redeemed'] = [r['code'] for r in db.execute('SELECT code FROM redemptions WHERE user_id=?',(uid,))]
        result['freeClaims'] = {r['case_id']:r['claimed']*1000 for r in db.execute('SELECT * FROM claims WHERE user_id=?',(uid,))}
        if result['mines'] and result['mines']['status']=='active':
            result['mines']['bombs'] = []
        round_ = self.current_round(db)
        public_round = {k:v for k,v in round_.items() if k not in ('seed','crash','endAt','capped')}
        public_round['ended'] = self.clock()*1000 >= round_['endAt']
        if public_round['ended']:
            public_round.update(crash=round_['crash'],capped=round_['capped'],serverSeed=round_['seed'],endAt=round_['endAt'])
        result['round'] = public_round
        game = result.get('rocket')
        if game and self.clock()*1000 < game['endAt']:
            game.pop('crash',None)
            game.pop('endAt',None)
            game.pop('capped',None)
        if uid in self.admins:
            result['payments']=[dict(id=r['id'],userId=r['user_id'],stars=r['stars'],status=r['status'],heldUntil=r['held_until']*1000,refundStatus=r['refund_status']) for r in db.execute('SELECT invoices.*,refund_jobs.status AS refund_status FROM invoices LEFT JOIN refund_jobs ON refund_jobs.invoice_id=invoices.id ORDER BY invoices.created DESC LIMIT 100')]
            day=datetime.fromtimestamp(self.clock(),timezone.utc).strftime('%Y-%m-%d')
            spent=db.execute('SELECT spent FROM bonus_spend WHERE day=?',(day,)).fetchone()
            result['bonusSpentToday']=(spent['spent']/100) if spent else 0
            result['transfers'] = [dict(id=r['id'],userId=r['user_id'],kind=r['kind'],status=r['status'],data=json.loads(r['data'])) for r in db.execute("SELECT * FROM transfers ORDER BY created DESC LIMIT 100")]
            result['users'] = [dict(id=r['id'],name=json.loads(r['profile']).get('first_name','Игрок'),balance=json.loads(r['state'])['balance']/100) for r in db.execute('SELECT id,profile,state FROM users ORDER BY id LIMIT 100')]
        else:
            result['transfers'] = [dict(id=r['id'],kind=r['kind'],status=r['status'],data=json.loads(r['data'])) for r in db.execute('SELECT * FROM transfers WHERE user_id=? ORDER BY created DESC LIMIT 100',(uid,))]
        result['serverNow'] = self.clock()*1000
        return result

    def state(self, uid, limit=200):
        with self.store.tx() as db:
            self.tick(db)
            return self.snapshot(db,uid,limit)

    def mutate(self, uid, action, body, key):
        if action.startswith('admin-') and uid not in self.admins:
            raise PermissionError('Доступ администратора запрещён')
        for field in ('caseId','targetId','itemId','uid','roundId','requestId'):
            if field in body and (not isinstance(body[field],str) or not 1<=len(body[field])<=100):
                raise ValueError(f'Некорректное поле {field}')
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}',key):
            raise ValueError('Требуется Idempotency-Key')
        fingerprint = hashlib.sha256(json.dumps([action,body],sort_keys=True).encode()).hexdigest()
        with self.store.tx() as db:
            cached = db.execute('SELECT * FROM requests WHERE user_id=? AND key=?',(uid,key)).fetchone()
            if cached:
                if cached['fingerprint'] != fingerprint:
                    raise ValueError('Ключ уже использован для другой операции')
                return json.loads(cached['response'])
            self.tick(db)
            _,state = load_user(db,uid)
            data = self.execute(db,uid,state,action,body)
            save_user(db,uid,state)
            response = dict(state=self.snapshot(db,uid),result=data)
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?)',(uid,key,fingerprint,json.dumps(response),self.clock()))
            return response

    def drop(self, db, uid, item_id):
        row,_ = load_user(db,uid)
        profile=json.loads(row['profile'])
        self.audit(db,uid,'drop',dict(itemId=item_id,playerName=profile.get('first_name','Игрок')))

    def audit(self, db, uid, action, detail):
        db.execute('INSERT INTO audit(actor,action,detail,created) VALUES(?,?,?,?)',(uid,action,json.dumps(detail),self.clock()))

    def execute(self, db, uid, state, action, b):
        now = self.clock()
        if state.get('debt',0)>0 and action not in ('deposit','fair-rotate','withdraw-cancel') and not action.startswith('admin-'):
            raise ValueError('Есть задолженность после возврата платежа. Обратись в поддержку.')
        if action in ('case','upgrade','slots','mines-start','rocket-bet'):
            control=db.execute("SELECT value FROM controls WHERE name='paused'").fetchone()
            if control and control['value']:
                raise ValueError('Приём новых ставок временно приостановлен. Активные игры продолжаются.')
        if action=='withdraw-cancel':
            row=db.execute("SELECT * FROM transfers WHERE id=? AND user_id=? AND kind IN ('withdraw','partner-withdraw') AND status='pending'",(str(b.get('requestId')),uid)).fetchone()
            if not row:
                raise ValueError('Заявка уже обработана или не найдена')
            data=json.loads(row['data'])
            if row['kind']=='withdraw':
                state['inventory'].extend(data['entries'])
            else:
                db.execute('UPDATE partners SET claimed=claimed-? WHERE user_id=?',(cents(data['value']),uid))
            db.execute("UPDATE transfers SET status='cancelled' WHERE id=?",(row['id'],))
            self.operation(db,uid,row['kind'],'Вывод отменён','done',detail='Отменено пользователем',op_id=row['id'])
            return None
        if action=='partner-code':
            code=str(b.get('code','')).strip().lower()
            if not re.fullmatch(r'[a-z][a-z0-9_]{3,23}',code) or code.startswith('u') and code[1:].isdigit():
                raise ValueError('Код: 4–24 латинских символа, цифры или _, первый символ — буква')
            owner=db.execute('SELECT user_id FROM referral_codes WHERE code=?',(code,)).fetchone()
            if owner and owner['user_id']!=uid: raise ValueError('Код занят')
            self.partner(db,uid)
            db.execute('INSERT OR IGNORE INTO referral_codes VALUES(?,?)',(code,uid))
            db.execute('UPDATE partners SET code=? WHERE user_id=?',(code,uid))
            return None
        if action in ('partner-claim','partner-withdraw'):
            amount=self.partner(db,uid)['availableCents']
            if amount<=0: raise ValueError('Нет доступной комиссии')
            if state.get('debt',0)>0 or self.withdraw_hold(db,uid)>now:
                raise ValueError('Вывод ограничен до завершения проверки платежей')
            db.execute('UPDATE partners SET claimed=claimed+? WHERE user_id=?',(amount,uid))
            if action=='partner-claim':
                self.credit(state,amount)
                self.operation(db,uid,'partner','Реферальная комиссия',delta=amount)
            else:
                request_id=ident()
                db.execute('INSERT INTO transfers VALUES(?,?,?,?,?,?)',(request_id,uid,'partner-withdraw','pending',json.dumps(dict(value=amount/100)),now))
                self.operation(db,uid,'partner-withdraw','Вывод комиссии','pending',detail=request_id,op_id=request_id)
                db.execute('INSERT INTO outbox(id,message) VALUES(?,?)',(request_id,f'Вывод комиссии #{request_id}: {uid}, {amount/100} BStars'))
                return dict(requestId=request_id)
            return None
        if action=='case':
            case=self.cases.get(b.get('caseId'))
            if not case:
                raise ValueError('Кейс не найден')
            if case.get('free'):
                previous=db.execute('SELECT claimed FROM claims WHERE user_id=? AND case_id=?',(uid,case['id'])).fetchone()
                if previous and (case['free']!='daily' or now<previous['claimed']+86400):
                    raise ValueError('Кейс пока недоступен')
                if case['free']=='subscribe' and not b.get('_subscribed'):
                    raise ValueError('Подпишись на канал для открытия кейса')
                if case['free']=='referral' and not db.execute('SELECT 1 FROM referrals WHERE invitee=?',(uid,)).fetchone():
                    raise ValueError('Кейс доступен после первого входа по реферальной ссылке')
                if case['free']=='nickname':
                    profile=json.loads(load_user(db,uid)[0]['profile'])
                    name=profile.get('first_name','')+' '+profile.get('last_name','')
                    if not re.search(r'(?<![\w@])@brainrotfreebie(?![\w])',name,re.I):
                        raise ValueError('Добавь @BrainrotFreebie в имя Telegram и заново открой приложение')
                db.execute('INSERT INTO claims VALUES(?,?,?) ON CONFLICT(user_id,case_id) DO UPDATE SET claimed=excluded.claimed',(uid,case['id'],now))
            price=cents(case['price'])
            maximum=max(self.items[d['itemId']]['value'] for d in case['drops'])
            self.limits.check(case['price'],maximum)
            self.check_risk(db,maximum)
            if case.get('free'):
                day=datetime.fromtimestamp(now,timezone.utc).strftime('%Y-%m-%d')
                db.execute('INSERT OR IGNORE INTO bonus_spend VALUES(?,0)',(day,))
                spent=db.execute('SELECT spent FROM bonus_spend WHERE day=?',(day,)).fetchone()['spent']
                if spent+cents(maximum)>cents(self.limits.daily_bonus_budget):
                    raise ValueError('Бюджет бесплатных наград на сегодня исчерпан')
            if state['balance'] < price:
                raise ValueError('Не хватает BStars')
            rng,proof=self.rng(db,uid,'case')
            item_id=roll_case(case,self.items,rng)
            if case.get('free'):
                db.execute('UPDATE bonus_spend SET spent=spent+? WHERE day=?',(cents(self.items[item_id]['value']),day))
            state['balance']-=price
            item_uid=self.add_item(state,item_id)
            state['stats']['opened']+=1
            table=[dict(itemId=d['itemId'],chance=d['chance']) for d in distribution(case,self.items)]
            self.operation(db,uid,'case',f'Кейс · {case["name"]}',delta=-price,detail=f'Получен {self.items[item_id]["name"]}',proof=dict(proof,caseId=case['id'],outcome=item_id,table=table))
            if not case.get('free'):
                self.referral_result(db,uid,item_uid,case['price'],self.items[item_id]['value'])
            self.drop(db,uid,item_id)
            return dict(itemId=item_id,uid=item_uid)
        if action=='sale':
            value,entries=self.stake(state,[b.get('uid')])
            self.credit(state,cents(value))
            self.operation(db,uid,'sale','Продажа предмета',delta=cents(value),detail=self.items[entries[0]['itemId']]['name'])
        elif action=='upgrade':
            target=self.items.get(b.get('targetId'))
            value,entries=self.stake(state,b.get('uids'))
            if not target or target['value']<=value:
                raise ValueError('Цель должна быть дороже ставки')
            self.limits.check(value,target['value'])
            self.check_risk(db,target['value'])
            rng,proof=self.rng(db,uid,'upgrade')
            chance=RTP*value/target['value']
            point=landing(chance,rng)
            won_uid=self.add_item(state,target['id']) if point['win'] else None
            state['stats']['upgrades']+=1
            if point['win']:
                state['stats']['wins']+=1
                self.drop(db,uid,target['id'])
            self.operation(db,uid,'upgrade','Апгрейд','win' if point['win'] else 'lose',detail=f'Ставка {value} · цель {target["name"]} · шанс {chance:.8f}',proof=dict(proof,chance=chance,outcome=point))
            self.referral_result(db,uid,ident(),value,target['value'] if point['win'] else 0)
            return dict(landing=point,wonUid=won_uid)
        elif action=='slots':
            value,_=self.stake(state,[b.get('uid')])
            self.limits.check(value,value*5)
            self.check_risk(db,value*5)
            rng,proof=self.rng(db,uid,'slots')
            result=slots(value,list(self.items),rng)
            self.credit(state,cents(result['payout']))
            self.referral_result(db,uid,ident(),value,result['payout'])
            state['slotResult']=result
            self.operation(db,uid,'slots','Слоты','win' if result['multiplier'] else 'lose',cents(result['payout']),f'Ставка {value} · ×{result["multiplier"]}',proof=dict(proof,rtp=RTP,outcome=result['symbols']))
            return result
        elif action=='mines-start':
            if state['mines'] and state['mines']['status']=='active':
                raise ValueError('Заверши текущую игру')
            bombs=b.get('bombCount')
            if bombs not in (3,5,10):
                raise ValueError('Выбери 3, 5 или 10 мин')
            value,entries=self.stake(state,b.get('uids'))
            maximum_steps=self.limits.mines_steps(value,bombs)
            maximum=cents(value*mines_multiplier(bombs,maximum_steps))/100
            self.limits.check(value,maximum)
            self.check_risk(db,maximum)
            rng,proof=self.rng(db,uid,'mines')
            pool=list(range(25))
            board=[rng.pick(pool) for _ in range(bombs)]
            op=self.operation(db,uid,'mines','Мины','pending',detail=f'Ставка {value} · автозабор после {maximum_steps} безопасных клеток',proof=dict(proof,bombCount=bombs,outcome=board,maxOpened=maximum_steps,riskMax=maximum))
            state['mines']=dict(id=op,rtp=RTP,bombCount=bombs,bombs=board,opened=[],stakeValue=value,stakeCount=len(entries),status='active',payout=0,hit=None,expiresAt=(now+60)*1000,maxOpened=maximum_steps,riskMax=maximum)
        elif action in ('mines-reveal','mines-cash'):
            game=state.get('mines')
            if not game or game['status']!='active':
                raise ValueError('Нет активной игры')
            if action=='mines-cash':
                if not game['opened']:
                    raise ValueError('Открой безопасную клетку')
                self.finish_mines(db,uid,state,True)
            else:
                index=integer(b.get('index'),0,24)
                if index in game['opened']:
                    raise ValueError('Клетка уже открыта')
                if index in game['bombs']:
                    game['hit']=index
                    self.finish_mines(db,uid,state,False)
                else:
                    game['opened'].append(index)
                    if len(game['opened'])==game.get('maxOpened',25-game['bombCount']):
                        self.finish_mines(db,uid,state,True)
        elif action=='rocket-bet':
            round_=self.current_round(db)
            if b.get('roundId')!=round_['id'] or now*1000>=round_['startAt']:
                raise ValueError('Приём ставок завершён')
            if state.get('rocket') and state['rocket']['roundId']==round_['id']:
                raise ValueError('Ставка на этот раунд уже принята')
            auto=b.get('autoCash')
            if auto is not None and (type(auto) not in (int,float) or not math.isfinite(auto) or not 1.01<=auto<=100 or abs(auto*100-round(auto*100))>1e-8):
                raise ValueError('Автозабор: ×1,01–×100, до двух знаков')
            value,entries=self.stake(state,b.get('uids'))
            self.limits.check(value,value*100)
            self.check_risk(db,value*100)
            total=sum(json.loads(r['state'])['rocket']['stakeValue'] for r in db.execute('SELECT state FROM users') if json.loads(r['state']).get('rocket') and json.loads(r['state'])['rocket'].get('roundId')==round_['id'])
            if total+value>round_.get('maxTotalStake',self.limits.rocket_round_stake):
                raise ValueError('Лимит ставок общего раунда достигнут')
            proof=dict(serverHash=round_['serverHash'],clientSeed=round_['id'],nonce=0,game='rocket',rtp=round_.get('rtp',.85),roundId=round_['id'])
            op=self.operation(db,uid,'rocket','Ракетка','pending',detail=f'Ставка {value} · раунд {round_["id"]}',proof=proof)
            state['rocket']=dict(id=op,roundId=round_['id'],startAt=round_['startAt'],endAt=round_['endAt'],crash=round_['crash'],capped=round_['capped'],stakeValue=value,stakeCount=len(entries),autoCash=auto,status='active',payout=0,cashAt=0,automatic=False,riskMax=value*100)
        elif action=='rocket-cash':
            game=state.get('rocket')
            if not game or game['status']!='active' or now*1000<game['startAt']:
                raise ValueError('Забор недоступен')
            value=math.floor(math.exp((now*1000-game['startAt'])/1000*.24)*100)/100
            self.finish_rocket(db,uid,state,value,False)
        elif action=='promo':
            code=str(b.get('code','')).strip().upper()
            promo=db.execute('SELECT * FROM promos WHERE code=?',(code,)).fetchone()
            if not promo or not promo['active'] or promo['uses']>=promo['max_uses']:
                raise ValueError('Промокод недоступен')
            if db.execute('SELECT 1 FROM redemptions WHERE user_id=? AND code=?',(uid,code)).fetchone():
                raise ValueError('Ты уже активировал этот промокод')
            db.execute('INSERT INTO redemptions VALUES(?,?)',(uid,code))
            db.execute('UPDATE promos SET uses=uses+1 WHERE code=?',(code,))
            day=datetime.fromtimestamp(now,timezone.utc).strftime('%Y-%m-%d')
            db.execute('INSERT OR IGNORE INTO bonus_spend VALUES(?,0)',(day,))
            spent=db.execute('SELECT spent FROM bonus_spend WHERE day=?',(day,)).fetchone()['spent']
            if spent+promo['reward']>cents(self.limits.daily_bonus_budget):
                raise ValueError('Бюджет бонусов на сегодня исчерпан')
            db.execute('UPDATE bonus_spend SET spent=spent+? WHERE day=?',(promo['reward'],day))
            self.credit(state,promo['reward'])
            self.operation(db,uid,'promo','Промокод активирован',delta=promo['reward'],detail=code)
        elif action=='fair-rotate':
            if state.get('mines') and state['mines']['status']=='active':
                raise ValueError('Заверши мины перед раскрытием seed')
            row,_=load_user(db,uid)
            client=str(b.get('clientSeed','')).strip()
            if not 1<=len(client)<=80 or ':' in client:
                raise ValueError('Client seed: 1–80 символов без двоеточия')
            db.execute('INSERT INTO seeds VALUES(?,?,?,?)',(commitment(row['seed']),row['seed'],uid,now))
            db.execute('UPDATE users SET seed=?,client=?,nonce=0 WHERE id=?',(new_seed(),client,uid))
            return dict(serverSeed=row['seed'],serverHash=commitment(row['seed']))
        elif action in ('deposit','withdraw'):
            if db.execute("SELECT count(*) FROM transfers WHERE user_id=? AND status='pending'",(uid,)).fetchone()[0]>=5:
                raise ValueError('Не более пяти незавершённых заявок')
            if action=='deposit':
                item=self.items.get(b.get('itemId'))
                if not item or item['value']<self.items['garama']['value'] or item['id']=='eviledon':
                    raise ValueError('Депозит от Garama, Eviledon не принимается')
                data=dict(itemId=item['id'],value=item['value'])
            else:
                if not self.withdrawal_open(now):
                    raise ValueError('Вывод доступен в субботу с 16:00 до 17:00 МСК')
                if self.withdraw_hold(db,uid)>now:
                    raise ValueError('Вывод временно ограничен после оплаты Stars. Срок указан в профиле.')
                value,entries=self.stake(state,b.get('uids'))
                if any(e['itemId'] not in ('ketupat','garama','cerberus','dragon') for e in entries):
                    raise ValueError('Вывод: Ketupat Kepat, Garama, Cerberus или Dragon Cannelloni')
                if value>self.limits.withdraw_request_max:
                    raise ValueError('Превышен лимит одной заявки на вывод')
                today=datetime.fromtimestamp(now,timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
                allocated=sum(json.loads(r['data']).get('value',sum(self.items[e['itemId']]['value'] for e in json.loads(r['data']).get('entries',[]))) for r in db.execute("SELECT data FROM transfers WHERE user_id=? AND kind='withdraw' AND status IN ('pending','approved') AND created>=?",(uid,today)))
                if allocated+value>self.limits.withdraw_user_daily:
                    raise ValueError('Суточный лимит вывода достигнут')
                data=dict(entries=entries,value=value)
            request_id=ident()
            db.execute('INSERT INTO transfers VALUES(?,?,?,?,?,?)',(request_id,uid,action,'pending',json.dumps(data),now))
            self.operation(db,uid,action,'Заявка на депозит' if action=='deposit' else 'Заявка на вывод','pending',detail=f'Заявка {request_id}',op_id=request_id)
            db.execute('INSERT INTO outbox(id,message) VALUES(?,?)',(request_id,f'{action} #{request_id}\nTelegram ID: {uid}\n{json.dumps(data,ensure_ascii=False)}'))
            return dict(requestId=request_id)
        elif action.startswith('admin-'):
            if uid not in self.admins:
                raise PermissionError('Доступ администратора запрещён')
            self.audit(db,uid,action,b)
            if action=='admin-pause':
                if type(b.get('paused')) is not bool:
                    raise ValueError('Invalid pause state')
                db.execute("INSERT INTO controls VALUES('paused',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(int(b['paused']),))
            elif action=='admin-balance':
                target=integer(b.get('userId'),1,2**53-1)
                amount=cents(integer(b.get('amount')))
                if b.get('direction') not in ('add','remove'):
                    raise ValueError('Неверное направление')
                delta=amount if b['direction']=='add' else -amount
                target_state=state if target==uid else load_user(db,target)[1]
                if target_state['balance']+delta<0:
                    raise ValueError('Списание превышает баланс')
                if delta>0:
                    self.credit(target_state,delta)
                else:
                    target_state['balance']+=delta
                if target!=uid:
                    save_user(db,target,target_state)
                self.operation(db,target,'admin','Изменение баланса',delta=delta,detail=f'Администратор {uid} · {str(b.get("reason",""))[:120]}')
            elif action=='admin-promo':
                code=str(b.get('code','')).strip().upper()
                if not re.fullmatch(r'[A-Z0-9_-]{3,30}',code):
                    raise ValueError('Код: 3–30 букв, цифр, _ или дефисов')
                reward,limit=integer(b.get('reward')),integer(b.get('limit'))
                if db.execute('SELECT 1 FROM promos WHERE code=?',(code,)).fetchone():
                    raise ValueError('Код уже существует')
                db.execute('INSERT INTO promos(code,reward,max_uses) VALUES(?,?,?)',(code,cents(reward),limit))
            elif action=='admin-promo-toggle':
                db.execute('UPDATE promos SET active=1-active WHERE code=?',(str(b.get('code')),))
            elif action=='admin-transfer':
                transfer=db.execute('SELECT * FROM transfers WHERE id=?',(str(b.get('requestId')),)).fetchone()
                if not transfer or transfer['status']!='pending' or b.get('decision') not in ('approve','reject'):
                    raise ValueError('Заявка уже обработана или не найдена')
                target=transfer['user_id']
                target_state=state if target==uid else load_user(db,target)[1]
                data=json.loads(transfer['data'])
                approve=b['decision']=='approve'
                if transfer['kind']=='withdraw' and approve and not self.withdrawal_open(now):
                    raise ValueError('Выдача предметов только в субботу с 16:00 до 17:00 МСК')
                if transfer['kind']=='partner-withdraw':
                    if approve and (target_state.get('debt',0)>0 or self.withdraw_hold(db,target)>now):
                        raise ValueError('Вывод комиссии заблокирован проверкой платежей')
                    if not approve:
                        db.execute('UPDATE partners SET claimed=claimed-? WHERE user_id=?',(cents(data['value']),target))
                if transfer['kind']=='withdraw' and approve and (target_state.get('debt',0)>0 or self.withdraw_hold(db,target)>now):
                    raise ValueError('Вывод заблокирован: возврат Stars или срок удержания')
                delta=cents(data['value']) if transfer['kind']=='deposit' and approve else 0
                self.credit(target_state,delta)
                if transfer['kind']=='withdraw' and not approve:
                    target_state['inventory'].extend(data['entries'])
                if target!=uid:
                    save_user(db,target,target_state)
                db.execute('UPDATE transfers SET status=? WHERE id=?',('approved' if approve else 'rejected',transfer['id']))
                self.operation(db,target,transfer['kind'],'Депозит' if transfer['kind']=='deposit' else 'Вывод','done' if approve else 'lose',delta,f'{"Подтверждено" if approve else "Отклонено"} администратором {uid}',op_id=transfer['id'])
            else:
                raise ValueError('Операция не найдена')
        else:
            raise ValueError('Операция не найдена')
        return None
