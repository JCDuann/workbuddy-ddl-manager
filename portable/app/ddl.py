"""DDL 管家: deterministic local tools, SQLite persistence, no third party dependency."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, pathlib, re, sqlite3, sys, uuid

TZ = dt.timezone(dt.timedelta(hours=8))
ROOT = pathlib.Path(__file__).resolve().parent
OWNER = os.getenv('DDL_OWNER') or (json.loads((ROOT/'deployment.json').read_text(encoding='utf8')).get('owner_id','ddl:local') if (ROOT/'deployment.json').exists() else 'ddl:local')
def now(): return dt.datetime.now(TZ)
def iso(value): return value.astimezone(TZ).isoformat(timespec='seconds')
def parse_date(value):
    t=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if t.tzinfo is None: t=t.replace(tzinfo=TZ)
    return t.astimezone(TZ)
def normalize(value, reference=None):
    """Reject underspecified dates. Plain calendar dates resolve to end of day."""
    ref=parse_date(reference) if reference else now()
    text=value.strip()
    if re.match(r'^\d{4}-\d\d-\d\d',text):
        if re.fullmatch(r'\d{4}-\d\d-\d\d',text): text+='T23:59:00'
        return iso(parse_date(text))
    clock=re.search(r'(\d{1,2})[:：](\d{2})',text)
    if clock: hour,minute=map(int,clock.groups())
    else:
        clock=re.search(r'([零一二三四五六七八九十两\d]{1,3})[点时](半|[零一二三四五六七八九十\d]{1,3}分?)?',text)
        nums={'零':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
        def number(s):
            if s.isdigit(): return int(s)
            if '十' in s:
                a,b=s.split('十'); return (nums.get(a,1)*10)+nums.get(b,0)
            return nums[s]
        if clock:
            hour=number(clock[1]); m=(clock[2] or '').rstrip('分'); minute=30 if m=='半' else number(m) if m else 0
            if any(x in text for x in ['下午','晚上','晚间']) and hour<12: hour+=12
        elif any(x in text for x in ['前','截止','当天','月底']) or re.fullmatch(r'今天|明天|后天',text): hour,minute=23,59
        else: raise ValueError('时间未明确，请提供几点截止')
    midnight=(hour==24 and minute==0)
    if midnight:hour=0
    if not (0<=hour<=23 and 0<=minute<=59): raise ValueError('无效的时分')
    date=None
    for word,offset in [('大后天',3),('后天',2),('明天',1),('今天',0)]:
        if word in text: date=ref.date()+dt.timedelta(days=offset); break
    week=re.search(r'(下下|下|本|这)?(?:周|星期)([一二三四五六日天])',text)
    if week:
        target='一二三四五六日'.index(week[2].replace('天','日'))
        monday=ref.date()-dt.timedelta(days=ref.weekday())
        shift={'下下':14,'下':7,'本':0,'这':0}.get(week[1],0)
        date=monday+dt.timedelta(days=target+shift)
        if not week[1] and dt.datetime.combine(date,dt.time(hour,minute),TZ)<ref: date+=dt.timedelta(days=7)
    if '月底' in text:
        month=ref.month+('下月' in text); year=ref.year+(month>12); month=(month-1)%12+1
        next_month=dt.date(year+int(month==12),month%12+1,1)
        date=next_month-dt.timedelta(days=1)
    explicit=re.search(r'(?:(\d{4})年)?(\d{1,2})[月/](\d{1,2})[日号]?',text)
    if explicit:
        if not explicit[1]: raise ValueError('缺少年份，请由 Agent 根据通知日期确认年份后传入 ISO 时间')
        date=dt.date(int(explicit[1]),int(explicit[2]),int(explicit[3]))
    if date is None: raise ValueError('日期未明确，请提供完整日期')
    if midnight:date+=dt.timedelta(days=1)
    return iso(dt.datetime.combine(date,dt.time(hour,minute),TZ))

RECURRENCE={'daily':1,'weekly':7,'biweekly':14,'monthly':0}
def normalize_recurrence(value):
    """Accept None/daily/weekly/biweekly/monthly; reject anything else."""
    if value in (None,'','none',False): return None
    text=str(value).strip().lower()
    if text in RECURRENCE: return text
    raise ValueError('recurrence 仅支持 daily/weekly/biweekly/monthly')
def month_last_day(year,month):
    """Last calendar day of a month, without external deps."""
    first=dt.date(year,month,1)
    return (first+dt.timedelta(days=31)).replace(day=1)-dt.timedelta(days=1)
def next_occurrence(after,rule):
    """Next datetime strictly after `after` for the given recurrence rule."""
    if rule=='daily': return after+dt.timedelta(days=1)
    if rule=='weekly': return after+dt.timedelta(days=7)
    if rule=='biweekly': return after+dt.timedelta(days=14)
    if rule=='monthly':
        month=after.month+1; year=after.year+(month>12); month=(month-1)%12+1
        day=min(after.day,month_last_day(year,month).day)
        return after.replace(year=year,month=month,day=day)
    raise ValueError('未知重复规则')
def group_items(rows):
    """Bucket rows into 今天/本周/更远/逾期, preserving deadline order."""
    clock=now(); today=clock.date(); monday=today-dt.timedelta(days=today.weekday()); sunday=monday+dt.timedelta(days=6)
    buckets=[('逾期',[]),('今天',[]),('本周',[]),('更远',[])]
    index={'逾期':0,'今天':1,'本周':2,'更远':3}
    for r in rows:
        due=parse_date(r['deadline_at'])
        if due<clock and r['status']!='done': key='逾期'
        elif due.date()==today: key='今天'
        elif due.date()<=sunday: key='本周'
        else: key='更远'
        buckets[index[key]][1].append(r)
    return [(name,items) for name,items in buckets if items]

SCHEMA='''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS ddl_items(
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, title TEXT NOT NULL,
 category TEXT NOT NULL DEFAULT '课程', deadline_at TEXT NOT NULL, start_at TEXT,
 location TEXT NOT NULL DEFAULT '', action TEXT NOT NULL DEFAULT '', contact TEXT NOT NULL DEFAULT '',
 source_type TEXT NOT NULL, source_url TEXT NOT NULL DEFAULT '', source_raw TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL CHECK(status IN ('todo','pending','done','deleted','expired')),
 previous_status TEXT, priority TEXT NOT NULL CHECK(priority IN ('high','medium','low')),
 confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1), fingerprint TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(owner_id,fingerprint));
CREATE INDEX IF NOT EXISTS idx_items_due ON ddl_items(owner_id,status,deadline_at);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, owner_id TEXT, item_id TEXT, operation TEXT, before_json TEXT, after_json TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS preferences(owner_id TEXT PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opportunities(id TEXT PRIMARY KEY, source_id TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
 title TEXT NOT NULL, published_at TEXT, text TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '[]',
 extraction TEXT, state TEXT NOT NULL DEFAULT 'unparsed', discovered_at TEXT NOT NULL, error TEXT);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, url TEXT, last_scan TEXT, last_success TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
 item_ids TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, last_attempt TEXT, sent_at TEXT, receipt TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS contexts(owner_id TEXT PRIMARY KEY, item_ids TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reminder_marks(owner_id TEXT,item_id TEXT,revision INTEGER,day TEXT,stage INTEGER,PRIMARY KEY(owner_id,item_id,revision,day,stage));
CREATE TABLE IF NOT EXISTS catchup(owner_id TEXT, item_id TEXT, revision INTEGER, day TEXT, PRIMARY KEY(owner_id,item_id,revision,day));
'''
class Store:
    def __init__(self,path=None,owner=OWNER):
        self.owner=owner
        path=path or os.getenv('DDL_DB') or ROOT/'data'/'ddl.sqlite3'
        if str(path)!=':memory:': pathlib.Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,timeout=20);self.db.row_factory=sqlite3.Row; self.db.executescript(SCHEMA)
        self._migrate()
    def _migrate(self):
        """Idempotent column additions for older databases."""
        cols={r[1] for r in self.db.execute('PRAGMA table_info(ddl_items)')}
        for name,decl in [('recurrence','TEXT'),('archived_at','TEXT'),('parent_id','TEXT')]:
            if name not in cols:
                with self.db:self.db.execute('ALTER TABLE ddl_items ADD COLUMN '+name+' '+decl)
    def close(self):self.db.close()
    def audit(self,item_id,op,before,after):
        self.db.execute('INSERT INTO audit(owner_id,item_id,operation,before_json,after_json,at) VALUES(?,?,?,?,?,?)',
            (self.owner,item_id,op,json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False),iso(now())))
    def add(self,item):
        allowed={'title','category','deadline_at','start_at','location','action','contact','source_type','source_url','source_raw','priority','confidence','recurrence','parent_id'}
        unknown=set(item)-allowed
        if unknown: raise ValueError('未知字段: '+','.join(sorted(unknown)))
        title=str(item.get('title','')).strip()
        if not title or len(title)>200: raise ValueError('标题应为1–200字')
        confidence=item.get('confidence')
        if isinstance(confidence,bool) or not isinstance(confidence,(int,float)) or not 0<=confidence<=1: raise ValueError('需要0–1之间的 confidence')
        if confidence<.7: return {'created':False,'needs_clarification':True,'reason':'置信度不足，先追问'}
        deadline=iso(parse_date(item['deadline_at']))
        if 'T' not in item['deadline_at'] and ' ' not in item['deadline_at']: raise ValueError('入库时间必须含时分，不能擅自补全')
        start=iso(parse_date(item['start_at'])) if item.get('start_at') else None
        priority=item.get('priority','medium')
        if priority not in ['high','medium','low']: raise ValueError('无效优先级')
        source=item.get('source_type','qq_text')
        if source not in ['qq_text','qq_image','qq_file','official_web','manual']: raise ValueError('无效来源类型')
        recurrence=normalize_recurrence(item.get('recurrence'))
        fp=hashlib.sha256((re.sub(r'\W','',title).casefold()+'|'+deadline+'|'+item.get('action','').strip()).encode()).hexdigest()
        # Cross-format duplicates retain the original record; deleted matches can be restored explicitly.
        existing=self.db.execute('SELECT * FROM ddl_items WHERE owner_id=? AND fingerprint=?',(self.owner,fp)).fetchone()
        if existing: return {'created':False,'duplicate':True,'item':dict(existing)}
        same=self.db.execute('SELECT * FROM ddl_items WHERE owner_id=? AND deadline_at=? AND title=? AND status != ?',(self.owner,deadline,title,'deleted')).fetchone()
        if same: return {'created':False,'duplicate':True,'item':dict(same)}
        stamp=iso(now()); row=dict(id='ddl_'+uuid.uuid4().hex[:12],owner_id=self.owner,title=title,category=item.get('category','课程'),
            deadline_at=deadline,start_at=start,location=item.get('location',''),action=item.get('action',''),contact=item.get('contact',''),
            source_type=source,source_url=item.get('source_url',''),source_raw=item.get('source_raw','')[:4000],
            status='todo' if confidence>=.9 else 'pending',previous_status=None,priority=priority,confidence=confidence,fingerprint=fp,
            revision=1,created_at=stamp,updated_at=stamp,recurrence=recurrence,archived_at=None,parent_id=item.get('parent_id'))
        with self.db:
            self.db.execute('INSERT INTO ddl_items('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
            self.audit(row['id'],'add',None,row)
        return {'created':True,'needs_confirmation':row['status']=='pending','item':row}
    def list(self,days=None,status='active',query='',week=False,all_items=False,grouped=False):
        where=['owner_id=?']; args=[self.owner]
        if status=='active': where.append("status IN ('todo','pending','expired','done')" if all_items else "status IN ('todo','pending','expired')")
        elif status!='all': where.append('status=?');args.append(status)
        if not all_items: where.append('archived_at IS NULL')
        if query: where.append('title LIKE ?');args.append('%'+query+'%')
        if days is not None: where.append('deadline_at>=? AND deadline_at<=?'); args.extend([iso(now()),iso(now()+dt.timedelta(days=days))])
        if week:
            start=now().replace(hour=0,minute=0,second=0,microsecond=0)-dt.timedelta(days=now().weekday())
            where.append('deadline_at>=? AND deadline_at<?');args.extend([iso(start),iso(start+dt.timedelta(days=7))])
        rows=[dict(r) for r in self.db.execute('SELECT * FROM ddl_items WHERE '+' AND '.join(where)+' ORDER BY deadline_at',args)]
        if grouped: rows=group_items(rows)
        if not grouped:
            flat=[r for r in rows if not isinstance(r,tuple)]
            with self.db:self.db.execute('INSERT OR REPLACE INTO contexts VALUES(?,?,?)',(self.owner,json.dumps([r['id'] for r in flat]),iso(now())))
        return rows
    def set_context(self,rows):
        with self.db:self.db.execute('INSERT OR REPLACE INTO contexts VALUES(?,?,?)',(self.owner,json.dumps([r['id'] for r in rows]),iso(now())))
    def resolve(self,selector,deleted=False):
        if selector.isdigit():
            r=self.db.execute('SELECT * FROM contexts WHERE owner_id=?',(self.owner,)).fetchone()
            if not r or now()-parse_date(r['updated_at'])>dt.timedelta(hours=2): return []
            ids=json.loads(r['item_ids']); index=int(selector)-1
            if index<0 or index>=len(ids):return []
            selector=ids[index]
        rows=self.db.execute('SELECT * FROM ddl_items WHERE owner_id=? AND (id=? OR title LIKE ?) AND '+("status='deleted'" if deleted else "status!='deleted'")+' ORDER BY deadline_at',
            (self.owner,selector,'%'+selector+'%')).fetchall()
        return [dict(r) for r in rows]
    def change(self,selector,operation,updates=None):
        rows=self.resolve(selector,operation=='restore')
        if len(rows)!=1:
            with self.db:self.db.execute('INSERT OR REPLACE INTO contexts VALUES(?,?,?)',(self.owner,json.dumps([r['id'] for r in rows[:5]]),iso(now())))
            return {'changed':False,'operation':operation,'matches':rows,'reason':'找不到事项' if not rows else '匹配多个事项，请选择编号或完整标题'}
        before=rows[0];after=before.copy();updates=updates or {}
        spawn=None
        if operation=='delete':after.update(previous_status=before['status'],status='deleted')
        elif operation=='restore': after.update(status=before.get('previous_status') or 'todo',previous_status=None)
        elif operation=='done': after['status']='done'
        elif operation=='archive': after.update(previous_status=before['status'],status='done',archived_at=iso(now()))
        elif operation=='unarchive': after.update(status='todo',archived_at=None)
        elif operation=='confirm':
            if before['status']!='pending':raise ValueError('该事项无需确认')
            after.update(status='todo',confidence=1)
        elif operation=='update':
            if set(updates)-{'deadline_at','start_at','title','category','location','action','priority','status','recurrence'}:raise ValueError('存在不可修改字段')
            after.update(updates)
            for key in ['deadline_at','start_at']:
                if updates.get(key):
                    if 'T' not in updates[key] and ' ' not in updates[key]:raise ValueError('修改时间必须含时分')
                    after[key]=iso(parse_date(updates[key]))
            if 'recurrence' in updates: after['recurrence']=normalize_recurrence(updates['recurrence'])
            if not after['title'].strip():raise ValueError('标题不可为空')
            if after['priority'] not in ['high','medium','low']:raise ValueError('无效优先级')
            if after['status'] not in ['todo','pending','done','expired']:raise ValueError('无效状态')
        else: raise ValueError('未知操作')
        after['fingerprint']=hashlib.sha256((re.sub(r'\W','',after['title']).casefold()+'|'+after['deadline_at']+'|'+after['action'].strip()).encode()).hexdigest()
        after.update(revision=before['revision']+1,updated_at=iso(now()))
        with self.db:
            keys=[k for k in after if k not in ['id','owner_id','created_at']]
            self.db.execute('UPDATE ddl_items SET '+','.join(k+'=?' for k in keys)+' WHERE id=? AND owner_id=?',[*[after[k] for k in keys],after['id'],self.owner])
            self.audit(after['id'],operation,before,after)
        # Recurring items roll forward to the next occurrence instead of disappearing.
        if operation=='done' and before.get('recurrence') and not before.get('archived_at'):
            spawn=self._spawn_recurrence(before)
        return {'changed':True,'operation':operation,'before':before,'item':after,'next':spawn}
    def _spawn_recurrence(self,before):
        base=parse_date(before['deadline_at']); nxt=next_occurrence(base,before['recurrence'])
        while nxt<=now(): nxt=next_occurrence(nxt,before['recurrence'])
        start=None
        if before.get('start_at'):
            start=iso(nxt-(base-parse_date(before['start_at'])))
        stamp=iso(now()); row=dict(id='ddl_'+uuid.uuid4().hex[:12],owner_id=self.owner,title=before['title'],category=before['category'],
            deadline_at=iso(nxt),start_at=start,location=before.get('location') or '',action=before.get('action') or '',contact=before.get('contact') or '',
            source_type=before.get('source_type') or 'manual',source_url=before.get('source_url') or '',source_raw=before.get('source_raw') or '',
            status='todo',previous_status=None,priority=before.get('priority') or 'medium',confidence=before.get('confidence') or 1,
            fingerprint=hashlib.sha256((re.sub(r'\W','',before['title']).casefold()+'|'+iso(nxt)+'|'+(before.get('action') or '').strip()).encode()).hexdigest(),
            revision=1,created_at=stamp,updated_at=stamp,recurrence=before['recurrence'],archived_at=None,parent_id=before['id'])
        try:
            with self.db:
                self.db.execute('INSERT INTO ddl_items('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
                self.audit(row['id'],'add',None,row)
            return {'created':True,'item':row}
        except sqlite3.IntegrityError:
            return {'created':False,'duplicate':True}
    def prefs(self,updates=None):
        row=self.db.execute('SELECT json FROM preferences WHERE owner_id=?',(self.owner,)).fetchone()
        value=json.loads(row[0]) if row else {'morning':'08:00','evening':'21:30','include_tags':[],'exclude_tags':[],'muted_until':None}
        if updates:
            if set(updates)-set(value):raise ValueError('未知偏好字段')
            for key in ['morning','evening']:
                if key in updates and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',updates[key]):raise ValueError('使用 HH:MM 时间')
            for key in ['include_tags','exclude_tags']:
                if key in updates and (not isinstance(updates[key],list) or not all(isinstance(t,str) for t in updates[key])):raise ValueError('标签必须是字符串数组')
            if updates.get('muted_until'):updates['muted_until']=iso(parse_date(updates['muted_until']))
            value.update(updates)
            with self.db:self.db.execute('INSERT OR REPLACE INTO preferences VALUES(?,?)',(self.owner,json.dumps(value,ensure_ascii=False)))
        return value
    def opportunities(self,unparsed=False,limit=10):
        rows=[dict(r) for r in self.db.execute('SELECT * FROM opportunities '+("WHERE state='unparsed' " if unparsed else "WHERE state='ready' ")+'ORDER BY published_at DESC,discovered_at DESC LIMIT ?',(max(1,min(100,limit)),))]
        prefs=self.prefs()
        if not unparsed:
            rows=[r for r in rows if any(parse_date(i['deadline_at'])>=now() for i in json.loads(r['extraction'] or '[]'))]
            rows=[r for r in rows if not any(t.casefold() in (r['title']+r['tags']).casefold() for t in prefs['exclude_tags'])]
            if prefs['include_tags']:rows=[r for r in rows if any(t.casefold() in (r['title']+r['tags']).casefold() for t in prefs['include_tags'])]
        return rows
    def classify_opportunity(self,id,items,tags):
        row=self.db.execute('SELECT * FROM opportunities WHERE id=?',(id,)).fetchone()
        if not row:raise ValueError('机会不存在')
        normalized=[]
        for item in items:
            if not item.get('title') or not isinstance(item.get('confidence'),(int,float)) or not 0<=item['confidence']<=1:raise ValueError('不完整的抽取结果')
            normalized.append({**item,'deadline_at':iso(parse_date(item['deadline_at'])),'source_url':row['url'],'source_type':'official_web'})
        with self.db:self.db.execute('UPDATE opportunities SET extraction=?,tags=?,state=?,error=NULL WHERE id=?',
            (json.dumps(normalized,ensure_ascii=False),json.dumps(tags,ensure_ascii=False),'ready' if normalized else 'no_action',id))
        return {'classified':True,'items':len(normalized)}
    def adopt(self,id):
        r=self.db.execute('SELECT * FROM opportunities WHERE id=?',(id,)).fetchone()
        if not r or r['state']!='ready':raise ValueError('该机会尚未完成日期抽取，先读取原文并抽取')
        return [self.add(item) for item in json.loads(r['extraction'])]
    def adopt_preview(self,id):
        """Show exactly which nodes would be created, before touching ddl_items."""
        r=self.db.execute('SELECT * FROM opportunities WHERE id=?',(id,)).fetchone()
        if not r or r['state']!='ready':raise ValueError('该机会尚未完成日期抽取，先读取原文并抽取')
        nodes=[{'title':n.get('title',''),'deadline_at':n['deadline_at']} for n in json.loads(r['extraction'])]
        return {'id':id,'title':r['title'],'nodes':nodes,'count':len(nodes)}
    def summary(self,kind='morning',at=None,remember=True):
        clock=parse_date(at) if at else now()
        rows=[dict(r) for r in self.db.execute("SELECT * FROM ddl_items WHERE owner_id=? AND status IN ('todo','expired') ORDER BY deadline_at",(self.owner,))]
        window=clock+dt.timedelta(hours=48 if kind=='morning' else 24*7)
        eligible=[r for r in rows if parse_date(r['deadline_at'])<=window];selected=eligible[:5]
        from cards import summary
        opp=[r for r in self.opportunities(limit=30) if r['state']=='ready' and dt.timedelta(0)<=clock-parse_date(r['discovered_at'])<dt.timedelta(hours=24)][:3]
        pending=self.db.execute("SELECT count(*) FROM ddl_items WHERE owner_id=? AND status='pending'",(self.owner,)).fetchone()[0]
        day_start=clock.replace(hour=0,minute=0,second=0,microsecond=0)
        completed=self.db.execute("SELECT count(DISTINCT a.item_id) FROM audit a JOIN ddl_items d ON d.id=a.item_id AND d.owner_id=a.owner_id WHERE a.owner_id=? AND a.operation='done' AND a.at>=? AND a.at<=? AND d.status='done' AND json_extract(a.before_json,'$.status')!='done'",(self.owner,iso(day_start),iso(clock))).fetchone()[0]
        if selected:
            if remember:
                with self.db:self.db.execute('INSERT OR REPLACE INTO contexts VALUES(?,?,?)',(self.owner,json.dumps([r['id'] for r in selected]),iso(clock)))
        elif remember:
            with self.db:self.db.execute('INSERT OR REPLACE INTO contexts VALUES(?,?,?)',(self.owner,'[]',iso(clock)))
        return {'text':summary(kind,selected,len(rows),pending,opp,clock,completed,len(eligible)),'item_ids':[r['id'] for r in selected]}
    def queue(self,at=None):
        clock=parse_date(at) if at else now();prefs=self.prefs(); added=[]
        if prefs['muted_until'] and parse_date(prefs['muted_until'])>clock:return {'queued':0,'muted':True}
        def add(key,kind,result):
            oid=hashlib.sha256((self.owner+'|'+key).encode()).hexdigest()
            with self.db:
                cur=self.db.execute('INSERT OR IGNORE INTO outbox(id,owner_id,kind,text,item_ids,created_at) VALUES(?,?,?,?,?,?)',
                    (oid,self.owner,kind,result['text'],json.dumps(result['item_ids']),iso(clock)))
            if cur.rowcount:added.append(oid)
        for kind in ['morning','evening']:
            hour,minute=map(int,prefs[kind].split(':')); scheduled=clock.replace(hour=hour,minute=minute,second=0,microsecond=0)
            # 定时器常因主机休眠/唤醒而晚点触发。同一 kind+日期 的 outbox 行由 sha256 主键去重，
            # 所以放宽到 4 小时内仍可补发，避免早间/晚间摘要仅因晚到 30 分钟而整天丢失。
            if dt.timedelta(0)<=clock-scheduled<dt.timedelta(hours=4):
                summary=self.summary(kind,iso(clock),remember=False);add(kind+str(clock.date()),kind,summary)
                if kind=='morning':
                    for id in summary['item_ids']:
                        r=self.db.execute('SELECT * FROM ddl_items WHERE id=? AND owner_id=?',(id,self.owner)).fetchone()
                        stage=(parse_date(r['deadline_at']).date()-clock.date()).days
                        if stage in [0,1]:
                            with self.db:self.db.execute('INSERT OR IGNORE INTO reminder_marks VALUES(?,?,?,?,?)',(self.owner,id,r['revision'],str(clock.date()),stage))
        rows=self.db.execute("SELECT * FROM ddl_items WHERE owner_id=? AND status='todo' ORDER BY deadline_at",(self.owner,)).fetchall()
        buckets={}
        for r in rows:
            due=parse_date(r['deadline_at']); days=(due.date()-clock.date()).days
            if due>=clock and clock.hour>=8:
                if days not in [0,1,3]:continue
                if self.db.execute('SELECT 1 FROM reminder_marks WHERE owner_id=? AND item_id=? AND revision=? AND day=? AND stage=?',(self.owner,r['id'],r['revision'],str(clock.date()),days)).fetchone():continue
                buckets.setdefault(days,[]).append(r)
            elif due>=clock:
                # Catch-up: item added/updated after today's reminder moment, due today or tomorrow.
                added_at=parse_date(r['created_at']);days=max(0,(due.date()-clock.date()).days)
                if days>1:continue
                if added_at<=clock.replace(hour=8,minute=0,second=0,microsecond=0):continue
                if self.db.execute('SELECT 1 FROM reminder_marks WHERE owner_id=? AND item_id=? AND revision=? AND day=? AND stage=?',(self.owner,r['id'],r['revision'],str(clock.date()),days)).fetchone():continue
                if self.db.execute('SELECT 1 FROM catchup WHERE owner_id=? AND item_id=? AND revision=? AND day=?',(self.owner,r['id'],r['revision'],str(clock.date()))).fetchone():continue
                buckets.setdefault(days,[]).append(r)
        for days,rows in buckets.items():
            text='DDL 临期提醒\n'+'\n'.join(f"{i}. {r['title']}｜{parse_date(r['deadline_at']):%m-%d %H:%M}" for i,r in enumerate(rows[:5],1))
            add('due'+str(clock.date())+str(days)+'|'+','.join(r['id']+':'+str(r['revision']) for r in rows), 'deadline',{'text':text,'item_ids':[r['id'] for r in rows[:5]]})
            with self.db:
                for r in rows[:5]:
                    self.db.execute('INSERT OR IGNORE INTO reminder_marks VALUES(?,?,?,?,?)',(self.owner,r['id'],r['revision'],str(clock.date()),days))
                    self.db.execute('INSERT OR IGNORE INTO catchup VALUES(?,?,?,?)',(self.owner,r['id'],r['revision'],str(clock.date())))
        return {'queued':len(added),'ids':added}
    def push_now(self,selector=None):
        """Immediate push entry point: queue one reminder for the given item(s) without waiting for the next scheduled run."""
        clock=now();marked=[]
        if selector:
            rows=self.resolve(selector)
        else:
            rows=[dict(r) for r in self.db.execute("SELECT * FROM ddl_items WHERE owner_id=? AND status='todo' AND recurrence IS NOT NULL ORDER BY deadline_at",(self.owner,))]
        rows=[r for r in rows if r['status']=='todo' and parse_date(r['deadline_at'])>=clock]
        if not rows:return {'queued':0,'reason':'没有可推送的待完成事项'}
        key='manual'+iso(clock)
        oid=hashlib.sha256((self.owner+'|'+key).encode()).hexdigest()
        text='DDL 提醒\n'+'\n'.join(f"{i}. {r['title']}｜{parse_date(r['deadline_at']):%m-%d %H:%M}" for i,r in enumerate(rows[:5],1))
        with self.db:
            cur=self.db.execute('INSERT OR IGNORE INTO outbox(id,owner_id,kind,text,item_ids,created_at) VALUES(?,?,?,?,?,?)',
                (oid,self.owner,'manual',text,json.dumps([r['id'] for r in rows[:5]]),iso(clock)))
        return {'queued':cur.rowcount,'ids':[oid] if cur.rowcount else []}
    def outbox(self):return [dict(r) for r in self.db.execute("SELECT * FROM outbox WHERE owner_id=? AND state='pending' ORDER BY created_at",(self.owner,))]
    def ack(self,id,receipt):
        if not receipt.strip():raise ValueError('必须提供实际发送回执')
        row=self.db.execute('SELECT * FROM outbox WHERE id=? AND owner_id=?',(id,self.owner)).fetchone()
        if not row:raise ValueError('提醒不存在')
        if row['state']=='sent':return {'acknowledged':True,'already_sent':True}
        if row['state']!='pending':raise ValueError('该提醒已失效')
        with self.db:
            self.db.execute("UPDATE outbox SET state='sent',sent_at=?,receipt=? WHERE id=? AND owner_id=? AND state='pending'",(iso(now()),receipt,id,self.owner))
            self.db.execute('INSERT OR REPLACE INTO contexts VALUES(?,?,?)',(self.owner,row['item_ids'],iso(now())))
        return {'acknowledged':True}
    def status(self):
        return {'owner':self.owner,'timezone':'Asia/Shanghai','items':dict(self.db.execute('SELECT status,count(*) FROM ddl_items WHERE owner_id=? GROUP BY status',(self.owner,)).fetchall()),
            'opportunities':dict(self.db.execute('SELECT state,count(*) FROM opportunities GROUP BY state').fetchall()),'outbox_pending':len(self.outbox()),
            'sources':[dict(r) for r in self.db.execute('SELECT * FROM sources')],'preferences':self.prefs(),
            'snapshots':self.snapshots()}
    def snapshot(self,retention=7,at=None):
        """Consistent daily copy of the live database via SQLite's backup API; prunes copies older than retention days."""
        clock=parse_date(at) if at else now();folder=ROOT/'data'/'snapshots';folder.mkdir(parents=True,exist_ok=True)
        target=folder/f"ddl-{clock:%Y%m%d}.sqlite3";replaced=target.exists()
        tmp=folder/f".ddl-{clock:%Y%m%d}.tmp"
        dest=sqlite3.connect(tmp)
        try:
            self.db.backup(dest);dest.commit()
        finally:
            dest.close()
        os.replace(tmp,target)
        cutoff=clock-(dt.timedelta(days=retention)+dt.timedelta(hours=12))
        removed=[]
        for path in sorted(folder.glob('ddl-*.sqlite3')):
            stamp=path.stem.split('-',1)[1]
            try:made=dt.datetime.strptime(stamp,'%Y%m%d').replace(tzinfo=TZ)
            except ValueError:continue
            if made<cutoff:
                path.unlink();removed.append(path.name)
        return {'snapshot':target.name,'path':str(target),'bytes':target.stat().st_size,'replaced':replaced,'removed':removed,'kept':len(list(folder.glob('ddl-*.sqlite3')))}
    def snapshots(self):
        folder=ROOT/'data'/'snapshots'
        if not folder.exists():return []
        rows=[]
        for path in sorted(folder.glob('ddl-*.sqlite3')):
            stat=path.stat();rows.append({'name':path.name,'bytes':stat.st_size,'at':iso(dt.datetime.fromtimestamp(stat.st_mtime,TZ))})
        return rows

