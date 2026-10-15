"""Encode exactly three loops at 30 fps; do not duplicate closing keyframes."""
import json
import subprocess
import sys
from pathlib import Path
import imageio_ffmpeg

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'models/animations/review_health'
TEMP=ROOT/'output/health_animation_render_final'
ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
manifest={'fps':30,'fps_base':1,'resolution':[960,680],'views':['front','45 degrees'],'blender':'5.2.1 LTS','engine':'EEVEE','samples':24,'color_management':'Standard / None / exposure 0 / gamma 1','device':'not recorded','render_seconds':'not recorded','videos':[]}
for name,count in [('Idle_Doctor',240),('Explain_Gentle',300),('Transition_10f',400)]:
    if len(sys.argv)>1 and name not in sys.argv[1:]:continue
    assert all((TEMP/name/f'{f:04d}.png').exists() for f in range(1,count+1)),name
    single=TEMP/(name+'_single.mp4')
    subprocess.run([ffmpeg,'-y','-v','error','-framerate','30','-start_number','1','-i',str(TEMP/name/'%04d.png'),'-frames:v',str(count),'-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(single)],check=True)
    loops=1 if name=='Transition_10f' else 3
    output=OUT/(name+('_preview.mp4' if loops==1 else '_3loops.mp4'))
    subprocess.run([ffmpeg,'-y','-v','error','-stream_loop',str(loops-1),'-i',str(single),'-c','copy','-movflags','+faststart',str(output)],check=True)
    info=subprocess.run([ffmpeg,'-i',str(output),'-map','0:v:0','-f','null','-'],text=True,capture_output=True)
    assert info.returncode==0,info.stderr
    manifest['videos'].append({'file':output.name,'action_frames':count,'loops':loops,'duration_seconds':count*loops/30,'decoded':True,'closing_key_rendered':False})
    print(output,flush=True)
(OUT/'render-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
