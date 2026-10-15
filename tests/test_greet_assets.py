import asyncio
import json
import math
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from vrm_demo import vrm_server as server

ROOT = Path(__file__).resolve().parents[1] / 'models' / 'animations'


def multiply(a, b):
    x,y,z,w=a; X,Y,Z,W=b
    return (w*X+x*W+y*Z-z*Y,w*Y-x*Z+y*W+z*X,w*Z+x*Y-y*X+z*W,w*W-x*X-y*Y-z*Z)


def rotate(q, v):
    return multiply(multiply(q, (*v,0)), (-q[0],-q[1],-q[2],q[3]))[:3]


class GreetAssetTests(unittest.TestCase):
    ASSET = 'greet_1.vrma'
    FRAME_COUNT = 73
    @classmethod
    def setUpClass(cls):
        raw=(ROOT/cls.ASSET).read_bytes()
        cls.magic,version,length=struct.unpack_from('<4sII',raw)
        assert version==2 and length==len(raw)
        chunks={};offset=12
        while offset<len(raw):
            size,kind=struct.unpack_from('<II',raw,offset);offset+=8
            chunks[kind]=raw[offset:offset+size];offset+=size
        cls.g=json.loads(chunks[0x4e4f534a]);data=chunks[0x004e4942]
        def accessor(i):
            a=cls.g['accessors'][i];v=cls.g['bufferViews'][a['bufferView']]
            assert a['componentType']==5126
            count={'SCALAR':1,'VEC3':3,'VEC4':4}[a['type']]
            start=v.get('byteOffset',0)+a.get('byteOffset',0)
            return [struct.unpack_from('<'+'f'*count,data,start+k*v.get('byteStride',count*4)) for k in range(a['count'])]
        cls.channels={};cls.times=[]
        ani=cls.g['animations'][0]
        for c in ani['channels']:
            sampler=ani['samplers'][c['sampler']]
            cls.times.append(accessor(sampler['input']))
            cls.channels[c['target']['node'],c['target']['path']]=accessor(sampler['output'])
        cls.ext=cls.g['extensions']['VRMC_vrm_animation']
        cls.human={n:b['node'] for n,b in cls.ext['humanoid']['humanBones'].items()}
        parents={c:i for i,n in enumerate(cls.g['nodes']) for c in n.get('children',[])}
        cls.world=[]
        for frame in range(cls.FRAME_COUNT):
            cache={}
            def world(i):
                if i in cache:return cache[i]
                n=cls.g['nodes'][i]
                t=cls.channels.get((i,'translation'));q=cls.channels.get((i,'rotation'))
                t=t[frame] if t else n.get('translation',(0,0,0))
                q=q[frame] if q else n.get('rotation',(0,0,0,1))
                if i in parents:
                    pt,pq=world(parents[i]);t=tuple(a+b for a,b in zip(pt,rotate(pq,t)));q=multiply(pq,q)
                cache[i]=(t,q);return cache[i]
            cls.world.append({n:world(i) for n,i in cls.human.items()})

    def test_duration_and_closed_endpoints(self):
        self.assertEqual(self.magic,b'glTF')
        self.assertEqual(self.ext['specVersion'],'1.0')
        self.assertTrue(all(len(t)==73 and t[0][0]==0 and t[-1][0]==3 for t in self.times))
        for values in self.channels.values():
            self.assertLess(max(abs(a-b) for a,b in zip(values[0],values[-1])),1e-6)

    def test_feet_locked_head_stable_and_face_side_wave(self):
        for name in ('leftFoot','rightFoot'):
            origin=self.world[0][name][0]
            self.assertLess(max(math.dist(f[name][0],origin) for f in self.world),.0001)
        q0=self.world[20]['head'][1]
        for f in self.world[20:39]:
            angle=2*math.acos(min(1,abs(sum(a*b for a,b in zip(q0,f['head'][1])))))
            self.assertLess(math.degrees(angle),.5)
        hand=self.world[30]['rightHand'][0]
        head=self.world[30]['head'][0]
        # Reference: fingers beside the face; wrist below the head, not overhead.
        self.assertGreater(head[1]-hand[1],.04)
        self.assertLess(head[1]-hand[1],.15)
        self.assertLess(abs(hand[0]-head[0]),.23)
        self.assertLess(self.world[30]['rightLowerArm'][0][1],self.world[30]['rightUpperArm'][0][1]-.07)
        self.assertGreater(math.dist(self.world[30]['leftHand'][0],self.world[0]['leftHand'][0]),.015)
        self.assertGreater(abs(self.world[30]['hips'][0][0]-self.world[0]['hips'][0][0]),.02)

    def test_smile_without_baked_speech_and_cloth_endpoints(self):
        presets=self.ext['expressions']['preset']
        happy=self.channels[presets['happy']['node'],'translation']
        self.assertAlmostEqual(max(v[0] for v in happy),.75)
        blink=self.channels[presets['blink']['node'],'translation']
        self.assertGreater(max(v[0] for v in blink[3:13]),.95)
        self.assertTrue(all(abs(v[0])<1e-6 for v in blink[13:]))
        for name in ('aa','ih','ou','ee','oh'):
            self.assertTrue(all(v[0]==0 for v in self.channels[presets[name]['node'],'translation']))
        cloth=json.loads((ROOT/'greet_1.secondary.json').read_text())
        self.assertEqual(len(cloth['tracks']),38)
        self.assertEqual(sum('Twist' in t['nodeName'] for t in cloth['tracks']),16)
        for t in cloth['tracks']:
            self.assertEqual(t['values'][:4],[0,0,0,1])
            self.assertEqual(t['values'][-4:],[0,0,0,1])

    def test_secondary_endpoint_and_missing_file(self):
        response=asyncio.run(server.greet_secondary())
        self.assertTrue(Path(response.path).is_file())
        self.assertEqual(response.media_type,'application/json')
        with patch.object(server.os.path,'isfile',return_value=False):
            with self.assertRaises(server.HTTPException) as error:
                asyncio.run(server.greet_secondary())
            self.assertEqual(error.exception.status_code,404)