TOOLS={
 'ddl_now':('获取当前北京时间',{}),
 'ddl_normalize':('将明确的相对时间转换成北京时间 ISO；歧义时返回错误',{'text':{'type':'string'},'reference':{'type':'string'}}),
 'ddl_add':('保存确认的文字、截图或文件抽取结果；低置信度不入库',{'item':{'type':'object'}}),
 'ddl_list':('查询持久化 DDL；days 或 week 筛选；返回编号上下文',{'days':{'type':'integer'},'status':{'type':'string'},'query':{'type':'string'},'week':{'type':'boolean'}}),
 'ddl_change':('唯一匹配后修改、软删除、恢复、完成或确认；多匹配不操作',{'selector':{'type':'string'},'operation':{'type':'string','enum':['update','delete','restore','done','confirm']},'updates':{'type':'object'}}),
 'ddl_preferences':('读取或修改提醒时间、标签订阅、静音截止时间',{'updates':{'type':'object'}}),
 'ddl_opportunities':('查看官网机会池，unparsed=true 返回需要模型抽取的原文',{'unparsed':{'type':'boolean'},'limit':{'type':'integer'}}),
 'ddl_classify':('保存官网时间节点抽取和标签；不自动加入个人 DDL',{'id':{'type':'string'},'items':{'type':'array','items':{'type':'object'}},'tags':{'type':'array','items':{'type':'string'}}}),
 'ddl_adopt':('用户明确表示参加某机会后，把抽取出的节点加入个人DDL',{'id':{'type':'string'}}),
 'ddl_summary':('生成早晚摘要',{'kind':{'type':'string','enum':['morning','evening']}}),
 'ddl_outbox':('查询尚未发送的提醒',{}),
 'ddl_ack':('发送成功后保存真实平台回执，发送失败不可调用',{'id':{'type':'string'},'receipt':{'type':'string'}}),
 'ddl_status':('读取部署、数据、来源和提醒队列状态',{}),
 'ddl_snapshot':('生成数据库每日快照并清理超期副本，默认保留7天',{'retention':{'type':'integer'}}),
 'ddl_radar':('对配置的官方源做增量扫描，返回机会池抓取统计',{})}
