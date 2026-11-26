"""The website: everything the web page needs, built from the pipeline's own outputs.

  python -m pipeline site   ->  web/data.json + web/assets/ (film, frames, voice lines, score stems)

No API calls and no keys: the page is static, so it is free to host (Vercel) and safe to share.
Run it after `python -m pipeline film`, so the page shows the same film you submit.
"""
from __future__ import annotations

import collections
import json
import subprocess
from pathlib import Path
from typing import Any

from pipeline import film, radio, score
from pipeline.common import OUT, ROOT, RUNS, cache_key, ffmpeg, load_storyboard

WEB = ROOT / "web"
ASSETS = WEB / "assets"


def run_ff(*args: str) -> None:
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", *args], check=True)


def thumb(src: Path, name: str, width: int = 540) -> str:
    from PIL import Image
    out = ASSETS / "frames" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src).convert("RGB")
    im.thumbnail((width, width))
    im.save(out, "JPEG", quality=80)
    return f"assets/frames/{name}"


def summary(verdict: dict[str, Any] | None) -> dict[str, Any]:
    v = verdict or {}
    return {k: v.get(k) for k in ("prompt_match", "same_person", "people_look_ethiopian", "cultural_issues",
                                  "artifacts", "note", "judge_model")}


def stats() -> dict[str, Any]:
    rows = [json.loads(line) for line in RUNS.read_text(encoding="utf-8").splitlines() if line.strip()]
    status = collections.Counter(r.get("status") for r in rows)
    by_stage = collections.Counter(r.get("stage") for r in rows if r.get("status") == "ok")
    return {"lines": len(rows), "ok": status["ok"], "errors": status["error"], "rejected": status["rejected"],
            "cache_hits": status["hit"] + status["cache_hit"], "by_stage": dict(by_stage),
            "minutes_waiting": round(sum(r.get("latency_s") or 0 for r in rows) / 60), "dollars": 0}


def run() -> Path:
    board = load_storyboard()
    voice = json.loads((OUT / "narration" / "manifest.json").read_text(encoding="utf-8"))
    frames = json.loads((OUT / "keyframes" / "manifest.json").read_text(encoding="utf-8"))
    review = json.loads((ROOT / "review.json").read_text(encoding="utf-8")) if (ROOT / "review.json").exists() else {}
    lengths = radio.shot_lengths(board, voice)
    ASSETS.mkdir(parents=True, exist_ok=True)

    # 1. the film in both shapes, small enough for the web: the page plays the one that fits the screen
    films = {}
    for fmt, size, name in (("9x16", "720:1280", "film.mp4"), ("16x9", "1280:720", "film_wide.mp4")):
        final = OUT / "film" / f"the_roots_we_carry_{fmt}.mp4"
        if not final.exists():
            if fmt == "9x16":
                raise SystemExit("run `python -m pipeline film` first")
            continue
        run_ff("-i", str(final), "-vf", f"scale={size}", "-c:v", "libx264", "-crf", "27", "-preset", "slow",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart",
               str(ASSETS / name))
        films[fmt] = f"assets/{name}"
    thumb(ROOT / frames["s11"]["file"], "poster.jpg", 720)

    # 2. shots: timing, both languages, Abba's voice for each line, chosen frame, candidates, review
    shots, t = [], 0.0
    for shot in board["shots"]:
        sid, length = shot["id"], lengths[shot["id"]]
        spoken = (voice.get(sid) or {}).get("seconds", 0.0)
        line_audio = None
        if voice.get(sid):
            line_audio = f"assets/lines/{sid}.m4a"
            (ASSETS / "lines").mkdir(parents=True, exist_ok=True)
            run_ff("-i", str(ROOT / voice[sid]["file"]), "-c:a", "aac", "-b:a", "64k", str(WEB / line_audio))
        chosen = frames[sid]["file"]
        cands = [{"img": thumb(ROOT / c["file"], f"{sid}-c{i}.jpg", 360), "score": c["score"],
                  "chosen": c["file"] == chosen, "verdict": summary(c.get("verdict"))}
                 for i, c in enumerate(frames[sid]["candidates"])]
        rev = dict(review.get(sid, {}))
        if rev.get("round1") and (ROOT / rev["round1"]).exists():
            rev["round1_img"] = thumb(ROOT / rev["round1"], f"{sid}-round1.jpg", 360)
        chapter = film.CHAPTERS.get(sid)
        shots.append({
            "id": sid, "start": round(t, 2), "end": round(t + length, 2),
            "line_start": round(t + radio.LEAD_IN, 2), "line_end": round(t + radio.LEAD_IN + spoken, 2),
            "am": shot["narration"], "en": shot["subtitle_en"], "reason": shot["reason"],
            "prompt": frames[sid]["prompt"], "frame": thumb(ROOT / chosen, f"{sid}.jpg"),
            "candidates": cands, "review": rev or None, "line_audio": line_audio,
            "syllables_per_second": (voice.get(sid) or {}).get("syllables_per_second"),
            "chapter": {"numeral": chapter[0], "am": chapter[1], "en": chapter[2]} if chapter else None,
        })
        t += length

    # 3. the score, one file per instrument, for the mixer
    key = cache_key(stage="score", version=score.VERSION, music=board["music"], lengths=lengths, end=film.END_CARD)
    stems_wav = OUT / "music" / f"stems-{key}"
    if not (stems_wav / "kebero.wav").exists():
        print("composing the score's stems (about 30 s)...")
        score.compose_for(board, lengths, film.END_CARD, OUT / "music" / "_stems_mix.wav", stems_wav)
    (ASSETS / "stems").mkdir(parents=True, exist_ok=True)
    for name in ("strings", "masinko", "krar", "kebero"):
        run_ff("-i", str(stems_wav / f"{name}.wav"), "-c:a", "aac", "-b:a", "112k", str(ASSETS / "stems" / f"{name}.m4a"))

    data = {"title_en": film.TITLE_EN, "title_am": film.TITLE_AM, "duration": round(t + film.END_CARD, 2),
            "language": board["language"], "logline": board["logline"], "voice": board["voice"]["name"],
            "music": board["music"], "shots": shots, "stats": stats(), "films": films,
            "github": "https://github.com/gecher/heritage-short"}
    (WEB / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    # the page reads data.js: a plain script works even when index.html is opened by double-click (no server)
    (WEB / "data.js").write_text("window.DATA = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    size = sum(f.stat().st_size for f in WEB.rglob("*") if f.is_file()) / 1e6
    print(f"site: web/ ready ({size:.1f} MB). Open web/index.html through a local server, or deploy web/ to Vercel.")
    return WEB
