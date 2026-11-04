"""Gemeinsamer OpenAI-Zugang ohne Aktionen oder automatischen Provider-Fallback."""
import hashlib
import json
import logging
import os
from types import SimpleNamespace

from openai import OpenAI
from jsonschema import validate, ValidationError

STANDARD_MODELL = os.getenv("OPENAI_TEXT_MODEL", "gpt-6.1-sol")
SCHNELLES_MODELL = os.getenv("OPENAI_FAST_MODEL", "gpt-6-luna")
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
if not log.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    log.addHandler(handler)
log.propagate = False


def _inhalt(content):
    if isinstance(content, str):
        return [{"type": "input_text", "text": content}]
    result = []
    for block in content:
        if block["type"] == "text":
            result.append({"type": "input_text", "text": block["text"]})
        elif block["type"] in {"document", "image"}:
            source = block["source"]
            if source["type"] != "base64":
                raise ValueError("Nur eingebettete Dokumente und Bilder sind erlaubt")
            data = f"data:{source['media_type']};base64,{source['data']}"
            if block["type"] == "document":
                if source["media_type"] != "application/pdf":
                    raise ValueError("Nicht unterstütztes Dokumentformat")
                result.append({"type": "input_file", "filename": "dokument.pdf", "file_data": data})
            else:
                result.append({"type": "input_image", "image_url": data, "detail": "high"})
        else:
            raise ValueError("Nicht unterstützter KI-Inhalt")
    return result


class KIClient:
    def __init__(self, *, api_key=None, timeout=120.0, max_retries=0):
        self.options = {"timeout": timeout, "max_retries": max_retries}
        if api_key:
            self.options["api_key"] = api_key

    def erzeugen(self, *, model, max_tokens, system, messages, tools=None, tool_choice=None):
        if not model.startswith("gpt-6"):
            raise ValueError("Die Text-KI benötigt ein konfiguriertes GPT-6-Modell")
        definitions = [{"type": "function", "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t["input_schema"], "strict": False} for t in tools or []]
        prefix = json.dumps([model, system, definitions], ensure_ascii=False, sort_keys=True)
        request = dict(
            model=model, store=False, reasoning={"effort": "low"},
            # Responses zählt auch interne Reasoning-Tokens zum Ausgabelimit.
            max_output_tokens=max_tokens + 4096,
            prompt_cache_key="krautl-" + hashlib.sha256(prefix.encode()).hexdigest()[:32],
            # Nur wiederverwendbaren System-/Tool-Kontext schreiben, keine Einzelmails.
            prompt_cache_options={"mode": "explicit", "ttl": "30m"},
            input=[{"role": "developer", "content": [{"type": "input_text", "text": system,
                    "prompt_cache_breakpoint": {"mode": "explicit"}}]}]
                  + [{"role": m["role"], "content": _inhalt(m["content"])} for m in messages],
        )
        if definitions:
            if not tool_choice or tool_choice.get("name") not in {t["name"] for t in definitions}:
                raise ValueError("Strukturierte KI-Ausgabe benötigt ein eindeutiges Zielschema")
            request.update(tools=definitions, parallel_tool_calls=False,
                           tool_choice={"type": "function", "name": tool_choice["name"]})
        with OpenAI(**self.options) as client:
            response = client.responses.create(**request)
        usage = response.usage
        if usage:
            details = usage.input_tokens_details
            log.info("KI provider=openai model=%s input=%s cached=%s cache_write=%s output=%s status=%s",
                     model, usage.input_tokens, getattr(details, "cached_tokens", 0),
                     getattr(details, "cache_write_tokens", 0), usage.output_tokens, response.status)
        if response.status != "completed":
            raise RuntimeError("KI-Ausgabe unvollständig; es wurde kein Ergebnis übernommen")
        blocks = []
        for item in response.output:
            if item.type == "function_call":
                if not tool_choice or item.name != tool_choice["name"]:
                    raise RuntimeError("Unerwartetes KI-Ausgabeformat")
                data = json.loads(item.arguments)
                if not isinstance(data, dict):
                    raise RuntimeError("KI-Ausgabe ist kein Datenobjekt")
                schema = next(t["input_schema"] for t in tools if t["name"] == item.name)
                try:
                    validate(data, schema)
                except ValidationError:
                    raise RuntimeError("KI-Ausgabe entspricht nicht dem erwarteten Datenschema") from None
                blocks.append(SimpleNamespace(type="tool_use", name=item.name, input=data))
            elif item.type == "message":
                for content in item.content:
                    if content.type == "refusal":
                        raise RuntimeError("Die KI hat die Verarbeitung abgelehnt")
                    if content.type == "output_text" and content.text.strip():
                        blocks.append(SimpleNamespace(type="text", text=content.text))
        if definitions:
            blocks = [b for b in blocks if b.type == "tool_use"]
            if len(blocks) != 1:
                raise RuntimeError("Keine eindeutige strukturierte KI-Ausgabe erhalten")
        elif not blocks:
            raise RuntimeError("Keinen KI-Antworttext erhalten")
        return SimpleNamespace(content=blocks, stop_reason="tool_use" if definitions else "end_turn")
