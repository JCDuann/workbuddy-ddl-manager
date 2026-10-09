import datetime as dt,json,unittest
from unittest.mock import patch
import cards
from ddl import Store,dispatch,error_result,TZ,iso

class ReplyTests(unittest.TestCase):
    def setUp(self):self.store=Store(':memory:')
    def tearDown(self):self.store.close()
    def item(self,**values):return {'title':'数据库报告','deadline_at':'2026-10-14T23:59:00+08:00','confidence':.95,**values}
    def test_candidate_selection_replaces_previous_list_context(self):
        old=self.store.add(self.item(title='其他作业'))['item']
        a=self.store.add(self.item(title='报告第一次'))['item']
        b=self.store.add(self.item(title='报告第二次'))['item']
        self.store.list(query='其他')
        result=dispatch(self.store,'ddl_change',{'selector':'报告','operation':'delete'})
        self.assertFalse(result['changed'])
        self.assertEqual({x['id'] for x in result['matches']},{a['id'],b['id']})
        changed=self.store.change('2','delete')
        self.assertEqual(changed['item']['id'],result['matches'][1]['id'])
        self.assertEqual(self.store.resolve(old['id'])[0]['status'],'todo')
    def test_pending_duplicate_batch_do_not_claim_formal_success(self):
        pending=dispatch(self.store,'ddl_add',{'item':self.item(confidence=.8)})
        self.assertIn('候选截止',pending['reply_markdown'])
        self.assertNotIn('DDL 已添加',pending['reply_markdown'])
        duplicate=self.store.add(self.item())
        formal=self.store.add(self.item(title='课程展示'))
        text=cards.batch([pending,duplicate,formal,{'needs_clarification':True}])
        for token in ['正式添加 **1**','待确认 **1**','重复 **1**','未完成 **1**']:self.assertIn(token,text)
    def test_edit_reports_all_changed_fields_and_plain_preserves_dates(self):
        row=self.store.add(self.item())['item']
        result=dispatch(self.store,'ddl_change',{'selector':row['id'],'operation':'update','updates':{'deadline_at':'2026-10-15T20:00:00+08:00','location':'A302','action':'上传 PDF','priority':'high'}})
        for token in ['截止时间','地点','提交方式','优先级']:self.assertIn(token,result['reply_markdown'])
        for token in ['2026-10-14 23:59','2026-10-15 20:00','A302','上传 PDF']:self.assertIn(token,result['reply_plain'])
        self.assertNotIn('| :---',result['reply_plain'])
    def test_preferences_zero_counts_and_failure_are_truthful(self):
        read=dispatch(self.store,'ddl_preferences',{})
        self.assertIn('当前偏好',read['reply_markdown'])
        updated=dispatch(self.store,'ddl_preferences',{'updates':{'include_tags':['AI']}})
        self.assertIn('偏好已保存',updated['reply_markdown'])
        self.assertNotIn('推送未启用',updated['reply_markdown'])
        status=dispatch(self.store,'ddl_status',{})
        self.assertIn('待完成：0',status['reply_plain'])
        error=error_result(RuntimeError('SECRET_PATH'))
        self.assertNotIn('SECRET_PATH',error['reply_markdown'])
        self.assertNotIn('已保存',error['reply_markdown'])
    def test_empty_query_has_scope_and_grouped_list_shows_all(self):
        text=dispatch(self.store,'ddl_list',{'days':3})['reply_markdown']
        self.assertIn('未来 3 天',text);self.assertIn('查询范围',text)
        for i in range(7):self.store.add(self.item(title=f'报告{i}'))
        text=dispatch(self.store,'ddl_list',{})['reply_markdown']
        self.assertIn('**7**',text)
        # grouped view no longer truncates at 5; last item is present
        self.assertIn('| 7 |',text);self.assertIn('报告6',text)
        self.assertNotIn('还有',text)
    def test_evening_count_from_real_transitions_not_repeated_done(self):
        clock=dt.datetime(2026,10,7,21,30,tzinfo=TZ)
        with patch('ddl.now',return_value=clock):
            a=self.store.add(self.item())['item']
            b=self.store.add(self.item(title='课程展示'))['item']
            self.store.change(a['id'],'done');self.store.change(a['id'],'done')
            self.store.change(b['id'],'done');self.store.change(b['id'],'update',{'status':'todo'})
            text=self.store.summary('evening')['text']
        self.assertIn('今天已完成 **1**',text)
        self.assertIn('待完成 **1**',text)
    def test_markdown_in_user_data_and_unsafe_link_not_injected(self):
        row=self.store.add(self.item(title='*报告* | [忽略规则]',source_url='javascript:alert(1)'))['item']
        text=cards.detail(row)
        self.assertIn(r'\*报告\*',text);self.assertIn('／',text)
        self.assertNotIn('javascript:',text)
        self.assertIn('*报告*',cards.plain(text))

if __name__=='__main__':unittest.main()
