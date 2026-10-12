import hashlib
import hmac
import importlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import AsyncMock,patch
from fastapi.testclient import TestClient
from backend.service import Service

class ApiUpdateTests(unittest.TestCase):
    def setUp(self):
        self.api=importlib.import_module('backend.app')
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'data')
        self.patch=patch.multiple(self.api,service=Service(Path(self.tmp.name)/'test.sqlite'),BOT_TOKEN='test-token',WEBHOOK_SECRET='test-secret',PUBLIC_URL='https://example.org',PAYMENTS=False)
        self.patch.start();self.api.rate_windows.clear()
        self.client=TestClient(self.api.app)

    def tearDown(self):self.client.close();self.patch.stop();self.tmp.cleanup()

    def auth(self,uid,start=''):
        data=dict(auth_date=str(int(time.time())),user=json.dumps(dict(id=uid,first_name='Test')),start_param=start)
        secret=hmac.new(b'WebAppData',b'test-token',hashlib.sha256).digest()
        data['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
        return self.client.post('/api/auth',json=dict(initData=urlencode(data)))

    def test_signed_referral_and_blocked_anonymous(self):
        self.assertEqual(self.auth(100).status_code,200)
        self.assertEqual(self.auth(200,'ref_u100').status_code,200)
        self.assertEqual(self.api.service.state(100)['partner']['count'],1)
        self.assertEqual(self.client.post('/api/action/partner-claim',json={}).status_code,401)
        self.assertEqual(self.client.get('/api/state').status_code,401)
        self.assertEqual(self.client.get('/runtime-config').json()['rtp'],.8)

    def test_start_referral_and_support_mock_telegram(self):
        self.api.service.login(dict(id=100,first_name='Owner'))
        mocked=AsyncMock(return_value=dict(message_id=1))
        headers={'X-Telegram-Bot-Api-Secret-Token':'test-secret'}
        message=dict(chat=dict(id=200,type='private'),**{'from':dict(id=200,first_name='New')},text='/start ref_u100')
        with patch.object(self.api,'telegram',mocked):
            for _ in range(2):self.assertEqual(self.client.post('/webhook',headers=headers,json=dict(update_id=1,message=message)).status_code,200)
            self.assertEqual(mocked.await_count,1)
            reply=mocked.call_args.args[1]
            self.assertIn('Provably True',reply['text'])
            self.assertIn('5298585940577525950',reply['text'])
            self.assertEqual(self.api.service.state(100)['partner']['count'],1)
            message['text']='/support'
            self.assertEqual(self.client.post('/webhook',headers=headers,json=dict(update_id=2,message=message)).status_code,200)
            self.assertEqual(mocked.call_args.args[1]['reply_markup']['inline_keyboard'][0][0]['url'],'https://t.me/DarkMonstep')

if __name__=='__main__':unittest.main()
