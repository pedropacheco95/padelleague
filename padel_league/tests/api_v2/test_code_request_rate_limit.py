"""Password-code requests are rate limited per account and per client IP."""

import pytest

from padel_league.modules.frontend_api.v1 import auth as v1_auth
from padel_league.tools.rate_limit import RateLimiter, code_requests

FORGOT = "/api/v1/auth/forgot_password"
NEW_CODE = "/api/v1/auth/generate_new_code/{}"


@pytest.fixture(autouse=True)
def fresh_limits():
    code_requests.reset()
    yield
    code_requests.reset()


@pytest.fixture
def seed_users(make_user):
    return [make_user(username="rl_first"), make_user(username="rl_second")]


def test_limiter_is_a_sliding_window(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("padel_league.tools.rate_limit.time.monotonic", lambda: clock[0])
    limiter = RateLimiter()
    assert [limiter.allow("k", 2, 60) for _ in range(3)] == [True, True, False]
    clock[0] += 61
    assert limiter.allow("k", 2, 60) is True
    assert limiter.allow("other", 2, 60) is True


def test_sixth_code_request_for_one_account_is_refused(client, seed_users):
    user = seed_users[0]
    for _ in range(v1_auth.CODE_REQUESTS_PER_ACCOUNT):
        assert client.post(NEW_CODE.format(user.id)).status_code == 200
    refused = client.post(NEW_CODE.format(user.id))
    assert refused.status_code == 429
    assert "Demasiados" in refused.get_json()["error"]
    # Another account is not affected by that account's limit.
    assert client.post(NEW_CODE.format(seed_users[1].id)).status_code == 200


def test_forgot_password_counts_against_the_same_account(client, seed_users):
    for _ in range(v1_auth.CODE_REQUESTS_PER_ACCOUNT):
        assert client.post(FORGOT, json={"username": "rl_first"}).status_code == 200
    assert client.post(FORGOT, json={"username": "rl_first"}).status_code == 429
    # Unknown usernames are limited too, so the route cannot be used to enumerate accounts quickly.
    for _ in range(v1_auth.CODE_REQUESTS_PER_ACCOUNT):
        assert client.post(FORGOT, json={"username": "nobody"}).status_code == 404
    assert client.post(FORGOT, json={"username": "nobody"}).status_code == 429


def test_one_client_ip_is_limited_across_accounts(client, seed_users, monkeypatch):
    monkeypatch.setattr(v1_auth, "CODE_REQUESTS_PER_IP", 3)
    headers = {"X-Forwarded-For": "203.0.113.9, 127.0.0.1"}
    ids = [seed_users[0].id, seed_users[1].id, 9999]
    assert [client.post(NEW_CODE.format(i), headers=headers).status_code for i in ids] == [200, 200, 404]
    assert client.post(NEW_CODE.format(seed_users[0].id), headers=headers).status_code == 429
    # A different client IP is unaffected.
    other = {"X-Forwarded-For": "198.51.100.4"}
    assert client.post(NEW_CODE.format(seed_users[0].id), headers=other).status_code == 200
