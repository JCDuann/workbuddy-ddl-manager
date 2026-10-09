"""Portable WorkBuddy deployment. Never installs Codex or an external scheduler."""
import argparse,datetime as dt,hashlib,json,pathlib,re,shutil,sqlite3,subprocess,sys,uuid
from contextlib import closing
ROOT=pathlib.Path(__file__).resolve().parent
TZ=dt.timezone(dt.timedelta(hours=8))
def read(path,default=None):return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8');temp.replace(path)
def verify():
    manifest=read(ROOT/'manifest.json')
    for name,digest in manifest['files'].items():
        path=ROOT/name
        if not path.resolve().is_relative_to(ROOT.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('安装包校验失败：'+name)
def account(home):
    claw=read(home/'settings.json',{}).get('claw',{})
    users=claw.get('users',{})
    if len(users)==1:return next(iter(users))
    if not users and claw.get('legacyOwnerUid'):return claw['legacyOwnerUid']
    return None
def native_tasks(home,workspace,definitions,owner,backup):
    path=home/'workbuddy.db'
    if not owner or not path.exists():return {'registered':False,'reason':'尚未识别 WorkBuddy 登录账号；先登录并连接QQ，再退出WorkBuddy重跑setup.cmd。'}
    db=sqlite3.connect(path,timeout=15)
    required={'id','name','prompt','status','schedule_type','next_run_at','cwds','rrule','created_at','updated_at','skills_json','permission_mode','owner_user_id','owner_status','owner_source','workspace_scope','deleted_at'}
    columns={r[1] for r in db.execute('PRAGMA table_info(automations)')}
    if not required<=columns:
        db.close();return {'registered':False,'reason':'该 WorkBuddy 版本的定时任务结构不同；请按原生定时任务.md在界面创建。'}
    with closing(sqlite3.connect(backup/'workbuddy-before-tasks.sqlite3')) as dest:db.backup(dest)
    clock=dt.datetime.now(TZ);stamp=int(clock.timestamp()*1000);registered=[]
    try:
        with db:
            for task in definitions:
                existing=db.execute('SELECT owner_user_id FROM automations WHERE id=?',(task['id'],)).fetchone()
                if existing and existing[0]!=owner:raise ValueError('同名DDL定时任务属于另一账号，请在界面处理后重试。')
                if task['id'].endswith('morning'):next_at=clock.replace(hour=8,minute=0,second=0,microsecond=0)
                elif task['id'].endswith('evening'):next_at=clock.replace(hour=21,minute=30,second=0,microsecond=0)
                else:next_at=clock+dt.timedelta(hours=4)
                if next_at<=clock:next_at+=dt.timedelta(days=1)
                db.execute("""INSERT INTO automations(id,name,prompt,status,schedule_type,next_run_at,cwds,rrule,created_at,updated_at,skills_json,permission_mode,owner_user_id,owner_status,owner_source,workspace_scope)
                  VALUES(?,?,?,'ACTIVE','recurring',?,?,?, ?,?,'[]','fullAccess',?,'confirmed','created','workspace')
                  ON CONFLICT(id) DO UPDATE SET name=excluded.name,prompt=excluded.prompt,rrule=excluded.rrule,cwds=excluded.cwds,status='ACTIVE',deleted_at=NULL,updated_at=excluded.updated_at""",
                  (task['id'],task['name'],task['prompt'],int(next_at.timestamp()*1000),json.dumps([workspace.as_posix()]),task['rrule'],stamp,stamp,owner))
                registered.append(task['name'])
    finally:db.close()
    return {'registered':True,'tasks':registered,'runtime_execution_verified':False}
def install(workspace,home,python,node,fresh=False,register=False):
    verify();workspace=workspace.resolve();home=home.resolve();target=workspace/'ddl-manager'
    if target.resolve()==(ROOT/'app').resolve():raise ValueError('安装工作目录不能是安装包app目录。')
    if not pathlib.Path(python).is_file() or not pathlib.Path(node).is_file():raise ValueError('需要可用的 Python 和 Node。请先在 WorkBuddy 初始化本地运行环境。')
    subprocess.run([python,'-c','import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'],check=True,capture_output=True)
    workspace.mkdir(parents=True,exist_ok=True);target.mkdir(exist_ok=True)
    backup=workspace/'.ddl-deployment-backups'/dt.datetime.now(TZ).strftime('%Y%m%d-%H%M%S-%f');backup.mkdir(parents=True)
    existing=read(target/'deployment.json',{})
    database=target/'data'/'ddl.sqlite3';owner=existing.get('owner_id')
    if database.exists() and not owner:
        with closing(sqlite3.connect(database)) as db:owners=[r[0] for r in db.execute('SELECT DISTINCT owner_id FROM ddl_items')]
        if len(owners)>1:raise ValueError('已有数据库包含多个用户，请分别迁移，不能自动选择。')
        owner=owners[0] if owners else 'ddl:local'
    use_backup=not fresh and not database.exists() and (ROOT/'personal-backup'/'ddl.sqlite3').exists()
    if not owner:owner=read(ROOT/'personal-backup'/'profile.json',{}).get('data_owner','ddl:local') if use_backup else 'ddl:local'
    replacements={'@@WORKSPACE@@':workspace.as_posix(),'@@PYTHON@@':pathlib.Path(python).as_posix(),'@@OWNER@@':owner}
    for source in (ROOT/'app').iterdir():
        if source.is_dir():
            if source.name=='runtime':shutil.copytree(source,target/source.name,dirs_exist_ok=True)
            continue
        old=target/source.name
        if old.exists():shutil.copy2(old,backup/source.name)
        content=source.read_text(encoding='utf8')
        for key,value in replacements.items():content=content.replace(key,value)
        old.write_text(content,encoding='utf8')
    (target/'data').mkdir(exist_ok=True)
    if use_backup:
        with closing(sqlite3.connect('file:'+(ROOT/'personal-backup'/'ddl.sqlite3').as_posix()+'?mode=ro',uri=True)) as src:
            with closing(sqlite3.connect(database)) as dest:src.backup(dest)
    config_path=workspace/'.mcp.json';config=read(config_path,{})
    for name,script in [('ddl-manager','ddl.py'),('qq-bot-connect','qq_message.py')]:
        previous=config.get('mcpServers',{}).get(name)
        if previous and previous.get('args') and not any(str(target).replace('\\','/') in str(arg).replace('\\','/') for arg in previous['args']):raise ValueError('同名MCP服务指向其他目录，拒绝覆盖：'+name)
        config.setdefault('mcpServers',{})[name]={'command':str(python),'args':[str(target/script),'serve'],'env':{'PYTHONUTF8':'1','DDL_OWNER':owner,'DDL_DB':str(database)}}
    if config_path.exists():shutil.copy2(config_path,backup/'mcp-before.json')
    save(config_path,config)
    record={'version':'portable-2026.10.08','owner_id':owner,'workspace':str(workspace),'python':str(python),'node':str(node),'workbuddy_home':str(home),'database':str(database),'imported_personal_backup':use_backup,'backup':str(backup)}
    save(target/'deployment.json',record)
    if not (target/'delivery.json').exists():save(target/'delivery.json',{'enabled':False,'provider':'workbuddy-native-qq','command':[str(python),str(target/'qq_skill_sender.py')],'status':'awaiting_new_machine_qq_verification'})
    skill=home/'skills'/'qq-bot-connect';skill.mkdir(parents=True,exist_ok=True)
    content=(ROOT/'app'/'qq-bot-connect'/'SKILL.md').read_text(encoding='utf8')
    for key,value in replacements.items():content=content.replace(key,value)
    (skill/'SKILL.md').write_text(content,encoding='utf8')
    (target/'qq-bot-connect').mkdir(exist_ok=True);(target/'qq-bot-connect'/'SKILL.md').write_text(content,encoding='utf8')
    rules=workspace/'CODEBUDDY.md';content=rules.read_text(encoding='utf8') if rules.exists() else ''
    marker='<!-- ddl-manager-portable-v1 -->'
    block='处理DDL、通知、截图、校园机会前先读取 ddl-manager/AGENT.md 与 ddl-manager/回复格式规范.md，查询真实数据库后回复。普通聊天保留普通助手能力。使用18类固定格式和Markdown卡片，工具返回reply_markdown时按规则回复；不能渲染时使用reply_plain。严格区分已保存、待确认、入队和已发送，发送成功必须有平台回执。定时任务使用WorkBuddy内置调度，不创建外部服务。QQ发送使用qq-bot-connect技能和同名MCP；连接信息以本机配置为准。'
    pattern=re.compile(re.escape(marker)+r'.*?<!-- /ddl-manager-portable-v1 -->',re.S)
    section=marker+'\n'+block+'\n<!-- /ddl-manager-portable-v1 -->'
    if rules.exists():shutil.copy2(rules,backup/'CODEBUDDY-before.md')
    rules.write_text(pattern.sub(lambda _:section,content) if marker in content else content+'\n'+section+'\n',encoding='utf8')
    subprocess.run([python,str(target/'ddl.py'),'status'],check=True,capture_output=True,encoding='utf8')
    definitions=read(target/'workbuddy-tasks.json',[])
    task_doc='# WorkBuddy 原生定时任务\n\n工作目录：`'+workspace.as_posix()+'`。在WorkBuddy定时任务页创建下列3项；使用本机北京时间。自动注册成功时不要重复创建。\n\n'
    for task in definitions:task_doc+='## '+task['name']+'\n\n周期：'+('每天08:00' if task['id'].endswith('morning') else '每天21:30' if task['id'].endswith('evening') else '每4小时')+'\n\n提示词：\n\n'+task['prompt']+'\n\n'
    (target/'原生定时任务.md').write_text(task_doc,encoding='utf8')
    tasks=native_tasks(home,workspace,definitions,account(home),backup) if register else {'registered':False,'reason':'WorkBuddy正在运行；退出后重跑setup.cmd，或按原生定时任务.md在界面创建。'}
    record['native_tasks']=tasks;save(target/'deployment.json',record)
    (ROOT/'installed.json').write_text(json.dumps({'deployment':str(target),'python':str(python),'node':str(node)},ensure_ascii=False,indent=2),encoding='utf8')
    return record
def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',required=True);p.add_argument('--workbuddy-home',required=True);p.add_argument('--python',required=True);p.add_argument('--node',required=True);p.add_argument('--fresh',action='store_true');p.add_argument('--register-tasks',action='store_true');a=p.parse_args()
    print(json.dumps(install(pathlib.Path(a.workspace),pathlib.Path(a.workbuddy_home),a.python,a.node,a.fresh,a.register_tasks),ensure_ascii=False,indent=2))
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8')
    try:main()
    except Exception as error:print('部署未完成：'+str(error));sys.exit(1)
