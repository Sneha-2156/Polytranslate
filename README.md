# PolyTranslate - Language Translation Tool

**SAM AI Technologies - AI Internship - Task 2: Language Translation Tool**

Translate text between 40+ languages from a **browser app** or the **terminal**. Uses real translation APIs with automatic fallback, auto-detects the source language, and can read translations aloud. Pure Python standard library - nothing to install.

## Task requirements -> how PolyTranslate meets them

| Requirement | Implementation |
|---|---|
| Translate text between languages | 40+ languages incl. Hindi, Kannada, Tamil, Telugu, Malayalam, Marathi, Bengali |
| Take user input text | Web text box (type, paste or dictate) and terminal prompt |
| Use API (Google Translate / similar) | Google Cloud Translation API, Google Translate and MyMemory, tried in order |
| Display translated output | Output pane / coloured terminal output with detected language and provider |
| Optional: voice / text-to-speech | Browser speech (listen + microphone dictation); `--speak` in the terminal |

## Features

- **Three APIs with automatic fallback**: if one is down or out of quota, the next is used.
- **Auto-detect** the source language (offline script detection backs up the MyMemory fallback).
- **Forgiving language input**: `kanada`, `KN`, `en-US`, `chinese` all work.
- **Long text**: split on sentence boundaries, paragraphs preserved (up to 5000 characters; whole files via `--file`).
- **Cache + history**: repeated phrases are instant, and history survives restarts (`data/`).
- **Browser extras**: swap languages, copy, listen, dictate, translate-as-you-type, dark mode, history.
- **Secure local server**: binds to 127.0.0.1, JSON only, rejects foreign Host headers.
- **23 unit tests** with a fake network, so they run without internet.

## Run it

Requires Python 3.9+ and an internet connection for real translations.

```bash
python web_app.py                              # browser app at http://127.0.0.1:8000
python cli.py                                  # interactive terminal translator
python cli.py "Good morning" --to kannada      # one-shot
python cli.py "Good morning" --to hi --speak   # read aloud (needs: pip install gTTS)
python cli.py --file notes.txt --to tamil      # writes notes.ta.txt
python cli.py --langs                          # list languages
python -m unittest -v test_translator          # tests
```

Terminal commands: `/to` `/from` `/swap` `/speak on|off` `/langs` `/history` `/help` `/exit`

## Using the official Google Cloud API (optional)

```bash
export GOOGLE_TRANSLATE_API_KEY="your-key"      # Windows PowerShell: $env:GOOGLE_TRANSLATE_API_KEY="your-key"
```

With a key, the official API becomes the first provider; without it the free endpoints are used.
`MYMEMORY_EMAIL` (optional) raises MyMemory's free daily quota.

## How it works

```
text -> validate -> cache? -> provider 1 -> (fails?) provider 2 -> provider 3 -> result + history
                              each provider: split into chunks -> translate -> join
```

## Project structure

```
polytranslate/
  languages.py   # language list, name/code lookup with typo tolerance
  providers.py   # API clients, chunking, script detection
  core.py        # Translator: fallback, cache, history
  tts.py         # optional terminal text-to-speech
  cli.py         # terminal app
  web_app.py     # local web server
  static/index.html   # browser UI
  test_translator.py
```

## Notes

- Google Translate (free) uses Google's public web endpoint, which is unofficial and may be rate-limited; that's why fallbacks and the official API option exist.
- When Google can't auto-detect, the MyMemory fallback guesses the language from the writing system and assumes English for Latin text. Pick the source language for best results.
- Browser voices depend on your device; install a language voice in your OS settings if one is missing.

---
Built by Sneha for the SAM AI Technologies internship program.
