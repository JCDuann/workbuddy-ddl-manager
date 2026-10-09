import datetime as dt,json,pathlib,subprocess,tempfile,unittest
from unittest.mock import patch
from ddl import Store,normalize,TZ,iso,now
class FeatureTests(unittest.TestCase):
    """Coverage for the optimisation round: recurrence, catch-up, archive, grouped list, snapshot."""
    def setUp(self):self.store=Store(':memory:')
    def tearDown(self):self.store.close()
    def item(self,**kwargs):return {'title':'矩阵小组作业','deadline_at':'2026-10-14T23:59:00+08:00','confidence':.95,'source_type':'qq_text',**kwargs}
    def test_recurrence_validation_and_spawn(self):
        from ddl import normalize_recurrence,next_occurrence
        self.assertEqual(normalize_recurrence('weekly'),'weekly');self.assertEqual(normalize_recurrence('daily'),'daily')
        self.assertIsNone(normalize_recurrence(None));self.assertIsNone(normalize_recurrence(''))
        with self.assertRaises(ValueError):normalize_recurrence('随时')
        self.assertEqual(next_occurrence(dt.datetime(2027,1,31,23,59,tzinfo=TZ),'monthly').isoformat(),'2027-02-28T23:59:00+08:00')
        self.assertEqual(next_occurrence(dt.datetime(2027,3,31,23,59,tzinfo=TZ),'monthly').isoformat(),'2027-04-30T23:59:00+08:00')
        self.assertEqual(next_occurrence(dt.datetime(2027,12,15,23,59,tzinfo=TZ),'monthly').isoformat(),'2028-01-15T23:59:00+08:00')
        r=self.store.add(self.item(recurrence='weekly'))['item']
        done=self.store.change(r['id'],'done')
        self.assertEqual(done['item']['status'],'done');self.assertIsNotNone(done['next'])
        spawned=self.store.db.execute('SELECT * FROM ddl_items WHERE parent_id=?',(r['id'],)).fetchone()
        self.assertEqual(spawned['deadline_at'],'2026-10-21T23:59:00+08:00')
    def test_archive_marks_done_but_keeps_history(self):
        r=self.store.add(self.item())['item']
        archived=self.store.change(r['id'],'archive')
        self.assertEqual(archived['item']['status'],'done')
        self.assertIsNotNone(archived['item']['archived_at'])
        self.assertEqual(len(self.store.list()),0)
        self.assertEqual(len(self.store.list(all_items=True)),1)
        self.assertEqual(self.store.change(r['id'],'unarchive')['item']['status'],'todo')
    def test_catchup_reminds_items_added_after_morning(self):
        clock=dt.datetime(2026,10,7,15,0,tzinfo=TZ)
        with patch('ddl.now',return_value=clock):
            self.store.add(self.item(title='矩阵 LaTeX 作业',deadline_at='2026-10-07T18:00:00+08:00'))
            self.store.add(self.item(title='报名材料',deadline_at='2026-10-07T23:59:00+08:00'))
            first=self.store.queue(at=iso(clock))
        self.assertEqual(first['queued'],1)
        with patch('ddl.now',return_value=clock):self.assertEqual(self.store.queue(at=iso(clock))['queued'],0)
    def test_grouped_list_buckets(self):
        clock=dt.datetime(2026,10,7,9,0,tzinfo=TZ)
        with patch('ddl.now',return_value=clock):
            self.store.add(self.item(title='逾期项',deadline_at='2026-10-05T23:59:00+08:00'))
            self.store.add(self.item(title='今天项',deadline_at='2026-10-07T18:00:00+08:00'))
            self.store.add(self.item(title='本周项',deadline_at='2026-10-09T23:59:00+08:00'))
            self.store.add(self.item(title='更远项',deadline_at='2026-10-25T23:59:00+08:00'))
            groups=dict((label,rows) for label,rows in self.store.list(grouped=True))
        self.assertEqual(len(groups['逾期']),1);self.assertEqual(len(groups['今天']),1)
        self.assertEqual(len(groups['本周']),1);self.assertEqual(len(groups['更远']),1)
    def test_adopt_preview_does_not_write(self):
        self.store.db.execute("INSERT INTO opportunities(id,source_id,url,title,text,tags,extraction,state,discovered_at) VALUES('o1','s1','u','SRTP 申报','正文','[]',?, 'ready',?)",
            (json.dumps([{'title':'报名截止','deadline_at':'2026-11-01T23:59:00+08:00'}]),iso(now())))
        self.store.db.commit()
        nodes=self.store.adopt_preview('o1')
        self.assertEqual(nodes['count'],1)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM ddl_items').fetchone()[0],0)
    def test_snapshot_is_consistent_and_pruned(self):
        import sqlite3,tempfile,shutil
        from ddl import ROOT
        self.store.add(self.item())
        folder=ROOT/'data'/'snapshots'
        before=set(folder.glob('ddl-*.sqlite3')) if folder.exists() else set()
        info=self.store.snapshot(retention=7)
        copy=pathlib.Path(info['path'])
        self.assertTrue(copy.exists())
        con=sqlite3.connect(copy)
        self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertEqual(con.execute('SELECT count(*) FROM ddl_items').fetchone()[0],1)
        con.close()
        self.assertGreaterEqual(info['kept'],1)
        for path in set(folder.glob('ddl-*.sqlite3'))-before-{copy}:path.unlink()
