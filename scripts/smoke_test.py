#!/usr/bin/env python3
"""Real local media smoke test; isolated temporary data; no paid APIs."""
from pathlib import Path
import sys
import tempfile
import os
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
os.environ["LIVEOPREK_DATA"]=tempfile.mkdtemp(prefix="liveoprek2-smoke-")
os.environ["APP_SECRET"]="smoke-only-secret-01234567890123456789"
from studio import store,media,render
from PIL import Image
store.init()
d=store.DATA
image=d/"background.png"
Image.new("RGB",(360,640),"#214963").save(image)
out=d/"shorts.mp4"
render.motion_video(str(image),str(out),d/"render","petals",5,None,
                    {"ribbon":"TETAP PULANG","lines":["Rumah bukan selalu tempat.","Kadang, ia adalah perasaan."],"signature":"ruang miring"},360,640)
info=media.probe(out)
v=next(x for x in info["streams"] if x["codec_type"]=="video")
assert v["width"]==360 and v["height"]==640 and v["codec_name"]=="h264"
assert media.has_audio(out)
a=store.import_file(out,"Hasil smoke test.mp4")
print("PASS: H.264 9:16 + AAC, particles/vector-heart/typography, duration",media.duration(store.asset_path(a)))
print("Output:",out)
print("Temporary smoke data may be deleted:",d)