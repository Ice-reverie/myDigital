"""Prepare silent-video frames and 478-point landmarks for the MiniLive pipeline."""

import argparse
from pathlib import Path
import pickle
import shutil
import subprocess
import tempfile

import cv2
import numpy as np

MODULO_N = 16


def encode_binary_pixels(frame, vid_width, modulo_value):
    """Encode frame % 16 in the top-right 2x2 block read by MiniLive2.js."""
    if frame.shape[0] < 2 or vid_width < 2:
        raise ValueError("Video frames must be at least 2x2 pixels")
    value = modulo_value % MODULO_N
    for (row, col), bit in zip([(0, -2), (0, -1), (1, -2), (1, -1)], [1, 0, 3, 2]):
        frame[row, vid_width + col, :3] = 255 if value & (1 << bit) else 0


def extract_from_video(frames_dir, output_pkl_path, output_video_path, matting=False, reverse_option=True):
    # Keep heavyweight model imports out of the CLI/import path.
    from talkingface.util.face_detect_scrfd import SCRFD
    from talkingface.util.face_mesh_478 import predict_mesh

    paths = sorted(Path(frames_dir).glob('*.png'))
    if not paths:
        raise ValueError("The input video contains no readable frames")
    detector = SCRFD(None)
    process_matting = None
    if matting:
        from talkingface.RVM import process_img_matting
        process_matting = process_img_matting

    output_dir = Path(output_video_path).resolve().parent
    output_dir.mkdir(parents=True, exist_ok=True)
    Path(output_pkl_path).parent.mkdir(parents=True, exist_ok=True)
    landmarks = []
    expected_shape = None
    # Only this run's images are removed, including on inference/FFmpeg failure.
    with tempfile.TemporaryDirectory(prefix='mini-encoded-', dir=output_dir) as encoded_dir:
        for index, path in enumerate(paths):
            frame = cv2.imread(str(path))
            if frame is None:
                raise ValueError(f"Cannot read frame: {path}")
            if expected_shape is None:
                expected_shape = frame.shape
            if frame.shape != expected_shape:
                raise ValueError(f"Inconsistent frame dimensions: {path}")
            xmin, ymin, xmax, ymax, keypoints = detector.detect_single_face(frame)
            points, scores = predict_mesh(
                cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                np.array([xmin, ymin, xmax, ymax], dtype=np.float32), keypoints,
            )
            if points.shape != (1, 478, 3) or not np.isfinite(points).all() or scores[0] < 0.5:
                raise ValueError(f"Face landmarks are unreliable in frame: {path}")
            landmarks.append(points[0].copy())
            if process_matting is not None:
                rgba = process_matting(cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA), is_new_video=index == 0)
                alpha = rgba[:, :, 3:4].astype(np.float32) / 255.0
                foreground = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2BGR)
                frame = (foreground * alpha + np.array([0, 255, 0]) * (1 - alpha)).astype(np.uint8)
            frame_indices = [index]
            if reverse_option:
                frame_indices.append(len(paths) * 2 - index - 1)
            for frame_index in frame_indices:
                encoded = frame.copy()
                encode_binary_pixels(encoded, encoded.shape[1], frame_index)
                if not cv2.imwrite(str(Path(encoded_dir) / f'{frame_index:06d}.png'), encoded):
                    raise OSError(f"Cannot write encoded frame {frame_index}")

        subprocess.run([
            'ffmpeg', '-y', '-framerate', '25', '-start_number', '0',
            '-i', str(Path(encoded_dir) / '%06d.png'),
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
            '-pix_fmt', 'yuv420p', str(output_video_path),
        ], check=True, capture_output=True, text=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    points = np.asarray(landmarks, dtype=np.float32)
    if reverse_option:
        points = np.concatenate([points, points[::-1]], axis=0)
    with open(output_pkl_path, 'wb') as output:
        pickle.dump(points, output)
    return len(points)


def prepare_video(input_path, output_path, resize_option=False):
    cap = cv2.VideoCapture(str(input_path))
    try:
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {input_path}")
        # OpenCV reports dimensions after its default orientation handling.
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        cap.release()
    if width <= 0 or height <= 0:
        raise ValueError("Video dimensions must be positive")
    scale = min(1.0, 720 / width, 1280 / height) if resize_option else 1.0
    width, height = max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)
    Path(output_path).mkdir(parents=True, exist_ok=True)
    subprocess.run([
        'ffmpeg', '-i', str(input_path), '-vf', f'scale={width}:{height}',
        '-r', '25', '-start_number', '0', '-f', 'image2', '-y',
        str(Path(output_path) / '%06d.png'),
    ], check=True, capture_output=True, text=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    count = len(list(Path(output_path).glob('*.png')))
    if not count:
        raise ValueError("The input video contains no readable frames")
    return count


def data_preparation_mini(input_video, video_dir_path, matting=False, resize_option=False, reverse_option=True):
    if not shutil.which('ffmpeg'):
        raise EnvironmentError("FFmpeg is not installed or is missing from PATH")
    data_dir = Path(video_dir_path).resolve() / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    output_video_path = data_dir / 'processed.mp4'
    with tempfile.TemporaryDirectory(prefix='mini-frames-', dir=data_dir.parent) as frames_dir:
        frame_count = prepare_video(input_video, frames_dir, resize_option)
        extract_from_video(frames_dir, data_dir / 'processed.pkl', output_video_path, matting, reverse_option)
    return {'status': 'success', 'frame_count': frame_count, 'output_video': str(output_video_path)}


def main():
    parser = argparse.ArgumentParser(description='Prepare a silent video for MiniLive')
    parser.add_argument('input_video')
    parser.add_argument('output_dir')
    parser.add_argument('--matting', action='store_true', help='Use RVM to replace the background with green')
    parser.add_argument('--resize', action='store_true', help='Limit dimensions to 720x1280')
    args = parser.parse_args()
    result = data_preparation_mini(args.input_video, args.output_dir, matting=args.matting, resize_option=args.resize)
    print(result)


if __name__ == '__main__':
    main()
