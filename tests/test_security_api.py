import base64
import hashlib
import hmac
import importlib
import json
import re
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import AsyncMock,patch
import httpx
from starlette.staticfiles import StaticFiles
from tests import test_v150 as fixtures
from backend.service import ident

class SecurityApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.Release150Tests.setUp(self)
        self.api=importlib.import_module('backend.app')
        self.api_patch=patch.multiple(self.api,service=self.s,BOT_TOKEN='test-token',WEBHOOK_SECRET='test-secret',PUBLIC_URL='https://example.org',PAYMENTS=True)
        self.api_patch.start()
        self.api.rate_windows.clear()
        self.api.app.middleware_stack=None
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.api.app),base_url='https://test.local')
        self.token=self.s.login(dict(id=200,first_name='Player'))
        self.headers={'Authorization':'Bearer '+self.token}
        self.hook={'X-Telegram-Bot-Api-Secret-Token':'test-secret'}

    async def asyncTearDown(self):
        await self.client.aclose()

    def tearDown(self):
        self.api_patch.stop()
        fixtures.Release150Tests.tearDown(self)

    def signed(self,uid=200):
        fields=dict(auth_date=str(int(time.time())),user=json.dumps(dict(id=uid,first_name='Player')))
        secret=hmac.new(b'WebAppData',b'test-token',hashlib.sha256).digest()
        fields['hash']=hmac.new(secret,'\n'.join(f'{key}={value}' for key,value in sorted(fields.items())).encode(),hashlib.sha256).hexdigest()
        return urlencode(fields)

    async def mutate(self,action,body,key=None):
        return await self.client.post('/api/action/'+action,json=body,headers=dict(self.headers,**{'Idempotency-Key':key or ident()}))

    async def test_anonymous_and_forged_auth_are_rejected(self):
        self.assertEqual((await self.client.get('/api/state')).status_code,401)
        self.assertEqual((await self.client.get('/api/catalog')).status_code,401)
        self.assertEqual((await self.client.post('/api/auth',json=dict(initData=self.signed()+'x'))).status_code,400)
        self.assertEqual((await self.client.post('/api/auth',json=dict(initData=self.signed()))).status_code,200)

    async def test_invalid_json_and_deep_body_are_400_not_500(self):
        for content in [b'{',b'{"x":'+b'['*1500+b'0'+b']'*1500+b'}']:
            result=await self.client.post('/api/auth',content=content,headers={'Content-Type':'application/json'})
            self.assertEqual(result.status_code,400)

    async def test_headers_inline_hash_and_catalog_contract(self):
        response=await self.client.get('/')
        headers=response.headers
        self.assertEqual(response.status_code,200)
        self.assertIn('content-security-policy',headers)
        for content in re.findall(r'<script>(.*?)</script>',response.text,re.S):
            value=base64.b64encode(hashlib.sha256(content.encode()).digest()).decode()
            self.assertIn("'sha256-"+value+"'",headers['content-security-policy'])
        self.assertEqual(headers['x-content-type-options'],'nosniff')
        catalog=await self.client.get('/api/catalog',headers=self.headers)
        self.assertEqual(catalog.status_code,200)
        self.assertIn('items',catalog.json())
        self.assertEqual(catalog.headers['cache-control'],'no-store')

    async def test_case_retry_and_client_balance_forgery(self):
        key=ident();body=dict(caseId='plant',balance=99999999,itemId='dragon')
        before=self.s.state(200)['balance']
        first=await self.mutate('case',body,key);second=await self.mutate('case',body,key)
        self.assertEqual(first.status_code,200);self.assertEqual(second.status_code,200)
        self.assertEqual(first.json()['result'],second.json()['result'])
        self.assertEqual(second.json()['state']['balance'],before-self.s.cases['plant']['price'])
        self.assertEqual(len(second.json()['state']['inventory']),1)
        denied=await self.mutate('admin-balance',dict(userId=200,amount=100,direction='add'))
        self.assertEqual(denied.status_code,403)

    async def test_poll_limit_is_429_and_forged_forwarded_ip_does_not_reset_it(self):
        for _ in range(12):
            result=await self.client.get('/api/state',headers=self.headers)
            self.assertEqual(result.status_code,200)
        result=await self.client.get('/api/state',headers=dict(self.headers,**{'X-Forwarded-For':'8.8.8.8'}))
        self.assertEqual(result.status_code,429)
        self.assertIn('retry-after',result.headers)

    async def test_paid_stars_are_credited_once_and_invoice_link_is_reused(self):
        mocked=AsyncMock(return_value='https://t.me/invoice-test')
        headers=dict(self.headers,**{'Idempotency-Key':ident()})
        with patch.object(self.api,'telegram',mocked):
            first=await self.client.post('/api/invoice',json=dict(stars=40,termsAccepted=True),headers=headers)
            second=await self.client.post('/api/invoice',json=dict(stars=40,termsAccepted=True),headers=headers)
        self.assertEqual(first.status_code,200);self.assertEqual(first.json(),second.json())
        self.assertEqual(mocked.await_count,1)
        with self.s.store.read() as db:
            invoice=db.execute('SELECT * FROM invoices WHERE user_id=200').fetchone()
        before=self.s.state(200)['balance']
        update=dict(update_id=321,message={'from':dict(id=200), 'successful_payment':dict(invoice_payload=invoice['id'],currency='XTR',total_amount=40,telegram_payment_charge_id='charge-security-321')})
        self.assertEqual((await self.client.post('/webhook',json=update)).status_code,403)
        for _ in range(2):
            self.assertEqual((await self.client.post('/webhook',json=update,headers=self.hook)).status_code,200)
        self.assertEqual(self.s.state(200)['balance'],before+(40*150+invoice['bonus'])/100)
        self.assertEqual(self.s.state(200)['bonuses']['depositCases'],0)

    async def test_freeze_blocks_api_and_old_invoice_precheckout(self):
        with patch.object(self.api,'telegram',AsyncMock(return_value='https://t.me/invoice-test')):
            invoice=await self.client.post('/api/invoice',json=dict(stars=100,termsAccepted=True),headers=dict(self.headers,**{'Idempotency-Key':ident()}))
        self.assertEqual(invoice.status_code,200)
        with self.s.store.read() as db:invoice_id=db.execute('SELECT id FROM invoices WHERE user_id=200').fetchone()[0]
        self.s.mutate(100,'admin-freeze',dict(userId=200,balanceFrozen=True,withdrawalFrozen=True),ident())
        self.assertEqual((await self.mutate('case',dict(caseId='plant'))).status_code,400)
        self.assertEqual((await self.client.post('/api/invoice',json=dict(stars=100,termsAccepted=True),headers=dict(self.headers,**{'Idempotency-Key':ident()}))).status_code,400)
        mocked=AsyncMock(return_value=True)
        with patch.object(self.api,'telegram',mocked):
            response=await self.client.post('/webhook',headers=self.hook,json=dict(update_id=333,pre_checkout_query={'id':'checkout-333','from':dict(id=200), 'invoice_payload':invoice_id,'currency':'XTR','total_amount':100}))
        self.assertEqual(response.status_code,200)
        self.assertFalse(mocked.call_args.args[1]['ok'])


    async def test_broadcast_webhook_requires_admin_and_confirmation(self):
        def message(update_id,uid,text):
            return dict(update_id=update_id,message={'from':dict(id=uid),'chat':dict(id=uid,type='private'),'text':text})
        await self.client.post('/webhook',headers=self.hook,json=message(410,200,'/broadcast nope'))
        with self.s.store.read() as db:self.assertEqual(db.execute('SELECT count(*) FROM broadcasts').fetchone()[0],0)
        await self.client.post('/webhook',headers=self.hook,json=message(411,100,'/broadcast обновление приложения'))
        with self.s.store.read() as db:job=dict(db.execute('SELECT * FROM broadcasts').fetchone())
        self.assertEqual(job['status'],'draft')
        mocked=AsyncMock(return_value=True)
        with patch.object(self.api,'telegram',mocked):
            for update_id,uid in [(412,200),(413,100),(413,100)]:
                callback=dict(update_id=update_id,callback_query={'id':str(update_id),'from':dict(id=uid),'message':dict(chat=dict(id=uid,type='private')),'data':'bc:send:'+job['id']})
                self.assertEqual((await self.client.post('/webhook',headers=self.hook,json=callback)).status_code,200)
        with self.s.store.read() as db:self.assertEqual(db.execute('SELECT status FROM broadcasts WHERE id=?',(job['id'],)).fetchone()[0],'queued')
        self.assertTrue(all(call.args[0]=='answerCallbackQuery' for call in mocked.call_args_list))
