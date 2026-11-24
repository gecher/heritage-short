"""What every stage shares: paths, the validated storyboard, the cache, retries and the call log.

Cache rule (the lesson from reviewing an answer cache): a key must hold EVERYTHING the output
depends on - stage, model, every parameter, the prompt text, the seed and the bytes of any input
file. Change any of them and the key changes, so only that shot regenerates. Miss one and you
serve a stale result.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"
RUNS = ROOT / "runs.jsonl"
STORYBOARD = ROOT / "storyboard.json"
SCHEMA = ROOT / "schema" / "storyboard.schema.json"
WORDS_PER_SECOND = (1.6, 2.6)  # a narration pace range; tune it against your own TTS output

load_dotenv(ROOT / ".env")


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    return value if value else default


def ffmpeg() -> str:
    """The ffmpeg executable: FFMPEG_BIN from .env, else the one on PATH."""
    import shutil
    found = env("FFMPEG_BIN") or shutil.which("ffmpeg")
    if not found:
        raise SystemExit("ffmpeg not found: install it (winget install ffmpeg), reopen the terminal, "
                         "or set FFMPEG_BIN in .env to the full path of ffmpeg.exe")
    return found


# --- the contract ------------------------------------------------------------------------------

def _short(error: Any) -> str:
    """A readable schema message: no dumps of whole arrays."""
    if error.validator in ("minItems", "maxItems"):
        return f"needs {error.validator_value} {'or more' if error.validator == 'minItems' else 'or fewer'} items, has {len(error.instance)}"
    return error.message[:160]


def validate(board: dict[str, Any]) -> list[str]:
    """Schema errors first, then the rules a schema cannot say. An empty list means valid."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = [f"{'/'.join(map(str, e.path)) or '(root)'}: {_short(e)}"
              for e in Draft202012Validator(schema).iter_errors(board)]
    if errors:
        return errors
    shots = board["shots"]
    ids = [s["id"] for s in shots]
    if len(ids) != len(set(ids)):
        errors.append("shots: ids must be unique")
    total = sum(s["duration"] for s in shots)
    if not 60 <= total <= 90:
        errors.append(f"shots: durations add up to {total:.1f}s, the film must be 60-90s")
    for cue in board["music"]["cues"]:
        if cue["at_shot"] not in ids:
            errors.append(f"music.cues: at_shot {cue['at_shot']} is not a shot id")
    for s in shots:
        words = len(s["narration"].split())
        lo, hi = WORDS_PER_SECOND
        # Only an upper bound: Amharic words are long, so a short line is fine (a held beat).
        # The real pace is measured from the TTS output in the narration stage (see EXPERIMENTS.md).
        if words > hi * s["duration"]:
            errors.append(f"{s['id']}: {words} words will not fit {s['duration']}s of narration")
        if s["narration"] and not s["subtitle_en"]:
            errors.append(f"{s['id']}: narration needs an English subtitle")
    return errors


def load_storyboard(path: Path = STORYBOARD) -> dict[str, Any]:
    board = json.loads(path.read_text(encoding="utf-8"))
    errors = validate(board)
    if errors:
        raise SystemExit("storyboard.json is invalid:\n  - " + "\n  - ".join(errors))
    return board


# --- providers ---------------------------------------------------------------------------------

def gemini_client():
    """Gemini on the v1beta API: the TTS speechConfig field does not exist in v1 (see FAILURES.md)."""
    from google import genai
    from google.genai import types
    return genai.Client(api_key=env("GEMINI_API_KEY"), http_options=types.HttpOptions(api_version="v1beta"))


def text_models() -> list[str]:
    """The preferred text model, then fallbacks for when it is overloaded (503)."""
    first = env("GEMINI_TEXT_MODEL", "gemini-3.8-flash")
    rest = (env("GEMINI_TEXT_FALLBACKS", "gemini-3.7-flash,gemini-flash-latest,gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite") or "").split(",")
    return [first] + [m.strip() for m in rest if m.strip() and m.strip() != first]


# --- caching -----------------------------------------------------------------------------------

def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cache_key(**inputs: Any) -> str:
    """A short stable hash of every input. Paths are replaced by the hash of their bytes."""
    def norm(v: Any) -> Any:
        if isinstance(v, Path):
            return {"file": file_digest(v)}
        if isinstance(v, dict):
            return {k: norm(x) for k, x in sorted(v.items())}
        if isinstance(v, (list, tuple)):
            return [norm(x) for x in v]
        return v
    blob = json.dumps(norm(inputs), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def cached_path(stage: str, shot: str, key: str, ext: str) -> Path:
    folder = OUT / stage
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{shot}-{key}.{ext}"


# --- the call log ------------------------------------------------------------------------------

def log_call(**record: Any) -> None:
    """One line per model call (or cache hit) in runs.jsonl."""
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **record}
    with RUNS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def call_model(stage: str, shot: str, provider: str, model: str, params: dict[str, Any],
               fn: Callable[[], Any], attempts: int = 3, cost_usd: float = 0.0) -> Any:
    """Run ``fn`` with retries and exponential backoff, logging every attempt."""
    for attempt in range(1, attempts + 1):
        start = time.perf_counter()
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - every provider fails differently
            latency = round(time.perf_counter() - start, 3)
            log_call(stage=stage, shot=shot, provider=provider, model=model, params=params,
                     seed=params.get("seed"), latency_s=latency, attempt=attempt, status="error",
                     error=f"{type(exc).__name__}: {str(exc)[:300]}")
            daily = "PerDay" in str(exc) or "per day" in str(exc)
            if attempt == attempts or daily:  # a daily quota will not recover by waiting
                raise
            limited = any(t in str(exc) for t in ("429", "RESOURCE_EXHAUSTED"))
            time.sleep(20 * attempt if limited else 2 ** attempt)  # quota limits need a longer wait
            continue
        latency = round(time.perf_counter() - start, 3)
        log_call(stage=stage, shot=shot, provider=provider, model=model, params=params,
                 seed=params.get("seed"), latency_s=latency, attempt=attempt, status="ok",
                 cost_usd_equiv=cost_usd)
        return result
    raise RuntimeError("unreachable")
