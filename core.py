"""
core.py - the Translator: validation, caching, provider fallback, history.

    t = Translator(data_dir="data")
    result = t.translate("Hello, how are you?", target="kn")      # source defaults to auto-detect
    print(result.translation, result.detected, result.provider)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from languages import name_of, resolve
from providers import Provider, ProviderError, chunk_text, default_providers

MAX_CHARS = 5000


class TranslationError(Exception):
    """User-facing translation failure (empty text, too long, all services down...)."""


class InputError(TranslationError):
    """The user's text was empty or too long (a 'bad request', not a service failure)."""


@dataclass
class Result:
    text: str
    translation: str
    source: str                      # what was requested ("auto" or a code)
    target: str
    provider: str
    detected: Optional[str] = None   # language the service detected (auto mode)
    cached: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        shown = self.detected or self.source
        d["source_name"], d["target_name"] = name_of(shown), name_of(self.target)
        return d


class _JsonFile:
    """Small JSON file with atomic writes. path=None keeps everything in memory only."""

    def __init__(self, path: Optional[Path], default):
        self.path, self.data = path, default
        if path and Path(path).exists():
            try:
                self.data = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass

    def save(self):
        if not self.path:
            return
        try:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=Path(self.path).parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass


class Cache(_JsonFile):
    """Remembers past translations: instant answers and a little offline replay."""
    MAX = 500

    def __init__(self, path=None):
        super().__init__(path, {})

    def get(self, key):
        return self.data.get(key)

    def put(self, key, value):
        self.data.pop(key, None)
        self.data[key] = value
        while len(self.data) > self.MAX:
            self.data.pop(next(iter(self.data)))         # drop the oldest
        self.save()


class History(_JsonFile):
    MAX = 100

    def __init__(self, path=None):
        super().__init__(path, [])

    def add(self, result: Result):
        item = result.to_dict()
        item["time"] = datetime.now().strftime("%d %b %H:%M")
        self.data.insert(0, item)
        del self.data[self.MAX:]
        self.save()

    def items(self, limit: int = 20) -> list[dict]:
        return self.data[:limit]

    def clear(self):
        self.data.clear()
        self.save()


class Translator:
    def __init__(self, providers: Optional[list[Provider]] = None, data_dir=None,
                 retry_delay: float = 0.4):
        self.providers = providers if providers is not None else default_providers()
        base = Path(data_dir) if data_dir else None
        self.cache = Cache(base / "cache.json" if base else None)
        self.history = History(base / "history.json" if base else None)
        self.retry_delay = retry_delay

    # ----------------------------------------------------------------- public
    def translate(self, text: str, target: str, source: str = "auto") -> Result:
        text = (text or "").strip()
        if not text:
            raise InputError("Please enter some text to translate.")
        if len(text) > MAX_CHARS:
            raise InputError(f"Text is too long ({len(text)} characters). Limit: {MAX_CHARS}.")
        src, tgt = resolve(source, allow_auto=True), resolve(target)
        if src == tgt:
            return Result(text, text, src, tgt, "none (same language)")

        key = hashlib.sha1(f"{src}|{tgt}|{text}".encode("utf-8")).hexdigest()
        hit = self.cache.get(key)
        if hit:
            result = Result(text, hit["translation"], src, tgt, hit["provider"],
                            hit.get("detected"), cached=True)
            self.history.add(result)
            return result

        errors = []
        for provider in self.providers:
            try:
                translation, detected = self._run(provider, text, src, tgt)
            except ProviderError as exc:
                errors.append(f"{provider.name}: {exc}")
                continue
            if src == "auto" and detected and detected.lower() == tgt.lower():
                translation = text                       # already in the target language
            result = Result(text, translation, src, tgt, provider.name, detected)
            self.cache.put(key, {"translation": translation, "provider": provider.name,
                                 "detected": detected})
            self.history.add(result)
            return result
        raise TranslationError("All translation services failed (" + "; ".join(errors) +
                               "). Check your internet connection and try again.")

    def translate_document(self, text: str, target: str, source: str = "auto",
                           block: int = 4000) -> str:
        """Translate text longer than MAX_CHARS, keeping its line structure."""
        blocks, cur = [], ""
        for line in text.splitlines():
            if cur and len(cur) + len(line) + 1 > block:
                blocks.append(cur)
                cur = ""
            cur = f"{cur}\n{line}" if cur else line
        if cur:
            blocks.append(cur)
        out = []
        for b in blocks:
            if not b.strip():
                out.append(b)
                continue
            lead, core, trail = re.match(r"^(\s*)(.*?)(\s*)$", b, re.S).groups()   # keep blank lines
            out.append(lead + self.translate(core, target, source).translation + trail)
        return "\n".join(out)

    # ---------------------------------------------------------------- private
    def _run(self, provider: Provider, text: str, src: str, tgt: str):
        """Translate line by line (keeps paragraphs); each line is chunked to fit the service."""
        detected, lines = None, []
        for line in text.splitlines():
            if not line.strip():
                lines.append("")
                continue
            parts = []
            for chunk in chunk_text(line, provider.limit, provider.size):
                translated, det = self._with_retry(provider, chunk, src, tgt)
                detected = detected or det
                parts.append(translated)
            lines.append(" ".join(parts))
        return "\n".join(lines), detected

    def _with_retry(self, provider, chunk, src, tgt, attempts: int = 2):
        for attempt in range(attempts):
            try:
                return provider.translate_chunk(chunk, src, tgt)
            except ProviderError:
                if attempt == attempts - 1:
                    raise
                time.sleep(self.retry_delay)
