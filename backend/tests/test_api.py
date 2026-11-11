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


def test_settings_validation_and_defaults(auth_client):
    data = auth_client.get("/api/settings").json()
    assert data["settings"]["strategy"]["stop_atr_mult"] == 3.0
    assert "trade_republic" in data["fee_presets"]
    assert data["env"]["anthropic_api_key"] is False
    bad = data["settings"]
    bad["risk"]["max_risk_per_trade"] = 5
    r = auth_client.put("/api/settings", json=bad)
    assert r.status_code == 422 and "max_risk_per_trade" in r.json()["detail"]


def test_backtest_endpoint(auth_client):
    auth_client.post("/api/system/refresh", json={"symbols": ["MEDCL.PA", "SAN.PA", "UCB.BR"]})
    _wait_refresh()
    r = auth_client.post("/api/backtests", json={"capital": 5000, "strategy": {"rsi_pullback": 50}})
    assert r.status_code == 202
    run_id = r.json()["id"]
    for _ in range(200):
        run = auth_client.get(f"/api/backtests/{run_id}").json()
        if run["status"] != "running":
            break
        time.sleep(0.05)
    assert run["status"] == "ok", run["error"]
    assert run["summary"]["capital"] == 5000
    assert run["report"]["settings"]["strategy"]["rsi_pullback"] == 50
    assert len(run["report"]["equity"]) > 50
    assert auth_client.get("/api/backtests").json()[0]["id"] == run_id
    bad = auth_client.post("/api/backtests", json={"risk": {"max_positions": 0}})
    assert bad.status_code == 422


def test_ai_status_and_jobs_endpoints(auth_client):
    st = auth_client.get("/api/ai/status").json()
    assert st["backend"] == "none" and st["available"] is False
    assert auth_client.post("/api/ai/screen/SAN.PA").status_code == 409
    assert auth_client.post("/api/system/run/nope").status_code == 404
    r = auth_client.post("/api/settings/test-notification").json()
    assert r == {"push": "skipped", "email": "skipped", "error": None}
    ev = auth_client.post(
        "/api/stocks/MEDCL.PA/events",
        json={"date": "2027-01-15", "kind": "trial", "title": "Readout", "binary": True},
    )
    assert ev.status_code == 201
    assert auth_client.get("/api/stocks/MEDCL.PA/events").json()[0]["title"] == "Readout"
    assert auth_client.delete(f"/api/events/{ev.json()['id']}").status_code == 204
    assert auth_client.get("/api/portfolios").json()[0]["mode"] == "paper"
