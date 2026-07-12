def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_login_wrong_password(client):
    resp = client.post("/api/auth/login", json={"password": "nope"})
    assert resp.status_code == 401


def test_me_requires_auth(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_login_and_me(auth_client):
    resp = auth_client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"]


def test_logout(auth_client):
    resp = auth_client.post("/api/auth/logout")
    assert resp.status_code == 204
    resp = auth_client.get("/api/auth/me")
    assert resp.status_code == 401
