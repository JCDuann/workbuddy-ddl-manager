"""Fixed QQ reply templates; render only facts present in tool results."""
import datetime as dt,json,re
TZ=dt.timezone(dt.timedelta(hours=8))
SOURCES={'qq_text':'QQ 文字','qq_image':'QQ 截图','qq_file':'QQ 文件','official_web':'官方通知','manual':'手动录入'}
FIELDS={'title':'事项','deadline_at':'截止时间','start_at':'开始时间','category':'类别','location':'地点','action':'提交方式','priority':'优先级','status':'状态'}
STATES={'pending':'待确认','done':'已完成','deleted':'已删除','expired':'已逾期','todo':'待完成'}
PRIORITIES={'high':'高','medium':'普通','low':'低'}
RECURRENCE_LABELS={'daily':'每天','weekly':'每周','biweekly':'每两周','monthly':'每月'}

def escape(text):
    value=str('' if text is None else text).replace('\r',' ').replace('\n',' ').replace('|','／').replace('<','＜').replace('>','＞')
    return re.sub(r'([\\`*_\[\]#])',r'\\\1',value)

def due(text):
    return dt.datetime.fromisoformat(text).astimezone(TZ).strftime('%Y-%m-%d %H:%M')

def state(row,at=None):
    clock=at or dt.datetime.now(TZ)
    if row['status']=='todo' and dt.datetime.fromisoformat(row['deadline_at']).astimezone(TZ)<clock:return '已逾期'
    return STATES.get(row['status'],'未知状态')

def link(url,label='查看原文'):
    if not isinstance(url,str) or not re.match(r'^https?://[^\s]+$',url):return ''
    return f'[{label}]({url.replace("(","%28").replace(")","%29")})'

def card(title,lead='',body='',action=''):
    return '\n\n'.join(part for part in ['### '+title,lead,body,('**下一步：** '+action) if action else ''] if part)

def fields(rows):
    return '\n'.join(['| 字段 | 内容 |','| :--- | :--- |',*[f'| {escape(k)} | {escape(v)} |' for k,v in rows]])

def table(rows,at=None,limit=5):
    clock=at or dt.datetime.now(TZ)
    lines=['| 编号 | 事项 | 截止 | 状态 |','| :---: | :--- | :--- | :---: |']
    for i,row in enumerate(rows[:limit],1):
        title=row['title'];title=title if len(title)<=24 else title[:23]+'…'
        date=due(row['deadline_at']);date=date[5:] if date[:4]==str(clock.year) else date
        if row['status']=='pending':date+='（待核实）'
        mark=' 🔁' if row.get('recurrence') else ''
        lines.append(f'| {i} | {escape(title+mark)} | {date} | {state(row,clock)} |')
    return '\n'.join(lines)

def grouped_table(groups,at=None,limit=15):
    """Render grouped buckets with continuous numbering; no truncation below limit."""
    clock=at or dt.datetime.now(TZ)
    out=[];index=0
    for name,rows in groups:
        if not rows:continue
        out.append(f'**{name}**')
        for row in rows:
            if index>=limit:break
            index+=1
            date=due(row['deadline_at']);date=date[5:] if date[:4]==str(clock.year) else date
            if row['status']=='pending':date+='（待核实）'
            mark=' 🔁' if row.get('recurrence') else ''
            out.append(f'{index}. {escape(row["title"]+mark)}｜{date}｜{state(row,clock)}')
        if index>=limit:break
    return '\n'.join(out)

def detail(row,label='📌 事项详情',lead=''):
    values=[('候选截止' if row['status']=='pending' else '截止',due(row['deadline_at'])),('状态',state(row)),('来源',SOURCES.get(row.get('source_type'),'未记录'))]
    for key,name in [('start_at','开始'),('action','提交方式'),('location','地点'),('contact','联系')]:
        if row.get(key):values.append((name,due(row[key]) if key=='start_at' else row[key]))
    if row.get('recurrence'):values.append(('重复',RECURRENCE_LABELS.get(row['recurrence'],row['recurrence'])))
    if row.get('archived_at'):values.append(('归档',due(row['archived_at'])))
    if row.get('priority')=='high':values.append(('优先级','高'))
    body='**'+escape(row['title'])+'**\n\n'+fields(values)
    source=link(row.get('source_url'))
    if source:body+='\n\n'+source
    return card(label,lead,body)

