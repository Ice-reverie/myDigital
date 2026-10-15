# Hospital scene assets

- `scenes/outpatient.png`, `scenes/waiting.png`, `scenes/guidance.png`: generated for this project from the three hospital directions selected during design exploration (2026-09-24). Original PNGs, 1448 × 1086. They depict fictional architecture, contain no patient records, and are used as visual scenery rather than factual hospital guidance.
- The live VRM character, dialogue and controls are rendered separately. Scene motion, crossfades and pointer parallax are implemented in `../js/hospital-scenes.js`.
- `scenes/outpatient-floor-albedo.png`: generated for the real 3D outpatient sample (2026-09-24), 1254 × 1254. Seamless-looking pale stone diffuse texture; contains no baked scene, character, shadows, or perspective. Used only as the repeating floor material, with a procedural fallback if loading fails. Architecture is built in `../js/outpatient-room.js`; the original `outpatient.png` remains available for comparison.
- `icons/*.svg`: unmodified Bootstrap Icons 1.13.1, from <https://github.com/twbs/icons/tree/v1.13.1/icons>. The upstream MIT license is included at `icons/LICENSE`. CSS masks apply the current scene color to these locally served icons.

- The three 3D rooms are built in `../js/outpatient-room.js`, `waiting-room.js`, and `guidance-room.js`. The latter two reuse the same floor albedo through `hospital-room-kit.js`; wood grain and physical signage are procedural material textures. Reference images remain available via the comparison button.
