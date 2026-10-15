import asyncio
import json
import math
import struct
import unittest
from pathlib import Path

from vrm_demo import vrm_server

MODELS = Path(__file__).resolve().parents[1] / 'models'


def read_vrm(path):
    data = path.read_bytes()
    magic, version, length = struct.unpack_from('<III', data)
    assert magic == 0x46546C67 and version == 2 and length == len(data)
    size = struct.unpack_from('<I', data, 12)[0]
    return json.loads(data[20:20 + size]), data[20 + size:]


class IdleAssetsTests(unittest.TestCase):
    def test_default_character_has_valid_expression_bindings(self):
        model, _ = read_vrm(MODELS / 'characters/schoolBoy.vrm')
        groups = model['extensions']['VRM']['blendShapeMaster']['blendShapeGroups']
        self.assertTrue({'a', 'i', 'u', 'e', 'o', 'blink'} <= {g['presetName'] for g in groups})
        for group in groups:
            for bind in group['binds']:
                mesh = model['meshes'][bind['mesh']]
                self.assertTrue(any(bind['index'] < len(primitive.get('targets', []))
                                    for primitive in mesh['primitives']))

    def test_blender_tracks_are_finite_normalized_and_seamless(self):
        data = json.loads((MODELS / 'animations/Lumine_idle.json').read_text())
        # This legacy idle asset keeps its source hash for provenance; the
        # source Lumine model is not part of the current character catalog.
        self.assertRegex(data['sourceSha256'], r'^[0-9a-f]{64}$')
        expected_samples = round(data['duration'] * data['fps']) + 1
        self.assertGreater(len(data['tracks']), 20)
        for track in data['tracks']:
            values = track['values']
            self.assertEqual(len(values), expected_samples * 4)
            for start in range(0, len(values), 4):
                q = values[start:start+4]
                self.assertTrue(all(math.isfinite(v) for v in q))
                self.assertAlmostEqual(sum(v*v for v in q), 1, places=4)
            dot = sum(a*b for a,b in zip(values[:4], values[-4:]))
            self.assertAlmostEqual(abs(dot), 1, places=4)

    def test_default_routes_use_classified_assets(self):
        avatar = asyncio.run(vrm_server.default_avatar())
        idle = asyncio.run(vrm_server.default_idle())
        self.assertEqual(Path(avatar.path).resolve(), (MODELS / 'characters/schoolBoy.vrm').resolve())
        self.assertEqual(Path(idle.path).resolve(), (MODELS / 'animations/Idle_Doctor.vrma').resolve())
        self.assertTrue(Path(avatar.path).is_file())
        self.assertTrue(Path(idle.path).is_file())
