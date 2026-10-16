import json
import unittest
from tests import test_v150 as fixtures
from backend.broadcast import Broadcaster
from backend.service import Service


class BroadcastTests(unittest.TestCase):
    def setUp(self):
        fixtures.Release150Tests.setUp(self)
        self.sender=Broadcaster(self.s.store,(100,),clock=lambda:self.now)
        self.sequence=10000
        for uid in (100,200,300):self.message(uid,'/start')

    tearDown=fixtures.Release150Tests.tearDown

    def message(self,uid,text,reply=None,update_id=None,private=True):
        self.sequence+=1
        update=dict(update_id=update_id or self.sequence,message=dict(chat=dict(id=uid,type='private' if private else 'group'),text=text,**{'from':dict(id=uid)}))
        if reply:update['message']['reply_to_message']=dict(text=reply)
        result=self.sender.handle(update)
        if not result['handled']:
            with self.s.store.tx() as db:db.execute('INSERT OR IGNORE INTO updates VALUES(?,?)',(update['update_id'],self.now))
        return result

    def latest(self):
        with self.s.store.read() as db:return dict(db.execute('SELECT * FROM broadcasts ORDER BY rowid DESC LIMIT 1').fetchone())

    def callback(self,job,choice='send',uid=100,update_id=None):
        self.sequence+=1
        return self.sender.handle(dict(update_id=update_id or self.sequence,callback_query=dict(id='callback-'+str(self.sequence),data='bc:'+choice+':'+job['id'],message=dict(chat=dict(id=uid,type='private')),**{'from':dict(id=uid)})))

    def draft(self,text='обновление приложения'):
        self.message(100,'/broadcast '+text)
        return self.latest()

    def test_admin_only_and_private_only(self):
        self.message(200,'/broadcast test')
        self.message(100,'/broadcast test',private=False)
        with self.s.store.read() as db:self.assertEqual(db.execute('SELECT count(*) FROM broadcasts').fetchone()[0],0)

    def test_draft_does_not_send_until_creator_confirms(self):
        job=self.draft()
        self.assertIsNone(self.sender.claim())
        self.assertEqual(self.callback(job,uid=200)['answer'],'Доступ запрещён.')
        self.assertIsNone(self.sender.claim())
        self.callback(job)
        self.assertEqual(self.sender.claim()['text'],job['text'])

    def test_command_and_confirmation_are_idempotent(self):
        self.message(100,'/broadcast exact',update_id=20000)
        self.message(100,'/broadcast exact',update_id=20000)
        job=self.latest()
        self.callback(job,update_id=20001);self.callback(job,update_id=20001)
        with self.s.store.read() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM broadcasts').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM broadcast_deliveries').fetchone()[0],3)

    def test_expired_preview_cannot_be_sent(self):
        job=self.draft();self.now+=901
        self.callback(job)
        self.assertIsNone(self.sender.claim())
        self.assertEqual(self.latest()['status'],'cancelled')

    def test_reply_text_and_literal_html_are_preserved(self):
        self.message(100,'/broadcast',reply='<b>текст</b>\nвторая строка')
        job=self.latest();self.callback(job)
        self.assertEqual(self.sender.claim()['text'],'<b>текст</b>\nвторая строка')

    def test_utf16_length_limit(self):
        self.message(100,'/broadcast '+'😀'*1800)
        with self.s.store.read() as db:self.assertEqual(db.execute('SELECT count(*) FROM broadcasts').fetchone()[0],0)

    def test_unsubscribe_after_preview_is_skipped_and_start_restores(self):
        job=self.draft();self.message(200,'/stop');self.callback(job)
        delivered=[]
        while True:
            item=self.sender.claim()
            if not item:break
            delivered.append(item['userId']);self.sender.finish(item)
        self.assertEqual(delivered,[100,300])
        self.message(200,'/start')
        with self.s.store.read() as db:self.assertEqual(db.execute('SELECT subscribed FROM bot_contacts WHERE user_id=200').fetchone()[0],1)

    def test_cancel_preserves_sent_messages_and_stops_pending(self):
        job=self.draft();self.callback(job)
        item=self.sender.claim();self.sender.finish(item)
        self.message(100,'/broadcast_cancel')
        self.assertIsNone(self.sender.claim())
        with self.s.store.read() as db:
            rows=dict(db.execute('SELECT status,count(*) FROM broadcast_deliveries GROUP BY status').fetchall())
        self.assertEqual(rows,dict(sent=1,cancelled=2))

    def test_retry_after_pauses_whole_campaign(self):
        job=self.draft();self.callback(job)
        item=self.sender.claim();self.sender.finish(item,429,15)
        self.assertIsNone(self.sender.claim())
        self.now+=15
        retry=self.sender.claim()
        self.assertEqual(retry['userId'],item['userId'])
        self.assertEqual(retry['attempts'],2)

    def test_blocked_user_is_not_retried_and_can_return(self):
        job=self.draft();self.callback(job)
        item=self.sender.claim();self.sender.finish(item,403)
        with self.s.store.read() as db:self.assertEqual(db.execute('SELECT reachable FROM bot_contacts WHERE user_id=?',(item['userId'],)).fetchone()[0],0)
        self.message(item['userId'],'/start')
        with self.s.store.read() as db:self.assertEqual(db.execute('SELECT reachable FROM bot_contacts WHERE user_id=?',(item['userId'],)).fetchone()[0],1)

    def test_restart_does_not_duplicate_uncertain_send(self):
        job=self.draft();self.callback(job)
        item=self.sender.claim()
        self.sender=Broadcaster(self.s.store,(100,),clock=lambda:self.now)
        self.sender.recover()
        following=self.sender.claim()
        self.assertNotEqual(item['userId'],following['userId'])
        with self.s.store.read() as db:self.assertEqual(db.execute('SELECT status FROM broadcast_deliveries WHERE user_id=? AND broadcast_id=?',(item['userId'],job['id'])).fetchone()[0],'uncertain')

    def test_unknown_delivery_is_not_blindly_retried(self):
        job=self.draft();self.callback(job)
        item=self.sender.claim();self.sender.finish(item,0)
        with self.s.store.read() as db:self.assertEqual(db.execute('SELECT status FROM broadcast_deliveries WHERE user_id=?',(item['userId'],)).fetchone()[0],'uncertain')

    def test_only_one_campaign_runs_and_old_buttons_do_not_restart(self):
        first=self.draft();self.callback(first)
        self.now+=2
        second=self.draft()
        self.assertIn('текущей',self.callback(second)['answer'])
        self.assertEqual(self.latest()['status'],'draft')
        self.callback(first,'cancel')
        self.callback(second)
        self.assertEqual(self.latest()['status'],'queued')
        self.callback(first)
        with self.s.store.read() as db:self.assertEqual(db.execute('SELECT status FROM broadcasts WHERE id=?',(first['id'],)).fetchone()[0],'cancelled')

    def test_cancel_command_prefers_running_job_over_new_preview(self):
        first=self.draft();self.callback(first)
        self.now+=2;second=self.draft()
        self.message(100,'/broadcast_cancel')
        with self.s.store.read() as db:
            self.assertEqual(db.execute('SELECT status FROM broadcasts WHERE id=?',(first['id'],)).fetchone()[0],'cancelled')
            self.assertEqual(db.execute('SELECT status FROM broadcasts WHERE id=?',(second['id'],)).fetchone()[0],'draft')

    def test_draft_recipient_list_is_fixed(self):
        job=self.draft();self.message(400,'/start');self.callback(job)
        with self.s.store.read() as db:self.assertEqual(db.execute('SELECT count(*) FROM broadcast_deliveries WHERE broadcast_id=?',(job['id'],)).fetchone()[0],3)

    def test_completion_queues_one_report_and_status_is_available(self):
        job=self.draft();self.callback(job)
        while True:
            item=self.sender.claim()
            if not item:break
            self.sender.finish(item)
        self.sender.claim();self.message(100,'/broadcast_status')
        with self.s.store.read() as db:
            report=db.execute('SELECT payload FROM outbox WHERE id=?',('broadcast-finished-'+job['id'],)).fetchone()[0]
            self.assertIn('Отправлено: 3',json.loads(report)['text'])
            self.assertEqual(db.execute('SELECT count(*) FROM outbox WHERE id=?',('broadcast-finished-'+job['id'],)).fetchone()[0],1)
