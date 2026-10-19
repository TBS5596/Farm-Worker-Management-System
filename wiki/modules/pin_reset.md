# `pin_reset.py`

← [Module index](README.md) · [Wiki index](../README.md)

**~220 lines. A convenience that had to be designed like a threat.**

---

## What it does

Lets a worker who has forgotten their PIN prove who they are at the terminal
and set a new one, without finding somebody with a dashboard login.

| | |
| --- | --- |
| **Owns** | Whether a reset is possible at all, who the worker is, the throttle, what makes a PIN acceptable, writing the new one |
| **Depends on** | `attendance_service.clockin_mode()`, `barcode_engine`, `face_engine`, the settings table |
| **Called by** | `app.py` — `/pin-reset` and `/pin-reset/set` |
| **Does not own** | The camera (the route grabs frames), the audit entries (the route writes them) |

## The rule the whole module is built around

> A reset must never be an easier door than the clock-in it protects.

Every design decision below follows from that one sentence, so it is worth
seeing why the obvious design fails it.

The obvious design is *face check, then new PIN*. On a farm running card + PIN +
face that is strictly weaker than clocking in, and weaker in a way this system
can be precise about: there is no liveness detection — a declared limitation —
so a photograph of a worker can sometimes pass a face check. Under the obvious
design, a photograph alone yields a working PIN, and the attacker has the
account with one of the three factors.

So the reset demands **every factor the clock-in demands, except the PIN** —
which is the thing being replaced.

| Clock-in mode | The reset asks for | Why |
| --- | --- | --- |
| Card + PIN + face | Card + face | The attacker still needs the physical card *and* the face |
| PIN + face | Worker number + face | Same proof the gate takes |
| Card + face | Card + face | Unchanged; the PIN was never a factor |
| Card + PIN *(no camera)* | **Nothing. No reset.** | Nothing here proves who is standing there |
| PIN only *(no camera)* | **Nothing. No reset.** | Same |

## Derived, not configured

```python
def required_factors():
    mode = CLOCKIN_MODES[clockin_mode()]
    card, _pin, face = mode["factors"]
    return {"card": bool(card), "face": bool(face), "mode": mode}
```

The table above is not a second setting anybody has to keep in step — it is read
off the clock-in mode every time. A farm that tightens its clock-in tightens its
resets in the same move, and no sequence of settings changes can leave the reset
looser than the gate. This is the same "derived, not stored" pattern as
`clockin_mode()` and `portal_mode()` themselves, applied for the same reason.

## Refusing honestly

```python
def available():
    if not enabled():                  return False, DISABLED
    if not required_factors()["face"]: return False, NO_FACE_FACTOR
    return True, ""
```

The second branch is the uncomfortable one. A farm with the camera check off
gets *no self-service reset at all*, and the page says so and sends the worker
to a supervisor. That is not a gap waiting to be filled: filling it would mean
handing a new PIN to anyone who can read a worker number off a card, which is
exactly the attack the PIN exists to stop.

## The functions

### `resolve(worker_code, card_value)`

Finds the worker, enforcing the card requirement, and returns
`(Worker | None, reason)`. Each refusal has its own reason code, because the
person at the terminal needs to know which problem is theirs:

| Reason | Means |
| --- | --- |
| `UNKNOWN` | No such worker number |
| `INACTIVE` | Off the register — a leaver must not be able to re-open their own account |
| `NOT_ENROLLED` | No face samples, so nothing to check against |
| `CARD_REQUIRED` | The farm scans cards and none was scanned |
| `CARD_UNKNOWN` / `CARD_MISMATCH` | The card is not ours, or belongs to somebody else |

`MESSAGES` maps each to a sentence a worker can act on.

### `verify_face(worker, frames, threshold, require_eyes)`

Delegates straight to `face_engine.verify_worker()` — the *same* call the gate
makes, against the same templates and the same threshold. Deliberately not a
second, more lenient path.

### `recent_attempts()` / `record_attempt()` / `clear_attempts()`

Three failures in fifteen minutes stop that worker number. Harder than the
sign-in throttle (five) on purpose: a reset *changes* a credential rather than
merely using one, and nobody forgets their PIN three times in a quarter of an
hour. In-process memory, like the sign-in throttle — a restart clears it, which
is an accepted cost on a single-machine deployment.

### `pin_problem(worker, new_pin, confirm)`

Returns why the PIN cannot be used, or `""`. Length, digits only, typed twice,
and not one another worker already holds — checked through `pin_fingerprint`, a
SHA-256 of the PIN kept precisely so uniqueness can be tested without ever
storing a readable PIN. The refusal says the PIN is taken but never whose it is;
naming them would disclose their PIN to whoever guessed it.

### `apply(worker, new_pin)`

Writes the hash and the fingerprint together, so the uniqueness index can never
disagree with what the gate will accept.

## The grant, which lives in the route rather than here

A passed face check is held in the session for `GRANT_SECONDS` (180) while the
worker types. Long enough on a terminal in the sun, short enough that a screen
walked away from is not an open door. `/pin-reset/set` re-checks the expiry and
re-checks that the worker is still active before writing anything.

## What `app.py` adds

Audit entries, at every outcome: `worker.pin_reset_refused` with the reason,
`worker.pin_reset_verified` with the match score, `worker.pin_reset` on success,
and `settings.pin_reset` when an administrator changes the switch. A reset is a
credential changing hands; it belongs in the record by name.

## Administrators get none of this

There is no equivalent for a forgotten dashboard password, and that is a
decision. The system runs on a farm office machine with no mail server and no
second channel, so a reset link has nowhere to go, and every substitute — a
security question, a recovery PIN — is a second, weaker password on the account
that reaches payroll. `/account-help` names the two routes that genuinely
exist: another administrator resetting it from **Users**, or
`tools/reset_admin.py` run on the machine itself.

## Tests

`tests/test_pin_reset.py`, 34 tests, and it is worth noticing that nearly all of
them are refusals. That ratio is the point: the happy path is three lines, and
everything else is the module earning the right to exist.
