"""One entry point: python -m pipeline <command>.

  validate   check storyboard.json against the schema and the film rules
  smoke      call every provider once and log it
  narration  Gemini TTS, one cached audio file per shot
  radio      narration over placeholder music on black, with subtitles
  say "..."  speak one test phrase into outputs/narration/_tests (pronunciation trials)
  film       every stage in order (stages are added as we build them)
"""
from __future__ import annotations

import sys

from pipeline.common import STORYBOARD, load_storyboard


def validate() -> None:
    board = load_storyboard()
    total = sum(s["duration"] for s in board["shots"])
    print(f"{STORYBOARD.name} is valid: {len(board['shots'])} shots, {total:.0f}s")


def smoke() -> None:
    from pipeline import smoke as s
    s.main()


def narration() -> None:
    from pipeline import narration as n
    n.run()


def radio() -> None:
    from pipeline import radio as r
    r.run()


def say() -> None:
    from pipeline import narration as n
    if len(sys.argv) < 3:
        raise SystemExit('usage: python -m pipeline say "text to speak"')
    n.say(" ".join(sys.argv[2:]))


COMMANDS = {"say": say, "validate": validate, "smoke": smoke, "narration": narration, "radio": radio}

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    if command not in COMMANDS:
        print(__doc__)
        sys.exit(0 if command == "help" else 2)
    COMMANDS[command]()
