"""The film: every stage in order, then one FFmpeg pass that puts it together.

  narration (cached) -> keyframes (cached, judged) -> shots (camera moves) -> end card
  -> picture + voice + music (ducked under the voice) + burned-in English subtitles -> MP4

Music: if outputs/music/score.wav (or .mp3) exists it is used; otherwise the placeholder drone.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from pipeline import keyframes, narration, radio, shots
from pipeline.common import OUT, ROOT, env, ffmpeg, load_storyboard, log_call

END_CARD = 3.5   # keeps the whole film under 90s
OPEN_FROM, OPEN_TO = 0.6, 5.2   # the opening title sits over the first shot (no extra length)
TITLE_EN = "The Roots We Carry"
TITLE_AM = "ሥርህን ይዘህ ትሄዳለህ"
CREDIT = "A film by Getacher Ashebir Yimer\nMade with AI: images FLUX, voice Gemini TTS\nAll characters are fictional"
FONTS = [env("FONT_FILE"), "C:/Windows/Fonts/ebrima.ttf", "C:/Windows/Fonts/nyala.ttf",
         "/usr/share/fonts/truetype/noto/NotoSansEthiopic-Regular.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
FOLDER = OUT / "film"


def font() -> str:
    for f in FONTS:
        if f and Path(f).exists():
            return f
    raise SystemExit("no font with Ethiopic letters found: set FONT_FILE in .env (e.g. C:/Windows/Fonts/ebrima.ttf)")


def esc(path: str) -> str:
    """A path inside an FFmpeg filter: forward slashes, and the drive colon escaped (C\\:/...)."""
    return path.replace("\\", "/").replace(":", "\\:")


TIBEB = [(0, 122, 61), (252, 209, 22), (218, 18, 26)]   # green, gold, red


def tibeb_band(width: int | None = None, height: int = 54) -> Path:
    """A woven-border strip like the tibeb on a netela: thin stripes framing a row of diamonds."""
    from PIL import Image, ImageDraw
    width = width or shots.W
    path = FOLDER / f"tibeb_{width}.png"
    im = Image.new("RGBA", (width, height), (250, 246, 236, 255))
    d = ImageDraw.Draw(im)
    for i, c in enumerate(TIBEB):                       # stripes at the top and bottom edges
        d.rectangle([0, i * 4, width, i * 4 + 3], fill=c)
        d.rectangle([0, height - 4 - i * 4, width, height - 1 - i * 4], fill=c)
    mid, size = height // 2, 13
    for j, x in enumerate(range(size, width, 2 * size + 4)):
        c = TIBEB[j % 3]
        d.polygon([(x, mid - size), (x + size, mid), (x, mid + size), (x - size, mid)], fill=c)
        d.polygon([(x, mid - 5), (x + 5, mid), (x, mid + 5), (x - 5, mid)], fill=(250, 246, 236))
    im.save(path)
    return path


def ass_time(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    sec, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{sec:02}.{cs:02}"


def bilingual_subtitles(board: dict[str, Any], voice_manifest: dict[str, Any], lengths: dict[str, float], out: Path) -> int:
    """Amharic (Ge'ez script, gold) above English (white), timed to each spoken line."""
    face = Path(font()).stem.capitalize() if "ebrima" in font().lower() else "Nyala" if "nyala" in font().lower() else "Noto Sans Ethiopic"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {shots.W}
PlayResY: {shots.H}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Am,{face},56,&H0070D8FF,&H000000FF,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,3,1,2,60,60,170,1
Style: En,{face},44,&H00FFFFFF,&H000000FF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2.6,1,2,70,70,190,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines, t, n = [], 0.0, 0
    for shot in board["shots"]:
        spoken = voice_manifest.get(shot["id"], {}).get("seconds", 0.0)
        if spoken:
            a, b = t + radio.LEAD_IN, t + radio.LEAD_IN + spoken
            # one event, Amharic line then English line, so wrapping can never swap their order
            lines.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Am,,0,0,0,,{{\\fad(200,250)}}{shot['narration']}"
                         f"\\N{{\\rEn}}{shot['subtitle_en']}")
            n += 1
        t += lengths[shot["id"]]
    out.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return n


# Memory chapters in Ge'ez numerals, shown as each one begins: (numeral, Amharic word, English)
CHAPTERS = {"s03": ("፩", "ተራራ", "mountains"), "s04": ("፪", "እምነት", "faith"), "s05": ("፫", "ሽማግሌዎች", "elders"),
            "s06": ("፬", "ቡና", "coffee"), "s08": ("፭", "ዛሬ", "today")}
TYPE_STEP = 0.11   # seconds per fidel when the title is "written"


