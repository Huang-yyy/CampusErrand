"""Key-rotation model client for CampusErrand.

Uses the OLD Ark key first, and automatically switches to the NEW key the instant the
old one stops working (401 / 403 / 429 quota-out). If both keys fail, returns a pure
rule-based local response with a flag so the app still works offline.
"""

import json
import os
import urllib.request
import urllib.error

# --- keys: OLD (use first) and NEW (fallback). Read from a gitignored local file ---
_SECRETS = os.path.join(os.path.dirname(__file__), "..", "secrets.local.json")
OLD_KEY = ""
NEW_KEY = ""
try:
    with open(_SECRETS, encoding="utf-8") as _f:
        _s = json.load(_f)
    OLD_KEY = _s.get("old_ark_key", "")
    NEW_KEY = _s.get("new_ark_key", "")
except Exception:
    pass
# env overrides
OLD_KEY = os.environ.get("CAMPUS_OLD_ARK_KEY", OLD_KEY)
NEW_KEY = os.environ.get("CAMPUS_NEW_ARK_KEY", NEW_KEY)

BASE = "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions"
MODEL = "ark-code-latest"


def _ordered_keys():
    keys = [k for k in (OLD_KEY, NEW_KEY) if k]
    if not keys:
        keys = [key for key in (os.environ.get("CAMPUS_OLD_ARK_KEY"),
                                os.environ.get("CAMPUS_NEW_ARK_KEY")) if key]
    return keys


def chat(prompt, system=None, max_tokens=512, temperature=0.3):
    """Return (text, used_key, switched). switched=True means we fell back to a later key."""
    keys = _ordered_keys()
    for idx, key in enumerate(keys):
        if not key:
            continue
        body = {
            "model": MODEL,
            "messages": [],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            body["messages"].append({"role": "system", "content": system})
        body["messages"].append({"role": "user", "content": prompt})
        req = urllib.request.Request(
            BASE,
            data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
                text = data["choices"][0]["message"]["content"].strip()
                return text, ("new" if idx else "old"), idx > 0
        except urllib.error.HTTPError as e:
            # 401/403/429 = auth/quota out -> definitely switch to next key
            if e.code in (401, 403, 429):
                continue
            # 5xx = maybe transient; still try the next key if there is one
            if e.code >= 500 and idx < len(keys) - 1:
                continue
            # last key also failed hard
            break
        except (urllib.error.URLError, KeyError, ValueError, json.JSONDecodeError):
            # network/parse error on this key: try the next if any
            if idx < len(keys) - 1:
                continue
            break
    return None, "local", False


def suggest_bounty(category, pickup, delivery):
    """Rule-based local suggestion so the UI works even with no model."""
    base = 5.0
    if category == "shopping":
        base = 12.0
    elif category == "meal":
        base = 6.0
    if "Hengqin" in pickup or "横琴" in pickup:
        base += 6.0
    return round(base, 1)