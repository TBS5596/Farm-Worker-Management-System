"""Threshold-sensitivity study for the face verification decision.

Chapter 4 of the project report needs accuracy evidence rather than an asserted
percentage. This script produces it, and prints the caveats with the numbers so
they cannot be quoted out of context.

Method
------
Genuine trials    one enrolled identity is probed with held-out captures of the
                  same face, altered to imitate real capture variation:
                  brightness, small rotations, scale and mild blur. None of the
                  probes is one of the enrolled samples.
Impostor trials   the same captures claim each OTHER enrolled worker's ID. A
                  correct system must refuse every one of these - this is the
                  buddy-punching case the project exists to stop.

For each candidate threshold the script counts:
  FRR  false rejection rate - genuine attempts wrongly refused
  FAR  false acceptance rate - impostor attempts wrongly accepted

Honest limits, which the report states alongside the results:
  * One real human identity was available, so the genuine set varies capture
    conditions rather than people. It measures robustness to conditions, not
    discrimination between many faces.
  * The other enrolled templates are deterministic synthetic patterns, so the
    impostor trials test that a non-matching template is refused, not that two
    similar-looking people are told apart.
  * A full FAR/FRR characterisation needs a multi-person enrolled population and
    belongs to the field pilot.

    python tools/accuracy_experiment.py
"""

import json
import os
import statistics
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import face_engine  # noqa: E402
from app import app  # noqa: E402
from models import FaceTemplate, Worker  # noqa: E402

THRESHOLDS = [10, 20, 25, 30, 35, 40, 45, 50, 55, 60, 70]

# Per-worker recognizers, cached. face_engine's model answers "who is this?"
# across everyone, which is the right question for the live decision but the
# wrong one for measuring separation: an impostor trial needs the score against
# the identity that was CLAIMED, not against whoever matched best. Training one
# single-label recognizer per worker gives exactly that.
_PER_WORKER = {}


def _score_against(worker_pk, crop):
    """Match confidence of `crop` against one worker's enrolled samples only."""
    import cv2 as _cv2

    if worker_pk not in _PER_WORKER:
        samples = [face_engine._decode(row.face_embedding)
                   for row in FaceTemplate.query.filter_by(worker_id=worker_pk).all()]
        samples = [s for s in samples if s is not None]
        if not samples:
            _PER_WORKER[worker_pk] = None
        elif face_engine.has_lbph():
            model = _cv2.face.LBPHFaceRecognizer_create(radius=1, neighbors=8, grid_x=8, grid_y=8)
            model.train(samples, np.array([worker_pk] * len(samples), dtype=np.int32))
            _PER_WORKER[worker_pk] = model
        else:
            _PER_WORKER[worker_pk] = {"crops": samples, "labels": [worker_pk] * len(samples)}

    model = _PER_WORKER[worker_pk]
    if model is None:
        return None
    _label, score = face_engine._predict(model, crop)
    return float(score)


def _variant(image, brightness=0, angle=0.0, scale=1.0, blur=0):
    """One held-out capture of the same face under different conditions."""
    out = image.copy()
    if angle or scale != 1.0:
        height, width = out.shape[:2]
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, scale)
        out = cv2.warpAffine(out, matrix, (width, height), borderMode=cv2.BORDER_REPLICATE)
    if brightness:
        out = cv2.convertScaleAbs(out, alpha=1.0, beta=brightness)
    if blur:
        out = cv2.GaussianBlur(out, (blur | 1, blur | 1), 0)
    return out


# Capture conditions a farm terminal actually sees: even light, bright morning
# sun, shade, a turned head, standing closer or further back, and camera shake.
CONDITIONS = [
    ("even light, square to camera", dict(brightness=0, angle=0)),
    ("bright light", dict(brightness=25, angle=0)),
    ("dim light", dict(brightness=-25, angle=0)),
    ("head turned left", dict(brightness=0, angle=-6)),
    ("head turned right", dict(brightness=0, angle=6)),
    ("standing closer", dict(brightness=0, angle=0, scale=1.08)),
    ("standing further back", dict(brightness=0, angle=0, scale=0.93)),
    ("bright and turned", dict(brightness=18, angle=-4)),
    ("dim and turned", dict(brightness=-18, angle=5)),
    ("slight camera shake", dict(brightness=0, angle=2, blur=3)),
]


