# Three real 3D hospital scenes — design QA

Date: 2026-09-24

final result: passed

## Accepted scope

The user accepted the real 3D outpatient sample and requested the remaining two rooms plus the school boy as the default avatar. All three rooms are now selectable under the existing demo settings. Each has an original-image comparison. This follows the accepted realtime geometry style, not a promise of pixel-identical rendering of the generated reference photographs.

## Visual references and evidence

Reference images: `vrm_demo/static/assets/scenes/{outpatient,waiting,guidance}.png`.

Live URL: `http://127.0.0.1:8890/static/VRMCharacter.html?preview=hospital-3d`.

Final evidence is under `output/hospital-3d/`:

- `waiting-original.png`, `waiting-3d.png`, `waiting-comparison.png`.
- `guidance-original.png`, `guidance-3d.png`, `guidance-comparison.png`.
- `outpatient-schoolboy.png`, `settings-default.png`, `waiting-reduced.png`.

Original-image and 3D captures use the same 1280 × 720 viewport, default greeting, schoolBoy avatar, full-body view and production controls. Both combined inputs are 2560 × 752 with a 32-pixel heading strip; the panels retain their original pixels. Both combined images were opened, reviewed, corrected and recaptured. Small pose/light differences result from running animations. The live original-image mode applies its existing crop and parallax, making it a direct comparison at the user's actual UI layout.

Earlier outpatient reference comparisons and mobile evidence remain in `output/3d-prototype/`. Current changes retain the shared mobile framing and include automated checks for small screens and growing reply controls; this continuation's manual browser QA focused on desktop scene and default-avatar integration.

## Implemented spaces

- **Outpatient:** existing accepted blue-white reception, glass corridor, slowly opening automatic doors and architectural floor reflections.
- **Waiting:** sage seats, frosted side windows, warm oak reception, clinic doors, physical green signage, subtle foliage motion and a slowly opening clinic door. The door opens onto actual corridor geometry.
- **Guidance:** curved cyan glass columns, circular ceiling coves, white/cyan desk, full-height windows, blue seating and physical guidance signage. A desk-screen indicator moves slowly and glass trim lighting breathes subtly.

Waiting and guidance reuse a shared room kit for floor materials, reflections, lights, geometry batching and resource lifecycle. Inactive rooms remain hidden and stop advancing their animations. Rooms load on demand and are reused when revisited.

## Resolved findings

1. **Cached default model mismatch:** after the server default changed, an older cached `/api/avatar` response could still show AstraYao under the schoolBoy label. Startup now requests the explicit model URL `/api/avatars/schoolBoy`. Refresh was verified to show the actual school boy. The catalog, fallback copy and initial selector agree; the male voice preset remains available even when the catalog fails. Explicit personal avatar/voice preferences are preserved.
2. **Room-loading races and failures:** a generic room cache replaces the single-room variable. Late completions remain hidden, failed loads can retry, and unsupported rendering reports the corresponding image fallback. Rapid switches cannot replace the newest selection with an older result.
3. **Guidance sign obscured by the avatar:** moved the physical sign and symbol to the right upper portion of the rear wall, keeping them inside its bounds. Moved the desk-screen indicator rightward so its motion remains visible.
4. **Waiting seats mostly obscured:** moved the linked seats inward and adjusted their depth; the left foreground and the bubble's right edge now expose more of the seating row while preserving the avatar's clear standing area.
5. **Shared grounding and lighting:** all rooms use the same sole-vertex contact, soft contact shadow, invisible directional-shadow proxies and portrait lighting. The character and architecture use a shared camera/depth buffer. Room lighting is tone-mapped independently of the toon character.
6. **Initial camera below the face:** after user feedback, raised the shared 3D camera from waist height to approximately eye height (90% of avatar height). The optical axis stays level; vertical projection offset preserves full-body framing and mobile control clearance. Checked all three rooms and the full-body reset in the in-app browser. Reran all 66 frontend behavior tests, including eye-height, horizontal sightline and four desktop/mobile framing cases. Earlier comparison captures above predate this camera correction.
7. **Scene comparison control placement:** moved the original-image/3D toggle from the stage corner to the scene picker in Demo Character Settings. The dialog closes after a successful toggle so the selected scene is visible. Checked both directions in the in-app browser; the stage now shows only the full-body reset control.

## Required fidelity surfaces

- **Layout:** retains the header, conversation on the left, standing avatar and service panel on the right. Three scene choices replace the prototype-plus-image card set; original images remain one click away.
- **Typography and copy:** existing readable Chinese system fonts, full production messages and large-text controls remain. Scene controls say 3D and distinguish the original-image mode. Physical signs describe fictional areas or demo services, not live queues or hospital facts.
- **Color:** outpatient blue, waiting sage/warm white and guidance turquoise themes apply to both image and 3D modes. Reading panels remain sufficiently opaque against the geometry.
- **Assets and details:** all new architecture is code-built as requested; floor albedo is reused with scene tints, wood grain and physical signage use material textures, and existing Bootstrap icons are retained. Surface shading and detailed indirect illumination remain simpler than the source images, consistent with the accepted 3D sample.

## Verification

- In-app browser: selected all three rooms, compared waiting/guidance against their original images, returned to 3D, refreshed, and verified the selected scene and actual schoolBoy model persisted.
- Settings show **校服男生（默认）**, system default schoolBoy, and male voice while following the avatar. The server catalog returns the same identity and gender; `/api/avatar` serves the schoolBoy file.
- Started a SQLite demo booking in the waiting room, switched to guidance, selected 内科, received date/slot options, and cancelled. No appointment was confirmed.
- Verified the reduce-motion button state and return to normal motion. Production room tests verify real door/indicator movement, freezing/resuming and separate clocks.
- **107/107 frontend tests passed.** Includes scene-selection races, failed-load retries, rendering layers, animated sole contact, shadow following, disposal, shared-room geometry, finite instance transforms, floor contact, late/failed texture loads, reflection state restoration, mobile framing and default-model voice behavior.
- **71/71 Python tests passed.** Includes default model resource, labels, voice selection and existing database/dialogue tests.
- Browser console: no errors. The existing three-vrm deprecated-joint warning remains.
- `git diff --check`: passed. Work remains on the current branch. `docs/` and the original untracked Blender file were preserved. No temporary source scripts were created; QA captures and preview-service logs remain in ignored `output/`.

## Remaining limits

These are presentation rooms with constrained orbit/zoom, not freely walkable environments or factual hospital maps. Floor reflections show architecture; character grounding combines directional shadows and a small ambient-shadow approximation. Real microphone input, every alternative avatar and low-end hardware frame-time were not exhaustively retested. The separate Playwright smoke harness was updated but not run; UI testing used the requested in-app browser.
