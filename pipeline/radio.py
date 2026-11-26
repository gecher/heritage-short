"""Radio cut: the narration over placeholder music on a black screen, with English subtitles.

The cheapest prototype of the film. It tests the story and its timing before any picture is
generated (Phase 1 of the brief). Each shot gets a short lead-in, its narration, then silence
up to the shot's duration; a narration longer than its shot stretches the shot and is flagged.
"""
from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path
from typing import Any

from pipeline import narration
from pipeline.common import OUT, ROOT, ffmpeg, load_storyboard

LEAD_IN = 0.4      # seconds of breath before each line
TAIL = 0.6         # minimum pause after each line
RATE = narration.RATE


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def shot_lengths(board: dict[str, Any], manifest: dict[str, Any]) -> dict[str, float]:
    """Each shot's real length: its duration, or longer if its narration needs more room.
    The voice track and the picture both use this, so they stay in sync."""
    out = {}
    for shot in board["shots"]:
        spoken = manifest.get(shot["id"], {}).get("seconds", 0.0)
        out[shot["id"]] = max(shot["duration"], LEAD_IN + spoken + TAIL) if spoken else shot["duration"]
    return out


def voice_track(board: dict[str, Any], manifest: dict[str, Any], out: Path) -> tuple[float, list[tuple[float, float, str]]]:
    """Concatenate the shots' narration with silence; return total seconds and subtitle cues."""
    frames, cues, t = bytearray(), [], 0.0
    for shot in board["shots"]:
        item = manifest.get(shot["id"])
        audio, spoken = b"", 0.0
        if item:
            with wave.open(str(ROOT / item["file"])) as w:
                audio, spoken = w.readframes(w.getnframes()), w.getnframes() / RATE
        length = max(shot["duration"], LEAD_IN + spoken + TAIL)
        if spoken:
            cues.append((t + LEAD_IN, t + LEAD_IN + spoken, shot["subtitle_en"]))
        silence_after = length - LEAD_IN - spoken
        frames += b"\0\0" * int(LEAD_IN * RATE) + audio + b"\0\0" * int(silence_after * RATE)
        t += length
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(bytes(frames))
    return t, cues


def run() -> Path:
    board = load_storyboard()
    manifest = narration.run(board)
    film = OUT / "film"
    film.mkdir(parents=True, exist_ok=True)
    voice, srt, mp4 = film / "radio_voice.wav", film / "radio_cut.srt", film / "radio_cut.mp4"
    total, cues = voice_track(board, manifest, voice)
    srt.write_text("\n".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n"
                             for i, (a, b, text) in enumerate(cues, 1)), encoding="utf-8")
    d = f"{total:.2f}"
    # Placeholder score: a soft D-minor drone (D3, F3, A3), faded in and out. Replaced by ACE-Step later.
    tones = [f"sine=frequency={f}:sample_rate=48000:duration={d}" for f in (146.83, 174.61, 220.0)]
    graph = (
        "[1:a][2:a][3:a]amix=inputs=3:normalize=0,volume=0.05,tremolo=f=0.2:d=0.4,"
        f"afade=t=in:d=2,afade=t=out:st={total - 3:.2f}:d=3,aformat=sample_rates=48000:channel_layouts=stereo[music];"
        "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[v1][v2];"
        "[music][v1]sidechaincompress=threshold=0.02:ratio=6:attack=300:release=1500[ducked];"
        "[v2][ducked]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1:LRA=11[out]"
    )
    cmd = [ffmpeg(), "-y", "-loglevel", "error", "-i", str(voice)]
    for tone in tones:
        cmd += ["-f", "lavfi", "-i", tone]
    cmd += ["-f", "lavfi", "-i", f"color=c=black:s=1080x1920:r=24:d={d}", "-i", str(srt),
            "-filter_complex", graph, "-map", "4:v", "-map", "[out]", "-map", "5:s",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-c:s", "mov_text", "-metadata:s:s:0", "language=eng", "-t", d, str(mp4)]
    subprocess.run(cmd, check=True)
    print(f"radio cut: {mp4.relative_to(ROOT)} ({total:.1f}s, {len(cues)} subtitles)")
    return mp4
