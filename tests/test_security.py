import asyncio
import unittest
from backend.security import BoundedRateLimiter,RateLimited,SecurityMiddleware

TOKEN=b'Bearer '+b'a'*43

class LimiterTests(unittest.TestCase):
    def test_saturation_never_clears_active_limits(self):
        now=[0.]
        limiter=BoundedRateLimiter(max_keys=2,clock=lambda:now[0])
        limiter.check('one',1,10);limiter.check('two',1,10)
        with self.assertRaises(RateLimited):limiter.check('three',1,10)
        with self.assertRaises(RateLimited):limiter.check('one',1,10)
        now[0]=61
        limiter.check('three',1,10)

    def test_window_refills_without_allowing_rejected_burst(self):
        now=[0.]
        limiter=BoundedRateLimiter(clock=lambda:now[0])
        for _ in range(3):limiter.check('key',3,10)
        with self.assertRaises(RateLimited):limiter.check('key',3,10)
        now[0]=10
        limiter.check('key',3,10)


class MiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def call(self,middleware,path='/api/auth',method='POST',headers=None,chunks=None,receive=None):
        sent=[];self.reads=0
        queue=list(chunks if chunks is not None else [dict(type='http.request',body=b'{}',more_body=False)])
        async def queued():
            self.reads+=1
            return queue.pop(0) if queue else dict(type='http.disconnect')
        async def send(message):sent.append(message)
        scope=dict(type='http',method=method,path=path,query_string=b'',headers=headers if headers is not None else [(b'content-type',b'application/json')],client=('127.0.0.1',123),scheme='https')
        await middleware(scope,receive or queued,send)
        return sent

    def middleware(self,**kwargs):
        self.calls=0
        async def app(scope,receive,send):
            self.calls+=1
            if scope['method']=='POST':await receive()
            await send(dict(type='http.response.start',status=200,headers=[]))
            await send(dict(type='http.response.body',body=b'{}'))
        return SecurityMiddleware(app,webhook_secret=lambda:'secret',**kwargs)

    async def test_oversize_chunked_body_is_stopped_before_app(self):
        middleware=self.middleware()
        messages=[dict(type='http.request',body=b'a'*20000,more_body=True),dict(type='http.request',body=b'b'*20000,more_body=True),dict(type='http.request',body=b'c',more_body=False)]
        result=await self.call(middleware,chunks=messages)
        self.assertEqual(result[0]['status'],413)
        self.assertEqual(self.calls,0);self.assertEqual(self.reads,2)
        self.assertEqual(middleware.active['api'],0)

    async def test_declared_oversize_and_invalid_length_reject_without_read(self):
        for length,status in [(b'999999',413),(b'-1',400),(b'NaN',400)]:
            with self.subTest(length=length):
                result=await self.call(self.middleware(),headers=[(b'content-length',length)])
                self.assertEqual(result[0]['status'],status);self.assertEqual(self.reads,0)

    async def test_range_and_malformed_host_never_reach_app(self):
        for headers,status in [([(b'range',b'bytes=0-1,0-2,0-3')],416),([(b'host',b'example.org/evil')],400),([(b'x-large',b'x'*17000)],431)]:
            result=await self.call(self.middleware(),path='/img/test.png',method='GET',headers=headers)
            self.assertEqual(result[0]['status'],status)
            self.assertEqual(self.calls,0)

    async def test_webhook_secret_checked_before_body(self):
        result=await self.call(self.middleware(),path='/webhook')
        self.assertEqual(result[0]['status'],403)
        self.assertEqual(self.reads,0);self.assertEqual(self.calls,0)

    async def test_anonymous_api_never_reaches_database(self):
        result=await self.call(self.middleware(),path='/api/state',method='GET')
        self.assertEqual(result[0]['status'],401);self.assertEqual(self.calls,0)

    async def test_slow_body_times_out_and_releases_slot(self):
        middleware=self.middleware();middleware.body_timeout=.005
        async def slow():await asyncio.sleep(.1);return dict(type='http.request',body=b'{}')
        result=await self.call(middleware,receive=slow)
        self.assertEqual(result[0]['status'],408);self.assertEqual(middleware.active['api'],0)

    async def test_state_polling_is_limited_and_has_retry_after(self):
        middleware=self.middleware();headers=[(b'authorization',TOKEN)]
        for _ in range(12):self.assertEqual((await self.call(middleware,path='/api/state',method='GET',headers=headers))[0]['status'],200)
        result=await self.call(middleware,path='/api/state',method='GET',headers=headers)
        self.assertEqual(result[0]['status'],429)
        self.assertIn(b'retry-after',dict(result[0]['headers']))

    async def test_security_headers_on_success_and_rejections(self):
        for result in [await self.call(self.middleware()),await self.call(self.middleware(),path='/api/state',method='GET')]:
            headers=dict(result[0]['headers'])
            self.assertEqual(headers[b'cache-control'],b'no-store')
            self.assertIn(b'content-security-policy',headers)
            self.assertIn(b"object-src 'none'",headers[b'content-security-policy'])

    async def test_disconnect_and_bad_content_type_do_not_leak_capacity(self):
        middleware=self.middleware()
        await self.call(middleware,chunks=[dict(type='http.disconnect')])
        self.assertEqual(middleware.active['api'],0)
        result=await self.call(middleware,headers=[(b'content-type',b'text/plain')])
        self.assertEqual(result[0]['status'],415)
        self.assertEqual(middleware.active['api'],0)

    async def test_webhook_keeps_reserved_capacity_when_api_is_full(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def app(scope,receive,send):
            if scope['path']=='/api/state':
                entered.set();await release.wait()
            await send(dict(type='http.response.start',status=200,headers=[]))
            await send(dict(type='http.response.body',body=b'{}'))
        middleware=SecurityMiddleware(app,webhook_secret=lambda:'secret',api_concurrency=1)
        first=asyncio.create_task(self.call(middleware,path='/api/state',method='GET',headers=[(b'authorization',TOKEN)]))
        await entered.wait()
        busy=await self.call(middleware,path='/api/state',method='GET',headers=[(b'authorization',TOKEN)])
        self.assertEqual(busy[0]['status'],503)
        hook=await self.call(middleware,path='/webhook',headers=[(b'content-type',b'application/json'),(b'x-telegram-bot-api-secret-token',b'secret')])
        self.assertEqual(hook[0]['status'],200)
        release.set();await first
        self.assertEqual(middleware.active['api'],0)
