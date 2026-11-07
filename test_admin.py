# -*- coding: utf-8 -*-
"""管理员审核后台的端到端测试。"""
import json
import time
import urllib.request
import urllib.error
import urllib.parse

BASE = 'http://127.0.0.1:8000'
KEY = 'campus-platform'
UNIQ = str(int(time.time()))[-7:]


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


print('1) /admin 页面可访问')
s, html = urllib.request.urlopen(BASE + '/admin').status, None
with urllib.request.urlopen(BASE + '/admin') as r:
    html = r.read().decode('utf-8')
print('   HTTP', s, '| 含口令输入框:', 'key_input' in html, '| 含审核工作台:', '平台审核后台' in html)

print('\n2) 权限:错误口令被拒')
s, r = call('GET', '/api/audit/items?key=hacker')
print('   错误口令 ->', s, r.get('detail'))
assert s == 403

print('\n3) 发一个含违禁词的单(自动拒绝),再人工通过让它重新上架')
s, pub = call('POST', '/api/register', {'name': '审核测试同学', 'student_id': 'audit-' + UNIQ})
s, e = call('POST', '/api/errands', {
    'title': '人工复核演示单', 'content': '一瓶酒精喷雾', 'category': 'parcel',
    'size': 'small', 'bounty': 8, 'requester_id': pub['id'], 'pickup': '横琴审核测试站',
    'tags': ['急单']})
eid = e['id']
print('   自动审核:', e['audit_status'], '| 订单状态:', e['status'])
assert e['audit_status'] == 'rejected'

# 管理员在后台能看到它(含普通用户看不到的申报内容)
s, items = call('GET', '/api/audit/items?key=' + KEY + '&status=rejected')
target = [x for x in items if x['id'] == eid][0]
print('   后台可见申报内容:', target['content'], '| 标签:', target['tags'], '| 发布者:', target['requester'])
assert target['content'] == '一瓶酒精喷雾'

# 人工通过 -> 重新上架
s, r = call('POST', '/api/audit/items/%d' % eid, {'key': KEY, 'decision': 'approve', 'note': '人工确认可带,放行'})
print('   人工通过 -> audit=%s status=%s note=%s' % (r['audit_status'], r['status'], r['audit_note']))
assert r['audit_status'] == 'approved' and r['status'] == 'open'

# 公开市场现在能看到这单(脱敏,无 content)
s, market = call('GET', '/api/errands')
m = [x for x in market if x['id'] == eid][0]
print('   公开市场可见:', m['title'], '| content 脱敏为:', m['content'])
assert m['content'] is None

print('\n4) 再人工驳回 -> 订单下架')
s, r = call('POST', '/api/audit/items/%d' % eid, {'key': KEY, 'decision': 'reject', 'note': '复测驳回:含压力罐'})
print('   驳回 -> audit=%s status=%s' % (r['audit_status'], r['status']))
assert r['audit_status'] == 'rejected' and r['status'] == 'rejected'
s, market = call('GET', '/api/errands')
assert all(x['id'] != eid for x in market), '被驳回的单不应出现在公开市场'
print('   公开市场已查无此单(下架成功)')

print('\n5) 非法 decision 被拒')
s, r = call('POST', '/api/audit/items/%d' % eid, {'key': KEY, 'decision': 'maybe'})
print('   ->', s, r.get('detail'))
assert s == 400

print('\n6) 状态筛选统计')
for st in ['pending', 'approved', 'rejected']:
    s, rows = call('GET', '/api/audit/items?key=' + KEY + '&status=' + st)
    print('   %-9s %d 条, 全部状态正确: %s' % (st, len(rows), all(x['audit_status'] == st for x in rows)))

print('\n全部断言通过 ✅ 审核后台端到端正常')
