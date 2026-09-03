"""seal.py — the one thing between a public repo and five years of messages."""
import base64
import json

import pytest

from tools.seal import (
    BadPassphrase, do_open, do_seal, derive, inspect, seal, unseal,
)

PASS = "a passphrase you could actually remember"


@pytest.fixture(autouse=True)
def cheap_kdf(monkeypatch):
    """scrypt is slow on purpose — that's the point of it. These tests are
    about behaviour, not cost, so turn the work right down. The two tests
    below that care about the real parameters opt out."""
    monkeypatch.setattr("tools.seal.KDF", {"n": 1 << 12, "r": 8, "p": 1})


def test_the_shipped_cost_is_memory_hard_enough_to_matter(monkeypatch):
    """Pinned deliberately. Lowering this silently is how a passphrase you can
    remember becomes a passphrase a GPU can guess."""
    monkeypatch.undo()                     # read what actually ships
    import tools.seal
    assert tools.seal.KDF == {"n": 1 << 15, "r": 8, "p": 1}


def test_a_round_trip_at_the_real_cost(monkeypatch):
    monkeypatch.undo()                     # the shipped parameters, once
    assert unseal(seal(b"the real thing", PASS), PASS) == b"the real thing"


def test_a_round_trip_returns_the_exact_bytes():
    data = "líne one\nlíne two 🫠\x00\xff".encode("utf-8", "surrogateescape")
    assert unseal(seal(data, PASS), PASS) == data


def test_the_wrong_passphrase_fails_closed():
    with pytest.raises(BadPassphrase):
        unseal(seal(b"secrets", PASS), PASS + "!")


def test_a_tampered_ciphertext_fails_closed_rather_than_returning_garbage():
    env = json.loads(seal(b"secrets", PASS))
    env["ct"] = env["ct"][:-8] + "AAAAAAAA"
    with pytest.raises(BadPassphrase):
        unseal(json.dumps(env).encode(), PASS)


def test_a_swapped_salt_fails_closed():
    env = json.loads(seal(b"secrets", PASS))
    env["salt"] = base64.b64encode(b"\x00" * 16).decode()
    with pytest.raises(BadPassphrase):
        unseal(json.dumps(env).encode(), PASS)


def test_a_file_that_isnt_an_envelope_fails_closed():
    with pytest.raises(BadPassphrase):
        unseal(b"not json at all", PASS)


def test_the_same_plaintext_seals_differently_every_time():
    """A fresh salt per seal. Otherwise re-sealing an unchanged dataset would
    show up in git as an unchanged blob, which leaks that nothing changed."""
    a, b = seal(b"same", PASS), seal(b"same", PASS)
    assert a != b
    assert unseal(a, PASS) == unseal(b, PASS) == b"same"


def test_the_envelope_carries_its_own_kdf_cost():
    """So a `.enc` sealed today still opens after these parameters are raised."""
    import tools.seal
    env = json.loads(seal(b"x", PASS))
    assert env["kdf"] == "scrypt" and env["n"] == tools.seal.KDF["n"]
    assert set("nrp") <= set(env)


def test_an_old_envelope_still_opens_after_the_cost_goes_up(monkeypatch):
    import tools.seal as s
    blob = seal(b"sealed last year", PASS)
    monkeypatch.setattr(s, "KDF", {"n": 1 << 16, "r": 8, "p": 1})
    assert unseal(blob, PASS) == b"sealed last year"


def test_the_ciphertext_contains_none_of_the_plaintext():
    blob = seal(b"we should probably talk about the thing", PASS)
    assert b"talk about" not in blob
    assert b"probably" not in blob


def test_deriving_is_deterministic_for_one_salt():
    salt = b"0123456789abcdef"
    assert derive(PASS, salt) == derive(PASS, salt)
    assert derive(PASS, salt) != derive(PASS + "x", salt)


# ── refusing to seal something broken ─────────────────────────────────────

