import time

from boursy.scheduler.jobs import refresh_lock


def test_health_is_public(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_api_requires_login(client):
    assert client.get("/api/stocks").status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_wrong_password(client):
    assert client.post("/api/auth/login", json={"password": "nope"}).status_code == 401


def test_login_logout(auth_client):
    assert auth_client.get("/api/auth/me").json() == {"user": "owner"}
    auth_client.post("/api/auth/logout")
    assert auth_client.get("/api/auth/me").status_code == 401


def test_seeded_universe(auth_client):
    stocks = auth_client.get("/api/stocks").json()
    symbols = {s["symbol"] for s in stocks}
    assert "MEDCL.PA" in symbols and "NOVO-B.CO" in symbols
    assert all(s["pea_eligible"] for s in stocks)
    novo = next(s for s in stocks if s["symbol"] == "NOVO-B.CO")
    assert novo["currency"] == "DKK"
    assert novo["snapshot"] is None


def _wait_refresh():
    for _ in range(100):
        if not refresh_lock.locked():
            return
        time.sleep(0.05)


def test_refresh_then_bars_with_indicators(auth_client):
    r = auth_client.post("/api/system/refresh", json={"symbols": ["MEDCL.PA"]})
    assert r.status_code == 202
    _wait_refresh()

    jobs = auth_client.get("/api/system/jobs").json()
    assert jobs[0]["job"] == "manual_refresh" and jobs[0]["status"] == "ok"

    detail = auth_client.get("/api/stocks/MEDCL.PA").json()
    assert detail["snapshot"]["close"] > 0
    assert detail["trend"] in {"up", "down", "mixed"}

    bars = auth_client.get("/api/stocks/medcl.pa/bars?days=100").json()["bars"]
    assert len(bars) == 100
    last = bars[-1]
    assert {"time", "open", "close", "sma200", "rsi14", "macd_hist", "atr14"} <= last.keys()
    assert last["sma200"] is not None and 0 <= last["rsi14"] <= 100


def test_add_and_patch_stock(auth_client):
    r = auth_client.post(
        "/api/stocks", json={"symbol": "ORP.PA", "name": "Test", "country": "FR", "bucket": "growth"}
    )
    assert r.status_code == 201
    assert (
        auth_client.post(
            "/api/stocks", json={"symbol": "ORP.PA", "name": "Test", "country": "FR", "bucket": "growth"}
        ).status_code
        == 409
    )
    bad = auth_client.post(
        "/api/stocks", json={"symbol": "AAPL", "name": "x", "country": "US", "bucket": "core"}
    )
    assert bad.status_code == 422
    r = auth_client.patch("/api/stocks/ORP.PA", json={"active": False})
    assert r.json()["active"] is False


def test_unknown_stock_404(auth_client):
    assert auth_client.get("/api/stocks/NOPE.PA").status_code == 404


def test_status(auth_client):
    s = auth_client.get("/api/system/status").json()
    assert s["stocks"] >= 20 and s["data_provider"] == "fake"
