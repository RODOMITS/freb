"""Deposit conversations: all messages travel through the bot, never peer DMs."""
import json
import time

def queue(db, key, method, payload):
    db.execute('INSERT OR IGNORE INTO outbox(id,message,method,payload) VALUES(?,?,?,?)',(key,'',method,json.dumps(payload,ensure_ascii=False)))

def handle(service, update, owner_id):
    callback=update.get('callback_query')
    message=update.get('message') or {}
    if message.get('successful_payment') or message.get('refunded_payment'):
        return None
    user=(callback or message).get('from') or {}
    actor=user.get('id')
    chat=((callback or {}).get('message') or message).get('chat') or {}
    if type(actor) is not int or actor<=0 or chat.get('type')!='private' or chat.get('id')!=actor:
        return None
    data=str(callback.get('data','')) if callback else ''
    if callback and not data.startswith('dep:'):
        return None
    text=message.get('text') or ''
    command=text.split(maxsplit=1)[0] if text else ''
    start=text.split(maxsplit=1)
    request_id=None
    choose=False
    stop=False
    list_=command=='/deposits'
    if callback and data.startswith('dep:'):
        parts=data.split(':',2)
        if len(parts)==3 and parts[1] in ('reply','chat'):
            request_id=parts[2];choose=True
        elif data=='dep:stop':
            stop=True
        else:
            return dict(answer='Неизвестная кнопка')
    elif command=='/start' and len(start)==2 and start[1].startswith('dep_'):
        request_id=start[1][4:];choose=True
    elif command in ('/stop','/stopdialog'):
        stop=True
    elif command.startswith('/') and not list_:
        return None
    with service.store.tx() as db:
        if db.execute('SELECT 1 FROM updates WHERE id=?',(update['update_id'],)).fetchone():
            return dict(answer='' if callback else None)
        session=db.execute('SELECT * FROM bot_dialogs WHERE actor=?',(actor,)).fetchone()
        if not (choose or stop or list_ or session):
            if actor!=owner_id:
                return None
            queue(db,'chat-help-'+str(update['update_id']),'sendMessage',dict(chat_id=actor,text='Выбери депозит кнопкой «Ответить» в уведомлении или отправь /deposits. Сообщение никому не отправлено.'))
        elif stop:
            db.execute('DELETE FROM bot_dialogs WHERE actor=?',(actor,))
            queue(db,'chat-stop-'+str(update['update_id']),'sendMessage',dict(chat_id=actor,text='Диалог остановлен. Заявка остаётся открытой. Для продолжения выбери её снова через /deposits.'))
        elif list_:
            rows=db.execute("SELECT id,user_id,data FROM transfers WHERE kind='deposit' AND status='pending'"+('' if actor==owner_id else ' AND user_id=?')+' ORDER BY created DESC LIMIT 20',() if actor==owner_id else (actor,)).fetchall()
            buttons=[[dict(text=('Депозит '+r['id'][:8]+' · '+str(r['user_id'])) if actor==owner_id else 'Написать по депозиту '+r['id'][:8],callback_data=('dep:reply:' if actor==owner_id else 'dep:chat:')+r['id'])] for r in rows]
            queue(db,'chat-list-'+str(update['update_id']),'sendMessage',dict(chat_id=actor,text='Выбери открытый депозит:' if rows else 'Открытых депозитов нет.',reply_markup=dict(inline_keyboard=buttons)))
        elif choose:
            row=db.execute("SELECT * FROM transfers WHERE id=? AND kind='deposit' AND status='pending'",(request_id,)).fetchone()
            if not row or actor not in (owner_id,row['user_id']):
                db.execute('DELETE FROM bot_dialogs WHERE actor=?',(actor,))
                if callback:
                    db.execute('INSERT INTO updates VALUES(?,?)',(update['update_id'],time.time()))
                    return dict(answer='Заявка недоступна или уже обработана')
                queue(db,'chat-denied-'+str(update['update_id']),'sendMessage',dict(chat_id=actor,text='Заявка недоступна или уже обработана. /deposits — твои открытые заявки.'))
            else:
                db.execute('INSERT INTO bot_dialogs(actor,request_id,last_sent) VALUES(?,?,0) ON CONFLICT(actor) DO UPDATE SET request_id=excluded.request_id,last_sent=0',(actor,row['id']))
                item=json.loads(row['data'])
                name=service.items.get(item['itemId'],{}).get('name',item['itemId'])
                destination='пользователю '+str(row['user_id']) if actor==owner_id else 'владельцу'
                queue(db,'chat-selected-'+str(update['update_id']),'sendMessage',dict(chat_id=actor,text=f"Диалог по депозиту #{row['id'][:8]}\n{name}\nСледующие сообщения будут отправлены {destination} через бота. Можно отправлять текст, фото, видео и документы.\n/stop — выйти из диалога, /deposits — выбрать другую заявку.",reply_markup=dict(inline_keyboard=[[dict(text='Завершить диалог',callback_data='dep:stop')]])))
        elif session:
            row=db.execute("SELECT * FROM transfers WHERE id=? AND kind='deposit' AND status='pending'",(session['request_id'],)).fetchone()
            if not row or actor not in (owner_id,row['user_id']):
                db.execute('DELETE FROM bot_dialogs WHERE actor=?',(actor,))
                queue(db,'chat-closed-'+str(update['update_id']),'sendMessage',dict(chat_id=actor,text='Этот депозит уже обработан, диалог закрыт. /deposits — другие открытые заявки. Сообщение не отправлено.'))
            elif time.time()-session['last_sent']<2:
                queue(db,'chat-rate-'+str(update['update_id']),'sendMessage',dict(chat_id=actor,text='Подожди пару секунд перед следующим сообщением. Это сообщение не отправлено.'))
            else:
                supported=any(message.get(k) for k in ('text','photo','video','document','audio','voice','animation','sticker','video_note'))
                if not supported or not message.get('message_id'):
                    queue(db,'chat-unsupported-'+str(update['update_id']),'sendMessage',dict(chat_id=actor,text='Отправь текст, фото, видео, голосовое сообщение или документ.'))
                else:
                    peer=row['user_id'] if actor==owner_id else owner_id
                    button=dict(text='Ответить по депозиту '+row['id'][:8],callback_data=('dep:chat:' if peer!=owner_id else 'dep:reply:')+row['id'])
                    if message.get('text'):
                        title='Владелец' if actor==owner_id else 'Пользователь '+str(actor)
                        body=f"Депозит #{row['id'][:8]} · {title}\n\n"+message['text']
                        queue(db,'chat-message-'+str(update['update_id']),'sendMessage',dict(chat_id=peer,text=body[:4096],reply_markup=dict(inline_keyboard=[[button]])))
                    else:
                        queue(db,'chat-header-'+str(update['update_id']),'sendMessage',dict(chat_id=peer,text=f"Депозит #{row['id'][:8]} · "+('владелец' if actor==owner_id else 'пользователь '+str(actor))))
                        queue(db,'chat-message-'+str(update['update_id']),'copyMessage',dict(chat_id=peer,from_chat_id=actor,message_id=message['message_id'],reply_markup=dict(inline_keyboard=[[button]])))
                    db.execute('UPDATE bot_dialogs SET last_sent=? WHERE actor=?',(time.time(),actor))
        db.execute('INSERT INTO updates VALUES(?,?)',(update['update_id'],time.time()))
    return dict(answer='Диалог выбран' if callback and choose else '' if callback else None)
