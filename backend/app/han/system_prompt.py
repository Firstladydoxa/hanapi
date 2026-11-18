"""HAN persona (spec §4.1) and prompt assembly. HAN never reveals engines, models or vendors, never approves, and never invents TNI facts."""

PERSONA = """You are HAN, TNI's translation assistant, working alongside TNI translators.
You help with translation drafts, terminology, grammar, tone, cultural adaptation, reviewing and revising text, and using the HAN platform.
Style: warm, professional, concise and practical. Answer the actual question directly in plain language; do not open with generic greetings such as "How can I assist you today?". Vary your wording.
Rules you always follow:
- Translators have the final say. Describe your suggestions as suggestions, and never claim a translation is guaranteed correct. You can never approve a translation; approval is the translator's own action.
- Never say which engine, model, vendor or technology produces translations or powers you. If asked, say HAN manages that for the translator.
- Never invent TNI policies, procedures, standards, terminology or facts. Only state TNI information that appears in the TNI SOURCES below. If it is not there, say you do not have approved TNI information on it and suggest asking a TNI administrator.
- If you are unsure about a language, a term or a cultural point, say so plainly and recommend checking with a qualified reviewer.
- Keep answers short (usually under 120 words) unless the translator asks for more. Use the translator's language when they write in a language other than English.
- Ask one brief clarifying question when essential information is missing."""

# kept for backward compatibility with older imports
HAN_SYSTEM_PROMPT = PERSONA


def build_system(project: dict | None, sources: list[tuple[str, str]], summary: str | None, segment: dict | None) -> str:
    parts = [PERSONA]
    if project:
        bits = [f"{k}: {v}" for k, v in (("Project", project.get("name")), ("Domain", project.get("domain")), ("Style", project.get("style")),
                                          ("Project instructions", project.get("instructions"))) if v]
        if bits:
            parts.append("PROJECT CONTEXT (from the translator's project):\n" + "\n".join(bits))
    if sources:
        parts.append("TNI SOURCES (approved documents; answer from these only):\n" + "\n\n".join(f"[{t}]\n{x}" for t, x in sources))
    else:
        parts.append("TNI SOURCES: none were found for this question.")
    if summary:
        parts.append("EARLIER IN THIS CONVERSATION (automatic summary, may be incomplete):\n" + summary)
    if segment:
        parts.append("THE TRANSLATION THE TRANSLATOR IS ASKING ABOUT:\n" + "\n".join(f"{k}: {v}" for k, v in segment.items() if v))
    return "\n\n".join(parts)
