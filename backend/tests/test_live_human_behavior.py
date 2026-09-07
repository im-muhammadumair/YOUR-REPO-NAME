"""Live human-like test: every account logs in and uses the app.

Exercises the whole user base the way a real person would:
  - logs in with the real stored credentials,
  - waits human-like random pauses between actions,
  - checks the me/profile endpoint plus a couple of self-service endpoints,
  - rotates sessions occasionally (logout + re-login),
  - a few accounts send a real AI chat question over the SSE stream.

Run:  python -m pytest tests/test_live_human_behavior.py -v
"""
import json
import random
import time

from conftest import auth_header, try_login

from database.connection import SessionLocal
from database.models import User
from sqlalchemy import select

AI_QUESTIONS = [
    "What is the IT Security Policy?",
    "How do I apply for annual leave?",
    "What are the employee responsibilities?",
    "Tell me about the company privacy policy",
]

# Deterministic seed so the same accounts are chosen for AI every run.
random.seed(7)


def all_credentials():
    """Return [(username, password)] for every user in the database."""
    db = SessionLocal()
    try:
        rows = db.scalars(select(User)).all()
        return [(u.username, u.password) for u in rows]
    finally:
        db.close()


def _human_pause(lo=0.3, hi=1.2):
    """Sleep a random, human-like pause."""
    time.sleep(random.uniform(lo, hi))


def _chat_ai(client, token, question):
    """Stream one AI question through the SSE endpoint and collect the result."""
    body = {"question": question, "document_id": None, "history": None}
    with client.stream(
        "POST",
        "/api/chat/stream",
        headers=auth_header(token),
        json=body,
    ) as r:
        if r.status_code != 200:
            return {"status": r.status_code, "answer": "", "sources": [], "grounded": False}

        answer_parts = []
        sources = []
        status_events = []
        grounded = False

        for line in r.iter_lines():
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="ignore")
            if not line or not line.startswith("data: "):
                continue
            try:
                frame = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            t = frame.get("type")
            if t == "status":
                status_events.append(frame.get("message", ""))
            elif t == "token":
                answer_parts.append(frame.get("text", ""))
            elif t == "done":
                if frame.get("answer"):
                    answer_parts = [frame["answer"]]
                sources = frame.get("sources", [])
                grounded = frame.get("grounded", False)

    return {
        "status": 200,
        "answer": "".join(answer_parts).strip(),
        "sources": sources,
        "grounded": grounded,
        "status_events": status_events,
    }


def _self_service_checks(client, token):
    """Hit a couple of read-only self-service endpoints; return {path: status}."""
    endpoints = [
        ("/api/me", lambda: client.get("/api/me", headers=auth_header(token)).status_code),
        ("/api/leaves/balance", lambda: client.get("/api/leaves/balance", headers=auth_header(token)).status_code),
        ("/api/attendance?year=2026&month=1", lambda: client.get("/api/attendance?year=2026&month=1", headers=auth_header(token)).status_code),
        ("/api/salary/structure", lambda: client.get("/api/salary/structure", headers=auth_header(token)).status_code),
    ]
    random.shuffle(endpoints)
    results = {}
    for path, fn in endpoints[:2]:
        results[path] = fn()
        _human_pause(0.2, 0.8)
    return results


def test_wrong_password_returns_clear_message(client):
    """A bad login must surface 'Invalid username or password', not a session error."""
    username, _ = all_credentials()[0]
    status, data = try_login(client, username, "definitely-wrong-password")
    assert status == 401
    assert "Invalid username or password" in (data.get("detail") or "")


def test_all_accounts_human_like_usage(client):
    """Every account logs in and uses the app with human-like pauses + AI messages."""
    creds = all_credentials()
    assert len(creds) >= 1

    ai_targets = set(random.sample(range(len(creds)), min(4, len(creds))))
    failures = []
    ai_checked = 0

    for i, (username, password) in enumerate(creds):
        _human_pause(0.5, 2.0)

        status, data = try_login(client, username, password)
        if status != 200:
            failures.append({"username": username, "why": f"login {status} {data}"})
            continue

        token = data["access_token"]
        _human_pause(0.3, 1.0)

        checks = _self_service_checks(client, token)
        bad = {k: v for k, v in checks.items() if v != 200}
        if bad:
            failures.append({"username": username, "why": f"self-service {bad}"})

        if i in ai_targets:
            _human_pause(0.5, 1.5)
            question = AI_QUESTIONS[i % len(AI_QUESTIONS)]
            res = _chat_ai(client, token, question)
            if res["status"] != 200:
                failures.append({"username": username, "why": f"ai http {res['status']}"})
            elif not res["answer"]:
                failures.append({"username": username, "why": f"ai empty answer for {question!r}"})
            ai_checked += 1

        # Occasional session rotation (human-like churn).
        if i % 5 == 0:
            _human_pause(0.3, 0.9)
            client.post(
                "/api/auth/logout",
                headers=auth_header(token),
                json={"refresh_token": data.get("refresh_token")},
            )

    assert not failures, f"{len(failures)} issues: {failures}"
    assert ai_checked >= 1, "at least one AI stream should have been exercised"