REQUIRED={'ddl_normalize':['text'],'ddl_add':['item'],'ddl_change':['selector','operation'],'ddl_classify':['id','items','tags'],'ddl_adopt':['id'],'ddl_ack':['id','receipt']}
def dispatch_data(store,name,args):
    if name=='ddl_now':
        clock=now();monday=clock.date()-dt.timedelta(days=clock.weekday())
        return {'now':iso(clock),'timezone':'Asia/Shanghai','calendar_week_start':str(monday),'calendar_week_end':str(monday+dt.timedelta(days=6))}
    if name=='ddl_normalize':return {'deadline_at':normalize(args['text'],args.get('reference'))}
    if name=='ddl_add':return store.add(args['item'])
    if name=='ddl_list':
        rows=store.list(**args)
        if args.get('week'):
            monday=now().date()-dt.timedelta(days=now().weekday())
            return {'items':rows,'filters':args,'calendar_week_start':str(monday),'calendar_week_end':str(monday+dt.timedelta(days=6))}
        return {'items':rows,'filters':args}
    if name=='ddl_change':return store.change(**args)
    if name=='ddl_preferences':return {**store.prefs(**args),'updated':bool(args.get('updates'))}
    if name=='ddl_opportunities':return store.opportunities(**args)
    if name=='ddl_classify':return store.classify_opportunity(**args)
    if name=='ddl_adopt':return store.adopt(**args)
    if name=='ddl_adopt_preview':
        node=store.adopt_preview(args['id']);node['action']='confirm'
        with store.db:store.db.execute('INSERT OR REPLACE INTO contexts VALUES(?,?,?)',(store.owner,json.dumps([args['id']]),iso(now())))
        return node
    if name=='ddl_push':return store.push_now(args.get('selector'))
    if name=='ddl_summary':return store.summary(**args)
    if name=='ddl_outbox':return store.outbox()
    if name=='ddl_ack':return store.ack(**args)
    if name=='ddl_status':return store.status()
    if name=='ddl_snapshot':return store.snapshot(**args)
    if name=='ddl_radar':
        from radar import scan
        return scan(store)
    raise ValueError('未知工具')
