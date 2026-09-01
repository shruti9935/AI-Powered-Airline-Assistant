"""Regression tests for the two first-run crashes."""
import importlib

import pytest


def test_blank_jwt_secret_still_yields_a_usable_secret(monkeypatch, tmp_path):
    """`.env.example` ships `JWT_SECRET=` — a set-but-empty variable.

    os.getenv(name, default) does not fall back for those, so the app used to
    boot with an empty HMAC key and 500 on every register/login.
    """
    monkeypatch.setenv("JWT_SECRET", "")
    monkeypatch.chdir(tmp_path)
    import config
    importlib.reload(config)
    try:
        assert config.JWT_SECRET, "an empty JWT_SECRET must not survive into config"
        assert len(config.JWT_SECRET) >= 32
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_register_and_login_round_trip(client):
    reg = client.post("/auth/register",
                      json={"email": "a@b.com", "password": "secret1"})
    assert reg.status_code == 200
    token = reg.json()["access_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "a@b.com"

    login = client.post("/auth/login", json={"email": "a@b.com", "password": "secret1"})
    assert login.status_code == 200


def test_duplicate_email_rejected(client):
    client.post("/auth/register", json={"email": "a@b.com", "password": "secret1"})
    again = client.post("/auth/register", json={"email": "a@b.com", "password": "secret1"})
    assert again.status_code == 409


@pytest.mark.parametrize("password", ["x" * 100, "🔒" * 25])
def test_overlong_password_is_rejected_not_a_crash(client, password):
    """bcrypt >= 4.2 raises ValueError past 72 bytes instead of truncating.

    Note the emoji case: 25 characters, but 100 bytes.
    """
    res = client.post("/auth/register", json={"email": "c@d.com", "password": password})
    assert res.status_code == 422, res.text


def test_overlong_password_login_is_401_not_500(client):
    client.post("/auth/register", json={"email": "a@b.com", "password": "secret1"})
    res = client.post("/auth/login", json={"email": "a@b.com", "password": "x" * 100})
    assert res.status_code == 401


def test_short_password_rejected(client):
    res = client.post("/auth/register", json={"email": "c@d.com", "password": "abc"})
    assert res.status_code == 422


@pytest.mark.parametrize("header", [None, "Bearer garbage", "Bearer "])
def test_bad_credentials_return_401_so_the_ui_can_recover(client, header):
    """The frontend branches on err.status === 401; anything else strands it."""
    headers = {"Authorization": header} if header else {}
    res = client.get("/auth/me", headers=headers)
    assert res.status_code == 401


def test_token_without_subject_is_rejected(client):
    import jwt

    import config
    forged = jwt.encode({"email": "a@b.com"}, config.JWT_SECRET, algorithm="HS256")
    res = client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert res.status_code == 401
