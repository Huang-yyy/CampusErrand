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


class Accept(BaseModel):
    user_id: int


class Deliver(BaseModel):
    user_id: int


class Recharge(BaseModel):
    user_id: int
    amount: float = 100.0


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
        cur = conn.execute(
            "INSERT INTO errands(title, description, category, size, pickup, delivery, bounty, "
            "requester_id, pickup_code, content, audit_status, audit_note, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (e.title.strip(), e.description, e.category, e.size, e.pickup, e.delivery,
             e.bounty, e.requester_id, e.pickup_code, e.content, result["status"],
             result["note"], status))
        conn.commit()
        return {"id": cur.lastrowid, "status": status,
                "audit_status": result["status"], "audit_note": result["note"]}
    finally:
        conn.close()


@app.get("/api/errands")
def list_errands(status: str | None = None, viewer_id: int | None = None):
    conn = db.get_conn()
    try:
        sql = ("SELECT e.*, u.name AS requester FROM errands e "
               "LEFT JOIN users u ON u.id = e.requester_id "
               "WHERE e.status NOT IN ('pending','rejected') ")
        params: list = []
        if status:
            sql += "AND e.status = ? "
            params.append(status)
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