def clarify(reason='截止日期或时间还不明确',known=None,question='请补充完整截止日期和时间。',pending=False):
    body=fields(known) if known else ''
    if pending:body+='\n\n**已暂存为待确认，确认前不生成确定日期提醒。**'
    else:body+='\n\n**尚未保存为正式 DDL。**'
    return card('❓ 请确认截止信息',reason,body.strip(),question)

def batch(results,title='📥 批量处理结果'):
    created=sum(bool(r.get('created')) and r.get('item',{}).get('status')!='pending' for r in results)
    pending=sum(bool(r.get('created')) and r.get('item',{}).get('status')=='pending' for r in results)
    duplicates=sum(bool(r.get('duplicate')) for r in results)
    other=len(results)-created-pending-duplicates
    lead=f'正式添加 **{created}** 项 · 待确认 **{pending}** 项 · 重复 **{duplicates}** 项'
    if other:lead+=f' · 未完成 **{other}** 项'
    lines=['| 序号 | 事项 | 处理结果 |','| :---: | :--- | :--- |']
    for i,r in enumerate(results[:5],1):
        row=r.get('item',{});title_text=row.get('title',r.get('title','待补充事项'))
        label=('重复，保持原记录' if r.get('duplicate') else '待确认' if r.get('created') and row.get('status')=='pending' else '已添加' if r.get('created') else '信息不足' if r.get('needs_clarification') else '未确认成功')
        lines.append(f'| {i} | {escape(title_text)} | {label} |')
    if len(results)>5:lines.extend(['',f'本卡显示前 5 项，还有 {len(results)-5} 项处理结果。'])
    return card(title,lead,'\n'.join(lines),'回复完整事项名称，确认日期或查看详情。')

def reminder(rows,at=None):
    return card('⏰ 临期提醒',f'有 **{len(rows)}** 项进入提醒范围。',table(rows,at)+'\n\n时间均为北京时间。','回复“第1个完成了”或完整事项名称。')

def summary(kind,selected,total,pending,opportunities,clock,completed_today=0,window_count=None):
    expired=sum(dt.datetime.fromisoformat(r['deadline_at']).astimezone(TZ)<clock for r in selected)
    title=('☀️ 早间行动摘要' if kind=='morning' else '🌙 晚间复盘')+' · '+clock.strftime('%m-%d')
    lead=(f'今天已完成 **{completed_today}** 项 · ' if kind=='evening' else '')+f'待完成 **{total}** 项 · 待确认 **{pending}** 项'
    body=(table(selected,clock) if selected else '**当前窗口暂无临近截止或已逾期事项。**')
    if window_count is not None and window_count>len(selected):body+=f'\n\n本卡展示前 {len(selected)} 项，窗口内另有 {window_count-len(selected)} 项。'
    if expired:body+=f'\n\n其中 **{expired}** 项已逾期，请优先核实是否补交或调整日期。'
    if opportunities:
        body+='\n\n**校园新机会（尚未加入个人 DDL）**'
        for row in opportunities:body+='\n- '+escape(row['title'])+' '+link(row['url'],'原文')
    if pending:body+='\n\n待确认事项不参与确定日期提醒。'
    body+='\n\n北京时间 · '+('未来 48 小时及逾期事项' if kind=='morning' else '未来 7 天及逾期事项')
    return card(title,lead,body,'回复“第1个完成了”或完整事项名称。' if selected else '发来课程通知，或说“查看校园机会”。')

