"""Worker identity rules: generated IDs and PIN uniqueness."""

import os

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


# ---------------------------------------------------------------------------
# Which database is open
#
# Students reported that restarting the project "created a new database". It
# does not - but running it two different ways opens two different files, and
# nothing said so. These tests pin the reporting that now says so.
# ---------------------------------------------------------------------------

def test_the_database_path_is_absolute(app_context):
    """A relative path would mean a different database per working directory.

    `sqlite:///x.db` (three slashes) resolves against wherever the process was
    started, which is exactly how somebody ends up with several half-full
    databases and no idea why.
    """
    import os
    import app as app_module

    path = app_module.database_path()
    assert path is not None
    assert os.path.isabs(path)


def test_both_run_locations_are_named(app_context):
    """The two files the project can use must both be declared."""
    import app as app_module

    assert set(app_module.DB_LOCATIONS) == {"native", "docker"}
    assert app_module.DB_LOCATIONS["native"].endswith("fms.db")
    assert app_module.DB_LOCATIONS["docker"].endswith(os.path.join("data", "fms.db"))
    assert app_module.DB_LOCATIONS["native"] != app_module.DB_LOCATIONS["docker"]


def test_the_startup_description_names_the_file(app_context):
    """Whatever else it says, it must say which file is open."""
    import app as app_module

    lines = app_module.describe_database()
    assert lines
    assert lines[0].startswith("Database: ")
    assert app_module.database_path() in lines[0]


def test_the_startup_description_reports_what_is_in_it(app_context, make_worker):
    """The counts are the point: they answer 'is this yesterday's database?'."""
    import app as app_module

    make_worker(name="Someone")
    # The suite runs against a temporary database created before this call, so
    # the existing-file branch is the one under test here.
    app_module._DB_EXISTED_AT_STARTUP = True
    text = " ".join(app_module.describe_database())

    assert "existing file" in text
    assert "workers" in text


def test_a_new_database_says_so_loudly(app_context, monkeypatch):
    """The case worth shouting about, because it is the one that alarms people."""
    import app as app_module

    monkeypatch.setattr(app_module, "_DB_EXISTED_AT_STARTUP", False)
    text = " ".join(app_module.describe_database())

    assert "NEW AND EMPTY" in text


def test_a_new_database_points_at_the_other_location(app_context, monkeypatch, tmp_path):
    """Name the other file rather than leave somebody thinking data is gone."""
    import app as app_module

    other = tmp_path / "fms.db"
    other.write_bytes(b"x" * 64)
    monkeypatch.setattr(app_module, "_DB_EXISTED_AT_STARTUP", False)
    monkeypatch.setattr(app_module, "DB_LOCATIONS",
                        {"native": str(other), "docker": "/nowhere/data/fms.db"})

    text = " ".join(app_module.describe_database())

    assert str(other) in text
    assert "probably there, not lost" in text


def test_the_demo_seeder_knows_its_own_workers(app_context, make_worker):
    """--force must be able to tell demo data from somebody's real work."""
    import importlib.util
    import os as _os

    spec = importlib.util.spec_from_file_location(
        "seed_demo", _os.path.join(_os.path.dirname(_os.path.dirname(__file__)),
                                   "tools", "seed_demo.py"))
    seed_demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed_demo)

    assert seed_demo._DEMO_NAMES, "the demo name set must not be empty"

    # A database holding only the fictional workers is demo data.
    for name in list(seed_demo._DEMO_NAMES)[:2]:
        make_worker(name=name)
    assert seed_demo._looks_like_real_data() is False

    # One unrecognised name is enough to make it somebody's real work.
    make_worker(name="Not A Demo Worker")
    assert seed_demo._looks_like_real_data() is True
