# greet — user-video reference revision

Reference: `b827ce56356169421d2264e329de0094.mp4`, 880×1280, 30fps.
The rejected overhead greeting is not used. Only the shared neutral pose is
retained from the imported Humanoid Action.

## Motion

- Reference interval 0.8–3.8 seconds maps to output frames 0–72 at 24fps.
- 72 consecutive reference images (original frames 24–95) were visually
  inspected; 198 manually interpreted angle/expression observations are in
  `greet.reference.json`. They are estimates from the frontal video, not 3D
  motion-capture measurements. Depth is adapted to this avatar's proportions.
- The relaxed hand moves outward first. The elbow then folds, the wrist turns
  and the fingers open near the face. These use separate observed timelines.
- A preparation blink, the quiet left arm, a held body/head inclination,
  gradual lowering, and delayed clothing return are included.
- Body and expressions have 145 Bezier/AUTO_CLAMPED key times, including every
  source-frame time and every 24fps output frame. VRMA samples at 24fps.
- Happy peaks at 0.75; blink peaks at 1.0. No recorded speech/vowel animation.
  During greet, the frontend plays its authored blink but keeps live lip sync.

## Files and regeneration

- `greet_1.vrma`: exported with the installed VRM Add-on's VRM Animation exporter.
- `greet_1.secondary.json`: 22 avatar-specific clothing tracks, 73 quaternion
  samples, identity at both ends; layered over existing idle clothing.
- `Lumine_greet_1.blend`: `DH_greet` body/cloth, `DHX_greet` expression and
  `DHC_greet` clothing Actions, all with Fake User.
- `greet_1.preview.mp4`, `greet.preview.front.png`, `greet.preview.side.png`:
  diagnostic previews; these are not website runtime dependencies.
- `build_greet.py`: run inside the saved Blender 5.2 source to rebuild Actions.
  Then run `validate_greet.py`, export VRM Animation, and save the source.
- `inspect_greet_reference.py VIDEO`: optional local OpenCV reference sheets.
- `render_greet_preview.py`: renders all 73 diagnostic frames to a new temporary
  directory; the caller is responsible for encoding and removing that directory.

## Verification

Quarter-frame pose checks are recorded in `greet.validation.json`: foot head
and toe-tip drift below 0.1 mm; identical start/end; no locked elbow/wrist;
stable head during the held wave; all authored curves Bezier.

The full diagnostic frame sequence was rendered; selected sequential poses and
front/side rendered views were visually checked.
Blender MCP viewport capture returned black, so rendered views were used for
visual checks instead. Browser-skill checks exercised the real chat greeting
and the reduced-motion control. Numeric/frontend tests cover secondary-data
failure, cancellation, stale avatar loads, expression ownership and cleanup.

Commands:

```text
python -m unittest discover -s tests -p test_greet_assets.py
node --test tests/test_vrm_frontend.cjs
```

Asset tests: 4/4 pass. Frontend tests: 24/25 pass. The existing test expecting
consecutive booking requests to deduplicate still fails against the existing
handler; that unrelated behavior was not changed.
