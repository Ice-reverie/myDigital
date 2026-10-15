# Arm / palm coordination repair

Both `greet_1` and `explain_2` retain their original timing, hand-position paths,
expressions and lower-body motion. The weighted ArmTwist / HandTwist helpers
were previously inactive. They are siblings of the limb end bone, not a serial
chain: their offsets therefore compensate the inherited parent rotation.

The repaired upper arm takes a small axial adjustment; the elbow-weighted
forearm takes 15% of the palm roll. Existing weighted helpers distribute the
remaining roll progressively, with the main distal sleeve helper at 90%.
The palm retains only the final difference relative to the distal sleeve.
The large local angle of the human hand bone relative to the human forearm
is not an anatomical wrist-angle measurement on this sibling-helper rig.

Measured over quarter frames:

| Asset | Distal sleeve-to-palm axial difference | Maximum foot drift |
| --- | --- | --- |
| greet_1 | 9.85 degrees | 0.016 mm |
| explain_2 | 18.55 degrees | 0.006 mm |

All source curves remain Bezier / AUTO_CLAMPED. Identical endpoints and
continuous rotations were checked. Full front sequences and enlarged wrist
poses were rendered. The original meshes and skin weights were not modified.

VRMA does not carry these nonhuman helpers. Always pair each VRMA with its
matching secondary JSON for this Lumine model: greet has 38 tracks, explain_2
has 49. The shared frontend validator now permits only the exact ArmTwist /
HandTwist helper name family, while continuing to reject head/body injection.
Standalone players that omit the sidecar will not reproduce the deformation.

Reproduction: rebuild the original using build_greet.py or build_explain_2.py,
then run repair_arm_twist.py ONCE, followed by validate_arm_twist.py. Export
with the VRM Add-on, save at frame zero. A repaired action is tagged to prevent
accidental double application. Body and secondary-only Actions are preserved
with Fake User. The source projects contain the repair script as a text block.
