"""One entry point: python -m pipeline <command>.

  validate   check storyboard.json against the schema and the film rules
  smoke      call every provider once and log it
  narration  Gemini TTS, one cached audio file per shot
  radio      narration over placeholder music on black, with subtitles
  reference  4 candidate portraits of the father; pick one into storyboard.json
  keyframes  every shot's still image: candidates, Gemini judge, best one chosen
  say "..."  speak one test phrase into outputs/narration/_tests (pronunciation trials)
  music      the film score from Lyria (outputs/music/score.wav)
  site       the website's data and assets in web/ (run after film)
  report     COSTS.md from runs.jsonl (calls, errors, cache hits, time)
  film       every stage in order, then the final MP4s (9x16 and 16x9; or name one: film 16x9)
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


def reference() -> None:
    from pipeline import keyframes as k
    k.reference()


def keyframes() -> None:
    from pipeline import keyframes as k
    k.run()


def film() -> None:
    from pipeline import film as f
    wanted = [a for a in sys.argv[2:] if a in ("9x16", "16x9")] or ["9x16", "16x9"]
    for fmt in wanted:          # both by default: vertical for phones, wide for laptops and YouTube
        f.run(fmt)


def music() -> None:
    from pipeline import music as mu
    mu.run()


def site() -> None:
    from pipeline import site as s
    s.run()


def report() -> None:
    from pipeline import report as r
    r.run()


def say() -> None:
    from pipeline import narration as n
    if len(sys.argv) < 3:
        raise SystemExit('usage: python -m pipeline say "text to speak"')
    n.say(" ".join(sys.argv[2:]))


COMMANDS = {"say": say, "validate": validate, "smoke": smoke, "narration": narration, "radio": radio,
            "reference": reference, "keyframes": keyframes, "film": film, "report": report, "music": music, "site": site}

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    if command not in COMMANDS:
        print(__doc__)
        sys.exit(0 if command == "help" else 2)
    COMMANDS[command]()