def render(name,result):
    if name=='ddl_add':
        if result.get('needs_clarification'):return clarify()
        row=result.get('item')
        if not row:return None
        if result.get('duplicate'):
            deleted=row['status']=='deleted'
            text=detail(row,'🔁 发现已有记录','这项此前已删除，本次没有新增。' if deleted else '已找到同一事项，本次没有重复添加。')
            return text+'\n\n**下一步：** '+('回复“恢复这项”。' if deleted else '需要调整时，回复事项名称和新日期。')
        if row['status']=='pending':
            return detail(row,'❓ 日期待确认','已暂存，确认前不生成确定日期提醒。')+'\n\n**下一步：** 请确认上面的截止信息，或提供正确日期。'
        return detail(row,'📌 DDL 已添加','已保存到你的个人待办。')+'\n\n**下一步：** 可回复“完成了”“修改日期”或“删除这项”。'
    if name=='ddl_list':
        raw=result['items'] if isinstance(result,dict) else result;filters=result.get('filters',{}) if isinstance(result,dict) else {}
        grouped=bool(filters.get('grouped')) and not raw or any(isinstance(x,tuple) for x in raw)
        title='🗓️ 我的 DDL'
        if isinstance(result,dict) and result.get('calendar_week_start'):title=f"🗓️ 本周 DDL · {result['calendar_week_start']} 至 {result['calendar_week_end']}"
        elif filters.get('days') is not None:title=f"🗓️ 未来 {filters['days']} 天 DDL"
        if filters.get('query'):title+=' · '+escape(filters['query'])
        if filters.get('status') and filters['status']!='active':title+=' · '+STATES.get(filters['status'],'全部状态')
        if grouped:
            total=sum(len(x[1]) for x in raw)
            if not total:return card(title,'**当前查询范围内没有记录。**',action='可调整查询范围，或发来新的课程通知。')
            body=grouped_table(raw)+'\n\n北京时间 · 🔁 表示重复事项。'
            return card(title,f'本次查到 **{total}** 项，按时间分组。',body,'回复“第2个完成了”“把第1个延后一天”。')
        rows=raw
        if not rows:return card(title,'**当前查询范围内没有记录。**',action='可调整查询范围，或发来新的课程通知。')
        total=len(rows);shown=min(total,12)
        lead=f'本次查到 **{total}** 项';body=table(rows,limit=shown)+'\n\n时间均为北京时间。'
        if total>shown:body+=f'\n本卡显示前 {shown} 项，还有 {total-shown} 项；可按日期或关键词继续查询。'
        return card(title,lead,body,'回复“第2个完成了”“把第1个延后一天”。')
    if name=='ddl_change':
        if not result.get('changed'):
            rows=result.get('matches',[])
            if rows:return card('🔎 请先选择事项',f'找到 **{len(rows)}** 个匹配，暂未修改。',table(rows)+(f'\n\n本卡显示前 5 项，还有 {len(rows)-5} 项；请缩小查询范围。' if len(rows)>5 else ''),'回复本卡编号并说明操作，或完整标题与截止日期。')
            return card('🔎 没有找到事项','这次没有修改记录。',action='回复完整标题，或先说“查看我的 DDL”。')
        row,before=result['item'],result['before'];op=result.get('operation')
        labels={'delete':'🗑️ 已删除','done':'✅ 已完成','restore':'↩️ 已恢复','confirm':'✅ 日期已确认','update':'✏️ 已修改',
                'archive':'📦 已归档','unarchive':'📤 已移出归档'}
        title=labels.get(op,'✅ 已更新');lines=[]
        for key,label in FIELDS.items():
            if before.get(key)==row.get(key):continue
            def value(r):
                v=r.get(key)
                if not v:return '未提供'
                if key in ['deadline_at','start_at']:return due(v)
                if key=='status':return STATES.get(v,v)
                if key=='priority':return PRIORITIES.get(v,v)
                return str(v)
            lines.append(f'| {label} | {escape(value(before))} | {escape(value(row))} |')
        body='**'+escape(row['title'])+'**\n\n'+ ('\n'.join(['| 字段 | 修改前 | 修改后 |','| :--- | :--- | :--- |',*lines]) if lines else fields([('截止',due(row['deadline_at'])),('状态',state(row))]))
        action='回复“恢复这项”可撤销删除。' if op=='delete' else '可回复完整事项名称继续管理。'
        return card(title,'信息与原记录一致。' if not lines else '操作已保存。',body,action)
    if name=='ddl_adopt':return batch(result)
    if name=='ddl_adopt_preview':
        nodes=result.get('nodes',[]);title_text=result.get('title','')
        if not nodes:return card('🎯 加入个人 DDL','该通知没有可加入的时间节点。',action='可查看其他校园机会。')
        lines=['| 编号 | 节点 | 截止 |','| :---: | :--- | :--- |']
        for i,n in enumerate(nodes[:10],1):
            lines.append(f"| {i} | {escape(n.get('title',''))} | {due(n['deadline_at'])[5:]} |")
        body='**'+escape(title_text)+'**\n\n'+'\n'.join(lines)
        return card('🎯 将加入以下事项',f'该通知含 **{len(nodes)}** 个时间节点，确认后一并加入个人 DDL。',body,
            f'回复「确认加入 {escape(title_text[:12])}」执行，或说「取消」。')
    if name=='ddl_push':
        if not result.get('queued'):
            return card('🔔 立即推送',result.get('reason','没有可推送的事项。'),action='可先说“查看我的 DDL”。')
        return card('🔔 已加入推送队列',f'**{result.get("queued")}** 条提醒已排队，将在下次投递时发出（以真实 QQ 回执为准）。',
            action='可先说“查看我的 DDL”。')
    if name=='ddl_opportunities':
        rows=result
        if not rows:return card('🎯 校园机会','暂无已核实、仍有效且符合订阅的机会。',action='可调整关注标签，或稍后再查看。')
        lines=[];clock=dt.datetime.now(TZ)
        for i,row in enumerate(rows[:3],1):
            items=json.loads(row.get('extraction') or '[]');valid=[x for x in items if dt.datetime.fromisoformat(x['deadline_at']).astimezone(TZ)>=clock]
            nearest=min((x['deadline_at'] for x in valid),default=None)
            lines.extend([f"**{i}. {escape(row['title'])}**",fields([('最近截止',due(nearest) if nearest else '尚待核实'),('来源',{'cqu':'重庆大学','sxic':'交叉创新中心'}.get(row['source_id'],row['source_id']))]),link(row['url'])])
        if len(rows)>3:lines.append(f'本卡展示前 3 个机会，当前结果还有 {len(rows)-3} 个。')
        return card('🎯 校园机会',f'本次找到 **{len(rows)}** 个机会，均尚未加入个人 DDL。','\n\n'.join(lines),'回复机会完整名称并说“加入我的 DDL”。')
    if name=='ddl_summary':return result.get('text')
    if name=='ddl_preferences':
        values=[('早间偏好',result['morning']),('晚间偏好',result['evening']),('关注标签','、'.join(result['include_tags']) or '不限'),('排除标签','、'.join(result['exclude_tags']) or '无'),('静音至',due(result['muted_until']) if result.get('muted_until') else '未设置')]
        return card('⚙️ 提醒与订阅','偏好已保存。' if result.get('updated') else '当前偏好如下。',fields(values)+'\n\n北京时间；实际执行时间以 WorkBuddy 定时任务为准。','可说“只关注 AI 和编程”或“今晚先静音”。')
    if name=='ddl_status':
        counts=result['items'];sources=result['sources'];failed=sum(bool(x['error']) for x in sources)
        return card('🔧 DDL 运行状态','已读取当前数据库状态。',fields([('待完成',counts.get('todo',0)+counts.get('expired',0)),('待确认',counts.get('pending',0)),('提醒待发送',result['outbox_pending']),('来源最近记录',f'{len(sources)-failed} 个无抓取错误 / {failed} 个有错误')])+'\n\nQQ连接与主动发送需另查实时状态，不能从数据库计数推断。')
    if name=='ddl_radar':
        errors=sum(len(x['errors']) for x in result);added=sum(x['new'] for x in result)
        rows=[({'cqu':'学校通知','sxic':'创新中心'}.get(x['id'],x['id']),f"新增 {x['new']} 条；"+('部分失败' if x['errors'] else '抓取完成')) for x in result]
        return card('📡 校园雷达扫描',f'新增 **{added}** 条通知'+(f' · **{errors}** 处抓取失败' if errors else '。'),fields(rows)+'\n\n抓取结果先进入机会池，不自动加入个人 DDL。', '查看校园机会，或继续核实未解析通知。')
    return None

