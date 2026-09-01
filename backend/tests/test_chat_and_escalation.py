"""Chat threading, the confidence gate, and human-in-the-loop escalation.

Gemini is mocked throughout, so the suite needs no API key and no network.
"""
import json
from unittest.mock import patch

import pytest

CHUNKS = [{
    "id": "airline-rules#baggage#p0",
    "text": "Economy class passengers may carry 7 kg cabin baggage.",
    "section": "1. Baggage Allowance",
    "source": "airline-rules",
    "similarity": 0.81,
}]

LOW_CONFIDENCE_CHUNKS = [dict(CHUNKS[0], similarity=0.20)]


def fake_gemini(kind="grounded", answer="Economy allows 7 kg cabin baggage."):
    def _generate(question, chunks, language, history=None):
        _generate.seen_history = history or []
        return {"answer": answer, "kind": kind}
    _generate.seen_history = []
    return _generate


NOTICE = "Sorry about that. Our {dept} team will contact you within {hours} hours."


@pytest.fixture(autouse=True)
def _stub_escalation_notice():
    """The escalation notice is a second live model call — stub it so this
    module never touches the network."""
    with patch("rag.generator.generate_escalation_notice",
               side_effect=lambda dept, lang, hours=None: NOTICE.format(
                   dept=dept, hours=hours or 24)):
        yield


def run_chat(client, headers, payload, chunks=CHUNKS, generator=None):
    generator = generator or fake_gemini()
    with patch("rag.retriever.retrieve", side_effect=lambda *a, **k: chunks), \
            patch("rag.generator.generate_answer", side_effect=generator):
        return client.post("/chat", json=payload, headers=headers), generator


