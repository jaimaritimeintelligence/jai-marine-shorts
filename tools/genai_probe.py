"""Which Google generative models does this key allow? Try one image."""
import os, base64, sys
sys.path.insert(0, os.getcwd())
from google import genai
from google.genai import types
c = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
names = [m.name.split("/")[-1] for m in c.models.list()]
print("ALL:", names)
cands = [n for n in names if any(k in n.lower() for k in ("image", "imagen", "veo"))]
print("IMAGE/VIDEO:", cands)
prompt = ("Cinematic photorealistic image, vertical 9:16: a Moss-type LNG carrier with four huge spherical cargo tanks sailing at dusk "
          "on a dark blue sea, one sphere shown as a glowing transparent cutaway full of icy blue liquid, dramatic clouds, high detail")
os.makedirs("tools/out", exist_ok=True)
for n in cands:
    try:
        if n.startswith("imagen"):
            r = c.models.generate_images(model=n, prompt=prompt, config=types.GenerateImagesConfig(number_of_images=1, aspect_ratio="9:16"))
            open(f"tools/out/{n}.png", "wb").write(r.generated_images[0].image.image_bytes); print("OK", n); continue
        if "veo" in n: print("skip video", n); continue
        r = c.models.generate_content(model=n, contents=prompt, config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]))
        for p in r.candidates[0].content.parts:
            if getattr(p, "inline_data", None) and p.inline_data.data:
                d = p.inline_data.data; d = base64.b64decode(d) if isinstance(d, str) else d
                open(f"tools/out/{n}.png", "wb").write(d); print("OK", n); break
        else:
            print("NO IMAGE", n)
    except Exception as e:
        print("FAIL", n, str(e)[:300])
