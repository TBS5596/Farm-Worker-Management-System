"""Which cameras can this machine actually see?

    python tools/list_cameras.py
    python tools/list_cameras.py --max 8          # sweep more indices
    python tools/list_cameras.py --source rtsp://192.168.1.50:554/stream1

Sweeps the local camera indices, opens each one, and reports the resolution it
really returns - then prints the exact source string to paste into the CCTV
page.

It exists mainly for one job: finding the index of a **phone attached as a
camera**. A phone connected to a Mac through Continuity Camera, or to Windows
through Camo or iVCam, or to Linux through DroidCam, does not announce itself.
It simply becomes another numbered device, and the only practical way to tell
which number is to open each one and look at what comes out. A phone almost
always reports a markedly higher resolution than a built-in laptop webcam,
which is usually enough to identify it without a preview window.

Nothing here writes to the database or changes any setting.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Quieten the backends before OpenCV is imported. Sweeping indices that do not
# exist is the normal case here, and every miss otherwise prints a warning that
# buries the answer.
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_MSMF", "0")

import cctv_engine  # noqa: E402


def _guess(width: int, height: int) -> str:
    """A hint at what a camera probably is, from its resolution alone.

    Deliberately phrased as a guess. Resolution is suggestive, not conclusive -
    an external USB webcam can match a phone, and a phone in a low-power mode
    can match a laptop. The operator confirms with the preview on the CCTV page;
    this only narrows the list.
    """
    pixels = width * height
    if pixels >= 1920 * 1080:
        return "high resolution - often a phone or a good external camera"
    if pixels >= 1280 * 720:
        return "typical of a built-in laptop webcam"
    if pixels > 0:
        return "low resolution"
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List the cameras this machine can open.")
    parser.add_argument("--max", type=int, default=5,
                        help="highest device index to try (default 5)")
    parser.add_argument("--source", action="append", default=[],
                        help="also test a specific source, e.g. an rtsp:// URL. "
                             "May be given more than once.")
    args = parser.parse_args()

    print()
    print("Cameras this machine can open")
    print("=" * 68)
    print(f"Platform: {sys.platform}    Backend: "
          f"{'AVFoundation' if sys.platform == 'darwin' else 'DirectShow' if sys.platform == 'win32' else 'V4L2'}")
    print()

    working = []

    for index in range(args.max + 1):
        result = cctv_engine.probe_source(index)
        if result["read_ok"]:
            working.append(result)
            size = f"{result['width']}x{result['height']}"
            fps = f"{result['fps']:g} fps" if result["fps"] else "fps unknown"
            print(f"  [{index}]  WORKS   {size:>11}   {fps:<12} ({result['elapsed_ms']} ms)")
            hint = _guess(result["width"], result["height"])
            if hint:
                print(f"         {hint}")
            print(f"         source string:  builtin://{index}")
            print()
        elif result["opened"]:
            print(f"  [{index}]  opened but returned no frame - in use by another "
                  f"application?")
            print()

    for source in args.source:
        result = cctv_engine.probe_source(source)
        status = "WORKS" if result["read_ok"] else "FAILED"
        print(f"  {status}   {source}")
        if result["read_ok"]:
            print(f"         {result['width']}x{result['height']}, "
                  f"{result['elapsed_ms']} ms")
            print(f"         source string:  {source}")
            working.append(result)
        else:
            print(f"         {result['error']}")
        print()

    print("=" * 68)

    if not working:
        print("""
No cameras found.

  - On Linux, check that /dev/video* exists and that your user is in the
    'video' group. Inside Docker, the device must be passed through - see the
    commented 'devices:' block in docker-compose.yml.
  - On macOS and Windows, another application holding the camera will block
    this one. Close video-conferencing apps and try again.
  - A phone attached as a camera has to be awake, unlocked and connected
    before it appears here.
""")
        return

    print(f"""
{len(working)} camera(s) available.

To use one for clock-in: CCTV page -> Add CCTV Feed -> paste the source string
above -> press Test -> press the star to make it the attendance camera.

Connecting a phone? See 'Using a phone as the camera' in the operator manual.
If two entries appear and you cannot tell which is the phone, unplug or
disconnect it, run this again, and see which one disappeared.
""")


if __name__ == "__main__":
    main()
