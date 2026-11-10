"""所有自动化测试硬性禁止真实HTTP，付费路径只能使用注入的Mock。"""
import pytest
import requests


@pytest.fixture(autouse=True)
def forbid_real_http(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('自动化测试禁止真实HTTP；请注入FakeSession/Mock。')
    monkeypatch.setattr(requests.sessions.Session, 'request', blocked)
