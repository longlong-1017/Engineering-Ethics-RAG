from dataclasses import replace

from streamlit.testing.v1 import AppTest

from src.config import Settings
from src.corpus import load_corpus
from src.deepseek_client import DeepSeekClient
from src.case_solver import CaseAnswer, CaseQuestion, CaseSolution
from src.qa import QA_MODE_LOCAL
from src.retriever import Retriever
from tests.test_deepseek_client import FakeResponse, FakeSession
from tests.helpers import structured_answer


def submit(app, question):
    app.text_area[0].set_value(question)
    next(button for button in app.button if button.label=='检索并回答').click().run()
    assert not app.exception
    return app


def runtime(monkeypatch,config):
    corpus=load_corpus()
    monkeypatch.setattr('src.app.load_runtime',lambda:(config,corpus,Retriever(corpus)))


def test_unverified_ai_draft_is_visible_with_evidence(monkeypatch,tmp_path):
    config=Settings(deepseek_api_key='synthetic-ui-key',api_enabled=True,api_state_path=tmp_path/'ledger.sqlite3')
    runtime(monkeypatch,config)
    content=structured_answer(
        '环境工程中的安全与社会公正是相互关联的。',
        [('环境工程安全包括生产安全。',['S3']),('事故造成999人死亡。',['S1'])],
    )
    response=FakeResponse(payload={'choices':[{'message':{'content':content},'finish_reason':'stop'}],
                                   'usage':{'total_tokens':123}})
    session=FakeSession(response=response)
    client=DeepSeekClient(config,session=session)
    monkeypatch.setattr('src.qa.DeepSeekClient',lambda settings:client)
    app=AppTest.from_file('app.py',default_timeout=60).run()
    app.toggle[0].set_value(True).run()
    submit(app,'环境工程中的安全与社会公正有什么关系？')
    assert len(session.calls)==1
    assert any('AI 生成草稿' in x.value for x in app.warning)
    assert any('999' in x.value for x in app.code)
    assert any('检索到的课件证据' in x.value for x in app.subheader)
    assert any('未核验' in x.value for x in [*app.markdown,*app.code,*app.warning])


def test_qa_clear_button_clears_question_and_keeps_mode(monkeypatch,tmp_path):
    runtime(monkeypatch,Settings(api_state_path=tmp_path/'ledger.sqlite3'))
    app=AppTest.from_file('app.py',default_timeout=60).run()
    app.text_area[0].set_value("待清空题目")
    app.run()
    app.radio[0].set_value(QA_MODE_LOCAL).run()
    next(button for button in app.button if button.label == "清空题目").click().run()
    assert app.text_area[0].value == ""
    assert app.radio[0].value == QA_MODE_LOCAL


def test_mode_switch_preserves_typed_question(monkeypatch,tmp_path):
    runtime(monkeypatch,Settings(api_state_path=tmp_path/'ledger.sqlite3'))
    app=AppTest.from_file('app.py',default_timeout=60).run()
    app.text_area[0].set_value("切换模式应保留的题目")
    app.run()
    app.radio[0].set_value(QA_MODE_LOCAL).run()
    assert app.text_area[0].value == "切换模式应保留的题目"


def test_choice_type_defaults_to_auto(monkeypatch,tmp_path):
    runtime(monkeypatch,Settings(api_state_path=tmp_path/'ledger.sqlite3'))
    app=AppTest.from_file('app.py',default_timeout=60).run()
    assert app.selectbox and app.selectbox[0].value == "自动判断"


def test_page_offline_copy_sources_and_insufficiency(monkeypatch,tmp_path):
    runtime(monkeypatch,Settings(api_state_path=tmp_path/'ledger.sqlite3'))
    app=AppTest.from_file('app.py',default_timeout=60).run()
    assert app.radio[0].value=='hybrid'
    app.radio[0].set_value(QA_MODE_LOCAL).run()
    assert app.radio[0].value==QA_MODE_LOCAL
    submit(app,'工程风险的技术因素有哪些？')
    assert app.code and '控制系统失灵' in app.code[0].value
    assert any('原文证据与 PDF 页码'==x.value for x in app.subheader)
    assert any('PDF 第' in x.value or '第 8 页' in x.value for x in app.markdown)
    submit(app,'这份课件是否解释了星际跃迁发动机的动力学方程？')
    assert any('资料不足' in x.value for x in app.warning)
    assert any('未检索到' in x.value or '未找到问题主体' in x.value for x in app.markdown)


def test_master_disabled_toggle_is_disabled_and_never_calls(monkeypatch,tmp_path):
    runtime(monkeypatch,Settings(deepseek_api_key='synthetic-ui-key',api_enabled=False,
                                 api_state_path=tmp_path/'ledger.sqlite3'))
    app=AppTest.from_file('app.py',default_timeout=60).run()
    assert app.toggle[0].disabled
    submit(app,'工程风险的技术因素有哪些？')
    assert not (tmp_path/'ledger.sqlite3').exists()


