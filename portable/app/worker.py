"""Scheduled outbox producer. Delivery is opt-in and requires a successful QQ response."""
import json,os,subprocess,sys,datetime as dt,traceback,pathlib
from ddl import Store,iso,now,ROOT,parse_date
def tick():
    store=Store();result=store.queue();config_path=ROOT/'delivery.json'
    try:
        result['snapshot']=store.snapshot()
    except Exception as error:
        result['snapshot']={'error':str(error)[:200]}
    config=json.loads(config_path.read_text(encoding='utf8')) if config_path.exists() else {'enabled':False}
    result['delivery_enabled']=bool(config.get('enabled'))
    if config.get('enabled') and not result.get('muted'):
        command=config.get('command')
        if not isinstance(command,list) or not command or not all(isinstance(x,str) for x in command):raise ValueError('发送适配器 command 必须是固定 argv 数组')
        for row in store.outbox():
            if row['attempts']>=5:continue
            if row['last_attempt'] and now()-parse_date(row['last_attempt'])<dt.timedelta(minutes=min(60,5*(2**row['attempts']))):continue
            if now()-parse_date(row['created_at'])>dt.timedelta(hours=4):
                with store.db:store.db.execute("UPDATE outbox SET state='stale',error='超过4小时，避免补发陈旧提醒' WHERE id=?",(row['id'],))
                continue
            try:
                if row['kind'] in ['morning','evening']:
                    content=store.summary(row['kind'],remember=False)
                else:
                    ids=json.loads(row['item_ids']);live=[]
                    for id in ids:
                        item=store.db.execute("SELECT * FROM ddl_items WHERE id=? AND owner_id=? AND status='todo'",(id,store.owner)).fetchone()
                        if item and parse_date(item['deadline_at'])>=now() and (parse_date(item['deadline_at']).date()-now().date()).days in [0,1,3]:live.append(item)
                    if not live:
                        with store.db:store.db.execute("UPDATE outbox SET state='stale',error='事项已完成、删除或改期' WHERE id=?",(row['id'],))
                        continue
                    from cards import reminder
                    content={'text':reminder([dict(r) for r in live]), 'item_ids':[r['id'] for r in live]}
                with store.db:store.db.execute('UPDATE outbox SET text=?,item_ids=? WHERE id=?',(content['text'],json.dumps(content['item_ids']),row['id']))
                with store.db:store.db.execute('UPDATE outbox SET attempts=attempts+1,last_attempt=? WHERE id=?',(iso(now()),row['id']))
                response=subprocess.run(command,input=json.dumps({'id':row['id'],'text':content['text']},ensure_ascii=False),capture_output=True,text=True,encoding='utf8',timeout=40,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if response.returncode:raise RuntimeError('发送适配器退出码 '+str(response.returncode))
                receipt=json.loads(response.stdout)
                if receipt.get('success') is not True or not receipt.get('message_id'):raise RuntimeError('未收到平台发送成功回执')
                store.ack(row['id'],str(receipt['message_id']))
            except Exception as error:
                with store.db:store.db.execute('UPDATE outbox SET error=? WHERE id=?',(str(error)[:500],row['id']))
    with (ROOT/'data'/'worker.log').open('a',encoding='utf8') as f:f.write(json.dumps({'at':iso(now()),**result},ensure_ascii=False)+'\n')
    return result
if __name__=='__main__':
    try:print(json.dumps(tick(),ensure_ascii=False))
    except Exception as error:
        (ROOT/'data').mkdir(exist_ok=True)
        with (ROOT/'data'/'worker.log').open('a',encoding='utf8') as f:f.write(json.dumps({'at':iso(now()),'error':str(error)},ensure_ascii=False)+'\n')
        sys.exit(1)
