"""A real, owner-bound QQ message MCP tool for WorkBuddy; Windows DPAPI credential store."""
import base64,ctypes,hashlib,json,os,pathlib,sqlite3,subprocess,sys,uuid
from ctypes import wintypes
ROOT=pathlib.Path(__file__).resolve().parent
from ddl import OWNER
class Blob(ctypes.Structure):_fields_=[('length',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
def protect(data,decrypt=False):
    if os.name!='nt':raise RuntimeError('此凭据仓库需要Windows当前用户身份')
    raw=ctypes.create_string_buffer(data);incoming=Blob(len(data),ctypes.cast(raw,ctypes.POINTER(ctypes.c_ubyte)));outgoing=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    if decrypt:
        fun=crypt.CryptUnprotectData;fun.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        ok=fun(ctypes.byref(incoming),None,None,None,None,1,ctypes.byref(outgoing))
    else:
        fun=crypt.CryptProtectData;fun.argtypes=[ctypes.POINTER(Blob),wintypes.LPCWSTR,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        ok=fun(ctypes.byref(incoming),'DDL QQ bot credentials',None,None,None,1,ctypes.byref(outgoing))
    if not ok:raise ctypes.WinError(ctypes.get_last_error())
    try:return ctypes.string_at(outgoing.data,outgoing.length)
    finally:kernel.LocalFree(ctypes.cast(outgoing.data,ctypes.c_void_p))
def config():
    p=ROOT/'qq_push.json'
    if not p.exists():raise ValueError('尚未配置已绑定的QQ发送目标')
    c=json.loads(p.read_text(encoding='utf-8-sig'))
    if c.get('provider')!='workbuddy-native-qq' or c.get('owner_id')!=OWNER:raise ValueError('QQ发送配置与本会话不匹配')
    if not c.get('openid') or not c.get('app_id'):raise ValueError('缺少实际QQ机器人或私聊OpenID')
    return c
def credentials():
    c=config();p=ROOT/c['credential_file']
    if not p.exists():raise ValueError('发送工具已安装，尚需手机QQ授权现有机器人')
    secret=json.loads(protect(p.read_bytes(),decrypt=True))
    if secret.get('appId')!=c['app_id']:raise ValueError('凭据属于另一个机器人，拒绝向错误账号发送')
    return secret
def store_credentials(value):
    c=config()
    if str(value.get('appId'))!=c['app_id']:raise ValueError('授权的机器人不是现有绑定账号，请选择AppID '+c['app_id'])
    if not isinstance(value.get('appSecret'),str) or not value['appSecret']:raise ValueError('未获得有效授权凭据')
    p=ROOT/c['credential_file'];p.parent.mkdir(exist_ok=True)
    encrypted=protect(json.dumps({'appId':str(value['appId']),'appSecret':value['appSecret']}).encode('utf8'))
    temporary=p.with_suffix('.tmp');temporary.write_bytes(encrypted)
    if os.name=='nt':
        user=subprocess.check_output(['whoami'],text=True).strip()
        locked=subprocess.run(['icacls',str(temporary),'/inheritance:r','/grant:r',user+':F','SYSTEM:F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        if locked.returncode:raise RuntimeError('无法限制凭据文件访问权限')
    temporary.replace(p)
    return {'stored':True,'app_id':c['app_id'],'protection':'Windows DPAPI current user','ready_for_test':True}
def status():
    try:
        c=config();p=ROOT/c['credential_file']
        return {'tool':'message','installed':True,'owner_id':OWNER,'app_id':c['app_id'],'target':'qqbot:c2c:'+c['openid'],
            'credentials_authorized':p.exists(),'proactive_send_verified':bool(c.get('verified')),'mode':'native QQ SDK, outbound only'}
    except ValueError as error:return {'tool':'message','installed':True,'configured':False,'error':str(error)}
def message(args):
    c=config();target='qqbot:c2c:'+c['openid']
    if args.get('action')!='send' or args.get('channel')!='qqbot':raise ValueError('此工具只支持 action=send、channel=qqbot')
    if args.get('target',target)!=target:raise ValueError('发送目标不是本会话已核实的QQ私聊，拒绝发送')
    text=args.get('message')
    if not isinstance(text,str) or not text.strip() or len(text)>4000:raise ValueError('消息应为1–4000字')
    creds=credentials();key=args.get('idempotency_key') or 'manual_'+uuid.uuid4().hex
    db=sqlite3.connect(ROOT/'data'/'qq_receipts.sqlite3',timeout=45)
    db.execute('CREATE TABLE IF NOT EXISTS native_deliveries(id TEXT PRIMARY KEY,hash TEXT,status TEXT,result TEXT)')
    digest=hashlib.sha256(text.encode()).hexdigest()
    try:
        db.execute('BEGIN IMMEDIATE')
        existing=db.execute('SELECT * FROM native_deliveries WHERE id=?',(key,)).fetchone()
        if existing:
            if existing[1]!=digest:raise ValueError('去重ID已用于另一条消息')
            if existing[2]=='sent':return {**json.loads(existing[3]),'cached':True}
            if existing[2] in ['sending','unknown']:raise ValueError('上一发送的结果不确定，已阻止重复发送；请先核实QQ是否收到')
        db.execute('INSERT OR REPLACE INTO native_deliveries VALUES(?,?,?,NULL)',(key,digest,'sending'));db.commit()
        from cards import plain
        payload={**creds,'targetId':c['openid'],'message':text,'plainMessage':plain(text),'markdownSupport':True}
        try:
            run=subprocess.run([c['node'],str(ROOT/c['sdk_script'])],input=json.dumps(payload,ensure_ascii=False),text=True,capture_output=True,encoding='utf8',timeout=35,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:r=json.loads(run.stdout)
            except ValueError:raise RuntimeError('发送进程未返回有效JSON')
            if r.get('success') is not True or not r.get('message_id'):
                with db:db.execute('UPDATE native_deliveries SET status=?,result=? WHERE id=?',('unknown' if r.get('uncertain') else 'failed',json.dumps(r,ensure_ascii=False),key))
                raise RuntimeError(r.get('error','QQ未返回真实发送回执'))
            with db:db.execute("UPDATE native_deliveries SET status='sent',result=? WHERE id=?",(json.dumps(r,ensure_ascii=False),key))
            return r
        except (subprocess.TimeoutExpired,RuntimeError):
            with db:db.execute("UPDATE native_deliveries SET status='unknown' WHERE id=? AND status='sending'",(key,))
            raise
    finally:db.close()
TOOLS=[
 {'name':'qq_connection_status','description':'查看本会话已核实的QQ私聊目标及发送授权状态；不返回密钥',
  'inputSchema':{'type':'object','properties':{},'additionalProperties':False}},
 {'name':'message','description':'通过QQ官方SDK实际向本会话已绑定的用户私聊主动发送消息。只允许已核实目标，返回真实QQ平台消息回执。无授权时明确报错。',
  'inputSchema':{'type':'object','properties':{'action':{'enum':['send']},'channel':{'enum':['qqbot']},'target':{'type':'string'},'message':{'type':'string'},'idempotency_key':{'type':'string'}},'required':['action','channel','message'],'additionalProperties':False}}]
def serve():
    for line in sys.stdin:
        request={}
        try:
            request=json.loads(line);id=request.get('id');method=request.get('method');params=request.get('params',{})
            if id is None:continue
            if method=='initialize':r={'protocolVersion':params.get('protocolVersion','2024-11-05'),'capabilities':{'tools':{}},'serverInfo':{'name':'qq-bot-connect','version':'1.0.0'}}
            elif method=='tools/list':r={'tools':TOOLS}
            elif method=='ping':r={}
            elif method=='tools/call':
                try:
                    if params['name']=='message':value=message(params.get('arguments',{}))
                    elif params['name']=='qq_connection_status':value=status()
                    else:raise ValueError('未知QQ工具')
                    r={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}]}
                except Exception as error:r={'isError':True,'content':[{'type':'text','text':str(error)}]}
            else:raise ValueError('未知MCP方法')
            output={'jsonrpc':'2.0','id':id,'result':r}
        except Exception as error:output={'jsonrpc':'2.0','id':request.get('id'),'error':{'code':-32602,'message':str(error)}}
        print(json.dumps(output,ensure_ascii=False),flush=True)
def main():
    sys.stdout.reconfigure(encoding='utf8');sys.stdin.reconfigure(encoding='utf8')
    command=sys.argv[1] if len(sys.argv)>1 else 'status'
    if command=='serve':serve();return
    if command=='store':result=store_credentials(json.load(sys.stdin))
    elif command=='status':result=status()
    elif command=='send':result=message(json.load(sys.stdin))
    else:raise ValueError('未知命令')
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':
    try:main()
    except Exception as error:print(json.dumps({'success':False,'error':str(error)},ensure_ascii=False));sys.exit(1)
