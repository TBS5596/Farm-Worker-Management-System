"""Worker identity rules: generated IDs and PIN uniqueness."""

import app as app_module
from database import db
from models import Worker


def test_worker_ids_are_sequential_four_digits(make_worker):
    first = make_worker(name="Alpha", pin="1111")
    second = make_worker(name="Bravo", pin="2222")

    assert first.worker_id == "0001"
    assert second.worker_id == "0002"


def test_worker_id_generator_skips_taken_codes(app_context, make_worker):
    make_worker(name="Alpha", pin="1111")
    # Simulate an imported record that already holds the next code.
    taken = Worker(worker_id="0002", name="Imported", pin_fingerprint="x")
    taken.set_pin("9999")
    db.session.add(taken)
    db.session.commit()

    assert app_module._generate_worker_id() == "0003"


def test_pin_must_be_unique_across_workers(make_worker):
    make_worker(name="Alpha", pin="4321")

    assert app_module._is_pin_unique("4321") is False
    assert app_module._is_pin_unique("5678") is True


def test_pin_uniqueness_ignores_the_worker_being_edited(make_worker):
    worker = make_worker(name="Alpha", pin="4321")

    assert app_module._is_pin_unique("4321", exclude_worker_id=worker.worker_id) is True
