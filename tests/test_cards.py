"""Worker identity cards: generating, resolving, voiding, printing.

Two things are worth testing hardest here, and neither is "does a barcode
render".

The first is that **what goes on the card is the farm's choice and the system
honours it exactly**. Three sources are offered and they differ in what a lost
card discloses, so a bug that silently produced the wrong one would be a
privacy failure rather than a cosmetic one.

The second is that **a card that should not work does not**. A voided card, a
card belonging to a deactivated worker, and a card nobody holds must each be
refused, and each for its own stated reason, because the three call for
different responses from the supervisor holding it.
"""

from datetime import datetime

import pytest

import barcode_engine
from database import db
from models import Worker


# ---------------------------------------------------------------------------
# Generating the value
# ---------------------------------------------------------------------------

def test_card_number_is_generated_and_unique(app_context, make_worker):
    """A generated card number means nothing outside this system."""
    worker = make_worker(name="Card One")
    first = barcode_engine.card_value(worker, "card_number")
    second = barcode_engine.card_value(worker, "card_number")

    assert first.startswith("FMS-")
    assert len(first) == 13          # FMS- plus 4, a dash, and 4
    # Generated afresh each time, which is what makes reissuing a lost card
    # meaningful under this setting.
    assert first != second


def test_card_number_avoids_ambiguous_characters(app_context, make_worker):
    """No I, O, 0 or 1 - the pairs a human mistypes off a printed card."""
    worker = make_worker(name="Card Two")
    for _ in range(40):
        value = barcode_engine.card_value(worker, "card_number")
        body = value.replace("FMS-", "").replace("-", "")
        assert not set(body) & set("IO01"), f"ambiguous character in {value}"


def test_nrc_plain_puts_the_nrc_on_the_card(app_context, make_worker):
    """The permissive option: the card literally carries the NRC.

    Asserted explicitly rather than left implicit, because this is the setting
    with a privacy consequence and a future change that quietly altered it
    would change what a dropped card discloses.
    """
    worker = make_worker(name="Card Three")
    worker.nrc_number = "123456/78/9"
    db.session.commit()

    assert barcode_engine.card_value(worker, "nrc_plain") == "123456/78/9"


def test_nrc_hash_does_not_disclose_the_nrc(app_context, make_worker):
    """The middle option: derived from the NRC, but the NRC is not in it."""
    worker = make_worker(name="Card Four")
    worker.nrc_number = "123456/78/9"
    db.session.commit()

    value = barcode_engine.card_value(worker, "nrc_hash")

    assert "123456" not in value
    assert "78" not in value.replace("FMS-", "")
    assert value.startswith("FMS-")
    # Deterministic: the same NRC always produces the same card, which is what
    # ties the card to the person and also why it cannot be reissued.
    assert value == barcode_engine.card_value(worker, "nrc_hash")


def test_nrc_derived_sources_need_an_nrc(app_context, make_worker):
    """A worker with no NRC cannot be carded while the barcode comes from it."""
    worker = make_worker(name="No NRC")
    assert worker.nrc_number is None

    assert barcode_engine.card_value(worker, "nrc_plain") is None
    assert barcode_engine.card_value(worker, "nrc_hash") is None
    # The generated option has no such dependency.
    assert barcode_engine.card_value(worker, "card_number") is not None


def test_unknown_source_is_rejected_loudly(app_context, make_worker):
    """A typo in the setting must fail, not silently pick a default."""
    worker = make_worker(name="Bad Source")
    with pytest.raises(ValueError):
        barcode_engine.card_value(worker, "nrc_reversed")


# ---------------------------------------------------------------------------
# Issuing
# ---------------------------------------------------------------------------

def test_issue_card_stores_the_value(app_context, make_worker):
    worker = make_worker(name="Issue Me")
    ok, message = barcode_engine.issue_card(db, worker, "card_number")

    assert ok, message
    assert worker.card_barcode
    assert worker.card_status == "active"
    assert isinstance(worker.card_issued_at, datetime)


def test_issue_refuses_to_overwrite_without_reissue(app_context, make_worker):
    """A mis-click must not invalidate a card already in somebody's pocket."""
    worker = make_worker(name="Careful")
    barcode_engine.issue_card(db, worker, "card_number")
    original = worker.card_barcode

    ok, message = barcode_engine.issue_card(db, worker, "card_number")

    assert not ok
    assert "already has a card" in message
    assert worker.card_barcode == original


def test_reissue_replaces_a_generated_card(app_context, make_worker):
    worker = make_worker(name="Reissue")
    barcode_engine.issue_card(db, worker, "card_number")
    original = worker.card_barcode

    ok, _ = barcode_engine.issue_card(db, worker, "card_number", reissue=True)

    assert ok
    assert worker.card_barcode != original


