"""LLM-движок: синглтон Llama + цикл генерации с tool calling."""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from typing import Any

from llama_cpp import Llama

from config import settings
from . import prompts, tools

log = logging.getLogger(__name__)

_llama: Llama | None = None
_MAX_TOOL_ROUNDS = 2
_THINK_CLOSE = "</think>"


def _strip_thinking(text: str) -> str:
    """Удалить thinking из финального ответа для пользователя.

    Qwen3.5 finetune использует формат: thinking (иногда без открывающего
    тега), затем </think>, затем финальный ответ. Иногда thinking
    не закрывается (генерация обрывается по max_tokens) — в этом случае
    возвращаем пустую строку, чтобы не показать пользователю сырой CoT.
    """
    if not text:
        return ""
    if _THINK_CLOSE in text:
        return text.split(_THINK_CLOSE, 1)[1].strip()
    if "<think>" in text:
        return ""
    return text.strip()


def _extract_thinking(text: str) -> str:
    """Достать thinking-часть из сырого ответа модели."""
    if not text:
        return ""
    if _THINK_CLOSE in text:
        return text.split(_THINK_CLOSE, 1)[0].replace("<think>", "").strip()
    if "<think>" in text:
        return text.replace("<think>", "").strip()
    return ""


def _log_thinking(message: dict[str, Any], round_idx: int) -> None:
    """Вывести thinking модели в консоль."""
    content = message.get("content") or ""
    reasoning = message.get("reasoning_content") or ""
    thinking = _extract_thinking(content) or reasoning
    if thinking:
        log.info("[round %d] THINKING:\n%s", round_idx, thinking)


def _clean_assistant_for_history(message: dict[str, Any]) -> dict[str, Any]:
    """Подготовить ассистентское сообщение для повторной отправки модели.

    Вырезает закрытый thinking (если есть), но сохраняет <tool_call> блоки и
    поле tool_calls. Unclosed thinking оставляем как есть —model сама разберётся.
    """
    out: dict[str, Any] = {"role": message.get("role", "assistant")}
    content = message.get("content") or ""
    if _THINK_CLOSE in content:
        content = content.split(_THINK_CLOSE, 1)[1].strip()
    if content:
        out["content"] = content
    if message.get("tool_calls"):
        out["tool_calls"] = message["tool_calls"]
    return out


def get_llama() -> Llama:
    """Ленивая инициализация синглтона Llama(). Потокобезопасная через GIL."""
    global _llama
    if _llama is None:
        log.info("Loading model: %s", settings.model_path)
        _llama = Llama(
            model_path=str(settings.model_path),
            n_gpu_layers=settings.n_gpu_layers,
            n_ctx=settings.n_ctx,
            verbose=False,
        )
        log.info("Model loaded. n_ctx=%d, n_gpu_layers=%d", settings.n_ctx, settings.n_gpu_layers)
    return _llama


def _disable_thinking(llm: Llama) -> None:
    """Отключить thinking mode, перезаписав chat template handler.

    Qwen3 chat template генерирует '<think>\\n' (thinking enabled) или
    '<think>\\n\\n</think>\\n\\n' (thinking disabled) в зависимости от
    переменной enable_thinking. llama-cpp-python 0.3.31 не позволяет
    передать эту переменную через create_chat_completion, поэтому мы
    патчим template, чтобы всегда вставлять пустой thinking-блок.
    """
    from llama_cpp import llama_chat_format

    template = llm.metadata.get("tokenizer.chat_template", "")
    if not template or "enable_thinking" not in template:
        return

    patched = template.replace(
        "{%- if enable_thinking is defined and enable_thinking is false %}\n"
        "    {{- '<think>\\n\\n</think>\\n\\n' }}\n"
        "{%- else %}\n"
        "    {{- '<think>\\n' }}\n"
        "{%- endif %}",
        "{{- '<think>\\n\\n</think>\\n\\n' }}",
    )
    if patched == template:
        patched = template.replace(
            "{%- if enable_thinking is defined and enable_thinking is false %}",
            "{%- if true %}",
        )

    eos_token = llm.metadata.get("tokenizer.ggml.eos_token", "<|im_end|>")
    bos_token = llm.metadata.get("tokenizer.ggml.bos_token", "")
    eos_token_id = int(llm.metadata.get("tokenizer.ggml.eos_token_id", 151645))

    formatter = llama_chat_format.Jinja2ChatFormatter(
        template=patched,
        eos_token=eos_token,
        bos_token=bos_token,
        stop_token_ids=[eos_token_id],
    )
    llm._chat_handlers[llm.chat_format] = formatter.to_chat_handler()
    log.info("Thinking mode disabled via template patch")


