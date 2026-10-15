"""Encode a rendered 24fps sequence without modifying the reference video."""
from pathlib import Path
import subprocess
import sys
import imageio_ffmpeg

directory,output,count=Path(sys.argv[1]),Path(sys.argv[2]),int(sys.argv[3])
subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-framerate','24',
    '-i',str(directory/'%03d.png'),'-frames:v',str(count),'-c:v','libx264',
    '-pix_fmt','yuv420p','-crf','19','-movflags','+faststart',str(output)],check=True)
