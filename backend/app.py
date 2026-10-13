import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .auth import validate_init_data
from .service import Service, ident, integer
from .store import load_user, save_user
from .risk import Limits

ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT/'web' if (ROOT/'web').exists() else ROOT
log = logging.getLogger('freebie')
BOT_TOKEN = os.getenv('BOT_TOKEN','')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET','')
PUBLIC_URL = os.getenv('PUBLIC_URL','').rstrip('/')
OWNER_ID = int(os.getenv('OWNER_ID','7613236278'))
OWNER_USERNAME = os.getenv('OWNER_USERNAME','DarkMonstep').lstrip('@')
BOT_USERNAME=os.getenv('BOT_USERNAME','').lstrip('@')
CHANNEL = int(os.getenv('SUBSCRIPTION_CHANNEL','-1003739017107'))
TERMS_URL = os.getenv('TERMS_URL','')
PRIVACY_URL = os.getenv('PRIVACY_URL','')
PAYMENTS = os.getenv('PAYMENTS_ENABLED','false').lower()=='true' and bool(TERMS_URL.startswith('https://') and PRIVACY_URL.startswith('https://') and BOT_TOKEN and WEBHOOK_SECRET)
service = Service(os.getenv('DATABASE_PATH',str(ROOT/'data/freebie.sqlite3')), admins=[int(x) for x in os.getenv('ADMIN_IDS','7613236278,1821268346').split(',')], starting_balance=float(os.getenv('STARTING_BALANCE','0')),limits=Limits.load(ROOT/'limits.json'))


async def telegram(method, data):
    if not BOT_TOKEN:
        raise HTTPException(503,'Токен бота ещё не настроен')
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.post(f'https://api.telegram.org/bot{BOT_TOKEN}/{method}',json=data)
            result = response.json()
        if not result.get('ok'):
            raise HTTPException(502,'Telegram временно отклонил запрос')
        return result['result']
    except (httpx.HTTPError,ValueError):
        # Never log request URLs: they contain the bot token.
        raise HTTPException(502,'Telegram недоступен. Попробуй позже.')


async def scheduler():
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception:
            log.error('Scheduler failed; will retry',exc_info=True)
        await asyncio.sleep(.2)


async def notify_outbox():
    while True:
        if BOT_TOKEN:
            with service.store.tx() as db:
                message=db.execute('SELECT * FROM outbox WHERE sent=0 AND attempts<10 AND retry_at<=? ORDER BY rowid LIMIT 1',(time.time(),)).fetchone()
            if message:
                try:
                    await telegram(message['method'] or 'sendMessage',json.loads(message['payload']) if message['payload'] else dict(chat_id=OWNER_ID,text=message['message']))
                    with service.store.tx() as db:
                        db.execute('UPDATE outbox SET sent=1 WHERE id=?',(message['id'],))
                except HTTPException:
                    with service.store.tx() as db:
                        db.execute('UPDATE outbox SET attempts=attempts+1,retry_at=? WHERE id=?',(time.time()+30,message['id']))
        await asyncio.sleep(1)


def tick():
    with service.store.tx() as db:
        service.tick(db)


async def backups():
    while True:
        try:
            await asyncio.to_thread(service.store.backup,Path(service.store.path).parent/'backups')
        except Exception:
            log.error('Backup failed',exc_info=True)
        await asyncio.sleep(86400)


async def configure_telegram():
    global BOT_USERNAME
    if os.getenv('AUTO_SETUP_TELEGRAM','false').lower()!='true' or not BOT_TOKEN:
        return
    if not PUBLIC_URL.startswith('https://') or not WEBHOOK_SECRET:
        raise RuntimeError('PUBLIC_URL and webhook secret are required for automatic setup')
    while True:
        try:
            BOT_USERNAME=(await telegram('getMe',{}))['username']
            await telegram('setWebhook',dict(url=PUBLIC_URL+'/webhook',secret_token=WEBHOOK_SECRET,allowed_updates=['message','pre_checkout_query'],drop_pending_updates=False))
            await telegram('setChatMenuButton',dict(menu_button=dict(type='web_app',text='Открыть Freebie',web_app=dict(url=PUBLIC_URL))))
            log.info('Telegram webhook and menu configured')
            return
        except HTTPException:
            log.error('Telegram setup failed: check BOT_TOKEN and PUBLIC_URL; retrying in 30s')
            await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app):
    setup_task=asyncio.create_task(configure_telegram())
    task=asyncio.create_task(scheduler())
    notifications=asyncio.create_task(notify_outbox())
    backup_task=asyncio.create_task(backups())
    yield
    task.cancel()
    notifications.cancel()
    backup_task.cancel()
    setup_task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    try:
        await backup_task
    except asyncio.CancelledError:
        pass
    try:
        await setup_task
    except asyncio.CancelledError:
        pass
    try:
        await notifications
    except asyncio.CancelledError:
        pass


