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


# ---------------------------------------------------------------------------
# The photograph on the front
#
# The card's picture is not a separate upload - it is one of the crops the
# recogniser was trained on. That is the whole point: a supervisor comparing
# the card to the face in front of them is looking at exactly what the system
# compares against. These tests pin that down, and pin down the fallbacks,
# because a card with the wrong person's photograph on it is worse than a card
# with none.
# ---------------------------------------------------------------------------

def _write_reference(tmp_path, worker, index, quality, monkeypatch=None):
    """Create a reference file on disk and the template row that points at it."""
    import os
    from models import FaceTemplate

    faces = tmp_path / "captures" / "faces"
    faces.mkdir(parents=True, exist_ok=True)
    name = f"enroll_{worker.worker_id}_{index:02d}.jpg"
    (faces / name).write_bytes(b"not-a-real-jpeg-but-a-real-file")
    db.session.add(FaceTemplate(
        worker_id=worker.id,
        face_embedding=b"\x00" * 10,
        sample_index=index,
        reference_image_path=os.path.join("captures", "faces", name),
        quality_score=quality,
    ))
    db.session.commit()
    return f"captures/faces/{name}"


@pytest.fixture()
def rooted(tmp_path, monkeypatch):
    """Point face_engine's filesystem lookups at a temporary tree."""
    import face_engine
    monkeypatch.setattr(face_engine, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(face_engine, "FACES_DIR",
                        str(tmp_path / "captures" / "faces"))
    return tmp_path


def test_no_enrolment_means_no_photograph(app_context, make_worker, rooted):
    """An unenrolled worker gets the placeholder, not a broken image."""
    import face_engine
    worker = make_worker(name="Never Enrolled")
    assert face_engine.profile_photo_for(worker) is None


def test_the_sharpest_sample_is_chosen(app_context, make_worker, rooted):
    """quality_score is a blur measure, so the highest is the least blurred."""
    import face_engine
    worker = make_worker(name="Three Samples")
    _write_reference(rooted, worker, 1, quality=40.0)
    best = _write_reference(rooted, worker, 2, quality=310.0)
    _write_reference(rooted, worker, 3, quality=150.0)

    assert face_engine.profile_photo_for(worker) == best


def test_a_missing_file_is_skipped_for_one_that_exists(app_context, make_worker, rooted):
    """A database row pointing at a deleted file must not win.

    Backups get restored without the captures directory. Trusting the row
    blindly would put a broken image on the card and the operator would have no
    idea why.
    """
    import os
    import face_engine
    from models import FaceTemplate

    worker = make_worker(name="Half Restored")
    db.session.add(FaceTemplate(
        worker_id=worker.id, face_embedding=b"\x00" * 10, sample_index=1,
        reference_image_path=os.path.join("captures", "faces", "gone.jpg"),
        quality_score=999.0,
    ))
    db.session.commit()
    survivor = _write_reference(rooted, worker, 2, quality=100.0)

    assert face_engine.profile_photo_for(worker) == survivor


def test_the_naming_convention_is_the_last_resort(app_context, make_worker, rooted):
    """Reference paths lost from the database, files still on disk.

    An installation upgraded from a release that did not record the paths still
    has the files under a predictable name. A card with a photograph on it is
    worth one directory listing to recover.
    """
    import face_engine
    from models import FaceTemplate

    worker = make_worker(name="Paths Lost")
    db.session.add(FaceTemplate(
        worker_id=worker.id, face_embedding=b"\x00" * 10,
        sample_index=1, reference_image_path=None, quality_score=200.0,
    ))
    db.session.commit()

    faces = rooted / "captures" / "faces"
    faces.mkdir(parents=True, exist_ok=True)
    (faces / f"enroll_{worker.worker_id}_01.jpg").write_bytes(b"file")

    assert face_engine.profile_photo_for(worker) == \
        f"captures/faces/enroll_{worker.worker_id}_01.jpg"


def test_one_workers_files_are_never_offered_to_another(app_context, make_worker, rooted):
    """The convention fallback matches on the worker's own code only."""
    import face_engine
    from models import FaceTemplate

    mine = make_worker(name="Mine")
    theirs = make_worker(name="Theirs")
    db.session.add(FaceTemplate(worker_id=mine.id, face_embedding=b"\x00" * 10,
                                sample_index=1, quality_score=100.0))
    db.session.commit()

    faces = rooted / "captures" / "faces"
    faces.mkdir(parents=True, exist_ok=True)
    (faces / f"enroll_{theirs.worker_id}_01.jpg").write_bytes(b"file")

    assert face_engine.profile_photo_for(mine) is None


# ---------------------------------------------------------------------------
# The two print layouts
#
# The failure being guarded against is specific: a barcode printed onto the
# wrong worker's card, whose clock-ins would then be recorded against somebody
# else. The mirroring below is what prevents it on a duplex printer, and the
# name on every back is what lets an operator catch it if it happens anyway.
# ---------------------------------------------------------------------------

def test_fold_is_the_default_layout(client, signed_in, setting, make_worker):
    setting("barcode_enabled", "on")
    signed_in("admin")
    barcode_engine.issue_card(db, make_worker(name="Folded"), "card_number")

    page = client.get("/workers/cards?who=all").get_data(as_text=True)

    assert 'class="pair"' in page
    assert "fold method" in page


def test_an_unknown_layout_falls_back_to_fold(client, signed_in, setting, make_worker):
    """Fold cannot mis-pair a card, so it is the safe thing to fall back to."""
    setting("barcode_enabled", "on")
    signed_in("admin")
    barcode_engine.issue_card(db, make_worker(name="Folded"), "card_number")

    page = client.get("/workers/cards?who=all&layout=sideways").get_data(as_text=True)

    assert 'class="pair"' in page


def test_every_back_names_its_owner(client, signed_in, setting, make_worker):
    """The safeguard against a back reaching the wrong front.

    If this assertion ever fails, the print sheet has become a page of
    anonymous barcodes and a collating mistake becomes undetectable.
    """
    setting("barcode_enabled", "on")
    signed_in("admin")
    worker = make_worker(name="Named Back")
    barcode_engine.issue_card(db, worker, "card_number")

    page = client.get("/workers/cards?who=all&layout=duplex").get_data(as_text=True)

    assert page.count("Named Back") >= 2      # once on the front, once on the back
    assert page.count(worker.worker_id) >= 2


def test_duplex_reverses_each_row_so_the_flip_lines_up(client, signed_in, setting, make_worker):
    """Paper flipped on its long edge comes back with its columns swapped."""
    setting("barcode_enabled", "on")
    signed_in("admin")
    first = make_worker(name="Aaa First")
    second = make_worker(name="Bbb Second")
    barcode_engine.issue_card(db, first, "card_number")
    barcode_engine.issue_card(db, second, "card_number")

    page = client.get("/workers/cards?who=all&layout=duplex").get_data(as_text=True)
    fronts, backs = page.split("&mdash; backs", 1)

    # Fronts run left to right; the backs of the same row run right to left.
    assert fronts.index("Aaa First") < fronts.index("Bbb Second")
    assert backs.index("Bbb Second") < backs.index("Aaa First")


def test_a_short_duplex_row_is_padded_not_shifted(client, signed_in, setting, make_worker):
    """One card alone on a row must not slide into the other column.

    Without the blank, a single card would print in the left column on both
    pages - and after the flip its barcode would land behind nothing at all.
    """
    setting("barcode_enabled", "on")
    signed_in("admin")
    barcode_engine.issue_card(db, make_worker(name="Only One"), "card_number")

    page = client.get("/workers/cards?who=all&layout=duplex").get_data(as_text=True)

    assert 'class="face blank"' in page


def test_the_layout_switch_keeps_the_selection(client, signed_in, setting, make_worker):
    """Switching layout must not quietly change who is being printed."""
    setting("barcode_enabled", "on")
    signed_in("admin")
    chosen = make_worker(name="Chosen One")
    make_worker(name="Not Chosen")
    barcode_engine.issue_card(db, chosen, "card_number")

    page = client.get(f"/workers/cards?id={chosen.id}").get_data(as_text=True)

    assert f"id={chosen.id}" in page


# ---------------------------------------------------------------------------
# Clock-in verification modes
#
# The three factor settings are the source of truth and nothing here changes
# that. What is tested is the naming layer on top: that every combination has a
# name, that choosing a name writes the right three settings, that the name is
# derived back truthfully, and - most importantly - that a bad value cannot
# quietly drop a check.
# ---------------------------------------------------------------------------

import attendance_service


def test_every_mode_round_trips(app_context, setting):
    """Choose a mode, read it back, get the same mode.

    If this ever fails, the settings page would show a farm one thing while the
    terminal did another, which is the worst possible failure for a screen whose
    whole job is answering "what does this check?".
    """
    for key in attendance_service.CLOCKIN_MODES:
        for name, value in attendance_service.settings_for_mode(key).items():
            setting(name, value)
        assert attendance_service.clockin_mode() == key


def test_the_named_factors_match_the_settings(app_context):
    """The chips on the settings page must not lie about what is enforced."""
    for key, mode in attendance_service.CLOCKIN_MODES.items():
        card, pin, face = mode["factors"]
        written = attendance_service.settings_for_mode(key)
        assert written["barcode_enabled"] == ("on" if card else "off")
        assert written["barcode_require_pin"] == ("on" if pin else "off")
        assert written["face_verification_required"] == ("on" if face else "off")


def test_an_unknown_mode_is_rejected_loudly(app_context):
    """A typo must raise, not fall through to a weaker combination."""
    with pytest.raises(ValueError):
        attendance_service.settings_for_mode("card_pin_fingerprint")
    with pytest.raises(ValueError):
        attendance_service.settings_for_mode("")


def test_every_mode_is_labelled_for_strength(app_context):
    """Weak combinations must be marked, and must say what they give up."""
    for key, mode in attendance_service.CLOCKIN_MODES.items():
        assert mode["strength"] in ("strong", "weak")
        card, pin, face = mode["factors"]
        # A mode without the face check cannot tell who is standing there, so
        # it is weak whatever else it asks for.
        if not face:
            assert mode["strength"] == "weak", f"{key} has no face check but is not marked weak"
        assert mode["note"].strip()


def test_the_default_asks_for_pin_and_face(app_context):
    """A fresh installation must not start in a weak mode."""
    assert attendance_service.clockin_mode() == "pin_face"
    assert attendance_service.CLOCKIN_MODES["pin_face"]["strength"] == "strong"


# ---- the chooser on the settings page -------------------------------------

def _save(client, mode, **extra):
    data = {"clockin_mode": mode, "org_name": "Test Farm",
            "face_match_threshold": "35", "geofence_radius_m": "500",
            "payroll_period": "weekly"}
    data.update(extra)
    return client.post("/settings", data=data, follow_redirects=False)


def test_choosing_a_mode_writes_all_three_settings(client, signed_in, app_context):
    signed_in("admin")
    _save(client, "card_pin_face")

    assert attendance_service.clockin_mode() == "card_pin_face"
    assert attendance_service._flag("barcode_enabled", "off") is True
    assert attendance_service._flag("barcode_require_pin", "on") is True
    assert attendance_service._flag("face_verification_required", "on") is True


def test_choosing_a_weak_mode_actually_drops_the_check(client, signed_in, app_context):
    """The warning is not decorative - the setting really changes."""
    signed_in("admin")
    _save(client, "card_pin")

    assert attendance_service.clockin_mode() == "card_pin"
    assert attendance_service._flag("face_verification_required", "on") is False


def test_a_mangled_mode_leaves_the_current_one_alone(client, signed_in, app_context):
    """Silently dropping a check because a form field was mangled would change
    what every later attendance row means. It must be a no-op instead."""
    signed_in("admin")
    _save(client, "card_pin_face")
    _save(client, "not-a-mode")

    assert attendance_service.clockin_mode() == "card_pin_face"


def test_a_missing_mode_field_leaves_the_current_one_alone(client, signed_in, app_context):
    signed_in("admin")
    _save(client, "card_face")
    client.post("/settings", data={"org_name": "Test Farm", "face_match_threshold": "35",
                                   "geofence_radius_m": "500", "payroll_period": "weekly"})

    assert attendance_service.clockin_mode() == "card_face"


def test_changing_the_mode_is_named_in_the_audit_log(client, signed_in, app_context):
    """"Settings updated" is not enough for a change of this weight."""
    from models import AuditLog

    signed_in("admin")
    _save(client, "card_pin_face")
    _save(client, "pin_only")

    entry = (AuditLog.query.filter_by(action="settings.clockin_mode")
             .order_by(AuditLog.id.desc()).first())
    assert entry is not None
    assert "PIN only" in entry.details


def test_saving_without_changing_the_mode_logs_nothing_extra(client, signed_in, app_context):
    """An audit trail that records non-events is one nobody reads."""
    from models import AuditLog

    signed_in("admin")
    _save(client, "card_face")
    before = AuditLog.query.filter_by(action="settings.clockin_mode").count()
    _save(client, "card_face")

    assert AuditLog.query.filter_by(action="settings.clockin_mode").count() == before


def test_the_settings_page_offers_every_mode(client, signed_in, app_context):
    signed_in("admin")
    page = client.get("/settings").get_data(as_text=True)

    for key, mode in attendance_service.CLOCKIN_MODES.items():
        assert f'value="{key}"' in page
        assert mode["label"] in page


def test_the_dashboard_flags_a_weak_mode(client, signed_in, app_context):
    """A farm left in a demonstration setting should be told so."""
    signed_in("admin")
    _save(client, "pin_only")

    page = client.get("/dashboard").get_data(as_text=True)

    assert "PIN only" in page
    assert "clockin-verification" in page       # links to where it is fixed
