"""Grounded answer generation with Gemini.

The model classifies each message with a leading marker so the backend can act:
  (no marker)   grounded airline answer from CONTEXT
  [CHAT]        greeting / small talk -> friendly reply, steer to airline help
  [OFF_TOPIC]   unrelated to airline travel -> professional redirect
  [NO_ANSWER]   airline question the CONTEXT cannot answer -> escalate to a human
"""
from typing import Dict, List

import config
from rag.embeddings import gemini_client

NO_ANSWER_MARKER = "[NO_ANSWER]"
CHAT_MARKER = "[CHAT]"
OFF_TOPIC_MARKER = "[OFF_TOPIC]"

SYSTEM_TEMPLATE = """You are the customer-support assistant of SkyWings Airlines. Always reply in {language}.

Decide which case the passenger's message falls into and respond accordingly:

1. GREETING / SMALL TALK in ANY language (e.g. "hi", "hello", "how are you", "thanks",
   "bye", "नमस्ते", "धन्यवाद", "hola", "gracias", "bonjour", "merci"):
   Start your reply with "{chat}" then respond warmly in one or two sentences and
   invite them to ask about flights, baggage, check-in, refunds, delays, or special assistance.

2. UNRELATED TO AIRLINE TRAVEL (e.g. recipes, weather, sports, homework, coding):
   Start your reply with "{off_topic}" then politely and professionally say you can only
   assist with SkyWings airline-related queries, and give one example of what you can help with.
   Do NOT answer the unrelated question, even partially.

3. AIRLINE QUESTION ANSWERABLE FROM CONTEXT:
   Answer ONLY from the policy excerpts in CONTEXT below. Never invent policies, fees,
   or timings. Be concise; quote exact figures from the context. No marker.

4. AIRLINE QUESTION NOT COVERED BY CONTEXT:
   Start your reply with "{no_answer}" then apologise in one short sentence and say the
   query will be forwarded to the right team.

CONTEXT:
{context}

PASSENGER MESSAGE: {question}"""


def generate_answer(question: str, chunks: List[Dict], language_code: str) -> Dict:
    """Return {answer, kind} where kind is grounded | chat | off_topic | no_answer."""
    language = config.SUPPORTED_LANGUAGES.get(
        language_code, "the same language as the message")
    context = "\n\n---\n\n".join(
        "[{0} | {1}]\n{2}".format(c["id"], c["section"], c["text"]) for c in chunks
    ) or "(no relevant excerpts found)"
    prompt = SYSTEM_TEMPLATE.format(
        language=language, chat=CHAT_MARKER, off_topic=OFF_TOPIC_MARKER,
        no_answer=NO_ANSWER_MARKER, context=context, question=question)

    response = gemini_client().models.generate_content(
        model=config.CHAT_MODEL, contents=prompt)
    text = (response.text or "").strip()

    if text.startswith(CHAT_MARKER):
        kind = "chat"
    elif text.startswith(OFF_TOPIC_MARKER):
        kind = "off_topic"
    elif text.startswith(NO_ANSWER_MARKER) or not text:
        kind = "no_answer"
    else:
        kind = "grounded"

    for marker in (CHAT_MARKER, OFF_TOPIC_MARKER, NO_ANSWER_MARKER):
        text = text.replace(marker, "").strip()
    if not text:
        text = ("Sorry — I could not find this in our policies. "
                "Your query is being forwarded to the right team.")
    return {"answer": text, "kind": kind}
