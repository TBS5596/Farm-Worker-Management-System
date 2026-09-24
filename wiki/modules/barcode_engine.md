# `barcode_engine.py`

← [Module index](README.md) · [Wiki index](../README.md)

**~270 lines. Turns a worker into a printable card, and a scan back into a worker.**

---

## What it does

A worker card is the third factor at the clock-in terminal. The worker **has**
the card, **knows** the PIN and **is** the face; with all three switched on, all
three must agree before attendance is recorded.

This module owns four small jobs: deciding what value goes on a worker's card,
drawing that value as a barcode, looking a scanned value back up, and counting
how much of the workforce has been carded.

| | |
| --- | --- |
| **Owns** | Card values, SVG rendering, scan normalisation, card lookup |
| **Depends on** | `python-barcode`, `qrcode`, `hashlib`, `secrets`, the `workers` table |
| **Called by** | `app.py` (issuing, printing, the clock-in route), `portal.py` (`/me/card`) |
| **Never does** | Write attendance, or decide whether a punch is allowed — it only answers *whose card is this* |

## The one decision this module refuses to make for you

What is actually printed on the card is a farm decision, not the code's, because
the three options trade convenience against exposure. The module implements all
three and prefers none; the manual explains the trade-off so the choice is an
informed one.

| `barcode_source` | Printed value | The cost |
| --- | --- | --- |
| `nrc_plain` *(default)* | The National Registration Number itself | Anyone who picks up a dropped card and scans it with a free phone app reads a national identifier |
| `nrc_hash` | `FMS-4A9C21-B0E7F3` — SHA-256 of the NRC with a per-installation salt | The NRC cannot be read back out, but the value is *determined* by the NRC, so a lost card cannot be given a genuinely new number |
| `card_number` | `FMS-K7P2-M4XQ` — generated, meaningless outside this database | A found card reveals only that it belongs to some worker somewhere. The only option under which a card can be voided and cleanly reissued |

**Worth knowing:** `nrc_plain` is the default because it is what supervisors ask
for first, not because it is the safest. It puts personal data on a piece of
plastic that leaves the farm in a pocket every evening, which sits awkwardly
beside the data-minimisation claim the project makes elsewhere. If you are
choosing for a real farm, choose `card_number`.

The salt for `nrc_hash` comes from `FMS_SECRET_KEY`. Without a salt the same NRC
would produce the same barcode at every farm running this software, so a card
from one farm would be recognisable at another.

## The functions

### `card_value(worker, source=DEFAULT_SOURCE) -> str | None`

The value to print for this worker, or `None` if it cannot be made.

The source is validated **before** the NRC is looked at. That ordering is
deliberate and there is a test for it: if a typo in the setting fell through to
"this worker has no NRC", an operator would go hunting for a data problem that
does not exist.

`nrc_plain` and `nrc_hash` both need an NRC on the worker record. `None` means
"cannot be issued under the current setting", and the caller says so by name.

### `normalize_scan(raw) -> str`

Strips all whitespace and upper-cases. A keyboard-wedge scanner may append a
carriage return, a tab or stray spaces depending on how it was configured at the
factory, and a supervisor typing the code by hand may use lower case. Normalising
in one place means the rest of the system compares like with like.

### `render_svg(value, symbology) -> str`

`code128` (striped, suits a laser scanner) or `qr` (survives a creased card,
readable by a phone).

**SVG rather than PNG, deliberately.** An SVG barcode prints crisply at any size
on whatever printer the farm office owns, and it needs no image library in the
install — both `python-barcode` and `qrcode` can write SVG on their own.

### `issue_card(db, worker, source, reissue=False) -> (ok, message)`

Refuses to overwrite an existing card unless `reissue` is set, so a mis-click on
the Workers page cannot silently invalidate a card already in somebody's pocket.
Also refuses a value another worker already holds — two workers cannot share a
card.

Note the honest failure message when reissuing under an NRC-derived source: those
are deterministic, so "reissuing" produces the *same* value. Only `card_number`
actually changes. Saying so prevents a supervisor believing a compromised card
has been retired when it has not.

### `void_card(db, worker) -> (ok, message)`

Sets `card_status` to `void`. It does **not** clear `card_barcode`, because the
attendance already recorded against that card must stay explicable.

### `resolve(scanned) -> (Worker | None, reason)`

The lookup at the capture point. The `reason` is what makes it useful:

| Reason | What went wrong | The remedy |
| --- | --- | --- |
| `no_card` | Nothing was scanned | Scan, or type the number |
| `card_unknown` | No worker holds this value | Issue the worker a card |
| `card_void` | The card was reported lost | Print a replacement |
| `worker_inactive` | The holder is no longer on the register | Usually nothing |

Three different problems with three different remedies — collapsing them into
"card not accepted" would send a supervisor guessing.

There is a slow path in `resolve()`: if the exact match fails it re-normalises
every stored card value and compares again. That covers an installation upgraded
from an earlier release whose stored NRCs still carry spaces or slashes. It is a
full scan, which is fine for a workforce in the hundreds and would need an index
for one in the tens of thousands.

### `stats() -> dict`

`active_workers`, `carded`, `uncarded`, `void`, `without_nrc` — the counts the
Settings page shows so an administrator can see how far the rollout has got, and
in particular how many workers cannot be carded because they have no NRC on file.

## Where the values are stored

Three columns on `workers`, all nullable and all added by the additive migration
in `migrations.py`:

```python
card_barcode   = db.Column(db.String(64), unique=True, nullable=True)
card_issued_at = db.Column(db.DateTime, nullable=True)
card_status    = db.Column(db.String(20), default="active", nullable=True)
```

`unique=True` is the database enforcing what `issue_card()` also checks in Python.
Two layers, because the check in Python has a race between reading and writing and
the constraint does not.

## A deliberate omission

There is no endpoint that takes a card number and returns a name without
authentication. It was considered — it would have made the clock-in screen
simpler — and rejected, because anyone on the farm network could then have
enumerated cardholders by trying values. The worker's name is shown on the
confirmation **after** the identity check has passed, not before it.

## Related pages

- [app.md](app.md) — the issuing, voiding, printing and clock-in routes
- [portal.md](portal.md) — `/me/card`, where a worker prints their own replacement
- [models.md](models.md) — the three columns above
- [../03-follow-a-clock-in.md](../03-follow-a-clock-in.md) — where the scan sits in the transaction
