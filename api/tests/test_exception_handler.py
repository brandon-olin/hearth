import httpx

from life_dashboard.main import app


async def test_unhandled_exception_returns_generic_body():
    @app.get("/__test_boom")
    async def _boom():
        raise ValueError("SECRET-INTERNAL-DETAIL-postgres://user:pw@host/db")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/__test_boom")

    assert resp.status_code == 500
    body = resp.json()
    assert body.get("detail") == "Internal server error"
    assert "SECRET-INTERNAL-DETAIL" not in resp.text
    assert "ValueError" not in resp.text