def test_local_mode_never_calls_api_even_if_toggle_on(monkeypatch,tmp_path):
    config=Settings(deepseek_api_key='synthetic-ui-key',api_enabled=True,
                    api_state_path=tmp_path/'ledger.sqlite3')
    runtime(monkeypatch,config)
    session=FakeSession(response=FakeResponse(payload={'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}],'usage':{'total_tokens':1}}))
    client=DeepSeekClient(config,session=session)
    monkeypatch.setattr('src.qa.DeepSeekClient',lambda settings:client)
    app=AppTest.from_file('app.py',default_timeout=60).run()
    app.radio[0].set_value(QA_MODE_LOCAL).run()
    app.toggle[0].set_value(True).run()
    submit(app,'工程风险的技术因素有哪些？')
    assert not session.calls



def test_ui_toggle_starts_off_and_explicitly_controls_api(monkeypatch,tmp_path):
    config=Settings(deepseek_api_key='synthetic-ui-key',api_enabled=True,api_state_path=tmp_path/'ledger.sqlite3')
    runtime(monkeypatch,config)
    response=FakeResponse(payload={'choices':[{'message':{'content':structured_answer(
        '控制系统失灵会带来事故隐患。',
        [('控制系统失灵；现代工程高度复杂、高度集成，但智能程度不高，存在引发事故的隐患。', ['S1'])],
    )},'finish_reason':'stop'}], 'usage':{'total_tokens':123}})
    session=FakeSession(response=response)
    client=DeepSeekClient(config,session=session)
    monkeypatch.setattr('src.qa.DeepSeekClient',lambda settings:client)
    app=AppTest.from_file('app.py',default_timeout=60).run()
    assert not app.toggle[0].value and not app.toggle[0].disabled and not session.calls
    app.toggle[0].set_value(True).run()
    assert not session.calls  # 开关本身不发送
    submit(app,'工程风险的技术因素有哪些？')
    assert len(session.calls)==1
    assert app.toggle[0].value
    assert any('123' in x.value for x in app.caption)
    assert any('DeepSeek' in x.value for x in app.success)
    app.run()
    assert len(session.calls)==1  # 刷新不重复计费
    assert app.code and '控制系统失灵' in app.code[0].value
    app.toggle[0].set_value(False).run()
    submit(app,'工程风险的技术因素有哪些？')
    assert len(session.calls)==1  # 用户关闭AI后只走本地
    assert any('离线' in x.value for x in app.success)


def test_case_tab_auto_questions_and_clear_keeps_simple_question(monkeypatch,tmp_path):
    runtime(monkeypatch,Settings(api_state_path=tmp_path/'ledger.sqlite3'))
    app=AppTest.from_file('app.py',default_timeout=60).run()
    case_area = next(area for area in app.text_area if area.label.startswith("案例文字"))
    case_area.set_value("案例：某工程发生事故。\n（1）工程师应承担什么责任？\n（2）如何保障社会公正？\n（3）提出改进措施。")
    app.run()
    question_area = next(area for area in app.text_area if area.label.startswith("识别到的设问"))
    assert "工程师应承担什么责任" in question_area.value
    assert "如何保障社会公正" in question_area.value
    assert "提出改进措施" in question_area.value
    assert any("当前设问数量：3" in caption.value for caption in app.caption)
    # 简答题内容不受案例清空影响。
    simple_area = next(area for area in app.text_area if area.label == "输入你的问题")
    simple_area.set_value("简答题保留")
    app.run()
    next(button for button in app.button if button.label == "清空案例").click().run()
    assert next(area for area in app.text_area if area.label.startswith("案例文字")).value == ""
    assert next(area for area in app.text_area if area.label == "输入你的问题").value == "简答题保留"


def test_case_submit_renders_all_question_answers(monkeypatch,tmp_path):
    runtime(monkeypatch,Settings(api_state_path=tmp_path/'ledger.sqlite3'))
    questions = (CaseQuestion(1, "责任是什么？"), CaseQuestion(2, "如何改进？"))
    solution = CaseSolution(
        status="ok", case_text="案例正文", questions=questions,
        answers=(
            CaseAnswer(1, questions[0].text, "设问一答案。", ()),
            CaseAnswer(2, questions[1].text, "设问二答案。", ()),
        ),
    )
    monkeypatch.setattr('src.app.solve_case', lambda *a, **kw: solution)
    app=AppTest.from_file('app.py',default_timeout=60).run()
    case_area = next(area for area in app.text_area if area.label.startswith("案例文字"))
    case_area.set_value("案例正文。\n（1）责任是什么？\n（2）如何改进？")
    app.run()
    next(button for button in app.button if button.label == "提交案例分析").click().run()
    assert any(subheader.value == "案例分析考试作答" for subheader in app.subheader)
    assert any("设问一答案" in markdown.value for markdown in app.markdown)
    assert any("设问二答案" in markdown.value for markdown in app.markdown)