def _chat_sync(
    messages: list[dict[str, Any]],
    tools_def: list[dict[str, Any]] | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    llama = get_llama()
    kwargs: dict[str, Any] = {
        "messages": messages,
        "max_tokens": max_tokens or settings.max_tokens,
        "temperature": settings.temperature,
        "top_p": settings.top_p,
        "repeat_penalty": settings.repeat_penalty,
    }
    if tools_def:
        kwargs["tools"] = tools_def
    return llama.create_chat_completion(**kwargs)


def _extract_content(message: dict[str, Any]) -> str:
    """Достать текстовый контент из ответа модели (ignoring reasoning_content).

    Если модель не использует <think> теги — отдаём контент как есть.
    Если использует (как Qwen3.5) —剥离 thinking и возвращаем только финал.
    """
    content = message.get("content") or ""
    return _strip_thinking(content)


async def chat(
    messages: list[dict[str, str]],
    *,
    use_tools: bool = True,
    max_tokens: int | None = None,
) -> str:
    """Основной цикл: генерация → tool calls → повтор. До _MAX_TOOL_ROUNDS."""
    current: list[dict[str, Any]] = list(messages)
    tools_def = tools.TOOL_DEFINITIONS if use_tools else None

    last_resp: dict[str, Any] = {}
    for round_idx in range(_MAX_TOOL_ROUNDS):
        last_resp = await asyncio.to_thread(_chat_sync, current, tools_def, max_tokens)
        message = last_resp["choices"][0]["message"]
        _log_thinking(message, round_idx)

        tool_calls = message.get("tool_calls")
        if not tool_calls and use_tools:
            # Фоллбэк: модели с Hermes-style tool calling кладут вызовы прямо в content
            raw_content = message.get("content") or ""
            if "<tool_call>" in raw_content:
                parsed = tools.parse_hermes_tool_calls(raw_content)
                if parsed:
                    tool_calls = parsed
                    # Присваиваем tool_calls в message, чтобы chat template
                    # корректно отрендерил последующий role=tool ответ.
                    message = dict(message)
                    message["tool_calls"] = parsed
                    log.info("parsed %d hermes-style tool call(s)", len(parsed))

        if not tool_calls:
            return _extract_content(message)

        # Добавляем ассистентское сообщение в историю (с tool_calls field).
        # _clean_assistant_for_history вырезает закрытый thinking, но оставляет
        # <tool_call> блок и поле tool_calls — это критично для следующей итерации.
        current.append(_clean_assistant_for_history(message))

        for tc in tool_calls:
            fn = tc.get("function", {}) or {}
            name = fn.get("name", "")
            raw_args = fn.get("arguments")
            if isinstance(raw_args, str):
                try:
                    import json as _json

                    args = _json.loads(raw_args or "{}")
                except Exception as e:
                    log.warning("bad tool arguments: %s", e)
                    args = {}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}
            try:
                result = await asyncio.to_thread(tools.dispatch_tool, name, args)
            except Exception as e:
                log.exception("tool dispatch error")
                result = f"Ошибка вызова инструмента: {e}"
            current.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result,
                }
            )

    log.warning("tool-call loop hit max rounds (%d)", _MAX_TOOL_ROUNDS)
    return _extract_content(last_resp["choices"][0]["message"]) or "(превышен лимит обращений к инструментам)"


async def summarize_day(messages: list[dict[str, Any]], date_str: str) -> str:
    """Сводка за день. Без tools — чистая генерация."""
    prompt = prompts.SUMMARY_PROMPT_TEMPLATE.format(
        date=date_str,
        messages=_format_history_messages(messages),
    )
    return await chat(
        messages=[
            {"role": "system", "content": "Ты ассистент. Отвечай только на русском."},
            {"role": "user", "content": prompt},
        ],
        use_tools=False,
        max_tokens=4096,
    )


async def compact_dialog_for_memory(
    dialog: list[dict[str, str]],
    previous_memory: str,
) -> str:
    """Сжать текущий диалог в текст для memory.json."""
    prompt = prompts.MEMORY_UPDATE_PROMPT_TEMPLATE.format(
        previous_memory=previous_memory or "(память пуста)",
        dialog=_format_dialog(dialog),
    )
    return await chat(
        messages=[
            {"role": "system", "content": "Ты ассистент. Отвечай только на русском."},
            {"role": "user", "content": prompt},
        ],
        use_tools=False,
        max_tokens=4096,
    )


def _format_history_messages(messages: list[dict[str, Any]]) -> str:
    lines = []
    for m in messages:
        ts = float(m.get("ts") or 0)
        hhmm = _dt.datetime.fromtimestamp(ts).strftime("%H:%M")
        uname = m.get("username") or m.get("first_name") or "?"
        text = (m.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"[{hhmm}] @{uname}: {text}")
    return "\n".join(lines) if lines else "(сообщений не было)"


def _format_dialog(dialog: list[dict[str, str]]) -> str:
    lines = []
    for m in dialog:
        role = "Пользователь" if m["role"] == "user" else "Ассистент"
        lines.append(f"{role}: {m['content']}")
    return "\n".join(lines) if lines else "(диалог пуст)"


def _strip_message_for_history(message: dict[str, Any]) -> dict[str, Any]:
    """Алиас для _clean_assistant_for_history — сохраняет backward compat."""
    return _clean_assistant_for_history(message)
