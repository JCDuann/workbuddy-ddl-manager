"""Official-source incremental reader; web content is data, never instructions."""
import datetime as dt, hashlib, html, json, pathlib, re, time, urllib.parse, urllib.request
from html.parser import HTMLParser
from ddl import iso,now,ROOT

SOURCES=[
 {'id':'cqu','url':'https://www.cqu.edu.cn/tzgg.htm','allow':['www.cqu.edu.cn'],'pattern':r'/info/\d+/\d+\.htm$'},
 {'id':'sxic','url':'https://sxic.cqu.edu.cn/content/news-list?menuIds=64,66&params=33&singlePage=1','allow':['sxic.cqu.edu.cn'],'pattern':r'/content/(?:news-detail|detail)'},
]
MAX_BYTES=3_000_000
class Page(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.text=[];self.blocked=0;self.current=None;self.label=[]
    def handle_starttag(self,tag,attrs):
        if tag in ['script','style','noscript']:self.blocked+=1
        if tag=='a':self.current=dict(attrs).get('href');self.label=[]
    def handle_endtag(self,tag):
        if tag in ['script','style','noscript']:self.blocked=max(0,self.blocked-1)
        if tag=='a' and self.current:self.links.append((self.current,' '.join(self.label).strip()));self.current=None
        if tag in ['p','div','li','br']:self.text.append('\n')
    def handle_data(self,data):
        if self.blocked:return
        if self.current:self.label.append(data.strip())
        self.text.append(data)
def fetch(url,allowed):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in allowed:raise ValueError('链接不属于已配置的官方来源')
    request=urllib.request.Request(url,headers={'User-Agent':'DDLManager/1.0 (campus notice reader)','Accept':'text/html,application/json'})
    with urllib.request.urlopen(request,timeout=18) as response:
        if urllib.parse.urlsplit(response.url).hostname not in allowed:raise ValueError('重定向超出官方来源')
        data=response.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:raise ValueError('网页内容超出限制')
        charset=response.headers.get_content_charset()
    if not charset:
        match=re.search(rb'charset\s*=\s*["\x27]?([\w-]+)',data[:8000],re.I)
        charset=match[1].decode('ascii') if match else 'utf8'
    text=data.decode(charset,errors='replace');page=Page();page.feed(text)
    return page,text
def scan(store):
    result=[]
    for source in SOURCES:
        stamp=iso(now());entry={'id':source['id'],'new':0,'errors':[]}
        try:
            page,raw=fetch(source['url'],source['allow']);found=[];seen=set()
            for href,title in page.links:
                url=urllib.parse.urljoin(source['url'],href).split('#')[0]
                if url in seen or urllib.parse.urlsplit(url).hostname not in source['allow']:continue
                if not re.search(source['pattern'],urllib.parse.urlsplit(url).path):continue
                if not title:continue
                if title.strip() in ['组织架构','中心简介','中心领导','帮助中心','交流合作','关于我们']:continue
                seen.add(url);found.append((url,title))
            if not found:raise ValueError('未发现通知链接；网站可能使用动态接口，需要适配，不能视为空列表成功')
            for url,title in found[:15]:
                if store.db.execute('SELECT 1 FROM opportunities WHERE url=?',(url,)).fetchone():continue
                try:
                    detail,_=fetch(url,source['allow']); text=re.sub(r'[ \t]+',' ',' '.join(detail.text));text=re.sub(r'\n\s*\n+','\n',text).strip()
                    date=re.search(r'(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})',text)
                    published=None
                    if date:
                        try:published=dt.date(*map(int,date.groups())).isoformat()
                        except ValueError:pass
                    oid='opp_'+hashlib.sha256(url.encode()).hexdigest()[:12]
                    with store.db:store.db.execute('INSERT OR IGNORE INTO opportunities(id,source_id,url,title,published_at,text,discovered_at) VALUES(?,?,?,?,?,?,?)',
                        (oid,source['id'],url,title,published,text[:24000],stamp))
                    entry['new']+=1
                    time.sleep(.3)
                except Exception as error:entry['errors'].append({'url':url,'error':str(error)[:200]})
            error=json.dumps(entry['errors'],ensure_ascii=False) if entry['errors'] else None
            with store.db:store.db.execute('INSERT INTO sources VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET url=excluded.url,last_scan=excluded.last_scan,last_success=excluded.last_success,error=excluded.error',
                (source['id'],source['url'],stamp,stamp,error))
        except Exception as error:
            entry['errors'].append({'error':str(error)[:200]})
            with store.db:store.db.execute('INSERT INTO sources(id,url,last_scan,error) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET last_scan=excluded.last_scan,error=excluded.error',
                (source['id'],source['url'],stamp,str(error)[:500]))
        result.append(entry)
    return result
if __name__=='__main__':
    from ddl import Store
    print(json.dumps(scan(Store()),ensure_ascii=False,indent=2))
