"""qq-bot-connect delivery adapter: native WorkBuddy MCP or an authorized Gateway."""
import json,os,pathlib,re,sqlite3,sys,urllib.parse,urllib.request
ROOT=pathlib.Path(__file__).resolve().parent
def receipt(value):
    if not isinstance(value,dict):return None
    if value.get('isError') or value.get('success') is False or value.get('ok') is False:return None
    for key in ['messageId','message_id','msg_id']:
        if isinstance(value.get(key),(str,int)) and str(value[key]):return str(value[key])
    for key in ['details','result','data','response']:
        nested=value.get(key)
        if isinstance(nested,dict):
            found=receipt(nested)
            if found:return found
    # Direct QQ API responses contain both id and timestamp; avoid confusing RPC IDs with message IDs.
    if value.get('id') and value.get('timestamp'):return str(value['id'])
    for block in value.get('content',[]):
        if isinstance(block,dict) and block.get('type')=='text':
            try:
                found=receipt(json.loads(block.get('text','')))
                if found:return found
            except (ValueError,TypeError):pass
    return None
def send(payload):
    config_path=ROOT/'qq_push.json'
    if not config_path.exists():raise ValueError('尚未配置用户实际运行的 qq-bot-connect Gateway 与 skill_config_path')
    cfg=json.loads(config_path.read_text(encoding='utf-8-sig'))
    if cfg.get('provider')=='workbuddy-native-qq':
        from qq_message import message
        return message({'action':'send','channel':'qqbot','message':payload['text'],'idempotency_key':payload['id']})
    url=cfg['gateway_url'].rstrip('/')
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme not in ['https','http'] or not parsed.hostname:raise ValueError('Gateway URL 无效')
    if parsed.scheme=='http' and parsed.hostname not in ['localhost','127.0.0.1','::1']:raise ValueError('远端 Gateway 必须使用 HTTPS')
    # The existing skill config is the target authority. Never substitute WorkBuddy UUIDs or a published example OpenID.
    skill=json.loads(pathlib.Path(cfg['skill_config_path']).read_text(encoding='utf-8-sig'))
    default=skill['default'];openid=default.get('openid','')
    if default.get('type')!='c2c' or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}',openid):raise ValueError('需要该机器人对应的真实私聊 OpenID')
    if not payload.get('id') or not isinstance(payload.get('text'),str):raise ValueError('缺少提醒ID或正文')
    token=os.getenv(cfg.get('gateway_token_env','OPENCLAW_GATEWAY_TOKEN'),'')
    if not token and cfg.get('gateway_config_path'):
        runtime=json.loads(pathlib.Path(cfg['gateway_config_path']).read_text(encoding='utf-8-sig'))
        token=runtime.get('gateway',{}).get('auth',{}).get('token','')
    if not isinstance(token,str) or not token:raise ValueError('既有 Gateway 的授权 token 不可用；不修改其权限配置')
    cache=sqlite3.connect(ROOT/'data'/'qq_receipts.sqlite3',timeout=30)
    cache.execute('CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, message_id TEXT NOT NULL)')
    cached=cache.execute('SELECT message_id FROM receipts WHERE id=?',(payload['id'],)).fetchone()
    if cached:cache.close();return {'success':True,'message_id':cached[0],'cached':True}
    target='qqbot:c2c:'+openid
    request_data={'tool':'message','args':{'action':'send','channel':'qqbot','target':target,'message':payload['text']},
        'sessionKey':cfg.get('session_key','main'),'idempotencyKey':payload['id']}
    headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','x-openclaw-message-channel':'qqbot','x-openclaw-message-to':target}
    if cfg.get('account_id'):headers['x-openclaw-account-id']=cfg['account_id'];request_data['args']['accountId']=cfg['account_id']
    req=urllib.request.Request(url+'/tools/invoke',data=json.dumps(request_data,ensure_ascii=False).encode('utf8'),headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=25) as response:
            data=json.load(response)
        if data.get('ok') is not True:raise RuntimeError('message 工具没有返回成功')
        message_id=receipt(data.get('result'))
        if not message_id:raise RuntimeError('未获得真实 QQ 消息回执；不能当作发送成功')
        with cache:cache.execute('INSERT OR IGNORE INTO receipts VALUES(?,?)',(payload['id'],message_id))
        return {'success':True,'message_id':message_id}
    finally:cache.close()
if __name__=='__main__':
    if sys.stdout is not None and hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf8');sys.stdin.reconfigure(encoding='utf8')
    try:print(json.dumps(send(json.load(sys.stdin)),ensure_ascii=False))
    except Exception as error:
        # Keep URLs, tokens, request bodies and platform exception payloads out of logs.
        code=getattr(error,'code',None)
        message='Gateway请求失败'+('，HTTP '+str(code) if code else '') if isinstance(error,urllib.error.URLError) else str(error)
        print(json.dumps({'success':False,'error':message},ensure_ascii=False));sys.exit(1)
