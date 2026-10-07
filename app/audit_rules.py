"""平台违禁品审核清单(CampusErrand)。

申报内容提交后,平台(脚本/自动规则 + 人工兜底)先对照本清单核查,
仅通过的发布才能在平台上公开。包裹内容仅三方可见、对外不公开。

本项目的违禁/限带范围参照跨境快递与校园平台常见规则,务实用、轻量措辞:
—— 请勿把它写成"承担法律责任"的重话,这是培训式的预防性过滤。
"""

# 违禁 / 限带物品关键词(简化版,供第一版演示过滤)
BANNED_KEYWORDS = [
    # 卷烟、酒精等限制品
    "香烟", "烟", "酒", "酒精",
    # 危险品
    "刀", "刀具", "易燃", "喷雾", "压缩气罐", "电池", "充电宝(超标)",
    # 处方药 / 药物
    "处方药", "药品", "药物",
    # 违禁品
    "违禁", "毒品", "爆炸", "枪", "弹",
]

# 允许但需备注的内容词(仅供提示,不拦截)
WARN_KEYWORDS = {
    "食品": "食品需密封并确保在保质期内",
    "易碎": "易碎品请注明包装加固",
    "贵重": "贵重物品请自行评估风险",
}


def review(content: str) -> dict:
    """对申报内容做平台审核。返回 {status, note}。

    status: approved(通过) | rejected(拦截)
    note:   给发布方/平台看的备注(仅三方可见)。
    """
    text = (content or "").strip()
    if not text:
        return {"status": "rejected", "note": "未填写包裹内容申报,发布未通过(请补充后再提交)"}

    hit = []
    for kw in BANNED_KEYWORDS:
        if kw and kw in text.lower():
            hit.append(kw)
    if hit:
        return {
            "status": "rejected",
            "note": "申报内容命中平台审核规则,发布未通过(涉及物品:" + "、".join(hit) + ")。平台将不公开该信息。",
        }

    warn = [w for k, w in WARN_KEYWORDS.items() if k in text]
    note = "已通过平台审核。"
    if warn:
        note += "注意:" + "；".join(warn) + "。"
    return {"status": "approved", "note": note}