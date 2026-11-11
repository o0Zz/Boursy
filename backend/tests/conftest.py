import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Keep `import boursy.main` (module-level app) away from the real data directory.
os.environ.setdefault("BOURSY_DATA_DIR", tempfile.mkdtemp(prefix="boursy-test-"))
os.environ.setdefault("BOURSY_SCHEDULER_ENABLED", "false")

from fastapi.testclient import TestClient  # noqa: E402

from boursy.config import Settings  # noqa: E402
from boursy.data.provider import BAR_COLUMNS, DataError  # noqa: E402
from boursy.main import create_app  # noqa: E402

PASSWORD = "test-password"


class FakeProvider:
    """Deterministic random-walk bars on weekdays."""

    name = "fake"

    def __init__(self, fail: set[str] | None = None):
        self.fail = fail or set()
        self.calls: list[tuple[str, date, date]] = []

    def daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        self.calls.append((symbol, start, end))
        if symbol in self.fail:
            raise DataError(f"{symbol}: boom")
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        days = [d for d in days if d.weekday() < 5]
        # Seed from the absolute date so overlapping downloads return identical values.
        closes = [100 + 10 * np.sin(d.toordinal() / 30) + (d.toordinal() % 7) * 0.3 for d in days]
        df = pd.DataFrame(
            {
                "open": [c - 0.5 for c in closes],
                "high": [c + 1.0 for c in closes],
                "low": [c - 1.0 for c in closes],
                "close": closes,
                "adj_close": closes,
                "volume": [10_000 + (d.toordinal() % 5) * 1000 for d in days],
            },
            index=pd.Index(days, name="date"),
        )
        return df[BAR_COLUMNS]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        app_password=PASSWORD,
        session_secret="x" * 32,
        scheduler_enabled=False,
        static_dir=tmp_path / "no-static",
        history_years=2,
    )


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def client(settings: Settings, provider: FakeProvider):
    app = create_app(settings, provider)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_client(client: TestClient) -> TestClient:
    assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 200
    return client
