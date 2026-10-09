"""Isolated deployment tests; no writes to the real WorkBuddy workspace/account."""
import hashlib,json,pathlib,shutil,sqlite3,sys,tempfile,unittest
from contextlib import closing
from unittest.mock import patch
import deploy
class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.temp.name)
        self.bundle=self.root/'解压目录 with spaces';shutil.copytree(deploy.ROOT,self.bundle,ignore=shutil.ignore_patterns('__pycache__','installed.json'))
        self.home=self.root/'新用户' /'.workbuddy';self.home.mkdir(parents=True)
        self.workspace=self.root/'新用户'/'学习助手 with spaces'/'Claw'
        import os, subprocess
        fixture=self.bundle/'personal-backup';fixture.mkdir(exist_ok=True)
        subprocess.run([sys.executable,str(self.bundle/'app'/'ddl.py'),'status'],check=True,capture_output=True,env={**os.environ,'DDL_DB':str(fixture/'ddl.sqlite3'),'DDL_OWNER':'ddl:local'})
        deploy.save(fixture/'profile.json',{'data_owner':'ddl:local'})
        self.patch=patch.object(deploy,'ROOT',self.bundle);self.patch.start()
        # Supplied at test time; never rely on the old Windows username in portable code.
        import os
        self.node=pathlib.Path(os.environ['DDL_TEST_NODE'])
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def run_install(self,**kwargs):return deploy.install(self.workspace,self.home,sys.executable,str(self.node),**kwargs)
    def test_relocated_fresh_install_and_repeat_preserve_database_and_rules(self):
        self.workspace.mkdir(parents=True);(self.workspace/'CODEBUDDY.md').write_text('用户原有规则\n',encoding='utf8')
        (self.workspace/'.mcp.json').write_text(json.dumps({'mcpServers':{'existing-tool':{'command':'other'}}}),encoding='utf8')
        result=self.run_install(fresh=True)
        target=self.workspace/'ddl-manager';config=deploy.read(self.workspace/'.mcp.json')
        self.assertIn('existing-tool',config['mcpServers']);self.assertIn(str(target/'ddl.py'),config['mcpServers']['ddl-manager']['args'])
        self.assertIn(self.workspace.as_posix(),(target/'AGENT.md').read_text(encoding='utf8'))
        self.assertNotIn('@@',(target/'AGENT.md').read_text(encoding='utf8'))
        self.assertFalse(deploy.read(target/'delivery.json')['enabled'])
        with closing(sqlite3.connect(target/'data'/'ddl.sqlite3')) as db:
            db.execute("INSERT INTO preferences VALUES('ddl:local','{\"morning\":\"09:00\"}')");db.commit()
        self.run_install(fresh=True)
        with closing(sqlite3.connect(target/'data'/'ddl.sqlite3')) as db:self.assertEqual(json.loads(db.execute('SELECT json FROM preferences').fetchone()[0])['morning'],'09:00')
        content=(self.workspace/'CODEBUDDY.md').read_text(encoding='utf8')
        self.assertIn('用户原有规则',content);self.assertEqual(content.count('<!-- ddl-manager-portable-v1 -->'),1)
    def test_personal_backup_imported_without_old_pending_messages(self):
        result=self.run_install()
        self.assertTrue(result['imported_personal_backup'])
        target=self.workspace/'ddl-manager'
        with closing(sqlite3.connect(target/'data'/'ddl.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM outbox').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM contexts').fetchone()[0],0)
        self.assertFalse((target/'qq_push.json').exists())
    def test_native_tasks_preserve_other_rows_and_repeat_is_idempotent(self):
        deploy.save(self.home/'settings.json',{'claw':{'users':{'new-workbuddy-user':{}}}})
        with closing(sqlite3.connect(self.home/'workbuddy.db')) as db:
            db.execute('CREATE TABLE automations(id TEXT PRIMARY KEY,name TEXT,prompt TEXT,status TEXT,schedule_type TEXT,next_run_at INTEGER,cwds TEXT,rrule TEXT,created_at INTEGER,updated_at INTEGER,skills_json TEXT,permission_mode TEXT,owner_user_id TEXT,owner_status TEXT,owner_source TEXT,workspace_scope TEXT,deleted_at INTEGER)')
            db.execute("INSERT INTO automations(id,status,owner_user_id) VALUES('unrelated','PAUSED','another-account')")
            db.commit()
        result=self.run_install(fresh=True,register=True)
        self.assertTrue(result['native_tasks']['registered']);self.run_install(register=True)
        with closing(sqlite3.connect(self.home/'workbuddy.db')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM automations').fetchone()[0],4)
            self.assertEqual(db.execute("SELECT status FROM automations WHERE id='unrelated'").fetchone()[0],'PAUSED')
            self.assertEqual(db.execute("SELECT count(*) FROM automations WHERE owner_user_id='new-workbuddy-user'").fetchone()[0],3)
    def test_corruption_blocks_install_before_workspace_writes(self):
        with (self.bundle/'app'/'cards.py').open('a',encoding='utf8') as f:f.write('\n# altered\n')
        with self.assertRaises(ValueError):self.run_install(fresh=True)
        self.assertFalse(self.workspace.exists())
if __name__=='__main__':unittest.main()
