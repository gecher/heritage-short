"""Fast checks of the pipeline's rules. No API calls, no keys, no rendering: `python -m pytest -q`."""
import copy
import json
from pathlib import Path

import pytest

from pipeline import common, narration, radio, shots
from pipeline.common import cache_key, validate

ROOT = Path(__file__).resolve().parent.parent
BOARD = json.loads((ROOT / "storyboard.json").read_text(encoding="utf-8"))


# --- the contract ------------------------------------------------------------------------------

def test_storyboard_is_valid():
    assert validate(BOARD) == []


def test_film_must_be_60_to_90_seconds():
    board = copy.deepcopy(BOARD)
    for s in board["shots"]:
        s["duration"] = 12
    assert any("60-90s" in e for e in validate(board))


def test_duplicate_shot_ids_are_rejected():
    board = copy.deepcopy(BOARD)
    board["shots"][1]["id"] = board["shots"][0]["id"]
    assert any("unique" in e for e in validate(board))


def test_music_cue_must_point_to_a_real_shot():
    board = copy.deepcopy(BOARD)
    board["music"]["cues"][0]["at_shot"] = "s99"
    assert any("s99" in e for e in validate(board))


# --- the cache ---------------------------------------------------------------------------------

def test_cache_key_is_stable_and_order_free():
    assert cache_key(a=1, b="x") == cache_key(b="x", a=1)


def test_cache_key_changes_with_any_input():
    base = cache_key(stage="keyframes", prompt="a jebena", take=1)
    assert base != cache_key(stage="keyframes", prompt="a jebena", take=2)       # a new take
    assert base != cache_key(stage="keyframes", prompt="a jebena.", take=1)      # one character


def test_cache_key_hashes_file_contents(tmp_path):
    f = tmp_path / "ref.jpg"
    f.write_bytes(b"one")
    k1 = cache_key(reference=f)
    f.write_bytes(b"two")                                                          # same name, new bytes
    assert k1 != cache_key(reference=f)


# --- the Ge'ez quality gate --------------------------------------------------------------------

def test_each_fidel_counts_as_one_syllable():
    assert narration.syllables("ልጄ ሆይ") == 4


def test_gate_rejects_a_line_far_too_long_for_its_syllables():
    line = BOARD["shots"][0]["narration"]
    limit = narration.max_plausible_seconds(line)
    assert 5.13 < limit < 18          # the real take (5.13 s) passes; the instruction read aloud (18 s+) fails


# --- timing ------------------------------------------------------------------------------------

def test_long_narration_stretches_its_shot_and_short_does_not():
    manifest = {s["id"]: {"seconds": 1.0} for s in BOARD["shots"]}
    manifest["s01"] = {"seconds": 20.0}
    lengths = radio.shot_lengths(BOARD, manifest)
    assert lengths["s01"] == pytest.approx(radio.LEAD_IN + 20.0 + radio.TAIL)
    assert lengths["s02"] == BOARD["shots"][1]["duration"]


def test_transitions_soft_in_memories_hard_in_the_present():
    t = shots.transitions(BOARD)
    assert t["s03"] == (shots.DIP, shots.DIP)        # a memory: dissolves both ways
    assert t["s08"][0] == 0.0                        # the present arrives with a hard cut
    assert t["s11"][0] == shots.DIP                  # back to the father: a dissolve
    assert t["s01"][0] == 0.0 and t["s11"][1] == 0.0  # the film's own fades are done elsewhere


@pytest.mark.parametrize("fmt,size", [("9x16", (1080, 1920)), ("16x9", (1920, 1080))])
def test_both_formats(fmt, size):
    shots.use(fmt)
    assert (shots.W, shots.H) == size
    shots.use("9x16")