def main():
    try:
        from skimage import data
    except ImportError:
        print("scikit-image is needed for the sample photograph: pip install scikit-image")
        return

    face = cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)

    with app.app_context():
        enrolled = (Worker.query
                    .filter(Worker.face_enrolled_at.isnot(None))
                    .order_by(Worker.worker_id.asc()).all())
        if len(enrolled) < 2:
            print("Need at least two enrolled workers. Run tools/seed_demo.py --force first.")
            return

        subject = enrolled[0]
        others = enrolled[1:]
        face_engine.invalidate()

        genuine, impostor, per_condition = [], [], []

        for label, kwargs in CONDITIONS:
            probe = _variant(face, **kwargs)

            result = face_engine.verify_worker(subject.id, [probe], threshold=0.0,
                                               require_eyes=True)
            crop, _quality, _reason = face_engine.extract_face(probe, require_eyes=True)
            own_score = _score_against(subject.id, crop) if crop is not None else None
            if own_score is not None:
                genuine.append(own_score)
            per_condition.append({
                "condition": label,
                "face_detected": bool(result["face_found"]),
                "genuine_score": round(own_score, 2) if own_score is not None else None,
                "attributed_to_subject": result["matched_worker_pk"] == subject.id,
            })

            for other in others:
                attempt = face_engine.verify_worker(other.id, [probe], threshold=0.0,
                                                    require_eyes=True)
                claimed_score = _score_against(other.id, crop) if crop is not None else None
                if claimed_score is not None:
                    impostor.append({
                        "claimed": other.worker_id,
                        # Score against the CLAIMED identity - what a verification
                        # system compares to its threshold.
                        "score": round(claimed_score, 2),
                        # And what the live system actually decided: it also
                        # requires the best match to BE the claimed worker.
                        "attributed_to_claimed": attempt["matched_worker_pk"] == other.id,
                    })

        sweep = []
        for threshold in THRESHOLDS:
            rejected = sum(1 for s in genuine if s < threshold)
            # Two readings, both reported: score-only (would a pure 1:1
            # verifier accept?) and the system's own rule, which additionally
            # requires the best match across all enrolled workers to be the
            # claimed one.
            accepted_score_only = sum(1 for a in impostor if a["score"] >= threshold)
            accepted_impostors = sum(
                1 for a in impostor if a["attributed_to_claimed"] and a["score"] >= threshold
            )
            sweep.append({
                "threshold_pct": threshold,
                "genuine_trials": len(genuine),
                "genuine_rejected": rejected,
                "frr_pct": round(rejected / len(genuine) * 100, 1) if genuine else None,
                "impostor_trials": len(impostor),
                "impostor_accepted": accepted_impostors,
                "far_pct": round(accepted_impostors / len(impostor) * 100, 1) if impostor else None,
                "impostor_accepted_score_only": accepted_score_only,
                "far_score_only_pct": round(accepted_score_only / len(impostor) * 100, 1)
                if impostor else None,
            })

        report = {
            "engine": face_engine.engine_info(),
            "subject_worker": subject.worker_id,
            "enrolled_samples_for_subject": FaceTemplate.query.filter_by(
                worker_id=subject.id).count(),
            "other_enrolled_identities": len(others),
            "genuine": {
                "trials": len(genuine),
                "mean": round(statistics.mean(genuine), 2) if genuine else None,
                "median": round(statistics.median(genuine), 2) if genuine else None,
                "min": round(min(genuine), 2) if genuine else None,
                "max": round(max(genuine), 2) if genuine else None,
                "stdev": round(statistics.stdev(genuine), 2) if len(genuine) > 1 else 0.0,
            },
            "impostor": {
                "trials": len(impostor),
                "accepted_at_default_threshold": sum(
                    1 for a in impostor if a["attributed_to_claimed"] and a["score"] >= 35),
                "mean_score": round(statistics.mean([a["score"] for a in impostor]), 2)
                if impostor else None,
                "max_score": round(max(a["score"] for a in impostor), 2) if impostor else None,
                "min_score": round(min(a["score"] for a in impostor), 2) if impostor else None,
                "stdev_score": round(statistics.stdev([a["score"] for a in impostor]), 2)
                if len(impostor) > 1 else 0.0,
            },
            "per_condition": per_condition,
            "threshold_sweep": sweep,
            "caveats": [
                "One real human identity; genuine trials vary capture conditions, not people.",
                "Impostor templates are synthetic patterns, not other photographed faces.",
                "A full FAR/FRR characterisation requires a multi-person enrolled population.",
            ],
        }

    out = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docs",
                                       "accuracy_results.json"))
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print(json.dumps(report, indent=2))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
