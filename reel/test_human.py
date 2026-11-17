"""CI self-test of the own-voice path: fake a one-take recording (with a false start) and render it."""
import asyncio, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import edge_tts, render

src = Path(sys.argv[1]); work = Path("/tmp/humantest"); work.mkdir(exist_ok=True)
ep = json.loads(src.read_text()); ep["id"] = "humantest"; ep.pop("voice", None); ep.pop("queue", None)
(work / "episode.json").write_text(json.dumps(ep))
parts = []
for i, sc in enumerate(ep["scenes"]):
    text = sc["narration"]
    if i == 1:
        text = text.split(".")[0] + "... sorry. " + text      # false start + retake
    mp3 = f"/tmp/p{i}.mp3"; asyncio.run(edge_tts.Communicate(text, "en-IN-PrabhatNeural").save(mp3)); parts.append(mp3)
lst = "/tmp/list.txt"; sil = "/tmp/sil.mp3"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "2", sil], check=True)
Path(lst).write_text("".join(f"file '{p}'\nfile '{sil}'\n" for p in parts))
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c:a", "libopus", "/tmp/rec.ogg"], check=True)
os.environ["VOICE_FILE"] = "/tmp/rec.ogg"
out = render.build(work / "episode.json", "human")
shutil.copy(out, "humantest.mp4"); shutil.copy(work / "timeline.json", "humantest-timeline.json")