def test_two_workers_cannot_share_a_card(app_context, make_worker):
    """A value already held must never be issued to a second worker.

    The database enforces this too, but reaching the constraint would mean an
    unhandled error in front of an operator. The guard turns it into a sentence
    they can act on.
    """
    first = make_worker(name="Twin One")
    second = make_worker(name="Twin Two")
    second.nrc_number = "555555/55/5"
    db.session.commit()

    # Whatever the second worker would be given, hand it to the first.
    would_be = barcode_engine.card_value(second, "nrc_hash")
    first.card_barcode = would_be
    first.card_status = "active"
    db.session.commit()

    ok, message = barcode_engine.issue_card(db, second, "nrc_hash")

    assert not ok
    assert "already held by another worker" in message
    assert second.card_barcode is None


# ---------------------------------------------------------------------------
# Reading a card back
# ---------------------------------------------------------------------------

def test_resolve_finds_the_holder(app_context, make_worker):
    worker = make_worker(name="Scan Me")
    barcode_engine.issue_card(db, worker, "card_number")

    found, reason = barcode_engine.resolve(worker.card_barcode)

    assert found is not None
    assert found.id == worker.id
    assert reason == ""


def test_resolve_tolerates_what_a_scanner_appends(app_context, make_worker):
    """Keyboard-wedge scanners add carriage returns, tabs and stray spaces."""
    worker = make_worker(name="Messy Scan")
    barcode_engine.issue_card(db, worker, "card_number")
    value = worker.card_barcode

    for variant in (f"{value}\r\n", f"  {value}  ", f"{value}\t", value.lower()):
        found, _ = barcode_engine.resolve(variant)
        assert found is not None and found.id == worker.id, f"failed on {variant!r}"


def test_voided_card_is_refused(app_context, make_worker):
    """A lost card stops working, and says why."""
    worker = make_worker(name="Lost Card")
    barcode_engine.issue_card(db, worker, "card_number")
    barcode_engine.void_card(db, worker)

    found, reason = barcode_engine.resolve(worker.card_barcode)

    assert found is None
    assert reason == "card_void"
    # The row survives, so attendance history that references this worker is
    # untouched by voiding the card.
    assert worker.card_barcode is not None


def test_inactive_workers_card_is_refused(app_context, make_worker):
    worker = make_worker(name="Gone", status="active")
    barcode_engine.issue_card(db, worker, "card_number")
    worker.status = "inactive"
    db.session.commit()

    found, reason = barcode_engine.resolve(worker.card_barcode)

    assert found is None
    assert reason == "worker_inactive"


def test_unknown_card_is_refused(app_context, make_worker):
    make_worker(name="Somebody")
    found, reason = barcode_engine.resolve("FMS-ZZZZ-ZZZZ")

    assert found is None
    assert reason == "card_unknown"


def test_empty_scan_is_refused(app_context):
    found, reason = barcode_engine.resolve("")
    assert found is None
    assert reason == "no_card"


def test_every_refusal_reason_has_a_message():
    """A reason with no message would reach a supervisor as a blank error."""
    for reason in ("no_card", "card_unknown", "card_void", "worker_inactive"):
        assert barcode_engine.CARD_REASON_MESSAGES.get(reason)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_renders_both_symbologies(app_context):
    for symbology in ("code128", "qr"):
        svg = barcode_engine.render_svg("FMS-AB12-CD34", symbology)
        assert svg.lstrip().startswith("<?xml") or svg.lstrip().startswith("<svg")
        assert "svg" in svg[:400]


def test_renders_an_nrc_containing_slashes(app_context):
    """nrc_plain values contain '/', which the encoder must accept."""
    svg = barcode_engine.render_svg("123456/78/9", "code128")
    assert len(svg) > 500


# ---------------------------------------------------------------------------
# The capture point
# ---------------------------------------------------------------------------

def test_clock_in_page_hides_the_card_field_when_cards_are_off(client, setting):
    setting("barcode_enabled", "off")
    page = client.get("/").get_data(as_text=True)
    assert 'name="card_code"' not in page


def test_clock_in_page_shows_the_card_field_when_cards_are_on(client, setting):
    setting("barcode_enabled", "on")
    page = client.get("/").get_data(as_text=True)
    assert 'name="card_code"' in page


def test_a_void_card_is_refused_at_the_capture_point(client, setting, make_worker):
    setting("barcode_enabled", "on")
    worker = make_worker(name="Void At Gate", pin="1234")
    barcode_engine.issue_card(db, worker, "card_number")
    value = worker.card_barcode
    barcode_engine.void_card(db, worker)

    response = client.post("/", data={
        "mode": "worker", "card_code": value, "pin": "1234", "log_type": "IN",
    }, follow_redirects=True)

    assert b"voided" in response.data.lower()


