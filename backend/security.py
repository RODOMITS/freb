"""Bounded request admission before JSON parsing, authentication and database work."""
import asyncio
import hashlib
import hmac
import json
import math
import re
import threading
import time
from collections import OrderedDict


class RateLimited(Exception):
    def __init__(self,retry_after=1):
        self.retry_after=max(1,int(retry_after))
        super().__init__('Слишком много запросов. Подожди немного.')


class BoundedRateLimiter:
    """Fixed-size token buckets; saturation never resets active limits."""
    def __init__(self,max_keys=10000,clock=time.monotonic):
        self.max_keys=max_keys
        self.clock=clock
        self.windows=OrderedDict()
        self.lock=threading.Lock()

    def clear(self):
        with self.lock: self.windows.clear()

    def check(self,key,maximum,seconds):
        now=self.clock()
        with self.lock:
            for _ in range(min(64,len(self.windows))):
                oldest,value=next(iter(self.windows.items()))
                if value[2]>now: break
                self.windows.pop(oldest)
            item=self.windows.get(key)
            if item is None:
                if len(self.windows)>=self.max_keys: raise RateLimited(60)
                tokens=float(maximum)
            else:
                tokens=min(maximum,item[0]+max(0,now-item[1])*maximum/seconds)
            expires=now+max(seconds,60)
            if tokens<1:
                self.windows[key]=(tokens,now,expires)
                self.windows.move_to_end(key)
                raise RateLimited(math.ceil((1-tokens)*seconds/maximum))
            self.windows[key]=(tokens-1,now,expires)
            self.windows.move_to_end(key)


