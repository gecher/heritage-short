"""Shots: turn each keyframe into a moving clip of the shot's exact length.

Every shot gets a slow, steady camera move on its still image (a "Ken Burns" move): push in,
pull out or pan, chosen from the words in the shot's motion_prompt. It is free, runs on the
laptop and never fails, so the film is always complete. Image-to-video (Wan on a GPU) can
replace single shots later: put a clip in outputs/shots/<id>-i2v.mp4 and the film uses it.

Each clip lasts exactly as long as the shot does in the voice track (a narration longer than
its shot stretches the shot), so picture and sound stay in sync.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from pipeline.common import OUT, ROOT, cache_key, ffmpeg, load_storyboard, log_call

FPS = 24
FORMATS = {"9x16": (1080, 1920), "16x9": (1920, 1080)}   # phones; laptops, TVs and YouTube
W, H = FORMATS["9x16"]


def use(fmt: str) -> None:
    """Switch the output format for the rest of the run."""
    global W, H
    W, H = FORMATS[fmt]
MOVE = 0.10                          # how far a push-in zooms over the whole shot (10%)
FOLDER = OUT / "shots"


def move_for(shot: dict[str, Any], index: int) -> str:
    """Pick a camera move from the motion prompt; alternate in/out so cuts don't feel repetitive."""
    words = (shot.get("motion_prompt") or "").lower()
    if "pan right" in words:
        return "pan_right"
    if "pan left" in words:
        return "pan_left"
    if shot.get("motion") == "still" or "static camera" in words and "push" not in words:
        return "drift"               # static camera: a barely visible breath of movement
    if "pull" in words or "zoom out" in words:
        return "pull_out"
    return "push_in" if index % 2 == 0 or "push" in words else "pull_out"


def filter_for(move: str, seconds: float) -> str:
    n = max(1, round(seconds * FPS))
    if move.startswith("pan"):
        # The square keyframe is wider than a 9:16 frame: slide the frame across it.
        x = f"(iw-ow)*t/{seconds:.3f}" if move == "pan_right" else f"(iw-ow)*(1-t/{seconds:.3f})"
        side = max(H, round(W * 1.25))      # the square keyframe, big enough to slide a W x H window across
        return f"scale={side}:{side},crop={W}:{H}:x='{x}':y=(ih-oh)/2,setsar=1"
    zoom = {"push_in": f"1+{MOVE}*on/{n}", "pull_out": f"{1 + MOVE}-{MOVE}*on/{n}",
            "drift": f"1.02+0.03*on/{n}"}[move]
    # Crop the centre strip in the output's shape, upscale 2x so the slow zoom does not shimmer, then zoom.
    return (f"crop='min(iw,ih*{W}/{H})':'min(ih,iw*{H}/{W})',scale={W * 2}:{H * 2},"
            f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},setsar=1")


DIP = 0.4          # seconds of dip-to-black at a soft transition
PRESENT = "s08"    # the first shot of the present: a hard cut into it, so the change of time is felt


def transitions(board: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """(fade in, fade out) per shot. The memories dissolve softly through black; the present (from
    the city shot) moves in hard cuts, so the change of time is felt; the last shot, back to the
    father, dissolves in. The film's first fade-in and last fade-out are done in the film stage."""
    ids = [s["id"] for s in board["shots"]]
    present = ids.index(PRESENT) if PRESENT in ids else len(ids)
    soft = set()                                  # cut points (between i-1 and i) that dissolve
    for i in range(1, len(ids)):
        if i < present or i == len(ids) - 1:      # the memories, and the return to the father at the end
            soft.add(i)
    return {sid: (DIP if i in soft else 0.0, DIP if i + 1 in soft else 0.0) for i, sid in enumerate(ids)}


def fade_filter(fades: tuple[float, float], seconds: float) -> str:
    f = ""
    if fades[0]:
        f += f",fade=t=in:st=0:d={fades[0]}"
    if fades[1]:
        f += f",fade=t=out:st={seconds - fades[1]:.3f}:d={fades[1]}"
    return f


def clip(shot: dict[str, Any], frame: Path, seconds: float, index: int,
         fades: tuple[float, float] = (0.0, 0.0)) -> Path:
    i2v = FOLDER / f"{shot['id']}-i2v.mp4"
    if i2v.exists():                 # a hand-made or GPU clip wins over the camera move
        return i2v
    move = move_for(shot, index)
    key = cache_key(stage="shots", frame=frame, move=move, seconds=round(seconds, 3), fps=FPS, size=[W, H], v=1,
                    fades=list(fades))
    FOLDER.mkdir(parents=True, exist_ok=True)
    out = FOLDER / f"{shot['id']}-{key}.mp4"
    if out.exists():
        log_call(stage="shots", shot=shot["id"], provider="cache", model="ffmpeg", status="hit", file=out.name)
        return out
    tmp = out.with_name(out.stem + ".partial.mp4")   # an interrupted run must not leave a "cached" half file
    cmd = [ffmpeg(), "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-t", f"{seconds:.3f}",
           "-i", str(frame), "-vf", filter_for(move, seconds) + fade_filter(fades, seconds), "-frames:v", str(round(seconds * FPS)),
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(tmp)]
    subprocess.run(cmd, check=True)
    tmp.replace(out)   # only a complete file gets the cached name (FAILURES F18)
    log_call(stage="shots", shot=shot["id"], provider="local", model="ffmpeg", status="ok",
             params={"move": move, "seconds": round(seconds, 3)}, cost_usd_equiv=0.0)
    print(f"  {shot['id']}: {move:9} {seconds:5.2f}s -> {out.relative_to(ROOT).as_posix()}")
    return out


def run(board: dict[str, Any], lengths: dict[str, float]) -> dict[str, Path]:
    manifest = json.loads((OUT / "keyframes" / "manifest.json").read_text(encoding="utf-8"))
    missing = [s["id"] for s in board["shots"] if s["id"] not in manifest]
    if missing:
        raise SystemExit(f"no keyframe for {', '.join(missing)}: run `python -m pipeline keyframes` first")
    fades = transitions(board)
    return {s["id"]: clip(s, ROOT / manifest[s["id"]]["file"], lengths[s["id"]], i, fades[s["id"]])
            for i, s in enumerate(board["shots"])}
