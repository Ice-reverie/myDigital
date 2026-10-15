"""Render a complete 24fps diagnostic preview of the active greet Action."""
import bpy
import tempfile
from pathlib import Path
from mathutils import Vector

scene=bpy.context.scene
scene.frame_start,scene.frame_end=0,72
scene.render.fps=24
scene.camera.location=(0,-4,.76)
scene.camera.rotation_euler=(Vector((0,0,.76))-scene.camera.location).to_track_quat('-Z','Y').to_euler()
scene.render.resolution_x=360
scene.render.resolution_y=480
scene.render.resolution_percentage=100
out=Path(tempfile.mkdtemp(prefix='greet-preview-'))
bpy.app.driver_namespace['greet_preview_dir']=str(out)
for frame in range(73):
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    scene.render.filepath=str(out/f'{frame:03d}.png')
    bpy.ops.render.render(write_still=True)
scene.frame_set(17)
result={'frames':73,'directory':str(out)}