class SecurityMiddleware:
    def __init__(self,app,webhook_secret,script_hashes=(),body_limit=32768,body_timeout=8,api_concurrency=24,webhook_concurrency=8):
        if not 1<=api_concurrency<=128 or not 1<=webhook_concurrency<=32 or not 1<=body_timeout<=30:
            raise ValueError('Invalid request protection settings')
        self.app=app
        self.webhook_secret=webhook_secret
        self.body_limit=body_limit
        self.body_timeout=body_timeout
        self.capacity={'api':api_concurrency,'webhook':webhook_concurrency,'public':64}
        self.active={key:0 for key in self.capacity}
        self.rates=BoundedRateLimiter()
        hashes=' '.join("'sha256-"+value+"'" for value in script_hashes)
        self.headers=[
            (b'x-content-type-options',b'nosniff'),
            (b'referrer-policy',b'same-origin'),
            (b'permissions-policy',b'camera=(), microphone=(), geolocation=()'),
            (b'content-security-policy',("default-src 'self'; script-src 'self' https://telegram.org "+hashes+"; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: https:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self' https://web.telegram.org https://*.telegram.org").encode()),
        ]

    async def reject(self,send,status,message,retry_after=None):
        payload=json.dumps(dict(detail=message),ensure_ascii=False).encode()
        headers=[(b'content-type',b'application/json; charset=utf-8'),(b'content-length',str(len(payload)).encode()),(b'cache-control',b'no-store')]+self.headers
        if retry_after is not None: headers.append((b'retry-after',str(retry_after).encode()))
        await send(dict(type='http.response.start',status=status,headers=headers))
        await send(dict(type='http.response.body',body=payload))

    async def __call__(self,scope,receive,send):
        if scope['type']!='http': return await self.app(scope,receive,send)
        path=scope.get('path','')
        lane='webhook' if path=='/webhook' else 'api' if path.startswith('/api/') else 'public'
        headers=scope.get('headers',[])
        if len(headers)>100 or len(scope.get('query_string',b''))>2048 or len(path)>512:
            return await self.reject(send,400,'Некорректный запрос')
        values={}
        for name,value in headers:
            values.setdefault(name.lower(),[]).append(value)
        if sum(len(name)+len(value) for name,value in headers)>16384:
            return await self.reject(send,431,'Заголовки запроса слишком большие')
        hosts=values.get(b'host',[])
        if len(hosts)>1 or hosts and not re.fullmatch(rb'(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,252}[A-Za-z0-9])?|\[[0-9A-Fa-f:]+\])(?::[0-9]{1,5})?',hosts[0]):
            return await self.reject(send,400,'Некорректный Host')
        # This app serves images/scripts and full backups, not partial media streams.
        # Reject ranges before vulnerable legacy FileResponse parsers can see them.
        if b'range' in values:
            return await self.reject(send,416,'Частичная загрузка файлов не поддерживается')
        length_values=values.get(b'content-length',[])
        if len(length_values)>1 or length_values and not re.fullmatch(rb'[0-9]{1,10}',length_values[0]):
            return await self.reject(send,400,'Некорректный размер запроса')
        if length_values and int(length_values[0])>self.body_limit:
            return await self.reject(send,413,'Запрос слишком большой')
        encoding=values.get(b'content-encoding',[b'identity'])
        if encoding!=[b'identity']:
            return await self.reject(send,415,'Сжатые тела запросов не поддерживаются')
        if lane=='webhook':
            supplied=values.get(b'x-telegram-bot-api-secret-token',[])
            secret=self.webhook_secret()
            if not secret or len(supplied)!=1 or not hmac.compare_digest(supplied[0],secret.encode()):
                return await self.reject(send,403,'Invalid webhook secret')
        token=None
        if lane=='api' and path!='/api/auth':
            auth=values.get(b'authorization',[])
            if len(auth)!=1 or not re.fullmatch(rb'Bearer [A-Za-z0-9_-]{32,128}',auth[0]):
                return await self.reject(send,401,'Открой приложение в Telegram')
            token=hashlib.sha256(auth[0]).hexdigest()
        ip=(scope.get('client') or ('unknown',0))[0]
        try:
            if lane!='webhook':
                self.rates.check(('ip',ip),1200,60)
                if lane=='api':
                    if token:
                        self.rates.check(('api',token),120,60)
                        if path=='/api/state': self.rates.check(('state',token),12,10)
                        elif path=='/api/catalog': self.rates.check(('catalog',token),6,60)
                        elif path=='/api/history': self.rates.check(('history',token),10,10)
                        elif path=='/api/admin/backup': self.rates.check(('backup',token),1,60)
                    else: self.rates.check(('auth',ip),30,60)
                else: self.rates.check(('public',ip),900,60)
            if self.active[lane]>=self.capacity[lane]:
                return await self.reject(send,503,'Сервер занят. Повтори запрос немного позже.',1)
        except RateLimited as error:
            return await self.reject(send,429,str(error),error.retry_after)
        self.active[lane]+=1
        try:
            if scope['method'] in ('POST','PUT','PATCH'):
                content_type=values.get(b'content-type',[b''])[0].split(b';')[0].strip().lower()
                if lane in ('api','webhook') and content_type!=b'application/json':
                    return await self.reject(send,415,'Ожидается application/json')
                body=bytearray()
                deadline=time.monotonic()+self.body_timeout
                while True:
                    try:
                        message=await asyncio.wait_for(receive(),max(.001,deadline-time.monotonic()))
                    except asyncio.TimeoutError:
                        return await self.reject(send,408,'Время загрузки запроса истекло')
                    if message['type']=='http.disconnect': return
                    if message['type']!='http.request': return await self.reject(send,400,'Некорректный запрос')
                    chunk=message.get('body',b'')
                    if len(body)+len(chunk)>self.body_limit:
                        return await self.reject(send,413,'Запрос слишком большой')
                    body.extend(chunk)
                    if not message.get('more_body',False): break
                if length_values and int(length_values[0])!=len(body):
                    return await self.reject(send,400,'Некорректный размер запроса')
                delivered=False
                async def buffered_receive():
                    nonlocal delivered
                    if not delivered:
                        delivered=True
                        return dict(type='http.request',body=bytes(body),more_body=False)
                    return await receive()
                app_receive=buffered_receive
            else: app_receive=receive
            async def secured_send(message):
                if message['type']=='http.response.start':
                    existing=list(message.get('headers',[]))
                    owned={name for name,_ in self.headers}
                    existing=[(name,value) for name,value in existing if name.lower() not in owned]
                    existing=[(name,value) for name,value in existing if name.lower()!=b'accept-ranges']
                    existing.extend(self.headers)
                    if lane in ('api','webhook') or path=='/runtime-config':
                        existing=[(name,value) for name,value in existing if name.lower()!=b'cache-control']
                        existing.append((b'cache-control',b'no-store'))
                    if scope.get('scheme')=='https': existing.append((b'strict-transport-security',b'max-age=31536000'))
                    message=dict(message,headers=existing)
                await send(message)
            await self.app(scope,app_receive,secured_send)
        finally:
            self.active[lane]-=1