app=FastAPI(title='Brainrot Freebie API',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)


@app.exception_handler(ValueError)
async def invalid(request, error):
    return JSONResponse(dict(detail=str(error)),status_code=400)


@app.exception_handler(PermissionError)
async def forbidden(request, error):
    return JSONResponse(dict(detail=str(error)),status_code=403)


@app.middleware('http')
async def limits(request: Request, call_next):
    try:
        length=int(request.headers.get('content-length','0') or 0)
    except ValueError:
        return JSONResponse(dict(detail='Invalid content length'),status_code=400)
    if length>32768 or request.method=='POST' and len(await request.body())>32768:
        return JSONResponse(dict(detail='Запрос слишком большой'),status_code=413)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    if request.url.path.startswith('/api/') or request.url.path=='/runtime-config':
        response.headers['Cache-Control']='no-store'
    return response


def user_id(authorization):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401,'Открой приложение в Telegram')
    try:
        uid=service.authenticate(authorization[7:])
        if uid not in service.admins and service.maintenance():
            raise HTTPException(503,dict(code='maintenance',message='Бот на обновлении. Скоро вернёмся.'))
        return uid
    except PermissionError as error:
        raise HTTPException(401,str(error))


rate_windows=defaultdict(deque)
def rate_limit(key, maximum, seconds):
    now=time.monotonic()
    if len(rate_windows)>10000:
        rate_windows.clear()
    window=rate_windows[key]
    while window and window[0]<now-seconds:
        window.popleft()
    if len(window)>=maximum:
        raise HTTPException(429,'Слишком много запросов. Подожди немного.')
    window.append(now)


async def object_body(request):
    body=await request.json()
    if not isinstance(body,dict):
        raise ValueError('Ожидается объект')
    return body


@app.get('/health')
def health():
    return dict(ok=True)


@app.get('/runtime-config')
def runtime_config():
    return dict(mode='server',version='1.5.0',depositIds=service.deposit_ids,newsUrl='https://t.me/brainrotFreebie',botUsername=BOT_USERNAME,rtp=.80,ownerUrl=f'https://t.me/{OWNER_USERNAME}',paymentsEnabled=PAYMENTS,termsUrl=TERMS_URL,privacyUrl=PRIVACY_URL,starsRate=1.5,starsHoldHours=service.limits.stars_hold_hours)


@app.get('/api/admin/backup')
async def download_backup(authorization: str=Header(default='')):
    uid=user_id(authorization)
    if uid not in service.admins:
        raise HTTPException(403,'Доступ запрещён')
    path=await asyncio.to_thread(service.store.backup,Path(service.store.path).parent/'backups')
    return FileResponse(path,filename=path.name,media_type='application/octet-stream')


