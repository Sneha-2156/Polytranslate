"""
cli.py - PolyTranslate in the terminal.

  python cli.py                                  interactive chat-style translator
  python cli.py "Good morning" --to kn           one-shot translation
  python cli.py "Good morning" --to hi --speak   ...and read it aloud
  python cli.py --file notes.txt --to ta         translate a whole file -> notes.ta.txt
  python cli.py --langs                          list supported languages
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from core import Translator, TranslationError
from languages import LANGUAGES, LanguageError, name_of, resolve
from tts import speak

DATA_DIR = Path(__file__).resolve().parent / "data"
RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
CYAN, GREEN, YELLOW, RED = "\033[96m", "\033[92m", "\033[93m", "\033[91m"

HELP = f"""{BOLD}Commands{RESET}
  /to <language>     set the target language        e.g. /to kannada
  /from <language>   set the source ('auto' = detect)  e.g. /from english
  /swap              swap source and target
  /speak on|off      read translations aloud
  /langs [filter]    list supported languages
  /history           show recent translations
  /help  /exit
Anything else you type is translated."""


def setup_terminal():
    os.system("")                                       # enable ANSI colours on Windows 10+
    for stream in (sys.stdout, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def show_languages(filter_text: str = ""):
    items = [(c, n) for c, n in LANGUAGES.items() if filter_text.lower() in f"{c} {n}".lower()]
    if not items:
        print(f"{YELLOW}No language matches '{filter_text}'.{RESET}")
        return
    for i in range(0, len(items), 3):
        print("  " + "".join(f"{c:<6}{n:<24}" for c, n in items[i:i + 3]))


def show_result(result, speak_on: bool):
    shown_source = result.detected or result.source
    note = "cached" if result.cached else result.provider
    print(f"\n  {GREEN}{BOLD}{result.translation.replace(chr(10), chr(10) + '  ')}{RESET}")
    print(f"  {DIM}{name_of(shown_source)} -> {name_of(result.target)}  |  {note}{RESET}\n")
    if speak_on:
        print(f"  {DIM}{speak(result.translation, result.target)}{RESET}\n")


def translate_file(translator: Translator, path: Path, target: str, source: str) -> Path:
    text = path.read_text(encoding="utf-8")
    out = path.with_name(f"{path.stem}.{resolve(target)}{path.suffix or '.txt'}")
    out.write_text(translator.translate_document(text, target, source), encoding="utf-8")
    return out


def interactive(translator: Translator, source: str, target: str, speak_on: bool):
    print(f"{CYAN}{BOLD}PolyTranslate{RESET}  {DIM}{RESET}")
    print(f"{DIM}Type text to translate. /help for commands. Currently: "
          f"{name_of(source)} -> {name_of(target)}{RESET}\n")
    while True:
        try:
            line = input(f"{CYAN}[{name_of(source)} -> {name_of(target)}]{RESET} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line.startswith("/"):
            cmd, _, arg = line.partition(" ")
            cmd, arg = cmd.lower(), arg.strip()
            try:
                if cmd in ("/exit", "/quit"):
                    return
                elif cmd == "/help":
                    print(HELP)
                elif cmd == "/to":
                    target = resolve(arg)
                elif cmd == "/from":
                    source = resolve(arg, allow_auto=True)
                elif cmd == "/swap":
                    if source == "auto":
                        print(f"{YELLOW}Pick a source language first (/from english).{RESET}")
                    else:
                        source, target = target, source
                elif cmd == "/speak":
                    speak_on = arg.lower() in ("on", "yes", "true", "1")
                    print(f"{DIM}Speech is {'on' if speak_on else 'off'}.{RESET}")
                elif cmd == "/langs":
                    show_languages(arg)
                elif cmd == "/history":
                    items = translator.history.items(10)
                    if not items:
                        print(f"{DIM}No history yet.{RESET}")
                    for it in items:
                        print(f"  {DIM}{it['time']}{RESET} {it['text'][:40]!r} -> {it['translation'][:40]!r} "
                              f"{DIM}({it['target_name']}){RESET}")
                else:
                    print(f"{YELLOW}Unknown command. Type /help.{RESET}")
            except LanguageError as exc:
                print(f"{RED}{exc}{RESET}")
            continue
        try:
            show_result(translator.translate(line, target, source), speak_on)
        except (TranslationError, LanguageError) as exc:
            print(f"{RED}{exc}{RESET}\n")


def main():
    parser = argparse.ArgumentParser(description="PolyTranslate - translate text between languages")
    parser.add_argument("text", nargs="*", help="text to translate (omit for interactive mode)")
    parser.add_argument("-t", "--to", default="hi", help="target language (default: hi)")
    parser.add_argument("-f", "--from", dest="source", default="auto", help="source language (default: auto)")
    parser.add_argument("--file", help="translate a text file")
    parser.add_argument("--speak", action="store_true", help="read the translation aloud")
    parser.add_argument("--langs", action="store_true", help="list supported languages")
    args = parser.parse_args()

    setup_terminal()
    if args.langs:
        show_languages()
        return 0
    translator = Translator(data_dir=DATA_DIR)
    try:
        source, target = resolve(args.source, allow_auto=True), resolve(args.to)
        if args.file:
            out = translate_file(translator, Path(args.file), target, source)
            print(f"{GREEN}Saved translation to {out}{RESET}")
            return 0
        if args.text:
            show_result(translator.translate(" ".join(args.text), target, source), args.speak)
            return 0
        interactive(translator, source, target, args.speak)
        return 0
    except (TranslationError, LanguageError, OSError) as exc:
        print(f"{RED}{exc}{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
