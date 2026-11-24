"""One entry point: python -m pipeline <command>.

  validate   check storyboard.json against the schema and the film rules
  smoke      call every provider once and log it
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


COMMANDS = {"validate": validate, "smoke": smoke}

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    if command not in COMMANDS:
        print(__doc__)
        sys.exit(0 if command == "help" else 2)
    COMMANDS[command]()
