"""
providers.py - the translation services PolyTranslate can talk to.

Three providers, tried in this order until one works:
    1. GoogleCloudProvider  official Cloud Translation API (needs GOOGLE_TRANSLATE_API_KEY)
    2. GoogleFreeProvider   Google Translate web endpoint (no key needed)
    3. MyMemoryProvider     free MyMemory API (no key, small daily quota)

Only the Python standard library is used.
"""
from __future__ import annotations

import html
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

USER_AGENT = "Mozilla/5.0 (compatible; PolyTranslate/1.0; +https://github.com)"


class ProviderError(Exception):
    """A single provider failed (network, quota, bad response). The next one is tried."""


# --------------------------------------------------------------------------
# HTTP + JSON helpers (tests replace `fetch` with a fake)
# --------------------------------------------------------------------------
def fetch(url: str, data: Optional[dict] = None, timeout: float = 8.0) -> str:
    body = urllib.parse.urlencode(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
        raise ProviderError(f"network error ({getattr(exc, 'reason', exc)})") from exc


def _json(body: str):
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ProviderError("service returned an unreadable response") from exc


# --------------------------------------------------------------------------
# Text chunking: services limit request size, so long text is split on
# sentence boundaries (then words, then characters as a last resort).
# --------------------------------------------------------------------------
_SENTENCE_END = re.compile(r"(?<=[.!?\u0964\u0965\u3002\uff01\uff1f])\s+")


def _split_long(piece: str, limit: int, size: Callable[[str], int]) -> list[str]:
    if size(piece) <= limit:
        return [piece]
    out, cur = [], ""
    for word in piece.split(" "):
        while size(word) > limit:                        # a single huge "word"
            n = len(word)
            while n > 1 and size(word[:n]) > limit:
                n -= 1
            if cur:
                out.append(cur)
                cur = ""
            out.append(word[:n])
            word = word[n:]
        candidate = f"{cur} {word}".strip() if cur else word
        if size(candidate) <= limit:
            cur = candidate
        else:
            out.append(cur)
            cur = word
    if cur:
        out.append(cur)
    return out


def chunk_text(text: str, limit: int, size: Callable[[str], int] = len) -> list[str]:
    chunks, cur = [], ""
    for sentence in _SENTENCE_END.split(text.strip()):
        for piece in _split_long(sentence, limit, size):
            candidate = f"{cur} {piece}" if cur else piece
            if size(candidate) <= limit:
                cur = candidate
            else:
                chunks.append(cur)
                cur = piece
    if cur:
        chunks.append(cur)
    return chunks


# --------------------------------------------------------------------------
# Offline script detection - used when a service can't auto-detect the language
# --------------------------------------------------------------------------
_SCRIPTS = [
    (0x0900, 0x097F, "hi"), (0x0980, 0x09FF, "bn"), (0x0A00, 0x0A7F, "pa"), (0x0A80, 0x0AFF, "gu"),
    (0x0B80, 0x0BFF, "ta"), (0x0C00, 0x0C7F, "te"), (0x0C80, 0x0CFF, "kn"), (0x0D00, 0x0D7F, "ml"),
    (0x0600, 0x06FF, "ar"), (0x0590, 0x05FF, "he"), (0x0400, 0x04FF, "ru"), (0x0370, 0x03FF, "el"),
    (0x0E00, 0x0E7F, "th"), (0x3040, 0x30FF, "ja"), (0xAC00, 0xD7AF, "ko"), (0x4E00, 0x9FFF, "zh-CN"),
]


def detect_script(text: str) -> Optional[str]:
    """Best-guess language from the writing system. Returns None if there are no letters."""
    counts: dict[str, int] = {}
    latin = 0
    for ch in text:
        if not ch.isalpha():
            continue
        cp = ord(ch)
        for lo, hi, code in _SCRIPTS:
            if lo <= cp <= hi:
                counts[code] = counts.get(code, 0) + 1
                break
        else:
            latin += 1
    if counts:
        return max(counts, key=counts.get)
    return "en" if latin else None


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------
class Provider:
    name = "provider"
    limit = 1000                                    # max "size" of one request
    size: Callable[[str], int] = staticmethod(len)

    def translate_chunk(self, text: str, source: str, target: str) -> tuple[str, Optional[str]]:
        """Return (translated text, detected source language or None)."""
        raise NotImplementedError


class GoogleCloudProvider(Provider):
    name = "Google Cloud Translation API"
    limit = 4000
    URL = "https://translation.googleapis.com/language/translate/v2"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def translate_chunk(self, text, source, target):
        data = {"q": text, "target": target, "format": "text"}
        if source != "auto":
            data["source"] = source
        url = f"{self.URL}?key={urllib.parse.quote(self.api_key)}"
        payload = _json(fetch(url, data))
        try:
            item = payload["data"]["translations"][0]
            return item["translatedText"], item.get("detectedSourceLanguage")
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("unexpected response from Google Cloud API") from exc


class GoogleFreeProvider(Provider):
    name = "Google Translate"
    limit = 5000                                    # measured on the URL-encoded text
    size = staticmethod(lambda s: len(urllib.parse.quote(s)))
    URL = "https://translate.googleapis.com/translate_a/single"
    CODE_FIX = {"he": "iw"}                         # legacy code for Hebrew

    def translate_chunk(self, text, source, target):
        params = urllib.parse.urlencode({
            "client": "gtx", "sl": self.CODE_FIX.get(source, source),
            "tl": self.CODE_FIX.get(target, target), "dt": "t", "q": text,
        })
        data = _json(fetch(f"{self.URL}?{params}"))
        try:
            translated = "".join(seg[0] for seg in data[0] if seg and seg[0])
        except (TypeError, IndexError) as exc:
            raise ProviderError("unexpected response from Google Translate") from exc
        if not translated.strip():
            raise ProviderError("empty translation")
        detected = data[2] if len(data) > 2 and isinstance(data[2], str) else None
        return translated, ("he" if detected == "iw" else detected)


class MyMemoryProvider(Provider):
    name = "MyMemory"
    limit = 450                                     # API accepts ~500 bytes per request
    size = staticmethod(lambda s: len(s.encode("utf-8")))
    URL = "https://api.mymemory.translated.net/get"

    def __init__(self, email: Optional[str] = None):
        self.email = email                          # optional: raises the free daily quota

    def translate_chunk(self, text, source, target):
        detected = None
        if source == "auto":                        # MyMemory can't detect - guess from the script
            source = detected = detect_script(text) or "en"
        params = {"q": text, "langpair": f"{source}|{target}"}
        if self.email:
            params["de"] = self.email
        payload = _json(fetch(f"{self.URL}?{urllib.parse.urlencode(params)}"))
        try:
            status = int(payload.get("responseStatus", 0))
            translated = payload["responseData"]["translatedText"]
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ProviderError("unexpected response from MyMemory") from exc
        if status != 200 or not translated or "MYMEMORY WARNING" in translated.upper():
            raise ProviderError("MyMemory quota reached or request rejected")
        return html.unescape(translated), detected


def default_providers() -> list[Provider]:
    providers: list[Provider] = []
    key = os.environ.get("GOOGLE_TRANSLATE_API_KEY")
    if key:
        providers.append(GoogleCloudProvider(key))
    providers.append(GoogleFreeProvider())
    providers.append(MyMemoryProvider(os.environ.get("MYMEMORY_EMAIL")))
    return providers
