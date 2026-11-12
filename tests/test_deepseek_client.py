from __future__ import annotations

import pytest
import requests

from src.config import Settings
from src.deepseek_client import DeepSeekClient, DeepSeekError


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(self, url, *, headers, json, timeout, allow_redirects=False):
        self.calls.append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout, "allow_redirects": allow_redirects}
        )
        if self.error is not None:
            raise self.error
        return self.response


def _settings(api_key="sk-test"):
    return Settings(
        deepseek_api_key=api_key,
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-flash",
        timeout_seconds=3.0,
        api_enabled=True,
    )


def test_missing_key_does_not_make_request():
    session = FakeSession()
    client = DeepSeekClient(_settings(api_key=None), session=session)
    assert client.configured is False
    with pytest.raises(DeepSeekError, match="DEEPSEEK_API_KEY"):
        client.chat([{"role": "user", "content": "问题"}], allow_api=True)
    assert session.calls == []


def test_chat_sends_expected_payload_and_headers():
    response = FakeResponse(
        payload={
            "model": "deepseek-flash",
            "choices": [{"message": {"content": "回答 [S1]"}}],
            "usage": {"total_tokens": 12},
        }
    )
    session = FakeSession(response=response)
    client = DeepSeekClient(_settings(), session=session)
    result = client.chat(
        [{"role": "system", "content": "系统"}, {"role": "user", "content": "问题"}],
        allow_api=True,
        temperature=0.1,
        max_tokens=321,
    )
    assert result.content == "回答 [S1]"
    assert result.usage == {"total_tokens": 12}
    call = session.calls[0]
    assert call["url"] == "https://api.deepseek.com/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-test"
    assert call["json"]["model"] == "deepseek-flash"
    assert call["json"]["temperature"] == 0.1
    assert call["json"]["max_tokens"] == 321
    assert call["json"]["stream"] is False
    assert call["timeout"] == (5.0, 3.0)


def test_http_error_is_reported_without_key():
    response = FakeResponse(status_code=401, text="Unauthorized")
    session = FakeSession(response=response)
    client = DeepSeekClient(_settings(), session=session)
    with pytest.raises(DeepSeekError, match="HTTP 401") as exc_info:
        client.chat([{"role": "user", "content": "问题"}], allow_api=True)
    assert "sk-test" not in str(exc_info.value)


def test_network_error_is_wrapped_without_key():
    session = FakeSession(error=requests.ConnectionError("boom"))
    client = DeepSeekClient(_settings(), session=session)
    with pytest.raises(DeepSeekError, match="网络请求失败") as exc_info:
        client.chat([{"role": "user", "content": "问题"}], allow_api=True)
    assert "sk-test" not in str(exc_info.value)


def test_invalid_json_is_reported():
    response = FakeResponse(payload=ValueError("bad json"))
    client = DeepSeekClient(_settings(), session=FakeSession(response=response))
    with pytest.raises(DeepSeekError, match="合法 JSON"):
        client.chat([{"role": "user", "content": "问题"}], allow_api=True)


def test_empty_choices_is_reported():
    response = FakeResponse(payload={"choices": []})
    client = DeepSeekClient(_settings(), session=FakeSession(response=response))
    with pytest.raises(DeepSeekError, match="未返回任何回答"):
        client.chat([{"role": "user", "content": "问题"}], allow_api=True)


def test_empty_content_is_reported():
    response = FakeResponse(payload={"choices": [{"message": {"content": "  "}}]})
    client = DeepSeekClient(_settings(), session=FakeSession(response=response))
    with pytest.raises(DeepSeekError, match="空回答") as exc:
        client.chat([{"role": "user", "content": "问题"}], allow_api=True)
    assert exc.value.code == "empty_response"


@pytest.fixture(autouse=True)
def isolate_request_ledger(tmp_path,monkeypatch):
    from src.api_limits import RequestLimiter
    monkeypatch.setattr('src.deepseek_client.RequestLimiter',lambda path:RequestLimiter(tmp_path/'limits.sqlite3'))
