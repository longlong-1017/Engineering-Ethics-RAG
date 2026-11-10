from __future__ import annotations

from src.app import main
from src.config import Settings
from src.corpus import load_corpus
from src.retriever import Retriever


def test_streamlit_main_is_importable_and_callable():
    assert callable(main)


def test_app_can_answer_a_question_end_to_end(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    corpus = load_corpus()
    settings = Settings(deepseek_api_key=None, api_state_path=tmp_path / 'ledger.sqlite3')
    monkeypatch.setattr('src.app.load_runtime', lambda: (settings, corpus, Retriever(corpus)))
    app = AppTest.from_file("app.py", default_timeout=60).run()
    app.text_area[0].set_value("工程风险的技术因素有哪些？")
    app.button[0].click().run()
    assert not list(app.exception)
    assert app.success
    assert any("原文证据与 PDF 页码" in item.value for item in app.subheader)
