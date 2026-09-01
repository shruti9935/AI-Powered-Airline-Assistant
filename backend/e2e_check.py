"""End-to-end verification against the REAL Gemini API and REAL SMTP.

Unlike backend/tests/ (which mocks the model), this script proves the whole
pipeline: retrieval from the ingested policy document, a grounded answer, a
passenger marking it unhelpful, routing to Baggage Services, and the escalation
email actually leaving over SMTP.

    cd backend
    python rag/ingest.py          # must run first
    python e2e_check.py

Requires GEMINI_API_KEY in .env; SMTP_* must also be set for the email step.
"""
import sys
from pathlib import Path

# The policy document quotes fares in rupees; a cp1252 Windows console
# cannot encode U+20B9 and would abort the report mid-print.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

BAGGAGE_QUESTION = "How much cabin baggage can I carry in economy class?"
FOLLOW_UP = "My bag never arrived at the belt. What do I do now?"


def _fail(message):
    print(f"\n  FAILED: {message}")
    sys.exit(1)


def main():
    print("=" * 70)
    print("END-TO-END CHECK — real Gemini, real SMTP")
    print("=" * 70)

    if not config.GEMINI_API_KEY:
        _fail("GEMINI_API_KEY is not set in .env")

    from fastapi.testclient import TestClient
    import main as app_module

    with TestClient(app_module.app) as client:
        # ---------- 0. preconditions ----------
        health = client.get("/health").json()
        print(f"\n[0] Health: {health}")
        if not health["knowledge_base_ready"]:
            _fail("knowledge base is empty — run `python rag/ingest.py` first")

        from db import Department, Escalation, SessionLocal
        with SessionLocal() as session:
            baggage = (session.query(Department)
                       .filter(Department.name == "Baggage Services").one())
            print(f"    Baggage Services routes to: {baggage.email}")
        smtp_ready = bool(config.SMTP_HOST and config.SMTP_USER and config.SMTP_PASSWORD)
        print(f"    SMTP configured: {smtp_ready}"
              + ("" if smtp_ready else "  (escalation will record but NOT send)"))

        # ---------- 1. auth ----------
        import uuid
        email = f"e2e-{uuid.uuid4().hex[:8]}@example.com"
        token = client.post("/auth/register",
                            json={"email": email, "password": "secret1"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print(f"\n[1] Registered {email}")

        # ---------- 2. RAG: grounded answer from the policy document ----------
        print(f"\n[2] Passenger asks: {BAGGAGE_QUESTION!r}")
        first = client.post("/chat", json={"message": BAGGAGE_QUESTION},
                            headers=headers)
        if first.status_code != 200:
            _fail(f"/chat returned {first.status_code}: {first.text}")
        first = first.json()
        conversation_id = first["conversation_id"]
        print(f"    kind       : {first['kind']}")
        print(f"    confidence : {first['confidence']}")
        print(f"    sources    : {[s['section'] for s in first['sources']]}")
        print(f"    ANSWER     : {first['answer']}")

        if first["kind"] != "grounded":
            _fail(f"expected a grounded answer from the document, got {first['kind']!r}")
        # The shipped policy says 7 kg cabin baggage in economy.
        if "7" not in first["answer"]:
            print("    WARNING: the answer does not quote '7 kg' — check grounding")
        else:
            print("    OK: answer quotes the figure from the policy document")

        # ---------- 3. a baggage complaint in the same thread ----------
        print(f"\n[3] Follow-up: {FOLLOW_UP!r}")
        second = client.post("/chat",
                             json={"message": FOLLOW_UP,
                                   "conversation_id": conversation_id},
                             headers=headers).json()
        print(f"    kind    : {second['kind']}")
        print(f"    ANSWER  : {second['answer']}")
        query_log_id = second["query_log_id"]
        already = second["escalated"]
        print(f"    auto-escalated: {already}")

        # ---------- 4. passenger is dissatisfied ----------
        print("\n[4] Passenger clicks 'Not helpful — talk to a human'")
        res = client.post("/escalate",
                          json={"query_log_id": query_log_id,
                                "reason": "user_marked_unhelpful"},
                          headers=headers)
        if res.status_code != 200:
            _fail(f"/escalate returned {res.status_code}: {res.text}")
        res = res.json()
        print(f"    department : {res['department']}")
        print(f"    status     : {res['status']}")
        print(f"    ASSISTANT  : {res['message']}")

        if res["department"] != "Baggage Services":
            _fail(f"routed to {res['department']!r}, expected 'Baggage Services'")
        print("    OK: routed to Baggage Services")

        if str(config.ESCALATION_SLA_HOURS) not in res["message"]:
            print(f"    WARNING: the notice does not mention "
                  f"{config.ESCALATION_SLA_HOURS} hours")
        else:
            print(f"    OK: notice promises contact within "
                  f"{config.ESCALATION_SLA_HOURS} hours")

        # ---------- 5. did the email actually leave? ----------
        with SessionLocal() as session:
            escalation = session.get(Escalation, res["escalation_id"])
            department = session.get(Department, escalation.department_id)
            body, status, to_addr = escalation.detail, escalation.status, department.email

        print("\n[5] Escalation record")
        print(f"    to     : {to_addr}")
        print(f"    status : {status}")
        for label, needle in [("transcript has the original question", BAGGAGE_QUESTION),
                              ("transcript has the complaint", FOLLOW_UP),
                              ("retrieved policy context included", "RETRIEVED POLICY CONTEXT")]:
            print(f"    {'OK ' if needle in body else 'MISSING'}: {label}")

        print("\n" + "-" * 70)
        print("EMAIL BODY SENT TO " + to_addr)
        print("-" * 70)
        print(body)
        print("-" * 70)

        if status == "emailed":
            print(f"\nRESULT: email dispatched to {to_addr} — check that inbox.")
        else:
            print(f"\nRESULT: escalation recorded as '{status}'. No email was sent "
                  "because SMTP_HOST / SMTP_USER / SMTP_PASSWORD are not all set in .env.")
            sys.exit(2)


if __name__ == "__main__":
    main()
