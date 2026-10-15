import asyncio
import hashlib
import json
import math
from pathlib import Path
import unittest
import test_greet_assets as assets


class ExplainAssetTests(unittest.TestCase):
    ASSET='legacy/explain_2.vrma'
    FRAME_COUNT=169
    setUpClass=classmethod(assets.GreetAssetTests.setUpClass.__func__)

    def test_export_endpoints_and_feet(self):
        self.assertEqual(self.ext['specVersion'],'1.0')
        self.assertTrue(all(len(t)==169 and t[0][0]==0 and t[-1][0]==7 for t in self.times))
        for values in self.channels.values():
            self.assertLess(max(abs(a-b) for a,b in zip(values[0],values[-1])),1e-6)
        for name in ('leftFoot','rightFoot'):
            self.assertLess(max(math.dist(f[name][0],self.world[0][name][0]) for f in self.world),.0001)
        self.assertGreater(max(math.dist(f['leftHand'][0],self.world[0]['leftHand'][0]) for f in self.world),.15)

    def test_expressions_and_secondary(self):
        presets=self.ext['expressions']['preset']
        self.assertAlmostEqual(max(v[0] for v in self.channels[presets['happy']['node'],'translation']),.7)
        self.assertAlmostEqual(max(v[0] for v in self.channels[presets['blink']['node'],'translation']),1)
        for name in ('aa','ih','ou','ee','oh'):
            self.assertTrue(all(v[0]==0 for v in self.channels[presets[name]['node'],'translation']))
        data=json.loads((assets.ROOT/'legacy/explain_2.secondary.json').read_text())
        self.assertEqual((data['version'],data['fps'],data['duration']),(1,24,7))
        self.assertEqual(len(data['tracks']),49)
        self.assertEqual(sum('Twist' in t['nodeName'] for t in data['tracks']),16)
        for track in data['tracks']:
            values=track['values']
            self.assertEqual(len(values),169*4)
            self.assertEqual(values[:4],[0,0,0,1]);self.assertEqual(values[-4:],[0,0,0,1])
            for i in range(0,len(values),4):
                self.assertAlmostEqual(sum(v*v for v in values[i:i+4]),1,places=5)

    def test_alias_uses_approved_gentle_action_and_retains_original_archive(self):
        response=asyncio.run(assets.server.scene_animation('explain'))
        self.assertEqual(Path(response.path).name,'explain_1.vrma')
        self.assertEqual(Path(response.path).read_bytes(), (assets.ROOT/'review_health/Explain_Gentle.vrma').read_bytes())
        self.assertEqual(hashlib.sha256((assets.ROOT/'legacy/explain_1.vrma').read_bytes()).hexdigest(),'7761a7a5f23bef642fde689b790ce4447a497d7f4125b7289144bb0b90f28254')
        self.assertNotIn('explain_2',assets.server.SCENE_ACTIONS)
        with self.assertRaises(assets.server.HTTPException):
            asyncio.run(assets.server.scene_animation('explain_2'))