def test_health_reports_whether_ingest_has_run(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    # 0 indexed chunks is the usual cause of "the bot escalates everything".
    assert body["indexed_chunks"] == 0
    assert body["knowledge_base_ready"] is False


def test_chat_requires_auth(client):
    assert client.post("/chat", json={"message": "hi"}).status_code == 401


def test_chat_opens_a_conversation_and_threads_follow_ups(client, auth_headers):
    first, _ = run_chat(client, auth_headers, {"message": "baggage limit?"})
    assert first.status_code == 200
    conversation_id = first.json()["conversation_id"]
    assert conversation_id

    second, generator = run_chat(
        client, auth_headers,
        {"message": "and business class?", "conversation_id": conversation_id})
    assert second.json()["conversation_id"] == conversation_id
    # The model must see the earlier turn — this is the multi-turn memory.
    assert len(generator.seen_history) == 1
    assert generator.seen_history[0]["query"] == "baggage limit?"


def test_cannot_post_into_another_users_conversation(client, auth_headers):
    first, _ = run_chat(client, auth_headers, {"message": "baggage limit?"})
    conversation_id = first.json()["conversation_id"]

    other = client.post("/auth/register",
                        json={"email": "other@example.com", "password": "secret1"})
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    res, _ = run_chat(client, other_headers,
                      {"message": "hi", "conversation_id": conversation_id})
    assert res.status_code == 404


@pytest.mark.parametrize("message", ["", "   "])
def test_empty_message_rejected(client, auth_headers, message):
    res = client.post("/chat", json={"message": message}, headers=auth_headers)
    assert res.status_code == 422


def test_overlong_message_rejected(client, auth_headers):
    res = client.post("/chat", json={"message": "x" * 5000}, headers=auth_headers)
    assert res.status_code == 422


def test_low_similarity_grounded_answer_escalates(client, auth_headers):
    res, _ = run_chat(client, auth_headers, {"message": "lost my bag"},
                      chunks=LOW_CONFIDENCE_CHUNKS)
    assert res.json()["escalated"] is True


def test_no_answer_escalates(client, auth_headers):
    res, _ = run_chat(client, auth_headers, {"message": "do you fly to Mars?"},
                      generator=fake_gemini(kind="no_answer", answer="Sorry, forwarding this."))
    assert res.json()["escalated"] is True


@pytest.mark.parametrize("kind", ["chat", "off_topic"])
def test_small_talk_and_off_topic_are_never_escalated(client, auth_headers, kind):
    res, _ = run_chat(client, auth_headers, {"message": "hello"},
                      chunks=LOW_CONFIDENCE_CHUNKS,
                      generator=fake_gemini(kind=kind, answer="Hi there!"))
    body = res.json()
    assert body["escalated"] is False
    assert body["sources"] == []


def test_escalation_failure_does_not_discard_the_answer(client, auth_headers):
    """Routing or SMTP breaking must not 500 a request whose answer is ready."""
    with patch("main.escalate", side_effect=RuntimeError("no departments")):
        res, _ = run_chat(client, auth_headers, {"message": "do you fly to Mars?"},
                          generator=fake_gemini(kind="no_answer", answer="Sorry."))
    assert res.status_code == 200
    assert res.json()["answer"] == "Sorry."
    assert res.json()["escalated"] is False


def test_manual_escalation_records_transcript_and_context(client, auth_headers):
    """The README promises the email carries the transcript and retrieved context."""
    first, _ = run_chat(client, auth_headers, {"message": "baggage limit?"})
    conversation_id = first.json()["conversation_id"]
    second, _ = run_chat(client, auth_headers,
                         {"message": "what about my lost bag?",
                          "conversation_id": conversation_id})

    res = client.post("/escalate",
                      json={"query_log_id": second.json()["query_log_id"],
                            "reason": "user_marked_unhelpful"},
                      headers=auth_headers)
    assert res.status_code == 200
    payload = res.json()
    assert payload["status"] == "pending_email"      # no SMTP configured
    assert payload["department"] == "Baggage Services"
    assert payload["sla_hours"] == 24
    # The passenger is told who took the query and when they will hear back.
    assert "Baggage Services" in payload["message"]
    assert "24 hours" in payload["message"]

    db = client.db_module
    with db.SessionLocal() as session:
        escalation = session.query(db.Escalation).one()
        department = session.get(db.Department, escalation.department_id)
        body = escalation.detail
    assert department.name == "Baggage Services"      # keyword routing
    assert "baggage limit?" in body                   # earlier turn
    assert "what about my lost bag?" in body          # escalated turn
    assert "1. Baggage Allowance" in body             # retrieved context


def test_manual_escalation_is_idempotent(client, auth_headers):
    res, _ = run_chat(client, auth_headers, {"message": "baggage limit?"})
    query_log_id = res.json()["query_log_id"]
    first = client.post("/escalate", json={"query_log_id": query_log_id},
                        headers=auth_headers).json()
    second = client.post("/escalate", json={"query_log_id": query_log_id},
                         headers=auth_headers).json()
    assert first["escalation_id"] == second["escalation_id"]
    assert second["detail"] == "Already escalated"


def test_cannot_escalate_another_users_query(client, auth_headers):
    res, _ = run_chat(client, auth_headers, {"message": "baggage limit?"})
    other = client.post("/auth/register",
                        json={"email": "other@example.com", "password": "secret1"})
    headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    escalate = client.post("/escalate",
                           json={"query_log_id": res.json()["query_log_id"]},
                           headers=headers)
    assert escalate.status_code == 404


def test_history_and_conversation_endpoints(client, auth_headers):
    first, _ = run_chat(client, auth_headers, {"message": "baggage limit?"})
    conversation_id = first.json()["conversation_id"]
    run_chat(client, auth_headers,
             {"message": "and refunds?", "conversation_id": conversation_id})

    history = client.get("/chat/history", headers=auth_headers).json()
    assert len(history) == 2
    assert all(row["conversation_id"] == conversation_id for row in history)

    conversations = client.get("/conversations", headers=auth_headers).json()
    assert len(conversations) == 1
    assert conversations[0]["turns"] == 2
    assert conversations[0]["title"] == "baggage limit?"

    thread = client.get(f"/conversations/{conversation_id}", headers=auth_headers).json()
    assert [t["query"] for t in thread["turns"]] == ["baggage limit?", "and refunds?"]


def test_retrieved_context_is_persisted_for_later_escalation(client, auth_headers):
    res, _ = run_chat(client, auth_headers, {"message": "baggage limit?"})
    db = client.db_module
    with db.SessionLocal() as session:
        log = session.query(db.QueryLog).one()
    assert json.loads(log.retrieved_chunk_ids) == [CHUNKS[0]["id"]]
    assert json.loads(log.retrieved_context)[0]["section"] == "1. Baggage Allowance"


def test_upstream_failures_do_not_leak_internals(client, auth_headers):
    with patch("rag.retriever.retrieve",
               side_effect=RuntimeError("connect to https://api?key=SECRET failed")):
        res = client.post("/chat", json={"message": "hi"}, headers=auth_headers)
    assert res.status_code == 502
    assert "SECRET" not in res.text
