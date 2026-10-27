"""
languages.py - supported languages and a forgiving name/code lookup.

resolve("kanada") -> "kn", resolve("Hindi") -> "hi", resolve("en-US") -> "en"
"""
from __future__ import annotations

import difflib

LANGUAGES: dict[str, str] = {
    "af": "Afrikaans", "ar": "Arabic", "bn": "Bengali", "zh-CN": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)", "cs": "Czech", "da": "Danish", "nl": "Dutch",
    "en": "English", "fi": "Finnish", "fr": "French", "de": "German", "el": "Greek",
    "gu": "Gujarati", "he": "Hebrew", "hi": "Hindi", "hu": "Hungarian", "id": "Indonesian",
    "it": "Italian", "ja": "Japanese", "kn": "Kannada", "ko": "Korean", "ml": "Malayalam",
    "mr": "Marathi", "ne": "Nepali", "no": "Norwegian", "fa": "Persian", "pl": "Polish",
    "pt": "Portuguese", "pa": "Punjabi", "ro": "Romanian", "ru": "Russian", "es": "Spanish",
    "sw": "Swahili", "sv": "Swedish", "ta": "Tamil", "te": "Telugu", "th": "Thai",
    "tr": "Turkish", "uk": "Ukrainian", "ur": "Urdu", "vi": "Vietnamese",
}

ALIASES = {
    "chinese": "zh-CN", "mandarin": "zh-CN", "zh": "zh-CN", "bangla": "bn", "farsi": "fa",
    "iw": "he", "panjabi": "pa", "kanada": "kn",
}

# BCP-47 tags used by the browser's speech engine (text-to-speech and dictation)
SPEECH_TAGS = {
    "en": "en-US", "hi": "hi-IN", "kn": "kn-IN", "ta": "ta-IN", "te": "te-IN", "ml": "ml-IN",
    "mr": "mr-IN", "bn": "bn-IN", "gu": "gu-IN", "pa": "pa-IN", "ur": "ur-PK", "ne": "ne-NP",
    "fr": "fr-FR", "de": "de-DE", "es": "es-ES", "it": "it-IT", "pt": "pt-PT", "ru": "ru-RU",
    "ja": "ja-JP", "ko": "ko-KR", "zh-CN": "zh-CN", "zh-TW": "zh-TW", "ar": "ar-SA",
    "tr": "tr-TR", "nl": "nl-NL", "sv": "sv-SE", "pl": "pl-PL", "th": "th-TH", "vi": "vi-VN",
    "id": "id-ID", "el": "el-GR", "he": "he-IL", "uk": "uk-UA", "fa": "fa-IR", "cs": "cs-CZ",
    "da": "da-DK", "fi": "fi-FI", "hu": "hu-HU", "no": "nb-NO", "ro": "ro-RO", "sw": "sw-KE",
    "af": "af-ZA",
}


class LanguageError(ValueError):
    """Raised when a language name or code can't be understood."""


def name_of(code: str) -> str:
    return "Auto-detect" if code == "auto" else LANGUAGES.get(code, code)


def resolve(value: str, allow_auto: bool = False) -> str:
    """Turn a user-typed language (name, code, typo) into a supported language code."""
    text = (value or "").strip()
    if not text:
        raise LanguageError("Please choose a language.")
    low = text.lower()
    if allow_auto and low in ("auto", "detect", "auto-detect", "automatic"):
        return "auto"

    codes = {c.lower(): c for c in LANGUAGES}
    names = {n.lower(): c for c, n in LANGUAGES.items()}
    if low in codes:
        return codes[low]
    if low in ALIASES:
        return ALIASES[low]
    if low in names:
        return names[low]
    base = low.replace("_", "-").split("-")[0]          # "en-US" -> "en"
    if base in codes and base != low:
        return codes[base]

    pool = list(names) + list(ALIASES)
    close = difflib.get_close_matches(low, pool, n=1, cutoff=0.75)
    if close:
        return names.get(close[0]) or ALIASES[close[0]]

    hints = difflib.get_close_matches(low, list(names), n=3, cutoff=0.65)
    extra = f" Did you mean {', '.join(n.title() for n in hints)}?" if hints else ""
    raise LanguageError(f"Unknown language '{text}'.{extra}")
