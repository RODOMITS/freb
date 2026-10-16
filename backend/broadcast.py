"""Administrator-only, confirmed broadcasts. Never sends anything on import."""
import json
import re
import time
import uuid


class Broadcaster:
    def __init__(self,store,admins,clock=time.time):
        self.store,self.admins,self.clock=store,set(admins),clock

    def reply(self,db,key,uid,text,buttons=None):
        payload=dict(chat_id=uid,text=text)
        if buttons:payload['reply_markup']=dict(inline_keyboard=buttons)
        db.execute('INSERT OR IGNORE INTO outbox(id,message,method,payload) VALUES(?,?,?,?)',(key,'','sendMessage',json.dumps(payload)))

    def summary(self,db,job):
        counts={r['status']:r['n'] for r in db.execute('SELECT status,count(*) n FROM broadcast_deliveries WHERE broadcast_id=? GROUP BY status',(job['id'],))}
        return (f'Рассылка #{job["id"]}\nСтатус: '+{'draft':'Предпросмотр','queued':'В очереди','running':'Отправляется','finished':'Завершена','cancelled':'Отменена'}.get(job['status'],job['status'])+
                f'\nВсего: {sum(counts.values())}\nОтправлено: {counts.get("sent",0)}\nНе доставлено: {counts.get("failed",0)}\nПропущено: {counts.get("skipped",0)}\nОтменено: {counts.get("cancelled",0)}\nНе подтверждено: {counts.get("uncertain",0)}\nОсталось: {counts.get("pending",0)+counts.get("sending",0)}')

    def cancel(self,db,job):
        if job['status'] in ('finished','cancelled'):return 'Рассылка уже завершена или отменена.'
        db.execute("UPDATE broadcasts SET status='cancelled' WHERE id=?",(job['id'],))
        db.execute("UPDATE broadcast_deliveries SET status='cancelled' WHERE broadcast_id=? AND status='pending'",(job['id'],))
        return 'Рассылка отменена. Уже отправленные сообщения отозвать нельзя.'

    def handle(self,update):
        message=update.get('message') or {}
        callback=update.get('callback_query') or {}
        data=str(callback.get('data',''))
        callback_match=re.fullmatch(r'bc:(send|cancel):([0-9a-f]{16})',data)
        if callback_match:
            who=callback.get('from',{}).get('id')
            chat=callback.get('message',{}).get('chat',{})
            valid=who in self.admins and chat.get('type')=='private' and chat.get('id')==who
            answer='Доступ запрещён.'
            with self.store.tx() as db:
                if valid and not db.execute('SELECT 1 FROM updates WHERE id=?',(update['update_id'],)).fetchone():
                    job=db.execute('SELECT * FROM broadcasts WHERE id=? AND actor=?',(callback_match[2],who)).fetchone()
                    if not job:answer='Рассылка не найдена.'
                    elif callback_match[1]=='cancel':answer=self.cancel(db,job)
                    elif job['status']!='draft':answer='Эта рассылка уже подтверждена или отменена.'
                    elif job['expires']<=self.clock():
                        answer=self.cancel(db,job)+' Предпросмотр устарел.'
                    elif db.execute("SELECT 1 FROM broadcasts WHERE status IN ('queued','running')").fetchone():
                        answer='Сначала дождись текущей рассылки или отмени её.'
                    else:
                        db.execute("UPDATE broadcasts SET status='queued' WHERE id=?",(job['id'],))
                        answer='Рассылка подтверждена и поставлена в очередь.'
                    self.reply(db,'broadcast-callback-'+str(update['update_id']),who,answer)
                    db.execute('INSERT INTO updates VALUES(?,?)',(update['update_id'],self.clock()))
                elif valid:answer='Это нажатие уже обработано.'
            return dict(handled=True,callbackId=callback.get('id'),answer=answer[:180])
        chat=message.get('chat',{})
        who=message.get('from',{}).get('id')
        if chat.get('type')!='private' or chat.get('id')!=who or type(who) is not int or who<=0:
            return dict(handled=False)
        text=message.get('text') or ''
        parts=text.split(maxsplit=1)
        command=parts[0].split('@',1)[0].lower() if parts else ''
        managed=command in ('/broadcast','/broadcast_status','/broadcast_cancel','/stop','/unsubscribe')
        with self.store.tx() as db:
            if db.execute('SELECT 1 FROM updates WHERE id=?',(update['update_id'],)).fetchone():
                return dict(handled=managed)
            db.execute('INSERT INTO bot_contacts(user_id,updated) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET reachable=1,updated=excluded.updated',(who,self.clock()))
            if command=='/start':db.execute('UPDATE bot_contacts SET subscribed=1 WHERE user_id=?',(who,))
            if not managed:return dict(handled=False)
            key='broadcast-command-'+str(update['update_id'])
            if command in ('/stop','/unsubscribe'):
                db.execute('UPDATE bot_contacts SET subscribed=0 WHERE user_id=?',(who,))
                self.reply(db,key,who,'Рассылки отключены. Чтобы включить снова, отправь /start. Служебные уведомления об операциях сохраняются.')
            elif who not in self.admins:self.reply(db,key,who,'Команда доступна только администраторам.')
            elif command in ('/broadcast_status','/broadcast_cancel'):
                job=db.execute("SELECT * FROM broadcasts WHERE actor=? ORDER BY CASE WHEN status IN ('queued','running') THEN 0 WHEN status='draft' THEN 1 ELSE 2 END,created DESC,rowid DESC LIMIT 1",(who,)).fetchone()
                answer='Рассылок пока нет.' if not job else self.cancel(db,job) if command=='/broadcast_cancel' else self.summary(db,job)
                self.reply(db,key,who,answer)
            else:
                content=parts[1] if len(parts)>1 else (message.get('reply_to_message') or {}).get('text','')
                if not content.strip():
                    self.reply(db,key,who,'Отправь /broadcast текст рассылки или ответь командой /broadcast на текстовое сообщение.\nСначала будет предпросмотр и подтверждение.\n/broadcast_status — статус\n/broadcast_cancel — отмена')
                elif len(content.encode('utf-16-le'))//2>3500:
                    self.reply(db,key,who,'Текст слишком длинный: максимум 3500 символов Telegram. Сократи его.')
                elif db.execute('SELECT count(*) FROM broadcasts WHERE actor=? AND created>?',(who,self.clock()-60)).fetchone()[0]>=5:
                    self.reply(db,key,who,'Слишком много предпросмотров. Подожди минуту.')
                else:
                    for old in db.execute("SELECT * FROM broadcasts WHERE actor=? AND status='draft'",(who,)).fetchall():self.cancel(db,old)
                    job_id=uuid.uuid4().hex[:16]
                    db.execute('INSERT INTO broadcasts(id,actor,text,status,created,expires) VALUES(?,?,?,?,?,?)',(job_id,who,content,'draft',self.clock(),self.clock()+900))
                    db.execute('INSERT INTO broadcast_deliveries(broadcast_id,user_id) SELECT ?,user_id FROM bot_contacts WHERE subscribed=1 AND reachable=1',(job_id,))
                    count=db.execute('SELECT count(*) FROM broadcast_deliveries WHERE broadcast_id=?',(job_id,)).fetchone()[0]
                    self.reply(db,key,who,f'Предпросмотр рассылки #{job_id}\nПолучателей по базе: {count}\n\n'+content+'\n\nОтправка начнётся только после подтверждения. Предпросмотр действует 15 минут.',[[dict(text='Отправить',callback_data='bc:send:'+job_id),dict(text='Отменить',callback_data='bc:cancel:'+job_id)]])
            db.execute('INSERT INTO updates VALUES(?,?)',(update['update_id'],self.clock()))
        return dict(handled=True)

    def recover(self):
        # A crash after sendMessage may have delivered the message. Never resend blindly.
        with self.store.tx() as db:
            db.execute("UPDATE broadcast_deliveries SET status='uncertain' WHERE status='sending'")

    def claim(self):
        with self.store.read() as db:
            if not db.execute("SELECT 1 FROM broadcasts WHERE status IN ('queued','running') AND paused_until<=? LIMIT 1",(self.clock(),)).fetchone():return None
        with self.store.tx() as db:
            job=db.execute("SELECT * FROM broadcasts WHERE status IN ('queued','running') ORDER BY created,rowid LIMIT 1").fetchone()
            if not job or job['paused_until']>self.clock():return None
            db.execute("UPDATE broadcast_deliveries SET status='skipped' WHERE broadcast_id=? AND status='pending' AND NOT EXISTS(SELECT 1 FROM bot_contacts c WHERE c.user_id=broadcast_deliveries.user_id AND c.subscribed=1 AND c.reachable=1)",(job['id'],))
            row=db.execute("SELECT * FROM broadcast_deliveries WHERE broadcast_id=? AND status='pending' ORDER BY user_id LIMIT 1",(job['id'],)).fetchone()
            if not row:
                if db.execute("SELECT 1 FROM broadcast_deliveries WHERE broadcast_id=? AND status='sending' LIMIT 1",(job['id'],)).fetchone():return None
                db.execute("UPDATE broadcasts SET status='finished' WHERE id=?",(job['id'],))
                finished=dict(job);finished['status']='finished'
                self.reply(db,'broadcast-finished-'+job['id'],job['actor'],self.summary(db,finished))
                return None
            db.execute("UPDATE broadcasts SET status='running' WHERE id=?",(job['id'],))
            db.execute("UPDATE broadcast_deliveries SET status='sending',attempts=attempts+1 WHERE broadcast_id=? AND user_id=?",(job['id'],row['user_id']))
            return dict(jobId=job['id'],userId=row['user_id'],text=job['text'],attempts=row['attempts']+1)

    def finish(self,item,code=None,retry_after=None):
        with self.store.tx() as db:
            job=db.execute('SELECT status FROM broadcasts WHERE id=?',(item['jobId'],)).fetchone()
            if code==429 and job['status']!='cancelled' and item['attempts']<10:
                status='pending'
                db.execute('UPDATE broadcasts SET paused_until=? WHERE id=?',(self.clock()+max(1,retry_after or 30),item['jobId']))
            else:status='sent' if code is None else 'failed' if code in (400,403,429) else 'uncertain'
            db.execute('UPDATE broadcast_deliveries SET status=? WHERE broadcast_id=? AND user_id=?',(status,item['jobId'],item['userId']))
            if code==403:db.execute('UPDATE bot_contacts SET reachable=0 WHERE user_id=?',(item['userId'],))
