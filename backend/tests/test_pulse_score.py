"""Smoke tests for /api/pulse-score."""
import os
import sys

import pytest
import httpx

BACKEND_URL = os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001"
ADMIN_EMAIL = "admin@ayci.com"
ADMIN_PW = "Admin@2026"


def test_pulse_score_shape():
    with httpx.Client(base_url=BACKEND_URL, timeout=60) as c:
        r = c.post(
            "/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PW},
        )
        r.raise_for_status()
        cookies = r.cookies

        r = c.get("/api/pulse-score", cookies=cookies)
        r.raise_for_status()
        data = r.json()

        # Shape
        assert isinstance(data["score"], int)
        assert 0 <= data["score"] <= 100
        assert data["label"] in {"Healthy", "Watch", "At risk"}
        assert "week_start" in data
        assert "computed_at" in data

        pillars = data["pillars"]
        for key in ("scorecard", "rocks", "sla", "students"):
            assert key in pillars, f"missing pillar {key}"
            p = pillars[key]
            assert p["max"] == 25
            assert 0 <= p["score"] <= 25
            assert isinstance(p["label"], str) and p["label"]

        # Total = sum of pillar scores
        total = sum(pillars[k]["score"] for k in pillars)
        assert total == data["score"], f"sum mismatch {total} vs {data['score']}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
