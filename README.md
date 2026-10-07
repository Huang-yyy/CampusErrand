# -*- coding: utf-8 -*-
"""
CampusErrand - campus errand-bounty platform. Local dev prototype.

Backend: Python FastAPI + SQLite (stdlib sqlite3, no ORM).
Frontend: static HTML/JS served by FastAPI.
Auth: lightweight (name + student id), real auth out of scope for the demo.
Money: virtual balance (escrow), no real payments.

Run:
    uvicorn app.main:app --reload --port 8000
or:
    python -m app  (see __main__)

Key-rotation proxy lives in app/llm.py so the SAME app can switch from the
old Ark key to the new one the moment the old one runs out.
"""