@pytest.fixture()
def punches(monkeypatch):
    """Capture who the capture point decided to record, without a camera.

    The route calls record_punch, which opens a camera - impossible under test.
    What these tests care about is the decision the route reached *before* that
    call: which worker the factors resolved to, and whether it got that far at
    all. Substituting record_punch isolates exactly that.
    """
    import app as app_module

    seen = []

    def _fake(_app, worker, log_type, lat, lon, frames=None):
        seen.append(worker)
        return {"ok": True, "code": "recorded", "message": f"Welcome, {worker.name}!",
                "category": "success", "attendance_id": 1, "score": 80.0,
                "log_type": log_type, "geofence": None, "snapshot": None}

    monkeypatch.setattr(app_module, "record_punch", _fake)
    return seen


def test_a_scanned_card_overrides_a_stale_worker_number(client, setting, make_worker, punches):
    """A value left on a shared terminal must not redirect somebody's punch.

    The card is the identity claim. If a previous worker's number is still in
    the field when the next person scans, the scan must win - otherwise a queue
    at a shared terminal silently records attendance against the wrong person,
    which is the exact failure the system exists to prevent.
    """
    setting("barcode_enabled", "on")
    scanner = make_worker(name="Scanner Holder", pin="1111")
    stale = make_worker(name="Previous Person", pin="2222")
    barcode_engine.issue_card(db, scanner, "card_number")

    client.post("/", data={
        "mode": "worker",
        "card_code": scanner.card_barcode,
        "worker_id": stale.worker_id,     # left over from the person before
        "pin": "1111",                    # the card holder's PIN
        "log_type": "IN",
    }, follow_redirects=True)

    assert len(punches) == 1
    assert punches[0].id == scanner.id, "the card must decide who this is"


def test_pin_is_still_required_by_default(client, setting, make_worker, punches):
    """The three-factor claim rests on this, so it is asserted rather than assumed."""
    setting("barcode_enabled", "on")
    setting("barcode_require_pin", "on")
    worker = make_worker(name="Needs Pin", pin="9876")
    barcode_engine.issue_card(db, worker, "card_number")

    client.post("/", data={
        "mode": "worker", "card_code": worker.card_barcode,
        "pin": "0000", "log_type": "IN",     # wrong PIN
    }, follow_redirects=True)

    assert punches == [], "a wrong PIN must refuse even with a valid card"


def test_pin_can_be_switched_off_for_a_faster_queue(client, setting, make_worker, punches):
    setting("barcode_enabled", "on")
    setting("barcode_require_pin", "off")
    worker = make_worker(name="No Pin Needed", pin="9876")
    barcode_engine.issue_card(db, worker, "card_number")

    client.post("/", data={
        "mode": "worker", "card_code": worker.card_barcode, "log_type": "IN",
    }, follow_redirects=True)

    assert len(punches) == 1
    assert punches[0].id == worker.id


def test_a_worker_without_a_card_can_still_clock_in(client, setting, make_worker, punches):
    """The fallback is part of the design, not an oversight.

    A card left at home must not cost somebody a day's pay, so the worker
    number and PIN still work. The audit trail records that the card was not
    used, which is what lets a farm see how often the third factor is skipped.
    """
    setting("barcode_enabled", "on")
    worker = make_worker(name="Card At Home", pin="3456")

    client.post("/", data={
        "mode": "worker", "worker_id": worker.worker_id,
        "pin": "3456", "log_type": "IN",
    }, follow_redirects=True)

    assert len(punches) == 1
    assert punches[0].id == worker.id


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def test_print_sheet_lists_only_active_carded_workers(client, signed_in, setting, make_worker):
    setting("barcode_enabled", "on")
    signed_in("admin")
    carded = make_worker(name="Has Card")
    uncarded = make_worker(name="No Card")
    barcode_engine.issue_card(db, carded, "card_number")

    page = client.get("/workers/cards?who=all").get_data(as_text=True)

    assert "Has Card" in page
    # The uncarded worker appears in the "not printable" list, not as a card.
    assert "Not printable" in page


def test_print_sheet_accepts_a_selection(client, signed_in, setting, make_worker):
    setting("barcode_enabled", "on")
    signed_in("admin")
    chosen = make_worker(name="Chosen One")
    other = make_worker(name="Not Chosen")
    barcode_engine.issue_card(db, chosen, "card_number")
    barcode_engine.issue_card(db, other, "card_number")

    page = client.get(f"/workers/cards?id={chosen.id}").get_data(as_text=True)

    assert "Chosen One" in page
    assert "Not Chosen" not in page


def test_print_sheet_requires_a_signed_in_admin(client, setting):
    setting("barcode_enabled", "on")
    response = client.get("/workers/cards?who=all")
    assert response.status_code in (302, 401, 403)


def test_stats_count_the_workforce(app_context, make_worker):
    active_carded = make_worker(name="Carded")
    make_worker(name="Uncarded")
    barcode_engine.issue_card(db, active_carded, "card_number")

    stats = barcode_engine.stats()

    assert stats["active_workers"] == 2
    assert stats["carded"] == 1
    assert stats["uncarded"] == 1
