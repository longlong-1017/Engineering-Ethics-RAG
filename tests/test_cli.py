from __future__ import annotations

import json

from src.cli import main


def test_cli_stats(capsys):
    assert main(["stats"]) == 0
    output = capsys.readouterr().out
    assert "严格检索页面：81" in output
    assert "未审核页面：462" in output


def test_cli_search_json(capsys):
    assert main(["search", "工程风险的技术因素", "--mode", "strict", "--top-k", "2", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "strict"
    assert payload["hits"]
    assert payload["hits"][0]["page_number"] == 8


def test_cli_insufficient_answer(capsys):
    assert main(["ask", "量子计算如何实现", "--mode", "strict"]) == 0
    output = capsys.readouterr().out
    assert "资料不足" in output
    assert "状态：insufficient" in output
