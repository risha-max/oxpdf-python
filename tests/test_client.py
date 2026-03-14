from unittest.mock import MagicMock, patch

import pytest
import requests

from oxpdf.client import Client, OxPDFError


def _mock_response(
    *,
    status_code: int = 200,
    json_data: dict | None = None,
    text: str = "",
    ok: bool | None = None,
):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = ok if ok is not None else (200 <= status_code < 300)
    resp.text = text
    resp.reason = "error"
    if json_data is None:
        resp.content = b""
        resp.json.side_effect = ValueError("no json")
    else:
        resp.content = b'{"mock": true}'
        resp.json.return_value = json_data
    return resp


def test_retries_on_retryable_status_then_succeeds():
    client = Client("test-key", max_retries=2, retry_delay=0.01)

    first = _mock_response(status_code=503, text="service unavailable")
    second = _mock_response(status_code=200, json_data={"success": True, "status": "completed"})

    with patch.object(client._session, "request", side_effect=[first, second]) as req, patch(
        "oxpdf.client.time.sleep"
    ) as mocked_sleep:
        out = client.job_status("job-1")

    assert out["success"] is True
    assert req.call_count == 2
    mocked_sleep.assert_called_once()


def test_retries_on_network_error_then_succeeds():
    client = Client("test-key", max_retries=2, retry_delay=0.01)

    with patch.object(
        client._session,
        "request",
        side_effect=[requests.RequestException("network down"), _mock_response(status_code=200, json_data={"ok": True})],
    ) as req, patch("oxpdf.client.time.sleep") as mocked_sleep:
        out = client._request("GET", "pricing/current")

    assert out["ok"] is True
    assert req.call_count == 2
    mocked_sleep.assert_called_once()


def test_wait_for_job_returns_on_terminal_status():
    client = Client("test-key")

    statuses = [{"status": "processing"}, {"status": "completed", "result": {"ok": True}}]
    with patch.object(client, "job_status", side_effect=statuses) as job_status, patch(
        "oxpdf.client.time.sleep"
    ) as mocked_sleep:
        out = client.wait_for_job("job-2", interval_seconds=0.01, timeout_seconds=2.0)

    assert out["status"] == "completed"
    assert job_status.call_count == 2
    mocked_sleep.assert_called_once()


def test_wait_for_job_times_out():
    client = Client("test-key")

    with patch.object(client, "job_status", return_value={"status": "processing"}), patch(
        "oxpdf.client.time.sleep", return_value=None
    ), patch("oxpdf.client.time.time", side_effect=[0.0, 0.2, 0.4, 0.6]):
        with pytest.raises(OxPDFError, match="Timed out waiting for job"):
            client.wait_for_job("job-3", interval_seconds=0.01, timeout_seconds=0.5)
