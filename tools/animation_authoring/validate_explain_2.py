"""Run after build_explain_2.py, inside Blender 5.2."""
import bpy
from pathlib import Path
ACTION_NAME='explain_2'
validator=Path(bpy.data.filepath).parents[2]/'tools'/'animation_authoring'/'validate_greet.py'
exec(compile(validator.read_text(encoding='utf-8'),str(validator),'exec'))
