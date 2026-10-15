from padel_league.tests.api_v2.conftest import assert_v2_shape


def test_news(client):
    resp = client.get("/api/v2/news")
    assert resp.status_code == 200
    items = resp.get_json()
    assert_v2_shape(items)
    assert all("text" not in n for n in items)
    latest = client.get("/api/v2/news/latest")
    if items:
        assert latest.status_code == 200 and "text" in latest.get_json()
        one = client.get(f"/api/v2/news/{items[0]['id']}")
        assert one.status_code == 200 and one.get_json()["id"] == items[0]["id"]
    assert client.get("/api/v2/news/99999999").status_code == 404