@app.post('/api/admin/refund/{invoice_id}')
async def refund_invoice(invoice_id: str,authorization: str=Header(default='')):
    uid=user_id(authorization)
    if uid not in service.admins:
        raise HTTPException(403,'Доступ запрещён')
    with service.store.tx() as db:
        row=db.execute('SELECT * FROM invoices WHERE id=?',(invoice_id,)).fetchone()
        if not row or row['status']!='paid' or not row['charge']:
            raise ValueError('Возврат уже выполнен, ожидает подтверждения или недоступен')
        db.execute("UPDATE invoices SET status='refund_requested' WHERE id=?",(invoice_id,))
        db.execute("INSERT INTO refund_jobs VALUES(?,'pending',?,?) ON CONFLICT(invoice_id) DO UPDATE SET status='pending'",(invoice_id,uid,time.time()))
        service.audit(db,uid,'request-refund',dict(invoiceId=invoice_id))
    try:
        result=await telegram('refundStarPayment',dict(user_id=row['user_id'],telegram_payment_charge_id=row['charge']))
        if result is not True:
            raise HTTPException(502,'Возврат не подтверждён')
    except HTTPException:
        # Ambiguous timeout: never fabricate success or restore funds blindly.
        # RefundedPayment webhook can still confirm it after a lost API response.
        with service.store.tx() as db:
            db.execute("UPDATE refund_jobs SET status='review' WHERE invoice_id=? AND status!='done'",(invoice_id,))
        raise HTTPException(502,'Результат возврата неизвестен. Проверь журнал Stars; уведомление Telegram подтвердит возврат автоматически.')
    with service.store.tx() as db:
        latest=db.execute('SELECT * FROM invoices WHERE id=?',(invoice_id,)).fetchone()
        service.apply_refund(db,latest,row['charge'])
    return service.state(row['user_id']) if row['user_id']==uid else service.state(uid)


@app.post('/api/auth')
async def auth(request: Request):
    rate_limit(('auth',request.client.host),30,60)
    body=await object_body(request)
    user=validate_init_data(str(body.get('initData','')),BOT_TOKEN)
    if user['id'] not in service.admins and service.maintenance():
        raise HTTPException(503,dict(code='maintenance',message='Бот на обновлении. Скоро вернёмся.'))
    return dict(token=service.login(user,dict(parse_qsl(str(body.get('initData','')))).get('start_param','')))


@app.get('/api/state')
def state(authorization: str=Header(default=''),limit: int=200):
    return service.state(user_id(authorization),max(20,min(limit,5000)))


@app.get('/api/catalog')
def catalog(authorization: str=Header(default='')):
    user_id(authorization)
    return dict(items=list(service.items.values()),cases=list(service.cases.values()))


@app.get('/api/history')
def full_history(authorization: str=Header(default=''),offset: int=0,limit: int=200):
    uid=user_id(authorization)
    with service.store.tx() as db:
        rows=db.execute('SELECT * FROM operations WHERE user_id=? ORDER BY created DESC,rowid DESC LIMIT ? OFFSET ?',(uid,max(20,min(limit,200)),max(0,offset))).fetchall()
    from datetime import datetime,timezone
    result=[dict(id=h['id'],type=h['type'],status=h['status'],delta=h['delta']/100,title=h['title'],detail=h['detail'],createdAt=datetime.fromtimestamp(h['created'],timezone.utc).isoformat(),proof=json.loads(h['proof']) if h['proof'] else None) for h in rows]
    for operation in result:
        if operation['type']=='mines' and operation['status']=='pending' and operation['proof']:
            operation['proof'].pop('outcome',None)
    return result


@app.post('/api/action/{action}')
async def action(action: str, request: Request, authorization: str=Header(default=''),idempotency_key: str=Header(default='')):
    uid=user_id(authorization)
    rate_limit(('action',uid),20,10)
    body=await object_body(request)
    if not isinstance(body,dict):
        raise ValueError('Ожидается объект')
    body.pop('_subscribed',None)
    if action=='case' and body.get('caseId')=='subscribe':
        member=await telegram('getChatMember',dict(chat_id=CHANNEL,user_id=uid))
        body['_subscribed']=member.get('status') in ('creator','administrator','member') or member.get('status')=='restricted' and member.get('is_member') is True
    return await asyncio.to_thread(service.mutate,uid,action,body,idempotency_key)


@app.get('/api/fair/reveal/{seed_hash}')
def reveal(seed_hash: str, authorization: str=Header(default='')):
    uid=user_id(authorization)
    with service.store.tx() as db:
        row=db.execute('SELECT seed FROM seeds WHERE hash=? AND user_id=?',(seed_hash,uid)).fetchone()
    if not row:
        raise HTTPException(404,'Seed ещё не раскрыт')
    return dict(serverSeed=row['seed'],serverHash=seed_hash)


