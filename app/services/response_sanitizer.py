import re
from typing import Optional

from agno.utils.log import log_error


_LEAK_START_PATTERNS = [
    re.compile(r"^(now|let's|i should|i need|i'll|therefore|so i|wait,)\b", re.IGNORECASE),
    re.compile(r"^(the (user|instructions?|workflow|tool) )", re.IGNORECASE),
    re.compile(r"^(note|okay|alright)[:,]", re.IGNORECASE),
]


def _looks_like_leaked_reasoning(text: str) -> bool:
    head = text.strip()[:120]
    return any(pattern.match(head) for pattern in _LEAK_START_PATTERNS)


def _dedupe_repeated_suffix(text: str) -> str:
    """Se o texto termina com o mesmo trecho colado duas vezes seguidas (byte a byte), mantém só a última cópia."""
    length = len(text)
    for split_at in range(length // 2, length):
        first, second = text[:split_at], text[split_at:]
        if len(second) > 20 and first.endswith(second):
            return second
    return text


def _normalize_for_compare(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().strip('"\'')).strip().lower()


def _dedupe_duplicate_paragraphs(paragraphs: list) -> Optional[list]:
    """Se a sequência final de parágrafos repete a sequência imediatamente anterior
    (ignorando aspas/espaços — ex: rascunho citado entre aspas, depois reafirmado sem
    aspas), devolve só a última cópia. Cobre o caso em que a duplicação não é
    byte-idêntica e por isso `_dedupe_repeated_suffix` não pega.
    """
    total = len(paragraphs)
    normalized = [_normalize_for_compare(p) for p in paragraphs]
    for dup_len in range(total // 2, 0, -1):
        tail = normalized[total - dup_len:]
        head = normalized[total - 2 * dup_len: total - dup_len]
        if head == tail and all(tail):
            return paragraphs[total - dup_len:]
    return None


def strip_leaked_reasoning(text: Optional[str]) -> Optional[str]:
    """
    Remove rascunhos de raciocínio que ocasionalmente vazam para o texto de
    resposta (em vez de ficarem isolados em `reasoning_content`) — comportamento
    observado no Gemini com "thinking" habilitado, no turno logo após uma tool
    call, e que não é resolvido de forma confiável só por instrução de prompt.

    Heurística: se o texto começa com uma frase típica de narração de processo
    (tipicamente em inglês, mesmo com o resto da conversa em português), tenta
    isolar a resposta real removendo qualquer trecho duplicado ao final ou,
    como segunda tentativa, pegando o último parágrafo que não parece narração.
    """
    if not text or not _looks_like_leaked_reasoning(text):
        return text

    log_error(f"Vazamento de raciocínio detectado no texto da resposta (sanitizando). Original: {text[:300]}")

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    # 1) Duplicação exata (byte a byte) ao final do texto todo.
    deduped = _dedupe_repeated_suffix(text)
    if deduped != text:
        return deduped.strip()

    # 2) Duplicação a nível de parágrafo, ignorando aspas/espaços — cobre o caso do
    # rascunho citado entre aspas e depois reafirmado sem aspas (não é byte-idêntico).
    if len(paragraphs) >= 2:
        deduped_paragraphs = _dedupe_duplicate_paragraphs(paragraphs)
        if deduped_paragraphs is not None:
            return "\n\n".join(deduped_paragraphs).strip(' "')

    # 3) Sem duplicação: acha o último parágrafo que ainda parece narração
    # (inclui os que terminam em ":", tipo "Let's write the response:") e
    # devolve TUDO que vem depois dele — preserva respostas com vários parágrafos.
    last_narration_index = -1
    for index, paragraph in enumerate(paragraphs):
        if _looks_like_leaked_reasoning(paragraph) or paragraph.endswith(":"):
            last_narration_index = index

    if 0 <= last_narration_index < len(paragraphs) - 1:
        return "\n\n".join(paragraphs[last_narration_index + 1:]).strip(' "')

    return paragraphs[-1] if paragraphs else text
