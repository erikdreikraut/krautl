import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from app.ki import KIClient, STANDARD_MODELL, _inhalt

TOOL = {"name": "ausgabe", "input_schema": {"type": "object", "properties": {"wert": {"type": "integer"}}, "required": ["wert"]}}


class OpenAITest(unittest.TestCase):
    def setUp(self):
        self.mock = patch("app.ki.OpenAI")
        self.factory = self.mock.start()
        self.addCleanup(self.mock.stop)
        self.create = self.factory.return_value.__enter__.return_value.responses.create
        self.create.return_value = NS(status="completed", usage=None, output=[
            NS(type="function_call", name="ausgabe", arguments='{"wert": 1}')])

    def call(self, text="Privater Inhalt", system="Stabile Regeln", structured=True):
        return KIClient(api_key="test").erzeugen(model=STANDARD_MODELL, max_tokens=1000,
            system=system, messages=[{"role": "user", "content": text}],
            **({"tools": [TOOL], "tool_choice": {"type": "tool", "name": "ausgabe"}} if structured else {}))

    def test_cache_prefix_and_no_storage_or_retries(self):
        self.assertEqual(self.call().content[0].input, {"wert": 1})
        first = self.create.call_args.kwargs
        self.call(text="Andere private Mail")
        second = self.create.call_args.kwargs
        self.assertEqual(first["prompt_cache_key"], second["prompt_cache_key"])
        self.call(system="Geaenderte Regeln")
        self.assertNotEqual(first["prompt_cache_key"], self.create.call_args.kwargs["prompt_cache_key"])
        self.assertFalse(first["store"])
        self.assertEqual(first["prompt_cache_options"], {"mode": "explicit", "ttl": "30m"})
        self.assertNotIn("prompt_cache_breakpoint", first["input"][1]["content"][0])
        self.assertEqual(self.factory.call_args.kwargs["max_retries"], 0)
        self.assertEqual(first["tool_choice"], {"type": "function", "name": "ausgabe"})
        self.assertFalse(first["parallel_tool_calls"])

    def test_incomplete_refusal_invalid_schema_and_multiple_calls_fail_closed(self):
        responses = [
            NS(status="incomplete", usage=None, output=[]),
            NS(status="completed", usage=None, output=[NS(type="message", content=[NS(type="refusal")])]),
            NS(status="completed", usage=None, output=[NS(type="function_call", name="ausgabe", arguments='{"wert": "falsch"}')]),
            NS(status="completed", usage=None, output=[NS(type="function_call", name="falsch", arguments='{}')]),
            NS(status="completed", usage=None, output=self.create.return_value.output * 2),
        ]
        for response in responses:
            with self.subTest(response=response):
                self.create.return_value = response
                with self.assertRaises(RuntimeError):
                    self.call()
        self.assertEqual(self.create.call_count, len(responses))

    def test_text_output_and_usage_without_content_logging(self):
        self.create.return_value = NS(status="completed", output=[NS(type="message", content=[NS(type="output_text", text="Antwort")])],
            usage=NS(input_tokens=2000, output_tokens=30, input_tokens_details=NS(cached_tokens=1500, cache_write_tokens=0)))
        with self.assertLogs("app.ki", level="INFO") as logs:
            self.assertEqual(self.call(structured=False).content[0].text, "Antwort")
        self.assertIn("cached=1500", logs.output[0])
        self.assertNotIn("Privater Inhalt", logs.output[0])

    def test_pdf_image_and_text_inputs(self):
        result = _inhalt([{"type": "text", "text": "Lesen"},
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "cGRm"}},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "cG5n"}}])
        self.assertEqual([b["type"] for b in result], ["input_text", "input_file", "input_image"])
        self.assertEqual(result[1]["file_data"], "data:application/pdf;base64,cGRm")
        self.assertEqual(result[2]["image_url"], "data:image/png;base64,cG5n")
        with self.assertRaises(ValueError):
            _inhalt([{"type": "image", "source": {"type": "url"}}])
