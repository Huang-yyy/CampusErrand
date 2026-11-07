# -*- coding: utf-8 -*-
"""三个新功能的端到端接口测试。"""
import json
import urllib.request
import urllib.error
import urllib.parse

BASE = 'http://127.0.0.1:8000'


def call(method, path, data=None):
    kw = {'method': method}
    if data is not None:
        kw['data'] = json.dumps(data).encode('utf-8')
        kw['headers'] = {'Content-Type': 'application/json'}
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + path, **kw)) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


import time
UNIQ = str(int(time.time()))[-7:]
print('=' * 60)
print('任务1:标签分类 + 筛选')
print('=' * 60)
s, pub = call('POST', '/api/register', {'name': '标签测试发布方', 'student_id': 'tag-pub-' + UNIQ})
s, run = call('POST', '/api/register', {'name': '标签测试接单者', 'student_id': 'tag-run-' + UNIQ})
s, e1 = call('POST', '/api/errands', {
    'title': '横琴菜鸟急单-易碎', 'content': '玻璃水杯一个', 'category': 'parcel',
    'size': 'small', 'bounty': 10, 'requester_id': pub['id'],
    'pickup': '横琴菜鸟驿站', 'tags': ['急单', '易碎', '急单'],  # 故意重复,测去重
})
s, e2 = call('POST', '/api/errands', {
    'title': '十字门外卖', 'content': '密封盒饭', 'category': 'meal',
    'size': 'medium', 'bounty': 6, 'requester_id': pub['id'],
    'pickup': '十字门美食城', 'tags': ['生鲜'],
})
print('发单1 id=%s 审核=%s  发单2 id=%s 审核=%s' % (e1['id'], e1['audit_status'], e2['id'], e2['audit_status']))
# 查库验证标签去重落库
import sqlite3
conn = sqlite3.connect(r'C:\Users\1\CampusErrand\app\campus_errand.db')
t1 = conn.execute('SELECT tags FROM errands WHERE id=?', (e1['id'],)).fetchone()[0]
print('单1落库标签(应去重):', t1)
assert t1 == '急单,易碎', '标签去重失败'
# 按标签筛选
s, lst = call('GET', '/api/errands?tag=' + urllib.parse.quote('急单'))
ids = [x['id'] for x in lst]
print('筛选 tag=急单 -> 订单号:', ids, '| 含单1:', e1['id'] in ids, '| 不含单2:', e2['id'] not in ids)
assert e1['id'] in ids and e2['id'] not in ids
# 按分类筛选
s, lst = call('GET', '/api/errands?category=meal')
assert all(x['category'] == 'meal' for x in lst)
print('筛选 category=meal -> 全部为外卖类,共', len(lst), '条')
# 按大小筛选
s, lst = call('GET', '/api/errands?size=small&tag=' + urllib.parse.quote('易碎'))
assert all(x['size'] == 'small' for x in lst)
print('组合筛选 size=small + tag=易碎 ->', len(lst), '条')
# 关键词搜索
s, lst = call('GET', '/api/errands?q=' + urllib.parse.quote('十字门'))
assert all('十字门' in x['pickup'] or '十字门' in x['title'] for x in lst)
print('关键词 q=十字门 ->', [x['id'] for x in lst])

print()
print('=' * 60)
print('任务2:平台内私聊(全程留痕 + 权限)')
print('=' * 60)
# 接单前私聊应被拒
s, r = call('POST', '/api/messages', {
    'errand_id': e1['id'], 'from_id': run['id'], 'to_id': pub['id'], 'body': '在吗'})
print('接单前私聊(应403):', s, r.get('detail'))
assert s == 403
# 接单
s, a = call('POST', '/api/errands/%s/accept' % e1['id'], {'user_id': run['id']})
print('接单:', a['status'])
# 接单后双向私聊
s, m1 = call('POST', '/api/messages', {
    'errand_id': e1['id'], 'from_id': run['id'], 'to_id': pub['id'], 'body': '我顺路,多久能取?'})
