"""Run with:  python -m unittest -v test_translator   (no internet needed - the network is faked)"""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import providers
from core import Translator, TranslationError
from languages import LanguageError, resolve
from providers import (GoogleFreeProvider, MyMemoryProvider, ProviderError, chunk_text,
                       detect_script)
from web_app import make_server


class FakeNet:
    """Replaces providers.fetch. `script` maps a URL fragment to a reply (or an exception)."""

    def __init__(self):
        self.calls = []
        self.google = lambda text, params: json.dumps([[[f"[{params['tl'][0]}] {text}", text]], None, "en"])
        self.mymemory = lambda text, params: json.dumps(
            {"responseStatus": 200, "responseData": {"translatedText": f"MM:{text}"}})

    def __call__(self, url, data=None, timeout=8.0):
        self.calls.append(url)
        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        text = params.get("q", [""])[0]
        if "translate.googleapis.com" in url:
            reply = self.google(text, params)
        elif "mymemory" in url:
            reply = self.mymemory(text, params)
        else:
            raise AssertionError(url)
        if isinstance(reply, Exception):
            raise reply
        return reply


class LanguageTests(unittest.TestCase):
    def test_resolve_variants(self):
        for given, code in {"Hindi": "hi", "KN": "kn", "kanada": "kn", "tamil": "ta", "en-US": "en",
                            "chinese": "zh-CN", "Chinese (Traditional)": "zh-TW", "spnish": "es"}.items():
            self.assertEqual(resolve(given), code, given)

    def test_auto_only_when_allowed(self):
        self.assertEqual(resolve("auto", allow_auto=True), "auto")
        with self.assertRaises(LanguageError):
            resolve("auto")

    def test_unknown_language_suggests(self):
        with self.assertRaises(LanguageError) as ctx:
            resolve("klingon")
        self.assertIn("Unknown language", str(ctx.exception))


class HelperTests(unittest.TestCase):
    def test_chunking_respects_limit(self):
        text = "First sentence here. Second one follows! " * 30
        chunks = chunk_text(text, 100)
        self.assertTrue(all(len(c) <= 100 for c in chunks))
        self.assertEqual(" ".join(chunks).split(), text.split())

    def test_chunking_huge_word_and_bytes(self):
        self.assertTrue(all(len(c) <= 10 for c in chunk_text("x" * 95, 10)))
        size = lambda s: len(s.encode("utf-8"))
        self.assertTrue(all(size(c) <= 30 for c in chunk_text("नमस्ते दुनिया " * 20, 30, size)))

    def test_script_detection(self):
        for text, code in {"नमस्ते": "hi", "ನಮಸ್ಕಾರ": "kn", "வணக்கம்": "ta", "hello": "en",
                           "привет": "ru", "こんにちは": "ja", "12345": None}.items():
            self.assertEqual(detect_script(text), code, text)


