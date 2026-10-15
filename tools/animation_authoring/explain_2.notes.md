# explain_2 — video-referenced left-hand explanation

- Reference: `877f087bf71e2373ea2fe25582408c5a.mp4`, 30 fps; consecutive source frames 24–191 inspected.
- Manually interpreted reference, not motion capture. Hidden depth, palm rotation and proportions are adapted to Lumine. Supination is spread across the lifting/opening phase to avoid wrist snapping.
- Timeline: 24 fps, frames 0–168, 7 seconds. 308 recorded observations; 337 authored pose times (all source-frame timestamps plus all output frames), 169 exported samples.
- Actions: `DH_explain_2` body, `DHX_explain_2` expressions, `DHC_explain_2` secondary bones. All retained with Fake User. The body action includes secondary tracks for direct Blender preview; DHC is an editable separate copy, not an additional additive layer.
- Primary motion: left upper arm/forearm/wrist and individual fingers, quiet right arm, pelvis/legs for planted feet, spine/chest breathing and restrained head orientation.
- Expression peaks: happy 0.7, blink 1.0; speech vowels remain zero. Face morph binding weights are deliberately mild in the source file.
- Secondary JSON: 33 nonhuman tracks, xyzw quaternion offsets, 24 fps, identity endpoints. Includes shoulder drapes, skirt and hair. Intended for this Lumine skeleton only; not integrated into the website.
- Source curves are Bezier with AUTO_CLAMPED handles. VRM Add-on exports sampled animation; the VRMA is validated independently.
- Quarter-frame QA: feet <0.006 mm; identical neutral endpoints within 1.5e-8 matrix error; minimum elbow 9.81°, wrist 4.68°; held-head variation 0.069°. See `explain_2.validation.json`.
- Visual QA: full front sequence plus front/side poses rendered; viewport screenshot returned black. MP4 preview retained for user review, not a claim of exact 3D reconstruction.
- Existing `explain.vrma` renamed `explain_1.vrma` without changing its bytes. The legacy `explain` endpoint resolves to that original asset. The catalog now includes `explain_2` as a random variant of the explain scene, with its matching secondary tracks.

Rebuild in Blender 5.2 with `build_explain_2.py`, then `validate_explain_2.py`. Reference observations and build script are also embedded as text blocks in `Lumine_explain_2.blend`. Export using the VRM Add-on's VRM Animation exporter.