@app.get('/api/round/{round_id}')
def round_proof(round_id: str,authorization: str=Header(default='')):
    user_id(authorization)
    with service.store.tx() as db:
        row=db.execute('SELECT data FROM rounds WHERE id=?',(round_id,)).fetchone()
    if not row:
        raise HTTPException(404,'Раунд не найден')
    game=json.loads(row['data'])
    if service.clock()*1000<game['endAt']:
        return dict(id=game['id'],serverHash=game['serverHash'],clientSeed=game['id'],nonce=0)
    return dict(id=game['id'],serverHash=game['serverHash'],serverSeed=game['seed'],clientSeed=game['id'],nonce=0,crash=game['crash'])


@app.post('/api/invoice')
async def invoice(request: Request,authorization: str=Header(default=''),idempotency_key: str=Header(default='')):
    uid=user_id(authorization)
    rate_limit(('invoice',uid),10,60)
    if not PAYMENTS:
        raise HTTPException(503,'Оплата звёздами ещё не включена')
    body=await object_body(request)
    amount=integer(body.get('stars'),1,10000)
    if body.get('termsAccepted') is not True:
        raise ValueError('Подтверди условия покупки')
    if len(idempotency_key)<16 or len(idempotency_key)>100:
        raise ValueError('Требуется Idempotency-Key')
    invoice_id=hashlib.sha256(f'{uid}:{idempotency_key}'.encode()).hexdigest()
    with service.store.tx() as db:
        prior=db.execute('SELECT * FROM invoices WHERE id=?',(invoice_id,)).fetchone()
        if prior and (prior['stars']!=amount or prior['status']!='pending'):
            raise ValueError('Счёт уже использован')
        if not prior:
            service.bind_referral(db,uid,body.get('referralCode'))
        bonus=prior['bonus'] if prior else service.topup_bonus(db,uid,amount*150)
        db.execute('INSERT OR IGNORE INTO invoices(id,user_id,stars,status,charge,created,bonus) VALUES(?,?,?,?,?,?,?)',(invoice_id,uid,amount,'pending',None,time.time(),bonus))
    link=await telegram('createInvoiceLink',dict(title='BStars',description=f'{amount} Stars → {(amount*150+bonus)/100:g} BStars',payload=invoice_id,provider_token='',currency='XTR',prices=[dict(label='BStars',amount=amount)]))
    return dict(url=link)


