"""Extract labeled, original-frame reference sheets; never modify the source video."""
import argparse
import tempfile
from pathlib import Path

import cv2
from PIL import Image, ImageDraw

parser = argparse.ArgumentParser()
parser.add_argument('video')
args = parser.parse_args()
cap = cv2.VideoCapture(args.video)
fps = cap.get(cv2.CAP_PROP_FPS)
print(dict(fps=fps, frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
           width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))))
out = Path(tempfile.mkdtemp(prefix='greet-reference-'))
for start, stop in [(24,36),(36,48),(48,60),(60,72),(72,84),(84,96)]:
    sheet = Image.new('RGB', (360*4, 390*3), '#eeeeee')
    for j, f in enumerate(range(start,stop)):
        cap.set(cv2.CAP_PROP_POS_FRAMES,f)
        ok, frame = cap.read()
        if not ok: raise RuntimeError(f'Cannot decode frame {f}')
        im = Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
        # Keep the head, both arms and hips in view; use original video pixels.
        w,h=im.size
        im=im.crop((0,int(h*.04),w,int(h*.61)))
        im.thumbnail((350,350))
        x=(j%4)*360; y=(j//4)*390
        sheet.paste(im,(x+(360-im.width)//2,y+30))
        ImageDraw.Draw(sheet).text((x+8,y+6),f'original f{f} | {f/fps:.3f}s',fill='black')
    path=out/f'frames_{start:03d}_{stop-1:03d}.jpg'
    sheet.save(path,quality=94)
    print(path)
cap.release()
