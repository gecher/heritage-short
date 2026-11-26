"""Keyframes: one still image per shot, plus an automatic judge that picks the best candidate.

  python -m pipeline reference   4 candidate portraits of the character; you pick one
  python -m pipeline keyframes   every shot's candidates, judged, best one chosen

Why a judge: FLUX schnell on Cloudflare takes no seed and no reference image, so the same
character can come out as a different man in every shot, and the model does not know Ethiopian
objects by name (the smoke test drew an Arabic coffee pot for "jebena"). So the pipeline makes
several candidates per shot and a Gemini vision model scores each one: does it match the
prompt, is it the same man as the chosen reference portrait, and would an Ethiopian viewer
spot anything wrong. The best score wins. A human still has the last word: every score and the
reason are in outputs/keyframes/manifest.json and on the contact sheet.

Caching: an image's key holds the model, prompt, steps, candidate number and take; a judgement's
key holds the bytes of both images and the judge's prompt version. Re-running costs nothing.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import requests

from pipeline.common import (OUT, ROOT, cache_key, cached_path, call_model, env, file_digest,
                             gemini_client, load_storyboard, log_call, text_models)

MODEL = env("CF_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell")
STEPS = 8                       # flux-1-schnell's maximum; more steps = more detail
CANDIDATES = int(env("KEYFRAME_CANDIDATES", "2") or 2)            # per shot
CHARACTER_CANDIDATES = int(env("KEYFRAME_CHARACTER_CANDIDATES", "4") or 4)
REFERENCE_CANDIDATES = 4
JUDGE_VERSION = 2               # bump when the judge prompt changes, so old scores are not reused
FOLDER = OUT / "keyframes"


# --- generation --------------------------------------------------------------------------------

def shot_prompt(board: dict[str, Any], shot: dict[str, Any]) -> str:
    parts = [shot["image_prompt"]]
    if shot["shows_character"]:
        parts.append(f"the man is {board['style']['character']['description']}")
    parts.append(board["style"]["style_block"])
    return ", ".join(parts)


def reference_prompt(board: dict[str, Any]) -> str:
    c = board["style"]["character"]
    return (f"head-and-shoulders portrait of {c['description']}, facing the camera, calm warm "
            f"expression, plain softly lit background, {board['style']['style_block']}")


def flux(prompt: str) -> bytes:
    account, token = env("CLOUDFLARE_ACCOUNT_ID"), env("CLOUDFLARE_API_TOKEN")
    if not account or not token:
        raise SystemExit("set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN in .env")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{MODEL}"
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"},
                      json={"prompt": prompt, "steps": STEPS}, timeout=180)  # no "seed": rejected (FAILURES.md)
    if not r.ok:
        raise RuntimeError(f"{r.status_code}: {r.text[:400]}")
    return base64.b64decode(r.json()["result"]["image"])


GEMINI_IMAGE_MODELS = [m.strip() for m in (env("GEMINI_IMAGE_MODELS", "gemini-3.1-flash-image,gemini-nano-banana-2.1,gemini-2.5-flash-image") or "").split(",") if m.strip()]
_EXHAUSTED: set[str] = set()   # providers/models out of daily quota in this run


def gemini_image(prompt: str, model: str, reference: Path | None) -> bytes:
    """Gemini image generation. Unlike FLUX it accepts a reference photo, so the character's face
    can be shown to the model instead of only described."""
    from io import BytesIO

    from google.genai import types
    from PIL import Image
    parts: list[Any] = []
    if reference is not None:
        parts.append(types.Part.from_bytes(data=reference.read_bytes(), mime_type="image/jpeg"))
        prompt = ("The man in this reference photo is the character Abba; keep his face exactly. "
                  "Create a new square cinematic film still: " + prompt)
    parts.append(prompt)
    client = gemini_client(timeout_s=120)   # keep a reference: a temporary client is closed before the call
    reply = client.models.generate_content(
        model=model, contents=parts,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]))
    for part in reply.candidates[0].content.parts:
        if getattr(part, "inline_data", None) and part.inline_data.data:
            im = Image.open(BytesIO(part.inline_data.data)).convert("RGB")
            out = BytesIO(); im.save(out, "JPEG", quality=92)       # every keyframe is a JPEG
            return out.getvalue()
    raise RuntimeError("no image in the reply")


def _key(provider: str, model: str, prompt: str, candidate: int, take: int, ref: Path | None) -> str:
    """FLUX keys keep their original fields, so images made before the Gemini fallback stay cached."""
    if provider == "cloudflare":
        return cache_key(stage="keyframes", model=model, prompt=prompt, steps=STEPS, candidate=candidate, take=take)
    return cache_key(stage="keyframes", model=model, prompt=prompt, candidate=candidate, take=take, reference=ref)


def image(stage_shot: str, prompt: str, candidate: int, take: int, folder: Path,
          reference: Path | None = None) -> Path:
    """One cached image: Cloudflare FLUX first, then Gemini image models when FLUX is out of quota.
    Same inputs -> same file, no API call."""
    folder.mkdir(parents=True, exist_ok=True)
    providers = [("cloudflare", MODEL)] + [("gemini", m) for m in GEMINI_IMAGE_MODELS]
    for provider, model in providers:                      # a cached image from any provider is reused
        ref = reference if provider == "gemini" else None
        key = _key(provider, model, prompt, candidate, take, ref)
        path = folder / f"{stage_shot}-{key}.jpg"
        if path.exists():
            log_call(stage="keyframes", shot=stage_shot, provider="cache", model=model, status="hit", file=path.name)
            return path
    last: Exception | None = None
    for provider, model in providers:
        if model in _EXHAUSTED:
            continue
        ref = reference if provider == "gemini" else None
        key = _key(provider, model, prompt, candidate, take, ref)
        path = folder / f"{stage_shot}-{key}.jpg"
        params = {"prompt": prompt, "candidate": candidate, "take": take, "reference": ref.name if ref else None}
        fn = (lambda: flux(prompt)) if provider == "cloudflare" else (lambda m=model, r=ref: gemini_image(prompt, m, r))
        try:
            data = call_model("keyframes", stage_shot, provider, model, params, fn, attempts=2)
        except Exception as exc:  # noqa: BLE001 - out of quota or overloaded: next provider
            last = exc
            _EXHAUSTED.add(model)
            print(f"  {model} unavailable ({str(exc)[:90]}), trying next")
            continue
        tmp = path.with_name(path.stem + ".partial")
        tmp.write_bytes(data)
        tmp.replace(path)                                  # complete files only (FAILURES F18)
        print(f"  wrote {path.relative_to(ROOT)} ({model})")
        return path
    raise SystemExit(f"no image provider answered for {stage_shot}: {last}")


# --- the judge ---------------------------------------------------------------------------------

JUDGE_PROMPT = """You are a strict Ethiopian film reviewer checking one keyframe for a short film about Ethiopian heritage, made for Ethiopian viewers. Judge it as an Ethiopian viewer would; do not be generous.
The shot should show: {description}
{reference_line}
Reply with JSON only:
{{"prompt_match": 0-10 (does the keyframe show what the shot should show),
  "same_person": 0-10 or null (how clearly the man in the keyframe is the SAME person as in the reference portrait; null if there is no reference or no man is visible),
  "people_look_ethiopian": 0-10 or null (do the people look like Habesha Ethiopians: skin tone, features, hair, clothing? Be strict: South Asian, Middle Eastern or generic faces score low; null if no faces are visible),
  "cultural_issues": [short strings: anything an Ethiopian viewer would find wrong or not Ethiopian: objects, clothing, buildings, food, faces; empty list if none],
  "artifacts": [short strings: distorted hands or faces, extra limbs, garbled text, watermarks; empty list if none],
  "note": "one short sentence"}}"""


def judge(shot: dict[str, Any], frame: Path, reference: Path | None) -> dict[str, Any] | None:
    """Score one candidate with a Gemini vision model (cached). None if every model is unavailable."""
    from google.genai import types
    use_ref = reference if (reference and shot.get("shows_character")) else None
    key = cache_key(stage="judge", version=JUDGE_VERSION, frame=frame, reference=use_ref,
                    description=shot["image_prompt"])
    path = cached_path("keyframes/judge", shot["id"], key, "json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    ref_line = ("The FIRST image is the reference portrait of the main character; the SECOND image is the keyframe."
                if use_ref else "The image is the keyframe.")
    parts = []
    if use_ref:
        parts.append(types.Part.from_bytes(data=use_ref.read_bytes(), mime_type="image/jpeg"))
    parts.append(types.Part.from_bytes(data=frame.read_bytes(), mime_type="image/jpeg"))
    parts.append(JUDGE_PROMPT.format(description=shot["image_prompt"], reference_line=ref_line))
    config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0)
    client = gemini_client(timeout_s=60)
    for model in list(_judge_order()):
        try:
            reply = call_model("judge", shot["id"], "gemini", model, {"frame": frame.name, "version": JUDGE_VERSION},
                               lambda: client.models.generate_content(model=model, contents=parts, config=config),
                               attempts=1)
            result = json.loads(reply.text)
            result["judge_model"] = model
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            _JUDGE_ORDER.remove(model); _JUDGE_ORDER.insert(0, model)   # sticky: try the winner first next time
            return result
        except Exception as exc:  # noqa: BLE001 - overloaded or out of quota: try the next model
            _JUDGE_ORDER.remove(model); _JUDGE_ORDER.append(model)      # demote: it failed just now
            print(f"    judge {model} unavailable ({type(exc).__name__}), trying next")
    return None


_JUDGE_ORDER: list[str] = []


def _judge_order() -> list[str]:
    """Models in the order to try them. Starts from the .env preference, then learns during the run:
    the model that last answered goes first, a model that just failed goes last. With every big
    model overloaded (503), this cut ~90 s of failed calls per image to ~3 s (EXPERIMENTS.md)."""
    if not _JUDGE_ORDER:
        _JUDGE_ORDER.extend(text_models())
    return _JUDGE_ORDER


def score(shot: dict[str, Any], verdict: dict[str, Any] | None) -> float:
    if verdict is None:
        return 0.0
    s = float(verdict.get("prompt_match") or 0)
    if shot.get("shows_character") and verdict.get("same_person") is not None:
        s += float(verdict["same_person"])
    looks = verdict.get("people_look_ethiopian")
    if looks is not None:
        s += float(looks) - 10                # 10 = no penalty; a non-Ethiopian face costs a lot
    s -= 2 * len(verdict.get("cultural_issues") or [])
    s -= 1 * len(verdict.get("artifacts") or [])
    return s


# --- stages ------------------------------------------------------------------------------------

def reference_path(board: dict[str, Any]) -> Path | None:
    ref = board["style"]["character"].get("reference_image")
    if not ref:
        return None
    path = ROOT / ref
    if not path.exists():
        raise SystemExit(f"style.character.reference_image points to {ref}, which does not exist")
    return path


def reference() -> list[Path]:
    """Candidate portraits for the character. You choose one; the judge compares every shot to it."""
    board = load_storyboard()
    prompt = reference_prompt(board)
    paths = [image("abba", prompt, i, 1, FOLDER / "reference") for i in range(REFERENCE_CANDIDATES)]
    print("\nOpen these and choose the father you want in the film:")
    for p in paths:
        print(f"  {p.relative_to(ROOT).as_posix()}")
    print('Then set it in storyboard.json:  "style" -> "character" -> "reference_image": "<that path>"')
    return paths


def run(board: dict[str, Any] | None = None) -> dict[str, Any]:
    board = board or load_storyboard()
    ref = reference_path(board)
    if ref is None and any(s["shows_character"] for s in board["shots"]):
        print("note: no reference_image yet, so the father is not checked for consistency "
              "(run `python -m pipeline reference` and pick one)")
    manifest: dict[str, Any] = {}
    for shot in board["shots"]:
        n = CHARACTER_CANDIDATES if shot["shows_character"] else CANDIDATES
        prompt = shot_prompt(board, shot)
        print(f"{shot['id']}: {n} candidate(s)")
        options = []
        for i in range(n):
            frame = image(shot["id"], prompt, i, shot.get("take", 1), FOLDER,
                          reference=ref if shot["shows_character"] else None)
            verdict = judge(shot, frame, ref)
            options.append({"file": frame.relative_to(ROOT).as_posix(), "score": score(shot, verdict),
                            "verdict": verdict})
            v = verdict or {}
            print(f"    c{i}: score {options[-1]['score']:.0f}  match={v.get('prompt_match')} "
                  f"same={v.get('same_person')} ethiopian={v.get('people_look_ethiopian')} issues={v.get('cultural_issues')} artifacts={v.get('artifacts')}")
        best = max(options, key=lambda o: o["score"])
        manifest[shot["id"]] = {"file": best["file"], "prompt": prompt, "candidates": options,
                                "judged": best["verdict"] is not None}
        print(f"    -> chose {Path(best['file']).name}")
    (FOLDER / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    sheet = contact_sheet(board, manifest)
    print(f"\nkeyframes: {len(manifest)} shots -> outputs/keyframes/manifest.json"
          + (f", contact sheet {sheet.relative_to(ROOT).as_posix()}" if sheet else ""))
    flagged = [k for k, v in manifest.items()
               if (v["candidates"] and (max(v["candidates"], key=lambda o: o["score"])["verdict"] or {}).get("cultural_issues"))]
    if flagged:
        print("check these (the judge still saw cultural issues in the best candidate): " + ", ".join(flagged))
    return manifest


def contact_sheet(board: dict[str, Any], manifest: dict[str, Any]) -> Path | None:
    """All chosen keyframes on one page, labelled, for a quick human review."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("(pip install pillow for a contact sheet)")
        return None
    thumbs = []
    for shot in board["shots"]:
        im = Image.open(ROOT / manifest[shot["id"]]["file"]).convert("RGB").resize((320, 320))
        ImageDraw.Draw(im).rectangle([0, 0, 70, 26], fill=(0, 0, 0))
        ImageDraw.Draw(im).text((6, 6), shot["id"], fill=(255, 255, 255))
        thumbs.append(im)
    cols = 4
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 320, rows * 320), (20, 20, 20))
    for i, im in enumerate(thumbs):
        sheet.paste(im, ((i % cols) * 320, (i // cols) * 320))
    path = FOLDER / "contact_sheet.jpg"
    sheet.save(path, quality=88)
    return path