class TranslatorTests(unittest.TestCase):
    def setUp(self):
        self.net = FakeNet()
        self._orig = providers.fetch
        providers.fetch = self.net
        self.t = Translator([GoogleFreeProvider(), MyMemoryProvider()], retry_delay=0)

    def tearDown(self):
        providers.fetch = self._orig

    def test_basic_translation_and_detection(self):
        r = self.t.translate("Hello", "kannada")
        self.assertEqual(r.translation, "[kn] Hello")
        self.assertEqual((r.detected, r.target, r.provider), ("en", "kn", "Google Translate"))

    def test_cache_avoids_second_network_call(self):
        self.t.translate("Hello", "hi")
        calls = len(self.net.calls)
        again = self.t.translate("Hello", "hi")
        self.assertTrue(again.cached)
        self.assertEqual(len(self.net.calls), calls)

    def test_same_language_short_circuits(self):
        r = self.t.translate("Hello", "en", source="english")
        self.assertEqual(r.translation, "Hello")
        self.assertEqual(self.net.calls, [])

    def test_falls_back_to_mymemory(self):
        self.net.google = lambda text, params: ProviderError("HTTP 429")
        r = self.t.translate("Hello", "fr")
        self.assertEqual((r.translation, r.provider), ("MM:Hello", "MyMemory"))

    def test_mymemory_quota_message_is_an_error(self):
        self.net.google = lambda text, params: ProviderError("down")
        self.net.mymemory = lambda text, params: json.dumps(
            {"responseStatus": 200, "responseData": {"translatedText": "MYMEMORY WARNING: YOU USED ALL"}})
        with self.assertRaises(TranslationError) as ctx:
            self.t.translate("Hello", "fr")
        self.assertIn("internet connection", str(ctx.exception))

    def test_retry_recovers_from_one_hiccup(self):
        attempts = {"n": 0}
        ok = self.net.google

        def flaky(text, params):
            attempts["n"] += 1
            return ProviderError("timeout") if attempts["n"] == 1 else ok(text, params)
        self.net.google = flaky
        self.assertEqual(self.t.translate("Hello", "de").provider, "Google Translate")

    def test_long_text_is_chunked_and_paragraphs_kept(self):
        text = "Para one. " * 400 + "\n\nPara two."
        r = self.t.translate(text[:4999], "es")
        self.assertIn("\n\n", r.translation)
        self.assertGreater(len(self.net.calls), 1)

    def test_validation(self):
        with self.assertRaises(TranslationError):
            self.t.translate("   ", "hi")
        with self.assertRaises(TranslationError):
            self.t.translate("x" * 6000, "hi")
        with self.assertRaises(LanguageError):
            self.t.translate("Hello", "klingon")

    def test_html_entities_unescaped_from_mymemory(self):
        self.net.google = lambda text, params: ProviderError("down")
        self.net.mymemory = lambda text, params: json.dumps(
            {"responseStatus": 200, "responseData": {"translatedText": "It&#39;s fine"}})
        self.assertEqual(self.t.translate("Está bien", "en", "es").translation, "It's fine")

    def test_mymemory_guesses_source_from_script(self):
        self.net.google = lambda text, params: ProviderError("down")
        seen = {}
        self.net.mymemory = lambda text, params: (seen.update(pair=params["langpair"][0]) or
                                                  json.dumps({"responseStatus": 200,
                                                              "responseData": {"translatedText": "Hello"}}))
        self.t.translate("नमस्ते", "en")
        self.assertEqual(seen["pair"], "hi|en")

    def test_persistence_of_history_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Translator([GoogleFreeProvider()], data_dir=tmp, retry_delay=0)
            first.translate("Hello", "ta")
            again = Translator([], data_dir=tmp)               # no providers: must come from cache
            self.assertTrue(again.translate("Hello", "ta").cached)
            self.assertEqual(len(again.history.items()), 2)

    def test_document_translation_keeps_lines(self):
        out = self.t.translate_document("line one\n\nline two", "hi", block=12)
        self.assertEqual(out.count("\n"), 2)


class WebAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.net = FakeNet()
        cls._orig = providers.fetch
        providers.fetch = cls.net
        cls.server = make_server(Translator([GoogleFreeProvider()], retry_delay=0), port=0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        providers.fetch = cls._orig

    def post(self, path, payload, headers=None, raw=None):
        req = urllib.request.Request(self.base + path, data=raw or json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_page_and_languages(self):
        with urllib.request.urlopen(self.base + "/") as resp:
            self.assertIn(b"PolyTranslate", resp.read())
        with urllib.request.urlopen(self.base + "/api/languages") as resp:
            langs = json.loads(resp.read())["languages"]
        self.assertTrue(any(l["code"] == "kn" and l["speech"] == "kn-IN" for l in langs))

    def test_translate_endpoint(self):
        status, body = self.post("/api/translate", {"text": "Hi there", "target": "hi", "source": "auto"})
        self.assertEqual(status, 200)
        self.assertEqual(body["translation"], "[hi] Hi there")
        self.assertEqual(body["target_name"], "Hindi")

    def test_bad_requests(self):
        self.assertEqual(self.post("/api/translate", {"text": "", "target": "hi"})[0], 400)
        self.assertEqual(self.post("/api/translate", {"text": "x", "target": "zzz"})[0], 400)
        self.assertEqual(self.post("/api/translate", None, raw=b"not json")[0], 400)
        self.assertEqual(self.post("/api/translate", {}, headers={"Content-Type": "text/plain"})[0], 415)

    def test_service_failure_is_502(self):
        self.net.google = lambda text, params: ProviderError("down")
        try:
            status, body = self.post("/api/translate", {"text": "zzz unique", "target": "fr"})
        finally:
            self.net.google = lambda text, params: json.dumps([[[f"[{params['tl'][0]}] {text}", text]], None, "en"])
        self.assertEqual(status, 502)
        self.assertIn("internet", body["error"])

    def test_foreign_host_header_rejected(self):
        req = urllib.request.Request(self.base + "/api/history", headers={"Host": "evil.example.com"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
