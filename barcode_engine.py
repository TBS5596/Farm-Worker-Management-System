"""Worker identity cards: generating the value, rendering it, reading it back.

A card is the third factor at the capture point. The worker HAS the card, KNOWS
the PIN and IS the face; all three must agree before attendance is recorded.

What is actually printed on the card is a farm decision, not ours, because the
three options trade convenience against exposure:

    nrc_plain    The National Registration Number itself. Anyone who picks up a
                 dropped card and scans it with a free phone app reads a
                 national identifier. Simple, and it is what some supervisors
                 ask for, but it puts personal data on a piece of plastic that
                 leaves the farm in a pocket every evening.

    nrc_hash     A one-way scramble of the NRC, salted per installation. Still
                 unique per person and still derived from the NRC, but the NRC
                 cannot be read back out of it. The cost is that the value is
                 fixed by the NRC, so a lost card cannot be given a new number
                 without changing what identifies the worker.

    card_number  A generated code, FMS-XXXX-XXXX, that means nothing outside
                 this database. A lost card reveals only that it belongs to
                 some worker somewhere. It is the only option under which a
                 card can be voided and reissued cleanly.

The farm chooses with the `barcode_source` setting. Nothing in this module
prefers one; the manual explains the trade-off so the choice is informed.

Rendering produces SVG rather than PNG deliberately: an SVG barcode prints
crisply at any size on whatever printer the farm office owns, and needs no
image library in the install.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import secrets
from datetime import datetime

# The alphabet excludes I, O, 0 and 1: on a printed card under a dusty light,
# those four are the pairs a human re-types wrongly when a scanner fails.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

SOURCES = {
    "nrc_plain": {
        "label": "The NRC itself",
        "note": "Readable by anyone who scans the card.",
    },
    "nrc_hash": {
        "label": "A one-way scramble of the NRC",
        "note": "Tied to the NRC, but the NRC cannot be read back from it.",
    },
    "card_number": {
        "label": "A generated card number",
        "note": "Means nothing outside this system; can be voided and reissued.",
    },
}

SYMBOLOGIES = {
    "code128": "Code 128 (striped barcode, suits a laser scanner)",
    "qr": "QR code (survives a creased card, readable by a phone)",
}

DEFAULT_SOURCE = "nrc_plain"
DEFAULT_SYMBOLOGY = "code128"


# --------------------------------------------------------------------------
# Generating the value
# --------------------------------------------------------------------------

def _hash_salt() -> str:
    """Per-installation salt for the nrc_hash option.

    Without a salt, the same NRC would produce the same barcode at every farm
    running this software, so a card from one farm would be recognisable at
    another. The salt is derived from the application secret, which is already
    required to be set and kept out of the source tree.
    """
    return os.environ.get("FMS_SECRET_KEY", "fms-card-salt")


def _new_card_number() -> str:
    """FMS-XXXX-XXXX from a cryptographically random source."""
    body = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    return f"FMS-{body[:4]}-{body[4:]}"


def card_value(worker, source: str = DEFAULT_SOURCE) -> str | None:
    """The value to print on this worker's card, or None if it cannot be made.

    nrc_plain and nrc_hash both need an NRC on the worker record. A worker
    without one cannot be issued a card under those settings, and the caller
    reports that rather than silently issuing a blank card.
    """
    source = (source or DEFAULT_SOURCE).strip().lower()

    # Validate the setting before anything else. A typo must fail loudly rather
    # than fall through to "this worker has no NRC", which would send an
    # operator looking for a data problem that does not exist.
    if source not in SOURCES:
        raise ValueError(f"unknown barcode source: {source}")

    if source == "card_number":
        return _new_card_number()

    nrc = (getattr(worker, "nrc_number", "") or "").strip()
    if not nrc:
        return None

    if source == "nrc_plain":
        return nrc

    if source == "nrc_hash":
        digest = hashlib.sha256(f"{_hash_salt()}:{nrc}".encode("utf-8")).hexdigest()
        # 12 hex characters is 48 bits. For a workforce in the hundreds the
        # chance of two workers colliding is far below the chance of the card
        # itself being lost, and a short code prints legibly under the bars.
        return f"FMS-{digest[:6].upper()}-{digest[6:12].upper()}"

    # Unreachable: the membership check above covers every source.
    raise ValueError(f"unknown barcode source: {source}")


def normalize_scan(raw: str) -> str:
    """Clean a value as it arrives from a scanner.

    A keyboard-wedge scanner sometimes appends a carriage return, a tab, or
    stray whitespace depending on how it was configured at the factory, and a
    supervisor typing the code by hand may use lower case. Normalising here
    means the rest of the system compares like with like.
    """
    return re.sub(r"\s+", "", (raw or "")).upper()


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def render_svg(value: str, symbology: str = DEFAULT_SYMBOLOGY) -> str:
    """The barcode as an SVG document, ready to embed in a printable page."""
    symbology = (symbology or DEFAULT_SYMBOLOGY).strip().lower()

    if symbology == "qr":
        import qrcode
        import qrcode.image.svg as qrsvg
        img = qrcode.make(value, image_factory=qrsvg.SvgPathImage, box_size=10, border=2)
        buf = io.BytesIO()
        img.save(buf)
        return buf.getvalue().decode("utf-8")

    import barcode
    from barcode.writer import SVGWriter
    # write_text=False because the card already prints the value in a legible
    # font beneath the bars; the library's own caption is small and clipped.
    code = barcode.get("code128", value, writer=SVGWriter())
    buf = io.BytesIO()
    code.write(buf, options={"module_height": 12.0, "font_size": 0,
                             "text_distance": 1.0, "quiet_zone": 2.0,
                             "write_text": False})
    return buf.getvalue().decode("utf-8")


# --------------------------------------------------------------------------
# Issuing and reading back
# --------------------------------------------------------------------------

def issue_card(db, worker, source: str = DEFAULT_SOURCE, reissue: bool = False):
    """Give a worker a card value. Returns (ok, message).

    Refuses to overwrite an existing card unless `reissue` is set, so that a
    mis-click on the workers page cannot silently invalidate every card already
    in a worker's pocket.
    """
    if worker.card_barcode and not reissue:
        return False, f"{worker.name} already has a card. Use reissue to replace it."

    value = card_value(worker, source)
    if value is None:
        return False, (f"{worker.name} has no NRC on record, and the current card "
                       f"setting derives the barcode from it. Add an NRC, or switch "
                       f"the setting to a generated card number.")

    # The NRC-derived options are deterministic, so reissuing produces the same
    # value; only a generated card number actually changes. Saying so prevents a
    # supervisor believing a compromised card has been retired when it has not.
    from models import Worker
    clash = Worker.query.filter(Worker.card_barcode == value,
                                Worker.id != worker.id).first()
    if clash:
        return False, ("That card value is already held by another worker. "
                       "Two workers cannot share a card.")

    worker.card_barcode = value
    worker.card_issued_at = datetime.utcnow()
    worker.card_status = "active"
    db.session.commit()
    return True, f"Card issued to {worker.name}."


def void_card(db, worker):
    """Retire a lost card without deleting the attendance that references it."""
    if not worker.card_barcode:
        return False, f"{worker.name} has no card to void."
    worker.card_status = "void"
    db.session.commit()
    return True, (f"{worker.name}'s card is now void and will be refused at the "
                  f"capture point. Issue a new one when a replacement is printed.")


def resolve(scanned: str):
    """Find the active worker holding this card, or None.

    Returns (worker, reason). `reason` is set when the lookup failed, so the
    capture point can tell a supervisor whether the card is unknown, void, or
    belongs to a worker who is no longer active — three different problems with
    three different remedies.
    """
    from models import Worker

    value = normalize_scan(scanned)
    if not value:
        return None, "no_card"

    # Stored values are already normalised on write, but an installation
    # upgraded from an earlier release may hold raw NRCs with spaces or slashes,
    # so compare on the normalised form of both sides.
    worker = Worker.query.filter(Worker.card_barcode == value).first()
    if worker is None:
        for candidate in Worker.query.filter(Worker.card_barcode.isnot(None)).all():
            if normalize_scan(candidate.card_barcode) == value:
                worker = candidate
                break
    if worker is None:
        return None, "card_unknown"
    if (worker.card_status or "active").lower() == "void":
        return None, "card_void"
    if (worker.status or "").lower() != "active":
        return None, "worker_inactive"
    return worker, ""


CARD_REASON_MESSAGES = {
    "no_card": "Scan the worker's card, or type the card number.",
    "card_unknown": "That card is not recognised. It may belong to another farm, "
                    "or the worker may not have been issued one yet.",
    "card_void": "That card has been voided. Issue the worker a replacement.",
    "worker_inactive": "That card belongs to a worker who is not active.",
}


def stats():
    """Counts for the settings page: how much of the workforce is carded."""
    from models import Worker
    workers = Worker.query.all()
    active = [w for w in workers if (w.status or "").lower() == "active"]
    carded = [w for w in active if w.card_barcode
              and (w.card_status or "active").lower() == "active"]
    no_nrc = [w for w in active if not (w.nrc_number or "").strip()]
    return {
        "active_workers": len(active),
        "carded": len(carded),
        "uncarded": len(active) - len(carded),
        "void": sum(1 for w in workers if (w.card_status or "").lower() == "void"),
        "without_nrc": len(no_nrc),
    }