class CoreTests(unittest.TestCase):
    def setUp(self):self.store=Store(':memory:')
    def tearDown(self):self.store.close()
    def item(self,**kwargs):return {'title':'数据库实验报告','deadline_at':'2026-10-14T23:59:00+08:00','confidence':.95,'source_type':'qq_text',**kwargs}
    def test_relative_time(self):
        self.assertEqual(normalize('下周三23:59前','2026-10-07T12:00:00+08:00'),'2026-10-14T23:59:00+08:00')
        self.assertEqual(normalize('周五晚上8点前','2026-10-07T12:00:00+08:00'),'2026-10-09T20:00:00+08:00')
        self.assertEqual(normalize('明天12:00前','2026-12-31T12:00:00+08:00'),'2027-01-01T12:00:00+08:00')
        self.assertEqual(normalize('2026年10月20日24:00前','2026-10-07T12:00:00+08:00'),'2026-10-21T00:00:00+08:00')
    def test_missing_year_and_ambiguous(self):
        for value in ['10月14日23:59','下周三晚上','周末','下周']:
            with self.assertRaises(ValueError):normalize(value,'2026-10-07T12:00:00+08:00')
    def test_confidence_and_confirm(self):
        self.assertFalse(self.store.add(self.item(confidence=.6))['created'])
        r=self.store.add(self.item(confidence=.8));self.assertEqual(r['item']['status'],'pending')
        self.assertEqual(self.store.change(r['item']['id'],'confirm')['item']['status'],'todo')
    def test_cross_format_dedup(self):
        self.store.add(self.item());r=self.store.add(self.item(source_type='qq_image'))
        self.assertTrue(r['duplicate']);self.assertEqual(len(self.store.list()),1)
    def test_ambiguous_delete_soft_delete_restore(self):
        a=self.store.add(self.item())['item'];self.store.add(self.item(title='数据库实验报告第二次'))
        self.assertFalse(self.store.change('数据库','delete')['changed'])
        self.assertEqual(self.store.change(a['id'],'delete')['item']['status'],'deleted')
        self.assertEqual(self.store.change(a['id'],'restore')['item']['status'],'todo')
        self.assertEqual(self.store.db.execute('select count(*) from audit').fetchone()[0],4)
    def test_number_context_and_update(self):
        self.store.add(self.item());self.store.list()
        r=self.store.change('1','update',{'deadline_at':'2026-10-15T23:59:00+08:00'})
        self.assertEqual(r['item']['deadline_at'],'2026-10-15T23:59:00+08:00')
        self.assertEqual(self.store.change('1','done')['item']['status'],'done')
    def test_isolation(self):
        a=self.store.add(self.item())['item'];self.store.owner='other'
        self.assertEqual(self.store.list(),[]);self.assertFalse(self.store.change(a['id'],'delete')['changed'])
    def test_reminder_dedup(self):
        at='2026-10-11T08:05:00+08:00';self.store.add(self.item())
        self.assertGreater(self.store.queue(at)['queued'],0)
        self.assertEqual(self.store.queue(at)['queued'],0)
        ids=self.store.outbox();self.assertEqual(len(ids),2)
        self.store.ack(ids[0]['id'],'test-receipt');self.assertEqual(len(self.store.outbox()),1)
    def test_morning_reminder_no_second_push(self):
        self.store.add(self.item(deadline_at='2026-10-12T23:59:00+08:00'))
        self.assertEqual(self.store.queue('2026-10-11T08:05:00+08:00')['queued'],1)
        self.assertEqual(self.store.queue('2026-10-11T08:35:00+08:00')['queued'],0)
    def test_summary_fires_when_scheduler_runs_late(self):
        self.store.add(self.item(deadline_at='2026-10-12T23:59:00+08:00'))
        # 08:00 的定时任务因主机唤醒晚到 08:44，仍应补发早间摘要，不能整天丢失
        self.assertEqual(self.store.queue('2026-10-11T08:44:00+08:00')['queued'],1)
        self.assertIn('morning',[r['kind'] for r in self.store.outbox()])
        # 同一天再跑不重复发送
        self.assertEqual(self.store.queue('2026-10-11T09:10:00+08:00')['queued'],0)
    def test_summary_not_sent_beyond_tolerance(self):
        self.store.add(self.item(deadline_at='2026-10-12T23:59:00+08:00'))
        self.store.queue('2026-10-11T12:30:00+08:00')  # 晚到 4.5 小时，超出补发窗口
        self.assertNotIn('morning',[r['kind'] for r in self.store.outbox()])
    def test_unseen_queue_does_not_override_number_context(self):
        a=self.store.add(self.item())['item'];b=self.store.add(self.item(title='AI作业',deadline_at='2026-10-12T20:00:00+08:00'))['item']
        self.store.list(query='数据库')
        self.store.queue('2026-10-11T08:05:00+08:00')
        self.assertEqual(self.store.resolve('1')[0]['id'],a['id'])
    def test_pending_not_reminded(self):
        self.store.add(self.item(confidence=.8));self.store.queue('2026-10-11T08:05:00+08:00')
        self.assertEqual(len(self.store.outbox()),1)
        self.assertEqual(json.loads(self.store.outbox()[0]['item_ids']),[])
    def test_muted(self):
        self.store.prefs({'muted_until':'2026-11-01T23:59:00+08:00'})
        self.assertEqual(self.store.queue('2026-10-11T08:05:00+08:00')['queued'],0)
    def test_injection_validation(self):
        with self.assertRaises(ValueError):self.store.add(self.item(sql='DROP TABLE ddl_items'))
        self.assertTrue(self.store.add(self.item(title="报告'; DROP TABLE ddl_items; --"))['created'])
    def test_persistence(self):
        with tempfile.TemporaryDirectory() as path:
            f=pathlib.Path(path)/'ddl.db';a=Store(f);a.add(self.item());a.close();b=Store(f);self.assertEqual(len(b.list()),1);b.close()
    def test_mcp_protocol(self):
        with tempfile.TemporaryDirectory() as path:
            requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05'}},
                {'jsonrpc':'2.0','id':2,'method':'tools/list'},
                {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'ddl_add','arguments':{'item':self.item()}}},
                {'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'ddl_change','arguments':{'selector':'missing','operation':'delete'}}}]
            import sys
            process=subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('ddl.py')),'--db',str(pathlib.Path(path)/'test.db'),'serve'],
                input='\n'.join(json.dumps(r) for r in requests)+'\n',text=True,capture_output=True,encoding='utf8',timeout=10)
            self.assertEqual(process.returncode,0,process.stderr)
            rows=[json.loads(r) for r in process.stdout.splitlines()]
            self.assertEqual(len(rows),4);self.assertGreater(len(rows[1]['result']['tools']),10)
            self.assertTrue(json.loads(rows[2]['result']['content'][0]['text'])['created'])
            self.assertFalse(json.loads(rows[3]['result']['content'][0]['text'])['changed'])
if __name__=='__main__':unittest.main(verbosity=2)
