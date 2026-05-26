from __future__ import annotations


class MessageFormatError(ValueError):
    """Raised when a DingTalk message does not contain usable split rules."""


_COMMAND_PREFIXES = ("/pdfsplit", "pdfsplit", "拆分pdf", "拆分 PDF")


def extract_rules_text_from_message(message_text: str) -> str:
    text = (message_text or "").strip()
    if not text:
        raise MessageFormatError("message did not include any split rules")

    lines = [line.rstrip() for line in text.splitlines()]
    if lines and lines[0].strip().lower() in {prefix.lower() for prefix in _COMMAND_PREFIXES}:
        lines = lines[1:]

    cleaned = "\n".join(lines).strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()

    if not cleaned:
        raise MessageFormatError("message did not include any split rules")
    return cleaned
