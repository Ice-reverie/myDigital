"""Create temporary labeled contact sheets from rendered animation frames."""
from pathlib import Path
from PIL import Image, ImageDraw
import sys

directory=Path(sys.argv[1])
frames=list(map(int,sys.argv[2].split(',')))
sheet=Image.new('RGB',(4*300,((len(frames)+3)//4)*420),'#282828')
draw=ImageDraw.Draw(sheet)
for i,frame in enumerate(frames):
    im=Image.open(directory/f'{frame:03d}.png').convert('RGB')
    im.thumbnail((300,400))
    x,y=(i%4)*300,(i//4)*420
    sheet.paste(im,(x,y+20));draw.text((x+8,y+4),f'frame {frame} / {frame/24:.3f}s',fill='white')
sheet.save(directory/f'sheet-{frames[0]}-{frames[-1]}.jpg')
