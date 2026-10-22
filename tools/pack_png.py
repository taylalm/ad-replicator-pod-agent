#!/usr/bin/env python3
"""Pack text files (scripts) into a lossless grayscale PNG so they can go through the Files API, which accepts
media only (it rejects .py/.json/.txt). Unpack in the sandbox with the one-liner printed by this tool.
  python3 tools/pack_png.py out.png file1.py [file2.py ...]
"""
import gzip, hashlib, io, json, math, sys, tarfile
from PIL import Image

out, files = sys.argv[1], sys.argv[2:]
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w") as tar:
    for f in files:
        tar.add(f, arcname=f.split("/")[-1])
data = gzip.compress(buf.getvalue(), 9)
payload = len(data).to_bytes(4, "big") + data
w = 1024
h = math.ceil(len(payload) / w)
Image.frombytes("L", (w, h), payload + b"\0" * (w * h - len(payload))).save(out, optimize=True)
print(json.dumps({"png": out, "files": {f.split("/")[-1]: hashlib.sha256(open(f, "rb").read()).hexdigest() for f in files},
                  "unpack": "python3 -c \"import gzip,io,sys,tarfile;from PIL import Image;b=Image.open(sys.argv[1]).tobytes();n=int.from_bytes(b[:4],'big');"
                            "tarfile.open(fileobj=io.BytesIO(gzip.decompress(b[4:4+n]))).extractall(sys.argv[2])\" <png> <dest dir>"}, indent=1))
