"""CampusErrand backend - FastAPI + SQLite."""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from . import llm
from . import audit_rules

app = FastAPI(title="CampusErrand")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

STATIC = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


# ---------------- request models ----------------
class Register(BaseModel):
    name: str
    student_id: str


class PostErrand(BaseModel):
    title: str
    description: str = ""
    category: str = "parcel"
    size: str = "medium"   # small | medium | large(物件大中小)
    pickup: str = "Hengqin courier point"
    delivery: str = "Dormitory"
    bounty: float = 5.0
    pickup_code: str = ""
    requester_id: int
    content: str = ""   # 发布方申报的包裹内容(必填,仅三方可见)
    tags: list[str] = []   # 任务标签(如 急单/易碎/生鲜),任务1


class Accept(BaseModel):
    user_id: int


class Deliver(BaseModel):
    user_id: int


class Recharge(BaseModel):
    user_id: int
    amount: float = 100.0


class SendMessage(BaseModel):
    errand_id: int
    from_id: int
    to_id: int
    body: str


class SetRoutes(BaseModel):
    user_id: int
    routes: list[str]   # 常跑取件点/路线关键词,如 ["横琴菜鸟驿站","十字门"]


# ---------------- 标签规范化 ----------------
def normalize_tags(raw: list[str] | str) -> str:
    """标签统一去空格、去重,存成逗号分隔字符串。"""
    if isinstance(raw, str):
        items = raw.split(",")
    else:
        items = raw or []
    seen, out = set(), []
    for t in items:
        t = (t or "").strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return ",".join(out[:8])   # 最多 8 个标签,防止刷屏


# ---------------- helpers ----------------
def _user(conn, user_id):
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(404, "user not found")
    return row


# ---------------- routes ----------------
@app.get("/api/health")
def health():
    return {"ok": True, "llm_old": bool(llm.OLD_KEY), "llm_new": bool(llm.NEW_KEY)}


