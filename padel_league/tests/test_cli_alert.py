"""`flask v2 alert`: the VM cron checks (scripts/disk_check.sh) email through it."""

from padel_league.tools import email_tools


def test_alert_emails_the_alert_address(pg, monkeypatch):
    sent = []
    monkeypatch.setenv("ALERT_EMAIL", "admin@example.com")
    monkeypatch.setattr(
        email_tools,
        "send_email",
        lambda subject, recipients, body=None: sent.append((subject, recipients, body)),
    )

    result = pg.test_cli_runner().invoke(
        args=["v2", "alert", "VM disk at 85%", "details"]
    )

    assert result.exit_code == 0, result.output
    assert sent == [("[Padel League] VM disk at 85%", ["admin@example.com"], "details")]


def test_alert_without_an_address_fails_loudly(pg, monkeypatch):
    monkeypatch.delenv("ALERT_EMAIL", raising=False)

    result = pg.test_cli_runner().invoke(args=["v2", "alert", "x", "y"])

    assert result.exit_code != 0
    assert "ALERT_EMAIL" in result.output