@app.post('/webhook')
async def webhook(request: Request,x_telegram_bot_api_secret_token: str=Header(default='')):
    if not WEBHOOK_SECRET or not hmac.compare_digest(WEBHOOK_SECRET,x_telegram_bot_api_secret_token):
        raise HTTPException(403,'Invalid webhook secret')
    update=await object_body(request)
    update_id=integer(update.get('update_id'),0,2**53-1)
    query=update.get('pre_checkout_query')
    if query:
        with service.store.tx() as db:
            row=db.execute('SELECT * FROM invoices WHERE id=?',(query.get('invoice_payload'),)).fetchone()
            ok=bool(PAYMENTS and (query.get('from',{}).get('id') in service.admins or not (db.execute("SELECT value FROM controls WHERE name='maintenance'").fetchone() or {'value':0})['value']) and row and (row['status']=='pending' or row['status']=='processing' and row['checkout']==query.get('id')) and row['user_id']==query.get('from',{}).get('id') and query.get('currency')=='XTR' and row['stars']==query.get('total_amount'))
            if ok and row['status']=='pending':
                db.execute('UPDATE invoices SET status=?,checkout=? WHERE id=?',('processing',query['id'],row['id']))
        await telegram('answerPreCheckoutQuery',dict(pre_checkout_query_id=query['id'],ok=ok,**({} if ok else dict(error_message='Счёт недоступен. Создай новый.'))))
        return dict(ok=True)
    message=update.get('message',{})
    payment=message.get('successful_payment')
    with service.store.tx() as db:
        if db.execute('SELECT 1 FROM updates WHERE id=?',(update_id,)).fetchone():
            return dict(ok=True)
        if payment:
            row=db.execute('SELECT * FROM invoices WHERE id=?',(payment.get('invoice_payload'),)).fetchone()
            uid=message.get('from',{}).get('id')
            if not row or row['user_id']!=uid or payment.get('currency')!='XTR' or row['stars']!=payment.get('total_amount'):
                raise HTTPException(400,'Payment mismatch')
            charge=payment.get('telegram_payment_charge_id')
            if not isinstance(charge,str) or not charge:
                raise HTTPException(400,'Missing payment charge')
            if row['status'] in ('pending','processing'):
                if db.execute('SELECT 1 FROM invoices WHERE charge=?',(charge,)).fetchone():
                    raise HTTPException(400,'Payment charge already used')
                _,account=load_user(db,uid)
                delta=row['stars']*150+row['bonus']
                service.credit(account,delta)
                save_user(db,uid,account)
                service.operation(db,uid,'topup','Пополнение звёздами',delta=delta,detail=f'{row["stars"]} Stars · бонус +{row["bonus"]/100:g} BStars')
                db.execute('UPDATE invoices SET status=?,charge=?,held_until=? WHERE id=?',('paid',charge,time.time()+service.limits.stars_hold_hours*3600,row['id']))
        refunded=message.get('refunded_payment')
        if refunded:
            row=db.execute('SELECT * FROM invoices WHERE id=?',(refunded.get('invoice_payload'),)).fetchone()
            charge=refunded.get('telegram_payment_charge_id')
            if not row or refunded.get('currency')!='XTR' or refunded.get('total_amount')!=row['stars'] or not isinstance(charge,str) or not charge or row['charge'] and row['charge']!=charge:
                raise HTTPException(400,'Refund mismatch')
            service.apply_refund(db,row,charge)
        db.execute('INSERT INTO updates VALUES(?,?)',(update_id,time.time()))
    text=message.get('text','').split()[0] if message.get('text') else ''
    chat=message.get('chat',{}).get('id')
    if chat and message.get('chat',{}).get('type')=='private' and message.get('from',{}).get('id') not in service.admins and service.maintenance() and not payment:
        try:
            await telegram('sendMessage',dict(chat_id=chat,text='Бот на обновлении. Скоро вернёмся.'))
        except HTTPException:
            log.warning('Maintenance notice delivery failed')
        return dict(ok=True)
    if text in ('/start','/support','/paysupport','/terms') and chat:
        if text=='/start':
            parts=message.get('text','').split(maxsplit=1)
            if message.get('chat',{}).get('type')=='private' and len(parts)==2 and message.get('from',{}).get('id')==chat:
                service.login(message['from'],parts[1].strip())
            welcome=('<tg-emoji emoji-id="5298585940577525950">🤩</tg-emoji> '
                     '<b>Добро пожаловать в Brainrot Freebie!</b>\n\n'
                     'Кейсы с брейнротами, ежедневные бонусы и бесплатный кейс за подписку.\n'
                     '<b>Provably True</b>')
            buttons=[]
            if PUBLIC_URL.startswith('https://'):
                buttons.append([dict(text='Играть',web_app=dict(url=PUBLIC_URL))])
            buttons.append([dict(text='Новости',url='https://t.me/brainrotFreebie'),dict(text='Поддержка',url=f'https://t.me/{OWNER_USERNAME}')])
            reply=dict(chat_id=chat,text=welcome,parse_mode='HTML',reply_markup=dict(inline_keyboard=buttons))
        else:
            reply=dict(chat_id=chat,text='Поддержка Brainrot Freebie\nОпиши проблему и приложи номер операции из истории. Не отправляй пароль или код входа Telegram.',reply_markup=dict(inline_keyboard=[[dict(text='Написать в поддержку',url=f'https://t.me/{OWNER_USERNAME}')]]))
        try:
            await telegram('sendMessage',reply)
        except HTTPException:
            with service.store.tx() as db:
                db.execute('INSERT INTO outbox(id,message) VALUES(?,?)',(ident(),f'Не удалось ответить пользователю {chat} на {text}'))
    return dict(ok=True)


@app.get('/')
def index():
    return HTMLResponse((WEB_ROOT/'index.html').read_text(encoding='utf-8').replace('<span id="balance">500</span>','<span id="balance">0</span>'))


# Explicit allowlist: never serve .env, databases, backend source or archives.
def file_handler(filename):
    def handler():
        return FileResponse(WEB_ROOT/filename,headers={'Cache-Control':'no-cache'})
    return handler


for filename in ('app.js','engine.js','audio.js','feature-views.js','config.js','server-client.js','styles.css'):
    app.add_api_route('/'+filename,file_handler(filename),methods=['GET'],include_in_schema=False)
app.mount('/img',StaticFiles(directory=WEB_ROOT/'img'),name='img')
