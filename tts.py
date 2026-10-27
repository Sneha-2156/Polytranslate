"""
tts.py - optional text-to-speech for the command line.

Works with whichever library you have installed (both are optional):
    pip install gTTS       online, natural voices, covers all the Indian languages
    pip install pyttsx3    offline, uses the voices installed on your computer

(The web app speaks through your browser instead, so it needs neither.)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from languages import LANGUAGES

_GTTS_CODES = {"he": "iw"}


def _play(path: Path):
    if sys.platform.startswith("win"):
        os.startfile(str(path))                       # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.run(["afplay", str(path)], check=False)
        return
    players = (["mpg123", "-q"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
               ["mpv", "--really-quiet"], ["cvlc", "--play-and-exit"])
    for cmd in players:
        if shutil.which(cmd[0]):
            subprocess.run([*cmd, str(path)], check=False)
            return
    if shutil.which("xdg-open"):
        subprocess.run(["xdg-open", str(path)], check=False)
        return
    raise RuntimeError("no audio player found (install mpg123 or ffmpeg)")


def _speak_gtts(text: str, lang: str) -> str:
    from gtts import gTTS                              # imported lazily: optional dependency
    path = Path(tempfile.gettempdir()) / f"polytranslate_{abs(hash((text, lang)))}.mp3"
    gTTS(text=text, lang=_GTTS_CODES.get(lang, lang)).save(str(path))
    _play(path)
    return "Spoken with gTTS."


def _speak_pyttsx3(text: str, lang: str) -> str:
    import pyttsx3                                     # imported lazily: optional dependency
    engine = pyttsx3.init()
    wanted = lang.split("-")[0].lower()
    language_name = LANGUAGES.get(lang, "").split(" ")[0].lower()
    matched = False
    for voice in engine.getProperty("voices"):
        langs = [(l.decode(errors="ignore") if isinstance(l, bytes) else str(l)).lower()
                 for l in (voice.languages or [])]
        if any(wanted in l for l in langs) or (language_name and language_name in voice.name.lower()):
            engine.setProperty("voice", voice.id)
            matched = True
            break
    engine.say(text)
    engine.runAndWait()
    return "Spoken with pyttsx3 (offline)." if matched else \
        "Spoken with pyttsx3, but no voice for this language is installed - pronunciation may be off."


def speak(text: str, lang: str) -> str:
    """Speak `text` in `lang`. Returns a short status message (never raises)."""
    problems = []
    for engine in (_speak_gtts, _speak_pyttsx3):
        try:
            return engine(text, lang)
        except ImportError:
            continue
        except Exception as exc:                       # network, audio device, player...
            problems.append(f"{engine.__name__.replace('_speak_', '')}: {exc}")
    if problems:
        return "Couldn't speak: " + "; ".join(problems)
    return ("Text-to-speech isn't installed. Run  pip install gTTS  (online, many languages) "
            "or  pip install pyttsx3  (offline).")
