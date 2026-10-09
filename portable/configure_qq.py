"""Configure only the new computer's local QQ connection; never logs credentials."""
import argparse,importlib,json,pathlib,re,subprocess,sys
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def find_openid(home):
    files=sorted((home/'logs').rglob('*.log'),key=lambda p:p.stat().st_mtime,reverse=True)[:20]
    targets=set()
    for path in files:
        with path.open('rb') as stream:
            stream.seek(max(0,path.stat().st_size-1024*1024));text=stream.read().decode('utf8',errors='replace')
        for line in text.splitlines():
            if 'C2C message received' not in line:continue
            targets.update(re.findall(r'"userOpenId"\s*:\s*"([A-Fa-f0-9]{32})"',line))
    if len(targets)!=1:raise ValueError('不能唯一确认本机QQ私聊目标。请先给已连接机器人发一句话；如仍有多个目标，在WorkBuddy核实本机入站userOpenId后使用 --openid 指定。')
    return next(iter(targets))
def configure(target,openid=None,test=False):
    deployment=json.loads((target/'deployment.json').read_text(encoding='utf8'));home=pathlib.Path(deployment['workbuddy_home'])
    settings=json.loads((home/'settings.json').read_text(encoding='utf-8-sig'))
    users=settings.get('claw',{}).get('users',{})
    entries=[u.get('channels',{}).get('qq',{}) for u in users.values() if u.get('channels',{}).get('qq',{}).get('enabled')]
    if len(entries)!=1:raise ValueError('需要在WorkBuddy连接一个QQ机器人；多账号时请单独部署并明确账号。')
    channel=entries[0];app=str(channel.get('appId',''))
    if not app.isdigit():raise ValueError('WorkBuddy尚未记录有效QQ机器人AppID。')
    openid=openid or find_openid(home)
    if not re.fullmatch(r'[A-Fa-f0-9]{32}',openid):raise ValueError('目标必须是已核实的32位QQ私聊OpenID，不能使用会话UUID或消息ID。')
    config={'provider':'workbuddy-native-qq','owner_id':deployment['owner_id'],'app_id':app,'openid':openid,'credential_file':'data/qq-credentials.dpapi','node':deployment['node'],'sdk_script':'qq_send.mjs','verified':False}
    save(target/'qq_push.json',config)
    delivery={'enabled':False,'provider':'workbuddy-native-qq','command':[deployment['python'],str(target/'qq_skill_sender.py')],'status':'awaiting_local_platform_receipt'}
    save(target/'delivery.json',delivery)
    sys.path.insert(0,str(target));qq=importlib.import_module('qq_message')
    secret=channel.get('appSecret')
    if isinstance(secret,str) and secret:
        qq.store_credentials({'appId':app,'appSecret':secret})
    else:
        # WorkBuddy encrypted envelopes remain within WorkBuddy; obtain fresh permission through its connector SDK.
        print('请用手机QQ扫描即将打开的本机授权二维码，选择WorkBuddy当前使用的机器人。',flush=True)
        image=target/'data'/'qq-authorize.png'
        process=subprocess.Popen([deployment['node'],str(target/'qq_bind.mjs'),str(image)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        shown=False;authorized=False
        try:
            for line in process.stdout:
                try:state=json.loads(line)
                except ValueError:continue
                if state.get('status')=='awaiting_scan' and not shown:
                    import os
                    os.startfile(str(image));shown=True
                if state.get('status')=='authorized':authorized=True
            process.wait(timeout=15)
        finally:
            if process.poll() is None:process.terminate()
        if not authorized:raise ValueError('本机QQ授权尚未完成，请重新运行qq-setup.cmd。')
    if not test:return {'configured':True,'delivery_enabled':False,'platform_receipt_verified':False}
    result=qq.message({'action':'send','channel':'qqbot','message':'### ✅ DDL管家部署验证\n\n这是新电脑发出的测试卡片。\n\n| 项目 | 状态 |\n| :--- | :--- |\n| 主动发送 | 请确认收到此消息 |\n| 显示格式 | Markdown表格 |','idempotency_key':'deployment-test-'+__import__('uuid').uuid4().hex})
    if result.get('success') is not True or not result.get('message_id'):raise ValueError('未取得平台发送成功回执，定时推送保持关闭。')
    config.update(verified=True,verification_message_id=result['message_id']);save(target/'qq_push.json',config)
    delivery.update(enabled=True,status='new_machine_platform_receipt_verified');save(target/'delivery.json',delivery)
    return {'configured':True,'delivery_enabled':True,'platform_receipt_verified':True,'test_received_requires_user_check':True}
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8');p=argparse.ArgumentParser();p.add_argument('--deployment',required=True);p.add_argument('--openid');p.add_argument('--test',action='store_true');a=p.parse_args()
    try:print(json.dumps(configure(pathlib.Path(a.deployment),a.openid,a.test),ensure_ascii=False))
    except Exception as error:
        print('QQ设置未完成：'+str(error));sys.exit(1)