s, m2 = call('POST', '/api/messages', {
    'errand_id': e1['id'], 'from_id': pub['id'], 'to_id': run['id'], 'body': '半小时内,取件码稍后给你'})
print('两条消息发送:', m1['id'], m2['id'])
# 空消息拦截
s, r = call('POST', '/api/messages', {
    'errand_id': e1['id'], 'from_id': run['id'], 'to_id': pub['id'], 'body': '   '})
print('空消息(应400):', s)
assert s == 400
# 陌生人查看聊天记录应被拒
s, outsider = call('POST', '/api/register', {'name': '路人甲', 'student_id': 'outsider-' + UNIQ})
s, r = call('GET', '/api/messages?errand_id=%s&viewer_id=%s' % (e1['id'], outsider['id']))
print('路人查看记录(应403):', s)
assert s == 403
# 参与者查看,验证留痕且按时间排序
s, msgs = call('GET', '/api/messages?errand_id=%s&viewer_id=%s' % (e1['id'], pub['id']))
print('聊天记录 %d 条,顺序:' % len(msgs))
for m in msgs:
    print('   [%s] %s -> %s: %s' % (m['created_at'], m['from_name'], m['to_name'], m['body']))
assert len(msgs) == 2 and msgs[0]['id'] < msgs[1]['id']
# 验证数据库层面消息只增不删(留痕):直接数表
n = conn.execute('SELECT COUNT(*) FROM messages WHERE errand_id=?', (e1['id'],)).fetchone()[0]
print('messages 表留痕条数(应为2):', n)
assert n == 2

print()
print('=' * 60)
print('任务3:按顺路程度排行匹配')
print('=' * 60)
# 三个潜在接单者设置不同路线
s, r2 = call('POST', '/api/register', {'name': '常跑横琴学长', 'student_id': 'route-2-' + UNIQ})
s, r3 = call('POST', '/api/register', {'name': '十字门常客', 'student_id': 'route-3-' + UNIQ})
s, r4 = call('POST', '/api/register', {'name': '完全不顺路', 'student_id': 'route-4-' + UNIQ})
call('POST', '/api/users/%s/routes' % run['id'], {'user_id': run['id'], 'routes': ['横琴', '菜鸟驿站', '口岸']})
call('POST', '/api/users/%s/routes' % r2['id'], {'user_id': r2['id'], 'routes': ['横琴', '菜鸟驿站']})
call('POST', '/api/users/%s/routes' % r3['id'], {'user_id': r3['id'], 'routes': ['十字门']})
call('POST', '/api/users/%s/routes' % r4['id'], {'user_id': r4['id'], 'routes': ['市区']})
# 对单2(十字门美食城,仍 open)做匹配
s, match = call('GET', '/api/match?errand_id=%s' % e2['id'])
print('取件点:', match['pickup'])
for i, m in enumerate(match['matches'], 1):
    print('  #%d %s 顺路分=%s 命中=%s 历史完成=%s' % (i, m['name'], m['score'], m['matched_routes'], m['delivered_count']))
names = [m['name'] for m in match['matches']]
assert '十字门常客' in names and '完全不顺路' not in names
print('不顺路者已被排除:', '完全不顺路' not in names)
# 用 pickup 参数直接匹配(不依赖具体订单)
s, match2 = call('GET', '/api/match?pickup=' + urllib.parse.quote('横琴菜鸟驿站'))
scores = {m['name']: m['score'] for m in match2['matches']}
print('pickup=横琴菜鸟驿站 的分数:', scores)
assert scores.get('标签测试接单者', 0) >= scores.get('常跑横琴学长', 0)
# 已接单的任务不允许再匹配
s, r = call('GET', '/api/match?errand_id=%s' % e1['id'])
print('已接单任务再匹配(应400):', s)
assert s == 400

conn.close()
print()
print('全部断言通过 ✅ 三个功能端到端正常')