def test_a_dataset_that_wont_validate_is_not_sealed(tmp_path, capsys):
    src = tmp_path / "real.json"
    src.write_text('{"meta": {}, "questions": []}')
    assert do_seal([(str(src), str(tmp_path / "real.json.enc"))], PASS) == 1
    assert not (tmp_path / "real.json.enc").exists()


def test_toml_that_wont_parse_is_not_sealed(tmp_path):
    src = tmp_path / "mine.toml"
    src.write_text("[[q]]\nid = broken")
    assert do_seal([(str(src), str(tmp_path / "mine.toml.enc"))], PASS) == 1
    assert not (tmp_path / "mine.toml.enc").exists()


def test_inspect_summarises_without_quoting_anything(tmp_path):
    src = tmp_path / "mine.toml"
    src.write_text('[[q]]\nid = "a"\nstatus = "draft"\n\n[[q]]\nid = "b"\n')
    out = inspect(str(src), src.read_bytes())
    assert out == "2 questions, 1 ready"
    assert "a" not in out.split()          # no ids, no text, just counts


def test_nothing_to_seal_is_an_error_not_a_silent_success(tmp_path):
    assert do_seal([(str(tmp_path / "nope.json"), str(tmp_path / "x.enc"))],
                   PASS) == 1


# ── refusing to write plaintext where git can see it ──────────────────────

def test_open_refuses_a_destination_git_would_track(tmp_path, monkeypatch):
    import tools.seal as s
    enc = tmp_path / "real.json.enc"
    enc.write_bytes(seal(b'{"ok": true}', PASS))
    monkeypatch.setattr(s, "is_ignored", lambda p: False)

    out = tmp_path / "leak.json"
    assert do_open(str(enc), str(out), PASS) == 1
    assert not out.exists()


def test_open_writes_when_the_destination_is_ignored(tmp_path, monkeypatch):
    import tools.seal as s
    enc = tmp_path / "mine.toml.enc"
    enc.write_bytes(seal(b'[[q]]\nid = "a"\n', PASS))
    monkeypatch.setattr(s, "is_ignored", lambda p: True)

    out = tmp_path / "mine.toml"
    assert do_open(str(enc), str(out), PASS) == 0
    assert out.read_bytes() == b'[[q]]\nid = "a"\n'


def test_open_with_the_wrong_passphrase_writes_nothing(tmp_path, monkeypatch):
    import tools.seal as s
    enc = tmp_path / "x.json.enc"
    enc.write_bytes(seal(b'{"ok": true}', PASS))
    monkeypatch.setattr(s, "is_ignored", lambda p: True)

    out = tmp_path / "x.json"
    assert do_open(str(enc), str(out), "wrong one") == 1
    assert not out.exists()


def test_restoring_a_backup_over_newer_work_needs_force(tmp_path, monkeypatch):
    """`make unseal` is a restore. If the file on disk isn't what was sealed,
    it may be an evening of curation that hasn't been sealed yet."""
    import tools.seal as s
    monkeypatch.setattr(s, "is_ignored", lambda p: True)
    enc = tmp_path / "mine.toml.enc"
    enc.write_bytes(seal(b'[[q]]\nid = "old"\n', PASS))
    out = tmp_path / "mine.toml"
    out.write_bytes(b'[[q]]\nid = "written tonight"\n')

    assert do_open(str(enc), str(out), PASS) == 1
    assert b"written tonight" in out.read_bytes()      # untouched

    assert do_open(str(enc), str(out), PASS, force=True) == 0
    assert b"old" in out.read_bytes()


def test_restoring_over_an_identical_file_is_not_an_obstacle(tmp_path, monkeypatch):
    import tools.seal as s
    monkeypatch.setattr(s, "is_ignored", lambda p: True)
    enc = tmp_path / "mine.toml.enc"
    enc.write_bytes(seal(b'[[q]]\nid = "a"\n', PASS))
    out = tmp_path / "mine.toml"
    out.write_bytes(b'[[q]]\nid = "a"\n')
    assert do_open(str(enc), str(out), PASS) == 0