@app.post("/api/register")
def register(r: Register):
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO users(name, student_id) VALUES (?,?)",
            (r.name.strip(), r.student_id.strip()))
        conn.commit()
        return dict(conn.execute(
            "SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone())
    except Exception as e:
        raise HTTPException(400, "register failed: " + str(e))
    finally:
        conn.close()


@app.post("/api/errands")
def post_errand(e: PostErrand):
    conn = db.get_conn()
    try:
        _user(conn, e.requester_id)
        # 第一步:平台审核申报内容(三方可见、对外不公开),审核通过才开放发布
        result = audit_rules.review(e.content)
        status = "open" if result["status"] == "approved" else "rejected"
        tag_str = normalize_tags(e.tags)
        cur = conn.execute(
            "INSERT INTO errands(title, description, category, size, pickup, delivery, bounty, "
            "requester_id, pickup_code, content, audit_status, audit_note, status, tags) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (e.title.strip(), e.description, e.category, e.size, e.pickup, e.delivery,
             e.bounty, e.requester_id, e.pickup_code, e.content, result["status"],
             result["note"], status, tag_str))
        conn.commit()
        return {"id": cur.lastrowid, "status": status,
                "audit_status": result["status"], "audit_note": result["note"]}
    finally:
        conn.close()


@app.get("/api/errands")
def list_errands(status: str | None = None, viewer_id: int | None = None,
                 category: str | None = None, size: str | None = None,
                 tag: str | None = None, q: str | None = None):
    conn = db.get_conn()
    try:
        sql = ("SELECT e.*, u.name AS requester FROM errands e "
               "LEFT JOIN users u ON u.id = e.requester_id "
               "WHERE e.status NOT IN ('pending','rejected') ")
        params: list = []
        if status:
            sql += "AND e.status = ? "
            params.append(status)
        if category:
            sql += "AND e.category = ? "
            params.append(category)
        if size:
            sql += "AND e.size = ? "
            params.append(size)
        if tag:
            # 逗号分隔标签的子串匹配(标签已规范化,不会误命中半个词的场景可接受)
            sql += "AND (',' || e.tags || ',') LIKE ? "
            params.append("%," + tag.strip() + ",%")
        if q:
            kw = "%" + q.strip() + "%"
            sql += "AND (e.title LIKE ? OR e.pickup LIKE ?) "
            params.extend([kw, kw])
        sql += "ORDER BY e.created_at DESC"
        rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            # 三方可见、对外不公开:申报内容只对发布方可见;
            # 接单者(顺路者)在接单后(already accepted)知情。
            is_requester = d["requester_id"] == viewer_id
            is_runner = (d["runner_id"] is not None and d["runner_id"] == viewer_id
                         and d["status"] != "open")
            # 方案 C:审核详情(申报内容/审核备注)只对「发布方」与「平台」可见。
            # 接单者(顺路者)看不到具体申报内容 —— 只看到 类别 + 尺寸 + 已审核标记。
            if not is_requester:
                d["content"] = None
                d["audit_note"] = None
            # 隐私保护:取件码与发布者真实姓名只对参与者(发布方/已接单的顺路者)可见,
            # 其余人一律脱敏 —— 避免真实姓名与取件码在公开列表泄露。
            if not (is_requester or is_runner):
                d["pickup_code"] = None
                d["requester"] = "某同学"
            out.append(d)
        return out
    finally:
        conn.close()


@app.post("/api/errands/{eid}/accept")
def accept(eid: int, a: Accept):
    conn = db.get_conn()
    try:
        e = conn.execute("SELECT * FROM errands WHERE id=?", (eid,)).fetchone()
        if not e:
            raise HTTPException(404, "errand not found")
        if e["status"] != "open":
            raise HTTPException(400, "errand already claimed")
        # validate the runner exists BEFORE the UPDATE, or the FK raises a 500
        runner = conn.execute("SELECT id FROM users WHERE id=?", (a.user_id,)).fetchone()
        if not runner:
            raise HTTPException(404, "user not found")
        if e["requester_id"] == a.user_id:
            raise HTTPException(400, "cannot accept your own errand")
        conn.execute(
            "UPDATE errands SET status='accepted', runner_id=?, accepted_at=datetime('now') "
            "WHERE id=?", (a.user_id, eid))
        conn.commit()
        return dict(conn.execute("SELECT * FROM errands WHERE id=?", (eid,)).fetchone())
    finally:
        conn.close()


@app.post("/api/errands/{eid}/deliver")
def deliver(eid: int, d: Deliver):
    conn = db.get_conn()
    try:
        e = conn.execute("SELECT * FROM errands WHERE id=?", (eid,)).fetchone()
        if not e:
            raise HTTPException(404, "errand not found")
        if e["status"] != "accepted":
            raise HTTPException(400, "not accepted yet")
        if e["runner_id"] != d.user_id:
            raise HTTPException(400, "not your errand")
        # escrow release: runner gets bounty, requester pays
        conn.execute("UPDATE users SET balance = balance - ? WHERE id=?",
                     (e["bounty"], e["requester_id"]))
        conn.execute("UPDATE users SET balance = balance + ? WHERE id=?",
                     (e["bounty"], e["runner_id"]))
        conn.execute("UPDATE errands SET status='delivered', delivered_at=datetime('now') WHERE id=?",
                     (eid,))
        conn.commit()
        return dict(conn.execute("SELECT * FROM errands WHERE id=?", (eid,)).fetchone())
    finally:
        conn.close()


# ---------------- 模拟货币:充值 / 查余额(测试阶段,不涉及真实支付) ----------------
@app.post("/api/recharge")
def recharge(r: Recharge):
    """测试阶段的模拟货币充值 —— 一键加币,不接支付网关。"""
    if r.amount <= 0 or r.amount > 10000:
        raise HTTPException(400, "充值金额需在 0 ~ 10000 之间")
    conn = db.get_conn()
    try:
        _user(conn, r.user_id)
        conn.execute("UPDATE users SET balance = balance + ? WHERE id=?", (r.amount, r.user_id))
        conn.commit()
        return dict(conn.execute("SELECT * FROM users WHERE id=?", (r.user_id,)).fetchone())
    finally:
        conn.close()


@app.get("/api/user/{uid}")
def get_user(uid: int):
    """查询用户信息(界面用于同步余额变化)。"""
    conn = db.get_conn()
    try:
        return dict(_user(conn, uid))
    finally:
        conn.close()


# ---------------- platform review view(第三方平台审核视角) ----------------
PLATFORM_KEY = os.getenv("CAMPUS_PLATFORM_KEY", "campus-platform")


@app.get("/api/audit/items")
def audit_items(key: str = "", limit: int = 50):
    """平台(第三方)审核视角:返回申报内容与审核状态。

    仅平台使用、对外不公开 —— 需要口令;接单者与普通用户都拿不到这些字段。
    """
    if key != PLATFORM_KEY:
        raise HTTPException(403, "platform access only")
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT e.id, e.category, e.size, e.status, e.audit_status, e.audit_note, "
            "e.content, e.created_at, u.name AS requester, u.student_id "
            "FROM errands e LEFT JOIN users u ON u.id = e.requester_id "
            "ORDER BY e.id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------- 平台内私聊(全程留痕:只新增,不修改不删除) ----------------
@app.post("/api/messages")
def send_message(m: SendMessage):
    body = m.body.strip()
    if not body:
        raise HTTPException(400, "消息内容不能为空")
    if len(body) > 500:
        raise HTTPException(400, "单条消息不能超过 500 字")
    conn = db.get_conn()
    try:
        if not conn.execute("SELECT 1 FROM users WHERE id=?", (m.from_id,)).fetchone():
            raise HTTPException(404, "发送方不存在")
        if not conn.execute("SELECT 1 FROM users WHERE id=?", (m.to_id,)).fetchone():
            raise HTTPException(404, "接收方不存在")
        e = conn.execute("SELECT * FROM errands WHERE id=?", (m.errand_id,)).fetchone()
        if not e:
            raise HTTPException(404, "任务不存在")
        # 只允许任务参与者(发布方/接单者)之间私聊,避免陌生人骚扰
        pair = {e["requester_id"], e["runner_id"]}
        if m.from_id not in pair or m.to_id not in pair or e["runner_id"] is None:
            raise HTTPException(403, "仅任务发布方与接单者可在该任务下私聊")
        cur = conn.execute(
            "INSERT INTO messages(errand_id, from_id, to_id, body) VALUES (?,?,?,?)",
            (m.errand_id, m.from_id, m.to_id, body))
        conn.commit()
        return dict(conn.execute("SELECT * FROM messages WHERE id=?",
                                 (cur.lastrowid,)).fetchone())
    finally:
        conn.close()


@app.get("/api/messages")
def list_messages(errand_id: int, viewer_id: int):
    conn = db.get_conn()
    try:
        e = conn.execute("SELECT * FROM errands WHERE id=?", (errand_id,)).fetchone()
        if not e:
            raise HTTPException(404, "任务不存在")
        pair = {e["requester_id"], e["runner_id"]}
        if viewer_id not in pair:
            raise HTTPException(403, "仅任务参与者可查看聊天记录")
        rows = conn.execute(
            "SELECT m.*, uf.name AS from_name, ut.name AS to_name "
            "FROM messages m "
            "JOIN users uf ON uf.id = m.from_id "
            "JOIN users ut ON ut.id = m.to_id "
            "WHERE m.errand_id=? ORDER BY m.id ASC", (errand_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------- 顺路程度匹配(任务3) ----------------
@app.post("/api/users/{uid}/routes")
def set_routes(uid: int, r: SetRoutes):
    if r.user_id != uid:
        raise HTTPException(400, "只能设置自己的常跑路线")
    conn = db.get_conn()
    try:
        if not conn.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
            raise HTTPException(404, "user not found")
        # 覆盖式重设:先清空再写入,保持路线列表最新
        conn.execute("DELETE FROM user_routes WHERE user_id=?", (uid,))
        seen = set()
        for tag in r.routes:
            tag = (tag or "").strip()
            if tag and tag not in seen:
                seen.add(tag)
                conn.execute("INSERT OR IGNORE INTO user_routes(user_id, route_tag) VALUES (?,?)",
                             (uid, tag))
        conn.commit()
        rows = conn.execute(
            "SELECT route_tag FROM user_routes WHERE user_id=? ORDER BY route_tag",
            (uid,)).fetchall()
        return {"user_id": uid, "routes": [x["route_tag"] for x in rows]}
    finally:
        conn.close()


@app.get("/api/match")
def match_runners(errand_id: int | None = None, pickup: str | None = None):
    """按顺路程度给待接任务排行潜在接单者。

    分数 = 该用户常跑路线里命中任务取件点的关键词数;同分时悬赏完成数多的优先。
    只返回设置过路线、且不是发布者本人的用户;零分(完全不顺路)不返回。
    """
    conn = db.get_conn()
    try:
        target_pickup, requester_id, bounty = "", None, 0.0
        if errand_id:
            e = conn.execute("SELECT * FROM errands WHERE id=?", (errand_id,)).fetchone()
            if not e:
                raise HTTPException(404, "errand not found")
            if e["status"] != "open":
                raise HTTPException(400, "该任务已被接单或已结束")
            target_pickup, requester_id, bounty = e["pickup"], e["requester_id"], e["bounty"]
        elif pickup:
            target_pickup = pickup
        else:
            raise HTTPException(400, "需要 errand_id 或 pickup 参数")

        users = conn.execute(
            "SELECT id, name FROM users WHERE id IS NOT NULL AND id != ?",
            (requester_id or -1,)).fetchall()
        results = []
        for u in users:
            routes = [r["route_tag"] for r in conn.execute(
                "SELECT route_tag FROM user_routes WHERE user_id=?", (u["id"],)).fetchall()]
            hit = [t for t in routes if t and t in target_pickup]
            if not hit:
                continue
            done = conn.execute(
                "SELECT COUNT(*) AS c FROM errands WHERE runner_id=? AND status='delivered'",
                (u["id"],)).fetchone()["c"]
            # 主分:命中路线数;次分:历史完成数(同分 tie-breaker)
            results.append({
                "user_id": u["id"], "name": u["name"],
                "score": len(hit), "matched_routes": hit,
                "delivered_count": done,
            })
        results.sort(key=lambda x: (x["score"], x["delivered_count"]), reverse=True)
        return {"pickup": target_pickup, "bounty": bounty, "matches": results}
    finally:
        conn.close()


# ---------------- static pages ----------------
@app.get("/")
def index():
    from fastapi.responses import HTMLResponse
    from pathlib import Path as _P
    html = _P(STATIC / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/recharge")
def recharge_page():
    """加值页(独立跳转页面:/recharge)。"""
    from fastapi.responses import HTMLResponse
    html = (STATIC / "recharge.html").read_text(encoding="utf-8")
    return HTMLResponse(html)