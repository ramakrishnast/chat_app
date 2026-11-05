import asyncio
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm import build_chat_model

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30.0
MAX_WORDS = 8
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def fallback_title(text: str, limit: int = 60) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed or "New chat"
    return collapsed[: limit - 1].rstrip() + "…"


def clean_title(raw: str) -> str | None:
    text = _THINK.sub("", raw).strip()
    if not text:
        return None
    junk = "\"'*#` "
    line = text.splitlines()[0].strip().strip(junk)
    line = re.sub(r"^title\s*:\s*", "", line, flags=re.IGNORECASE).strip().strip(junk).rstrip(".")
    if not line:
        return None
    words = line.split()  # small models often ignore the length instruction
    return " ".join(words[:MAX_WORDS])[:80]


async def generate_title(model_id: str, user_text: str, answer: str) -> str | None:
    prompt = [
        SystemMessage(
            "You name chat conversations. Reply with a 3-6 word title only: no quotes, "
            "no punctuation at the end, no explanation."
        ),
        HumanMessage(f"User: {user_text[:2000]}\n\nAssistant: {answer[:2000]}\n\nTitle:"),
    ]
    try:
        model = build_chat_model(model_id, thinking=False)
        reply = await asyncio.wait_for(model.ainvoke(prompt), timeout=TIMEOUT_SECONDS)
    except Exception as exc:  # titles are best effort
        log.info("title generation skipped", extra={"reason": str(exc) or type(exc).__name__})
        return None
    return clean_title(reply.text)
