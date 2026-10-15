from padel_league.models import Sponsor


def test_sponsors(client):
    body = client.get("/api/v2/sponsors").get_json()
    assert len(body) == Sponsor.query.count()
    for s in body:
        assert s["clickUrl"] == f"/sponsors/sponsor_click/{s['id']}" and s["website"]
        assert s["image"] is None or s["image"]["url"].startswith("http")
