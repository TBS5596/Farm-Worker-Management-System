"""Every page renders.

This file exists because of a real failure. `templates/payroll.html` had its
header destroyed by an edit - the comment terminator, the title block, the
stylesheet block and the opening of the content block were all lost, so the
template did not compile and `/payroll` returned 500. It shipped that way, was
committed, and nobody noticed for weeks, because the suite tested the payroll
*engine* thoroughly and never once asked the payroll *page* to render.

The lesson is not "add a test for payroll". It is that a page nobody renders in
the suite is a page that can break silently. So this walks the URL map itself:
any page added later is covered the day it is added, without anybody
remembering to come back here.
"""

import jinja2
import pytest

import app as app_module


def _renderable_rules():
    """Every GET rule that returns a page, with its arguments filled in.

    Skipped on purpose:
      - streaming endpoints, which never return
      - file downloads and exports, which are not templates
      - anything needing an id that would have to exist first; those are
        covered by their own tests, where the row can be created
    """
    skip_endpoints = {
        "static",
        "camera_stream",            # MJPEG: opens a camera and never finishes
        "worker_camera_stream",     # the same, unauthenticated
        "captured_image",           # serves a file from disk
        "export_csv",               # CSV, not a template
        "portal.snapshot",          # needs a snapshot row
        "portal.photo",             # serves an image, worker session only
        "portal.payslip",           # needs a payroll row
    }

    rules = []
    for rule in app_module.app.url_map.iter_rules():
        if rule.endpoint in skip_endpoints:
            continue
        if "GET" not in rule.methods:
            continue
        if rule.arguments:
            continue                # needs an id; its own test covers it
        rules.append(rule)
    return sorted(rules, key=lambda r: str(r))


ALL_RULES = _renderable_rules()


def test_the_url_map_actually_has_pages_in_it():
    """Guard the guard: a filter bug that skipped everything would make every
    test below pass while checking nothing."""
    assert len(ALL_RULES) >= 15, f"only found {len(ALL_RULES)} pages to check"


@pytest.mark.parametrize("rule", ALL_RULES, ids=lambda r: str(r))
def test_a_page_never_returns_a_server_error(client, signed_in, rule):
    """Signed in as an administrator, no page may 500.

    A redirect is fine - some pages are role-gated or disabled by a setting.
    A 404 is fine - the worker portal turns itself off when disabled. What is
    never fine is 500, which means the page could not be built at all.
    """
    signed_in("admin")
    response = client.get(str(rule))

    assert response.status_code != 500, (
        f"{rule} returned 500. If this is a template problem, "
        f"run the template syntax test below for the exact line."
    )
    assert response.status_code < 500


def test_every_template_compiles(app_context):
    """Catches the specific fault above at its source, with a line number.

    A route test says "500"; this says "payroll.html line 281". When a template
    is broken, the second message is the one worth having.
    """
    import os

    env = jinja2.Environment(loader=jinja2.FileSystemLoader("templates"))
    broken = []
    for name in sorted(os.listdir("templates")):
        if not name.endswith(".html"):
            continue
        try:
            with open(os.path.join("templates", name)) as handle:
                env.parse(handle.read(), name=name)
        except jinja2.TemplateSyntaxError as err:
            broken.append(f"{name} line {err.lineno}: {err.message}")

    assert not broken, "templates with syntax errors:\n  " + "\n  ".join(broken)


def test_datatables_always_has_jquery_loaded_before_it(app_context):
    """DataTables is a jQuery plugin, and it fails at load time without it.

    This was live for the whole project's history: nine admin pages loaded
    `dataTables.min.js` with no jQuery anywhere, so the script threw
    "jQuery is not defined" on every one of them, `window.DataTable` was never
    defined, and every table silently lost its search, sorting and paging -
    features the README, the wiki and the report all claim.

    Nothing caught it because the page still returns 200 and still renders the
    table as plain HTML. Only a browser sees the error, so the check lives here
    as a source check instead.
    """
    import glob

    broken = []
    for path in sorted(glob.glob("templates/*.html")):
        with open(path) as handle:
            source = handle.read()
        if "vendor/dataTables.min.js" not in source:
            continue
        if "vendor/jquery.min.js" not in source:
            broken.append(f"{path}: loads DataTables with no jQuery")
            continue
        # Order matters as much as presence: jQuery must be parsed first.
        if source.index("vendor/jquery.min.js") > source.index("vendor/dataTables.min.js"):
            broken.append(f"{path}: loads jQuery after DataTables")

    assert not broken, "DataTables cannot start on these pages:\n  " + "\n  ".join(broken)


def test_every_vendored_asset_a_template_asks_for_exists(app_context):
    """A vendored path with a typo is a 404 that only a browser would notice.

    The whole point of vendoring was that the interface works with no internet;
    a missing file puts it right back to a half-styled page, and the server
    still returns 200 for the page itself.
    """
    import glob
    import os
    import re

    missing = []
    for path in sorted(glob.glob("templates/*.html")):
        with open(path) as handle:
            source = handle.read()
        for asset in re.findall(r"filename='(vendor/[^']+)'", source):
            if not os.path.exists(os.path.join("static", asset)):
                missing.append(f"{path} -> static/{asset}")

    assert not missing, "templates reference vendored files that do not exist:\n  " + \
        "\n  ".join(missing)


def test_a_jinja_comment_cannot_swallow_a_block(app_context):
    """The exact shape of the payroll.html failure, named so it stays fixed.

    Jinja comments do not nest: a `{# ... #}` inside a longer comment closes the
    outer one early, and everything after it becomes live template. That is how
    a descriptive header ended up eating `{% block content %}`. Every template
    that extends a base must therefore actually declare a content block.
    """
    import os
    import re

    missing = []
    for name in sorted(os.listdir("templates")):
        if not name.endswith(".html"):
            continue
        with open(os.path.join("templates", name)) as handle:
            source = handle.read()
        if not re.search(r"{%-?\s*extends", source):
            continue                # a standalone page, no blocks required
        if not re.search(r"{%-?\s*block\s+content", source):
            missing.append(name)

    assert not missing, (
        "these templates extend a base but declare no content block, so they "
        "would render as an empty page: " + ", ".join(missing))
