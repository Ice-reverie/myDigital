from pathlib import Path
import pickle
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import data_preparation_mini as preparation


class PreparationTests(unittest.TestCase):
    def test_cli_help_does_not_load_models_or_start_a_server(self):
        result = subprocess.run([sys.executable, '-B', preparation.__file__, '--help'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--matting', result.stdout)

    def test_frame_marker_matches_browser_bit_order(self):
        for index in range(32):
            frame = np.zeros((4, 8, 3), dtype=np.uint8)
            preparation.encode_binary_pixels(frame, 8, index)
            pixels = frame[:2, -2:, 0].flatten()
            decoded = sum((int(pixel > 128) << bit) for pixel, bit in zip(pixels, [1, 0, 3, 2]))
            self.assertEqual(decoded, index % 16)

    def test_extraction_keeps_reverse_frames_and_landmarks_aligned(self):
        class Detector:
            def __init__(self, model): pass
            def detect_single_face(self, frame): return 0, 0, 8, 8, np.zeros((5, 2))

        def predict(frame, bbox, keypoints):
            return np.full((1, 478, 3), frame[3, 3, 0], dtype=np.float32), np.array([1.0])

        modules = {
            'talkingface.util.face_detect_scrfd': types.SimpleNamespace(SCRFD=Detector),
            'talkingface.util.face_mesh_478': types.SimpleNamespace(predict_mesh=predict),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = root / 'frames'
            frames.mkdir()
            for i in range(3):
                cv2.imwrite(str(frames / f'{i:06d}.png'), np.full((8, 8, 3), 20 + i, np.uint8))

            def encode(command, **kwargs):
                encoded = Path(command[command.index('-i') + 1]).parent
                images = [cv2.imread(str(p)) for p in sorted(encoded.glob('*.png'))]
                self.assertEqual([int(image[3, 3, 0]) for image in images], [20, 21, 22, 22, 21, 20])
                Path(command[-1]).write_bytes(b'mocked video')

            with patch.dict(sys.modules, modules), patch.object(preparation.subprocess, 'run', side_effect=encode):
                count = preparation.extract_from_video(frames, root / 'processed.pkl', root / 'processed.mp4')
            with (root / 'processed.pkl').open('rb') as source:
                points = pickle.load(source)
            self.assertEqual(count, 6)
            self.assertEqual(points.shape, (6, 478, 3))
            self.assertEqual(points[:, 0, 0].tolist(), [20, 21, 22, 22, 21, 20])
            self.assertFalse(list(root.glob('mini-encoded-*')))

    def test_pipeline_cleans_its_frames_on_failure_without_removing_user_files(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / 'frames'
            existing.mkdir()
            sentinel = existing / 'keep.txt'
            sentinel.write_text('keep')
            with patch.object(preparation.shutil, 'which', return_value='ffmpeg'), \
                 patch.object(preparation, 'prepare_video', return_value=2), \
                 patch.object(preparation, 'extract_from_video', side_effect=RuntimeError('failed')):
                with self.assertRaises(RuntimeError):
                    preparation.data_preparation_mini('video.mp4', directory)
            self.assertTrue(sentinel.exists())
            self.assertFalse(list(Path(directory).glob('mini-frames-*')))
