# -*- coding: utf-8 -*-
import json, urllib.request, urllib.error
base='http://127.0.0.1:8000'
def req(method, path, data=None):
    body = json.dumps(data, ensure_ascii=False).encode('utf-8') if data is not None else None
    r = urllib.request.Request(base+path, data=body, method=method,
        headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8','replace'))

print("正常单(矿泉水):", req('POST','/api/errands', {
  'title':'帮取快递','category':'parcel','pickup':'横琴快递站（校园外）','delivery':'宿舍（校内）',
  'bounty':8,'requester_id':2,'content':'顺路带一箱矿泉水','pickup_code':'OK1'}))
print("违禁单(香烟):", req('POST','/api/errands', {
  'title':'带烟','category':'parcel','pickup':'横琴','delivery':'宿舍',
  'bounty':10,'requester_id':2,'content':'帮带两条香烟','pickup_code':'NO1'}))
print("空申报:", req('POST','/api/errands', {
  'title':'无申报','category':'parcel','pickup':'横琴','delivery':'宿舍',
  'bounty':5,'requester_id':2,'content':'','pickup_code':'NO2'})[0])

# 三方可见性验证:以路人视角(id=999,不存在)看列表,正常单的 content 应为 null
st, lst = req('GET','/api/errands?viewer_id=999')
print("路人视角正常单 content:", lst[0]['content'] if lst else 'list empty')