def error_card(reason='这次操作没有确认成功。',impact='请先核实当前记录，避免重复操作。',next_step='回复事项名称或重试查询。'):
    return card('⚠️ 操作未完成',reason,impact,next_step)

def plain(markdown):
    """Turn tables into labeled readable blocks while preserving all represented fields."""
    output=[];headers=None;previous_table=False
    source=markdown.splitlines()
    for index,line in enumerate(source):
        if line.startswith('|'):
            cells=[x.strip() for x in line.strip('|').split('|')]
            if all(re.fullmatch(r':?-+:?',x) for x in cells):continue
            if index+1<len(source) and re.match(r'^\|\s*:?-+',source[index+1]):headers=cells;previous_table=True;continue
            if headers and headers[0] in ['编号','序号']:
                output.append(cells[0]+'. '+cells[1]);output.extend(f'{headers[i]}：{cells[i]}' for i in range(2,min(len(headers),len(cells))));output.append('')
            elif headers and len(cells)==2:output.append(cells[0]+'：'+cells[1])
            elif headers:output.append(cells[0]+'：'+'；'.join(f'{headers[i]} {cells[i]}' for i in range(1,min(len(headers),len(cells)))))
            else:output.append(' · '.join(cells))
        else:
            if previous_table:headers=None;previous_table=False
            output.append(line)
    text='\n'.join(output)
    text=re.sub(r'(?m)^#{1,6}\s+','',text).replace('**','')
    text=re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)',r'\1：\2',text)
    text=re.sub(r'\\([\\`*_\[\]#])',r'\1',text)
    return re.sub(r'\n{3,}','\n\n',text).strip()