def dispatch(store,name,args):
    result=dispatch_data(store,name,args)
    if name in ['ddl_add','ddl_list','ddl_change','ddl_preferences','ddl_summary','ddl_adopt','ddl_adopt_preview','ddl_push','ddl_status','ddl_radar'] or (name=='ddl_opportunities' and not args.get('unparsed')):
        from cards import render,plain
        card=render(name,result)
        if card:
            if not isinstance(result,dict):result={'items':result}
            result={**result,'reply_markdown':card,'reply_plain':plain(card)}
    return result

def error_result(error):
    from cards import error_card,plain
    text=error_card()
    return {'error':str(error),'reply_markdown':text,'reply_plain':plain(text)}
def serve(store):
    for line in sys.stdin:
        try:
            req=json.loads(line);id=req.get('id');method=req.get('method');params=req.get('params',{})
            if id is None:continue
            if method=='initialize':result={'protocolVersion':params.get('protocolVersion','2024-11-05'),'capabilities':{'tools':{}},'serverInfo':{'name':'ddl-manager','version':'1.0.0'}}
            elif method=='ping':result={}
            elif method=='tools/list':result={'tools':[{'name':k,'description':v[0],'inputSchema':{'type':'object','properties':v[1],'required':REQUIRED.get(k,[]),'additionalProperties':False}} for k,v in TOOLS.items()]}
            elif method=='tools/call':
                try: value=dispatch(store,params['name'],params.get('arguments',{}));result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}]}
                except Exception as e:result={'isError':True,'content':[{'type':'text','text':json.dumps(error_result(e),ensure_ascii=False)}]}
            else:raise ValueError('method not supported')
            out={'jsonrpc':'2.0','id':id,'result':result}
        except Exception as e:out={'jsonrpc':'2.0','id':req.get('id') if 'req' in locals() else None,'error':{'code':-32602,'message':str(e)}}
        print(json.dumps(out,ensure_ascii=False),flush=True)
def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf8');sys.stdin.reconfigure(encoding='utf8')
    p=argparse.ArgumentParser();p.add_argument('--db');p.add_argument('--owner',default=OWNER);p.add_argument('command');p.add_argument('--json');p.add_argument('--file');args=p.parse_args()
    store=Store(args.db,args.owner)
    if args.command=='serve':serve(store);return
    payload=json.loads(pathlib.Path(args.file).read_text(encoding='utf8')) if args.file else json.loads(args.json) if args.json else {}
    if args.command=='tick':value=store.queue()
    else:value=dispatch(store,'ddl_'+{'status':'status','snapshot':'snapshot','add':'add','list':'list','change':'change','preferences':'preferences','opportunities':'opportunities','classify':'classify','adopt':'adopt','adopt-preview':'adopt_preview','push':'push','summary':'summary','normalize':'normalize','outbox':'outbox','ack':'ack','radar':'radar','now':'now'}.get(args.command,args.command),payload)
    print(json.dumps(value,ensure_ascii=False,indent=2))
if __name__=='__main__':
    try:main()
    except Exception as e:print(json.dumps(error_result(e),ensure_ascii=False));sys.exit(1)