def TITLE_Y() -> int:
    """Top of the Amharic title line; the English line and both tibeb borders are placed around it."""
    return round(shots.H * 0.36)


def fade_alpha(a: float, b: float, d: float = 0.5) -> str:
    return f"if(lt(t,{a}),0,if(lt(t,{a + d}),(t-{a})/{d},if(lt(t,{b - d}),1,if(lt(t,{b}),({b}-t)/{d},0))))"


def typewriter_title(fontfile: str, alpha: str) -> list[str]:
    """The Amharic title appears one fidel at a time, like a hand writing it; the English follows."""
    letters = list(TITLE_AM)
    out, t = [], OPEN_FROM
    for i in range(1, len(letters) + 1):
        if letters[i - 1] == " " and i < len(letters):
            continue
        name = f"t_am_{i:02}.txt"
        (FOLDER / name).write_text("".join(letters[:i]), encoding="utf-8")
        last = i == len(letters)
        end = OPEN_TO if last else t + TYPE_STEP
        a = f"if(lt(t,{OPEN_TO - 0.8}),1,({OPEN_TO}-t)/0.8)" if last else "1"
        out.append(f"drawtext=fontfile='{fontfile}':textfile={name}:fontsize=78:fontcolor=white:borderw=3:"
                   f"bordercolor=0x00000088:x=(w-tw)/2:y={TITLE_Y()}:enable='between(t,{t:.2f},{end:.2f})':alpha='{a}'")
        t = end
    en_from = t if t < OPEN_TO - 1.5 else OPEN_FROM
    out.append(f"drawtext=fontfile='{fontfile}':textfile=t_en.txt:fontsize=62:fontcolor=white:borderw=3:"
               f"bordercolor=0x00000088:x=(w-text_w)/2:y={TITLE_Y() + 96}:alpha='{fade_alpha(en_from, OPEN_TO, 0.6)}'")
    return out


def chapter_marks(fontfile: str, board: dict[str, Any], lengths: dict[str, float]) -> list[str]:
    out, t = [], 0.0
    for shot in board["shots"]:
        if shot["id"] in CHAPTERS:
            num, word, _ = CHAPTERS[shot["id"]]
            name = f"ch_{shot['id']}.txt"
            (FOLDER / name).write_text(f"{num}   {word}", encoding="utf-8")
            a, b = t + 0.5, t + min(3.2, lengths[shot["id"]] - 0.3)
            out.append(f"drawtext=fontfile='{fontfile}':textfile={name}:fontsize=64:fontcolor=0xFFD870:borderw=3:"
                       f"bordercolor=0x00000099:x=(w-text_w)/2:y=h*0.09:alpha='{fade_alpha(a, b)}'")
        t += lengths[shot["id"]]
    return out


def end_card() -> Path:
    out = FOLDER / f"end_card_{shots.W}x{shots.H}.mp4"
    texts = {"t_en.txt": TITLE_EN, "t_am.txt": TITLE_AM, "t_cr.txt": CREDIT}
    for name, text in texts.items():
        (FOLDER / name).write_text(text, encoding="utf-8")
    f = esc(font())
    alpha = f"if(lt(t,0.6),t/0.6,1)"
    draw = lambda file, size, y, colour="white": (
        f"drawtext=fontfile='{f}':textfile={file}:fontsize={size}:fontcolor={colour}:"
        f"x=(w-text_w)/2:y={y}:alpha='{alpha}':line_spacing=12")
    vf = ",".join([draw("t_am.txt", 72, "h*0.40"), draw("t_en.txt", 64, "h*0.47"),
                   draw("t_cr.txt", 34, "h*0.78", "0xCCCCCC")])
    band = tibeb_band()
    graph = (f"[0:v]{vf}[t];[1:v]format=rgba,split=2[b1][b2];[t][b1]overlay=0:H*0.30[t1];[t1][b2]overlay=0:H*0.60[v]")
    cmd = [ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
           f"color=c=0x120d08:s={shots.W}x{shots.H}:r={shots.FPS}:d={END_CARD}", "-i", band.name,
           "-filter_complex", graph, "-map", "[v]", "-t", str(END_CARD),
           "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", out.name]
    subprocess.run(cmd, check=True, cwd=FOLDER)   # run inside the folder: text files by plain name
    return out


