"""Filesystem locations used across the app."""

import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CAPTURES_DIR = os.path.join(BASE_DIR, "captures")
FACES_DIR = os.path.join(CAPTURES_DIR, "faces")
CLIPS_DIR = os.path.join(CAPTURES_DIR, "clips")


def ensure_dirs() -> None:
    for directory in (CAPTURES_DIR, FACES_DIR, CLIPS_DIR):
        os.makedirs(directory, exist_ok=True)
