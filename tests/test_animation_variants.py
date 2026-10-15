import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from vrm_demo import vrm_server as server


class AnimationVariantTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_and_all_variant_resources_over_http(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://test') as client:
            response = await client.get('/api/animations')
            self.assertEqual(response.status_code, 200)
            catalog = response.json()
            self.assertEqual(set(catalog), server.SCENE_ACTIONS)
            self.assertEqual(catalog['explain'], [{'id': 'explain_1', 'secondary': False}])
            self.assertEqual((await client.get('/api/animations/idle')).content[:4], b'glTF')
            self.assertEqual((await client.get('/api/animations/idle/legacy')).json()['version'], 1)
            for name, variants in catalog.items():
                self.assertTrue(variants)
                for variant in variants:
                    url = f"/api/animations/{name}/{variant['id']}"
                    result = await client.get(url)
                    self.assertEqual(result.status_code, 200)
                    self.assertEqual(result.content[:4], b'glTF')
                    secondary = await client.get(url+'/secondary')
                    self.assertEqual(secondary.status_code, 200 if variant['secondary'] else 404)
            for url in ['/api/animations/explain/explain_2', '/api/animations/greet/explain_2', '/api/animations/explain/explain_999',
                        '/api/animations/unknown/unknown_1', '/api/animations/explain/explain_2.vrma',
                        '/api/animations/explain/%2e%2e%2fcharacters']:
                self.assertEqual((await client.get(url)).status_code, 404)

    async def test_discovery_orders_numbers_and_ignores_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'vrm_demo').mkdir()
            assets = root/'models'/'animations'
            assets.mkdir(parents=True)
            for filename in ('explain_10.vrma','explain_2.vrma','explain_1.vrma','explain_01.vrma',
                             'explain_0.vrma','explain_3.preview.mp4','unknown_1.vrma'):
                (assets/filename).write_bytes(b'test')
            with patch.object(server, 'BASE_DIR', str(root/'vrm_demo')):
                self.assertEqual(server.animation_variants('explain'), ['explain_1','explain_2','explain_10'])
                (assets/'explain_2.vrma').unlink()
                self.assertEqual(server.animation_variants('explain'), ['explain_1','explain_10'])
                self.assertEqual((await server.animation_catalog())['greet'], [])
                with self.assertRaises(server.HTTPException):
                    await server.scene_animation('greet')
                with self.assertRaises(server.HTTPException):
                    await server.scene_animation_variant('explain','explain_2')
