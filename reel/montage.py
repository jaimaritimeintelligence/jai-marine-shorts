"""Dev helper: render a frame near the end of every scene and tile them into one image."""
import json, sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).parent)); import render
ep_path = Path(sys.argv[1]); out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/montage.jpg"
frac = float(sys.argv[3]) if len(sys.argv) > 3 else 0.8
render.build(ep_path, "none", snaps=[0])          # writes timeline.json
w = ep_path.parent; ep = json.loads((w / "timeline.json").read_text())
for f in w.glob("snap_*"): f.unlink()
st = 0; times = []
for sc in ep["scenes"]: times.append(round(st + sc["_dur"] * frac, 2)); st += sc["_dur"]
render.snapshot(ep, times, w)
fs = sorted(w.glob("snap_*.jpg")); ims = [Image.open(f).resize((270, 480)) for f in fs]
cols = 6; rows = (len(ims) + cols - 1) // cols; M = Image.new("RGB", (270 * cols, 480 * rows), "black")
for i, im in enumerate(ims): M.paste(im, ((i % cols) * 270, (i // cols) * 480))
M.save(out, quality=85)
for f in fs: f.unlink()
print(out, times)