def music_input(total: float) -> tuple[list[str], str]:
    """FFmpeg inputs and the label of the music stream (ending in [music])."""
    for ext in ("wav", "mp3"):
        score = OUT / "music" / f"score.{ext}"
        if score.exists():
            return (["-stream_loop", "-1", "-i", str(score)],
                    f"[2:a]atrim=0:{total:.2f},volume=0.55,afade=t=in:d=1.5,afade=t=out:st={total - 4:.2f}:d=4,"
                    "aformat=sample_rates=48000:channel_layouts=stereo[music];")
    tones = [f"sine=frequency={f}:sample_rate=48000:duration={total:.2f}" for f in (146.83, 174.61, 220.0)]
    args = []
    for t in tones:
        args += ["-f", "lavfi", "-i", t]
    return (args, "[2:a][3:a][4:a]amix=inputs=3:normalize=0,volume=0.05,tremolo=f=0.2:d=0.4,"
                  f"afade=t=in:d=2,afade=t=out:st={total - 3:.2f}:d=3,"
                  "aformat=sample_rates=48000:channel_layouts=stereo[music];")


def run(fmt: str = "9x16") -> Path:
    shots.use(fmt)
    board = load_storyboard()
    FOLDER.mkdir(parents=True, exist_ok=True)
    voice_manifest = narration.run(board)
    keyframes.run(board)
    lengths = radio.shot_lengths(board, voice_manifest)
    clips = shots.run(board, lengths)
    card = end_card()

    voice, srt, ass = FOLDER / "voice.wav", FOLDER / "subtitles.srt", FOLDER / f"subtitles_{fmt}.ass"
    spoken_total, cues = radio.voice_track(board, voice_manifest, voice)
    srt.write_text("\n".join(f"{i}\n{radio.srt_time(a)} --> {radio.srt_time(b)}\n{text}\n"
                             for i, (a, b, text) in enumerate(cues, 1)), encoding="utf-8")   # English .srt for platforms
    bilingual_subtitles(board, voice_manifest, lengths, ass)
    total = spoken_total + END_CARD

    listing = FOLDER / f"clips_{fmt}.txt"
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in [*clips.values(), card]), encoding="utf-8")
    picture = FOLDER / f"picture_{fmt}.mp4"
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", str(picture)], check=True)

    music_args, music_graph = music_input(total)
    band = tibeb_band()
    band_index = 2 + music_args.count("-i")   # after the picture, voice and music inputs
    band_args = ["-loop", "1", "-t", f"{OPEN_TO:.2f}", "-i", band.name]
    fonts_dir = esc(str(Path(font()).parent))
    f = esc(font())
    title = (OPEN_FROM, OPEN_TO)
    alpha = (f"if(lt(t,{title[0]}),0,if(lt(t,{title[0] + 0.8}),(t-{title[0]})/0.8,"
             f"if(lt(t,{title[1] - 0.8}),1,if(lt(t,{title[1]}),({title[1]}-t)/0.8,0))))")
    titles = ",".join(typewriter_title(f, alpha) + chapter_marks(f, board, lengths))
    band_in = (f"[{band_index}:v]format=rgba,fade=t=in:st={title[0]}:d=0.8:alpha=1,"
               f"fade=t=out:st={title[1] - 0.8}:d=0.8:alpha=1[band];")
    graph = (
        band_in +
        f"[0:v]{titles}[tv];[tv][band]overlay=0:{TITLE_Y() - 84}:eof_action=pass[tb];"
        f"[tb][band2]overlay=0:{TITLE_Y() + 96 + 84}:eof_action=pass[tbb];"
        f"[tbb]subtitles={ass.name}:fontsdir='{fonts_dir}',fade=t=in:d=1,fade=t=out:st={total - 1.5:.2f}:d=1.5[v];"
        + music_graph +
        "[1:a]apad,aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[v1][v2];"
        "[music][v1]sidechaincompress=threshold=0.02:ratio=6:attack=300:release=1500[ducked];"
        "[v2][ducked]amix=inputs=2:duration=longest:normalize=0,loudnorm=I=-14:TP=-1:LRA=11,aformat=sample_rates=48000:channel_layouts=stereo[a]"   # loudnorm works at 192 kHz: back to 48 kHz stereo
    )
    out = FOLDER / f"the_roots_we_carry_{fmt}.mp4"
    graph = graph.replace("[band];", "[band0];[band0]split=2[band][band2];", 1)
    cmd = [ffmpeg(), "-y", "-loglevel", "error", "-i", picture.name, "-i", voice.name, *music_args, *band_args,
           "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "19",
           "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-b:a", "192k",
           "-movflags", "+faststart", "-t", f"{total:.2f}", out.name]
    subprocess.run(cmd, check=True, cwd=FOLDER)
    log_call(stage="film", shot="-", provider="local", model="ffmpeg", status="ok", params={"seconds": round(total, 2)})
    print(f"\nfilm: {out.relative_to(ROOT).as_posix()} ({total:.1f}s, {len(clips)} shots, {len(cues)} subtitles)")
    return out
