"""案例分析：设问拆分、逐问检索、一次模型调用与完整性检查。"""
from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.case_solver import (
    CaseEvidence,
    CaseQuestion,
    _trim_for_input_budget,
    case_answer_markdown,
    parse_case_questions,
    questions_from_editable_lines,
    solve_case,
)
from src.config import Settings
from src.deepseek_client import DeepSeekError
from src.retriever import Hit
from tests.helpers import make_page


class FakeCaseClient:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.calls = 0
        self.messages = None
        self.kwargs = None
        self.configured = True

    def chat(self, messages, **kwargs):
        self.calls += 1
        self.messages = messages
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.content, model="deepseek-flash",
                               usage={"total_tokens": 321}, accounting={})


class FakeCaseRetriever:
    def __init__(self):
        self.queries = []
        self.calls = 0

    def search(self, query, *, mode="expanded", top_k=4):
        self.queries.append(query)
        self.calls += 1
        pages = [
            ("安全责任课件.pdf", 28, "安全责任包括生产安全、公共安全和风险预警。"),
            ("社会公正课件.pdf", 34, "社会公正要求公平分配资源，保障弱势群体。"),
            ("工程师责任课件.pdf", 68, "工程师应披露利益冲突并承担职业责任。"),
        ]
        if "社会" in query:
            filename, page_no, text = pages[1]
        elif "工程师" in query or "职业" in query:
            filename, page_no, text = pages[2]
        else:
            filename, page_no, text = pages[0]
        page = make_page(text, category="A", filename=filename, page_number=page_no)
        hit = Hit(page, 1.0, 1.0, 0.9, ("责任",), True, text, rank=1)
        return SimpleNamespace(hits=[hit])


def _question(n, text):
    return CaseQuestion(n, text)


def _answer(n, text, citations=()):
    return {"index": n, "question": text, "answer": text + "，结合案例事实分析。",
            "citations": list(citations), "insufficient": False}


def _solve(questions, content, *, allow_api=True, client=None, retriever=None, settings=None):
    return solve_case(
        "某工程发生安全事故，工程师发现隐患但未报告，涉及安全责任、社会公正和职业责任。",
        questions,
        retriever=retriever,
        settings=settings or Settings(deepseek_api_key="synthetic-case-key", api_enabled=True),
        allow_api=allow_api,
        client=client or FakeCaseClient(content=content),
    )


def test_parse_multiple_questions_and_event_numbers():
    text = (
        "案例背景：2019年某工程发生事故。\n"
        "（1）工程师应承担什么责任？\n"
        "（2）说明安全与公正的关系？\n"
        "（3）提出改进措施。\n"
    )
    parsed = parse_case_questions(text)
    assert len(parsed.questions) == 3
    assert parsed.questions[0].text.startswith("工程师")
    assert parsed.background.startswith("案例背景")

    event_only = "1. 2019年发生事故。\n2. 2020年完成整改。\n3. 2021年发布报告。"
    parsed_event = parse_case_questions(event_only)
    assert parsed_event.questions == ()


def test_parse_circled_chinese_and_unnumbered_questions():
    circled = "案例：某工程存在隐患。①工程师应如何报告？②应采取哪些措施？"
    parsed = parse_case_questions(circled)
    assert len(parsed.questions) == 2

    chinese = "案例：某工程存在隐患。问题一：责任如何划分？问题二：如何改进？"
    parsed = parse_case_questions(chinese)
    assert len(parsed.questions) == 2

    plain = "请分析工程师的责任。为什么应优先保护公众安全？如何改进？"
    parsed = parse_case_questions(plain)
    assert len(parsed.questions) >= 2


def test_numbering_gap_is_flagged():
    parsed = parse_case_questions("案例：\n（1）责任是什么？\n（3）如何改进？")
    assert len(parsed.questions) == 2
    assert parsed.uncertain
    assert any("编号不连续" in warning for warning in parsed.warnings)


def test_editable_question_lines_support_manual_edits():
    questions = questions_from_editable_lines("1. 第一问被修改？\n新增第二问？\n（3）第三问？")
    assert [q.text for q in questions] == ["第一问被修改？", "新增第二问？", "第三问？"]
    assert [q.number for q in questions] == [1, 2, 3]


def test_edited_questions_drive_each_retrieval_query():
    retriever = FakeCaseRetriever()
    questions = [_question(1, "用户修改后的安全责任问题？")]
    content = json.dumps({"answers": [
        _answer(1, "结合案例的安全责任分析。", []),
    ]}, ensure_ascii=False)
    result = _solve(questions, content, client=FakeCaseClient(content), retriever=retriever)
    assert result.status == "ok"
    assert retriever.queries
    assert "安全优先" in retriever.queries[0]
    assert "责任伦理" in retriever.queries[0]
    assert "案例全文" not in retriever.queries[0]


def test_three_questions_one_api_call_and_answers_in_order():
    retriever = FakeCaseRetriever()
    questions = [_question(1, "安全责任是什么？"), _question(2, "社会公正如何体现？"),
                 _question(3, "工程师职业责任是什么？")]
    content = json.dumps({"answers": [
        _answer(1, "安全责任包括生产安全和公共安全。", ["S1", "S2"]),
        _answer(2, "社会公正要求公平分配资源。", ["S3"]),
        _answer(3, "工程师应披露利益冲突并承担责任。", ["S1"]),
    ]}, ensure_ascii=False)
    client = FakeCaseClient(content)
    result = _solve(questions, content, client=client, retriever=retriever)
    assert result.status == "ok"
    assert client.calls == 1
    assert len(result.answers) == 3
    assert [a.index for a in result.answers] == [1, 2, 3]
    assert len(result.evidence) == 3
    assert [e.ref for e in result.evidence] == [1, 2, 3]
    assert "设问1" in client.messages[1]["content"]
    assert "设问3" in client.messages[1]["content"]
    assert "[S1]" in client.messages[1]["content"]
    assert "安全责任" in result.answers[0].answer
    assert "【案例分析考试作答】" in case_answer_markdown(result)


def test_missing_answer_is_incomplete_not_silent():
    questions = [_question(1, "问题一？"), _question(2, "问题二？"), _question(3, "问题三？")]
    content = json.dumps({"answers": [_answer(1, "答案一"), _answer(2, "答案二")]}, ensure_ascii=False)
    result = _solve(questions, content)
    assert result.status == "incomplete"
    assert len(result.answers) == 2
    assert any("数量不匹配" in error for error in result.errors)
    assert "缺少该设问答案" in case_answer_markdown(result)


def test_wrong_order_and_invalid_citation_are_reported():
    questions = [_question(1, "问题一？"), _question(2, "问题二？")]
    content = json.dumps({"answers": [
        _answer(2, "答案二", ["S99"]),
        _answer(1, "答案一", []),
    ]}, ensure_ascii=False)
    result = _solve(questions, content)
    assert result.status == "incomplete"
    assert any("顺序" in error for error in result.errors)
    assert any("S99" in error for error in result.errors)


def test_api_failure_keeps_evidence_and_no_answers():
    questions = [_question(1, "安全责任是什么？")]
    client = FakeCaseClient(error=DeepSeekError("timeout", code="timeout", attempted=True))
    result = _solve(questions, "", client=client, retriever=FakeCaseRetriever())
    assert result.status == "error"
    assert result.answers == ()
    assert result.evidence
    assert result.api_outcome == "timeout"
    assert result.api_attempted is True


def test_no_api_keeps_evidence_without_fake_answer():
    questions = [_question(1, "安全责任是什么？")]
    client = FakeCaseClient(content="{}")
    result = _solve(questions, "{}", allow_api=False, client=client, retriever=FakeCaseRetriever())
    assert result.status == "error"
    assert result.answers == ()
    assert result.evidence
    assert client.calls == 0


def test_long_case_fails_before_api_and_does_not_truncate():
    questions = [_question(1, "问题？")]
    config = Settings(deepseek_api_key="synthetic-case-key", api_enabled=True, max_input_chars=1000)
    client = FakeCaseClient(content="{}")
    result = solve_case("很长" * 1000, questions, settings=config, allow_api=True, client=client)
    assert result.status == "error"
    assert result.api_outcome == "input_too_long"
    assert client.calls == 0
    assert "未截断" in result.errors[0]


def test_no_ppt_still_allows_one_general_case_call():
    questions = [_question(1, "不存在的案例设问？")]
    content = json.dumps({"answers": [_answer(1, "基于通用工程伦理知识作答。")]}, ensure_ascii=False)
    client = FakeCaseClient(content)
    result = _solve(questions, content, retriever=None, client=client)
    assert result.status == "ok"
    assert client.calls == 1
    assert "（无直接 PPT 理论依据）" in client.messages[1]["content"]


class MixedCaseRetriever:
    """同一次检索同时返回 PPT 理论页和其他事故叙述页。"""
    def __init__(self, theory=True, similar=True):
        self.theory = theory
        self.similar = similar
        self.queries = []
        self.calls = 0

    def search(self, query, *, mode="expanded", top_k=4):
        self.queries.append(query)
        self.calls += 1
        hits = []
        if self.similar:
            page = make_page(
                "某大桥坍塌事故：2018年某地大桥发生坍塌，造成多人受伤。",
                category="A", filename="其他事故案例.pdf", page_number=12,
            )
            hits.append(Hit(page, 999., 20., .8, ("事故",), True, page.text, rank=1))
        if self.theory:
            page = make_page(
                "安全优先原则与责任伦理：工程师应把公众安全放在首位，承担职业责任和风险预警义务。",
                category="A", filename="老师理论课件.pdf", page_number=28,
            )
            hits.append(Hit(page, 1., 1., .9, ("安全", "责任"), True, page.text, rank=2))
        return SimpleNamespace(hits=hits)


def _custom_case(content, case_text, questions, retriever):
    return solve_case(
        case_text, questions,
        retriever=retriever,
        settings=Settings(deepseek_api_key="synthetic-case-key", api_enabled=True),
        allow_api=True,
        client=FakeCaseClient(content=content),
    )


def test_theory_evidence_is_prioritized_over_other_accident_narrative():
    retriever = MixedCaseRetriever(theory=True, similar=True)
    questions = [_question(1, "安全原则与责任伦理如何适用于本案？")]
    content = json.dumps({"answers": [
        _answer(1, "依据安全优先原则和责任伦理，应优先保障公众安全。", []),
    ]}, ensure_ascii=False)
    client = FakeCaseClient(content)
    result = solve_case(
        "某工程发生安全事故。", questions, retriever=retriever,
        settings=Settings(deepseek_api_key="synthetic-case-key", api_enabled=True),
        allow_api=True, client=client,
    )
    assert result.status == "ok"
    kinds = [e.kind for e in result.evidence]
    assert kinds[0] == "theory"
    assert "similar_case" in kinds
    assert "老师理论课件" in result.evidence[0].hit.page.filename
    prompt = client.messages[1]["content"]
    assert "### 理论依据" in prompt
    assert "### 类似案例" in prompt


def test_similar_case_citation_is_flagged_as_analogy_only():
    retriever = MixedCaseRetriever(theory=True, similar=True)
    questions = [_question(1, "本案的安全责任如何分析？")]
    content = json.dumps({"answers": [
        _answer(1, "可参考其他事故的责任处理。", ["S2"]),
    ]}, ensure_ascii=False)
    client = FakeCaseClient(content)
    result = solve_case(
        "某工程发生安全事故。", questions, retriever=retriever,
        settings=Settings(deepseek_api_key="synthetic-case-key", api_enabled=True),
        allow_api=True, client=client,
    )
    assert result.status == "ok"
    assert any("类似案例" in flag for flag in result.answers[0].fact_flags)
    assert any("类似案例" in warning for warning in result.warnings)


def test_no_theory_evidence_reports_theory_gap_and_keeps_similar_case_as_analogy():
    retriever = MixedCaseRetriever(theory=False, similar=True)
    questions = [_question(1, "本案的责任伦理依据是什么？")]
    content = json.dumps({"answers": [
        _answer(1, "可参考类似事故，但课件理论依据不足。", []),
    ]}, ensure_ascii=False)
    client = FakeCaseClient(content)
    result = solve_case(
        "某工程发生安全事故。", questions, retriever=retriever,
        settings=Settings(deepseek_api_key="synthetic-case-key", api_enabled=True),
        allow_api=True, client=client,
    )
    assert result.status == "ok"
    assert any(("课件理论依据不足" in warning or "缺少直接课件理论依据" in warning)
               for warning in result.warnings)
    assert result.evidence and all(e.kind == "similar_case" for e in result.evidence)
    prompt = client.messages[1]["content"]
    assert "类似案例（只能类比" in prompt
    assert "（无直接 PPT 理论依据）" in prompt


def test_unsupported_report_and_signing_claims_are_flagged():
    questions = [_question(1, "工程师应承担什么责任？")]
    content = json.dumps({"answers": [
        _answer(1, "工程师未向监管部门报告，并拒绝签署文件。", []),
    ]}, ensure_ascii=False)
    result = _custom_case(content, "某工程发现安全隐患，工程师继续施工。", questions, None)
    assert result.status == "ok"
    flags = result.answers[0].fact_flags
    assert any("报告" in flag for flag in flags)
    assert any("签署" in flag for flag in flags)
    assert any("未完成全面事实核验" in warning for warning in result.warnings)


def test_legal_responsibility_is_flagged_when_case_lacks_legal_facts():
    questions = [_question(1, "责任如何认定？")]
    content = json.dumps({"answers": [
        _answer(1, "工程师应承担刑事责任和民事赔偿。", []),
    ]}, ensure_ascii=False)
    result = _custom_case(content, "工程师发现隐患但继续施工。", questions, None)
    assert result.status == "ok"
    assert any("法律责任" in flag or "责任结论" in flag for flag in result.answers[0].fact_flags)


def test_case_prompt_requires_fact_boundary_and_concise_points():
    questions = [_question(1, "安全责任是什么？")]
    client = FakeCaseClient(json.dumps({"answers": [_answer(1, "要点答案。", [])]}, ensure_ascii=False))
    result = solve_case(
        "案例明确：负责人发现隐患后仍决定继续施工。", questions,
        settings=Settings(deepseek_api_key="synthetic-case-key", api_enabled=True),
        allow_api=True, client=client,
    )
    assert result.status == "ok"
    system = client.messages[0]["content"]
    user = client.messages[1]["content"]
    assert "3～5 个核心要点" in system
    assert '"points"' in system and "evidence_ids" in system
    assert "model_knowledge" in system
    assert "已知事实" in system and "合理推断" in system and "未知情况" in system
    assert "案例已知事实" in user
    assert "负责人发现隐患后仍决定继续施工" in user


def test_four_question_case_uses_case_output_budget_and_one_call():
    questions = [_question(i, f"设问{i}：应如何分析？") for i in range(1, 5)]
    content = json.dumps({"answers": [
        _answer(i, f"设问{i}的直接结论与理论分析。", []) for i in range(1, 5)
    ]}, ensure_ascii=False)
    client = FakeCaseClient(content)
    result = _solve(questions, content, client=client)
    assert result.status == "ok"
    assert len(result.answers) == 4
    assert [a.index for a in result.answers] == [1, 2, 3, 4]
    assert client.calls == 1
    assert client.kwargs["max_tokens"] == 3600


def test_output_truncation_is_distinct_from_json_and_network_failure():
    questions = [_question(1, "安全责任是什么？")]
    for code in ("output_truncated", "json_parse", "network_error"):
        client = FakeCaseClient(error=DeepSeekError(f"failure-{code}", code=code, attempted=True))
        result = _solve(questions, "", client=client, retriever=FakeCaseRetriever())
        assert result.status == "error"
        assert result.answers == ()
        assert result.api_outcome == code
        assert client.calls == 1
        assert result.evidence


def test_four_question_parse_error_is_not_success():
    questions = [_question(i, f"设问{i}？") for i in range(1, 5)]
    client = FakeCaseClient("这不是 JSON")
    result = _solve(questions, "", client=client, retriever=FakeCaseRetriever())
    assert result.status == "error"
    assert result.answers == ()
    assert result.api_outcome == "invalid_response"
    assert client.calls == 1


def test_four_question_no_theory_reports_each_gap_without_fake_citation():
    questions = [_question(i, f"一般案例设问{i}？") for i in range(1, 5)]
    content = json.dumps({"answers": [
        _answer(i, f"通用分析{i}。", []) for i in range(1, 5)
    ]}, ensure_ascii=False)
    client = FakeCaseClient(content)
    result = _solve(questions, content, client=client, retriever=None)
    assert result.status == "ok"
    assert len(result.warnings) >= 4
    assert all("课件理论依据不足" in warning for warning in result.warnings[:4])
    assert "（无直接 PPT 理论依据）" in client.messages[1]["content"]


class FactSensitiveRetriever:
    """模拟校准器：含事故专有事实的 query 会把理论页判为不相关。"""
    def __init__(self):
        self.queries = []

    def search(self, query, *, mode="expanded", top_k=4):
        self.queries.append(query)
        if "挑战者" in query or "1986" in query:
            return SimpleNamespace(hits=[])
        page = make_page(
            "责任伦理与安全优先原则：工程师应优先保障公众安全，履行职业责任。",
            category="A", filename="理论课件.pdf", page_number=18,
        )
        hit = Hit(page, 1., 1., .9, ("安全", "责任"), True, page.text, rank=1)
        return SimpleNamespace(hits=[hit])


def test_theory_query_does_not_include_challenge_accident_details():
    retriever = FactSensitiveRetriever()
    questions = [_question(1, "案例中有哪些工程伦理问题？")]
    content = json.dumps({"answers": [
        _answer(1, "依据责任伦理与安全优先原则分析。", []),
    ]}, ensure_ascii=False)
    client = FakeCaseClient(content)
    result = solve_case(
        "1986年挑战者号航天飞机爆炸，工程师曾指出密封圈风险。", questions,
        retriever=retriever,
        settings=Settings(deepseek_api_key="synthetic-case-key", api_enabled=True),
        allow_api=True, client=client,
    )
    assert result.status == "ok"
    assert result.evidence and result.evidence[0].kind == "theory"
    theory_query = retriever.queries[0]
    assert "责任伦理" in theory_query or "安全优先" in theory_query
    assert "挑战者" not in theory_query and "1986" not in theory_query
    assert not any("课件理论依据不足" in warning for warning in result.warnings)


def test_case_solver_uses_case_output_budget_when_creating_client(monkeypatch):
    questions = [_question(1, "设问？")]
    content = json.dumps({"answers": [_answer(1, "答案。", [])]}, ensure_ascii=False)
    config = Settings(
        deepseek_api_key="synthetic-case-key", api_enabled=True,
        max_output_tokens=1000, case_max_output_tokens=3600,
    )
    created = {}
    def factory(settings):
        created["settings"] = settings
        return FakeCaseClient(content)
    monkeypatch.setattr("src.case_solver.DeepSeekClient", factory)
    result = solve_case("案例事实。", questions, settings=config, allow_api=True)
    assert result.status == "ok"
    assert created["settings"].max_output_tokens == 3600
    assert created["settings"].case_max_output_tokens == 3600


class TwoVersionRetriever:
    def __init__(self):
        self.queries = []

    def search(self, query, *, mode="expanded", top_k=4):
        self.queries.append(query)
        new_page = replace(make_page(
            "安全优先原则要求把公众安全放在首位，并履行工程师职业责任。",
            category=None, filename="新版理论.pdf", page_number=10,
        ), dataset_version="exam_2026")
        old_page = make_page(
            "安全优先原则 要求把公众安全放在首位，并履行工程师职业责任。",
            category="A", filename="旧版理论.pdf", page_number=10,
        )
        hits = [
            Hit(old_page, 2., 2., .9, ("安全",), True, old_page.text, rank=1),
            Hit(new_page, 1., 1., .9, ("安全",), True, new_page.text, rank=2),
        ]
        return SimpleNamespace(hits=hits)


def test_cross_version_near_duplicate_keeps_new_primary_and_merged_sources():
    retriever = TwoVersionRetriever()
    questions = [_question(1, "安全原则与职业责任是什么？")]
    content = json.dumps({"answers": [_answer(1, "答案。", ["S1"])]}, ensure_ascii=False)
    client = FakeCaseClient(content)
    result = solve_case(
        "某工程发生安全事故。", questions, retriever=retriever,
        settings=Settings(deepseek_api_key="synthetic-case-key", api_enabled=True),
        allow_api=True, client=client,
    )
    assert result.status == "ok"
    assert len(result.evidence) == 1
    item = result.evidence[0]
    assert item.hit.page.filename == "新版理论.pdf"
    assert len(item.sources) == 2
    assert {h.page.filename for h in item.sources} == {"新版理论.pdf", "旧版理论.pdf"}


class SameCaseRetriever:
    def __init__(self):
        self.queries = []

    def search(self, query, *, mode="expanded", top_k=4):
        self.queries.append(query)
        p10 = make_page(
            "挑战者号航天飞机事故案例介绍：1986年发射后爆炸。",
            category="A", filename="挑战者号案例.pdf", page_number=10,
        )
        p66 = make_page(
            "挑战者号工程师职业责任分析：工程师应如何履行职业责任和风险报告。",
            category="A", filename="挑战者号责任.pdf", page_number=66,
        )
        theory = make_page(
            "责任伦理与风险治理原则：工程师应保护公众安全。",
            category="A", filename="理论课件.pdf", page_number=2,
        )
        return SimpleNamespace(hits=[
            Hit(p10, 3., 3., .9, ("案例",), True, p10.text, rank=1),
            Hit(p66, 1., 1., .9, ("责任",), True, p66.text, rank=2),
            Hit(theory, 1., 1., .9, ("责任",), True, theory.text, rank=3),
        ])


def test_current_case_analysis_is_distinct_from_background_and_abstract_theory():
    retriever = SameCaseRetriever()
    questions = [_question(1, "挑战者号工程师职业责任是什么？")]
    content = json.dumps({"answers": [_answer(1, "结合本题案例回答。", [])]}, ensure_ascii=False)
    client = FakeCaseClient(content)
    result = solve_case(
        "挑战者号航天飞机事故：工程师发现风险。", questions, retriever=retriever,
        settings=Settings(deepseek_api_key="synthetic-case-key", api_enabled=True),
        allow_api=True, client=client,
    )
    assert result.status == "ok"
    kinds = {e.hit.page.page_number: e.kind for e in result.evidence}
    assert kinds[66] == "same_case_analysis"
    assert kinds[10] == "background"
    assert kinds[2] == "theory"
    assert result.evidence[0].hit.page.page_number == 66


def test_shared_evidence_is_passed_once_with_multiple_question_numbers():
    retriever = TwoVersionRetriever()
    questions = [_question(1, "安全原则？"), _question(2, "职业责任？")]
    content = json.dumps({"answers": [
        _answer(1, "答案一。", ["S1"]), _answer(2, "答案二。", ["S2"]),
    ]}, ensure_ascii=False)
    client = FakeCaseClient(content)
    result = solve_case(
        "某工程发生安全事故。", questions, retriever=retriever,
        settings=Settings(deepseek_api_key="synthetic-case-key", api_enabled=True),
        allow_api=True, client=client,
    )
    # 两个设问共享同一页时只保留一条证据，并记录两个关联设问。
    shared = [e for e in result.evidence if e.hit.page.filename in {"新版理论.pdf", "旧版理论.pdf"}]
    assert shared
    assert any(len(e.questions) == 2 for e in shared)
    assert "S1" in client.messages[1]["content"]


class VersionConflictRetriever:
    def search(self, query, *, mode="expanded", top_k=4):
        new = make_page("一般课程背景介绍，与本题无关。", category=None,
                        filename="新版无关.pdf", page_number=1)
        old = make_page("安全优先原则和职业责任理论：工程师应保护公众安全。",
                        category="A", filename="旧版理论.pdf", page_number=2)
        return SimpleNamespace(hits=[
            Hit(new, 1., 1., .5, ("背景",), False, new.text, rank=1),
            Hit(old, 1., 1., .9, ("安全",), True, old.text, rank=2),
        ])


def test_relevant_old_theory_beats_irrelevant_new_version():
    retriever = VersionConflictRetriever()
    questions = [_question(1, "安全原则与职业责任？")]
    content = json.dumps({"answers": [_answer(1, "答案。", [])]}, ensure_ascii=False)
    client = FakeCaseClient(content)
    result = solve_case(
        "某工程发生安全事故。", questions, retriever=retriever,
        settings=Settings(deepseek_api_key="synthetic-case-key", api_enabled=True),
        allow_api=True, client=client,
    )
    assert result.status == "ok"
    assert result.evidence[0].hit.page.filename == "旧版理论.pdf"
    assert result.evidence[0].kind == "theory"


def test_input_budget_drops_low_priority_evidence_without_truncating_text():
    questions = [_question(1, "安全责任？")]
    evidence = []
    for index in range(1, 5):
        page = make_page(
            f"第{index}条理论证据：安全优先原则、责任伦理和风险治理。" * 20,
            category="A", filename=f"证据{index}.pdf", page_number=index,
        )
        hit = Hit(page, 1., 1., .9, ("安全",), True, page.text, rank=index)
        evidence.append(CaseEvidence(index, hit, page.text, (1,), "theory", .5, {}, (hit,)))
    trimmed, warnings = _trim_for_input_budget(
        "某工程发生安全事故。", questions, evidence, ("某工程发生安全事故。",), 1000
    )
    assert len(trimmed) < len(evidence)
    assert [e.ref for e in trimmed] == list(range(1, len(trimmed) + 1))
    assert any("未截断正文" in warning for warning in warnings)


def test_different_theories_sharing_safety_words_are_not_merged():
    safe_page = make_page(
        "安全优先原则要求优先保护公众安全，工程师应进行风险预警和风险防范。" * 2,
        category="A", filename="安全理论.pdf", page_number=1,
    )
    responsibility_page = make_page(
        "责任伦理强调工程师对公众的社会伦理责任，不等于只对企业忠诚。" * 2,
        category="A", filename="责任理论.pdf", page_number=2,
    )
    safe = CaseEvidence(1, Hit(safe_page, 1., 1., .9, ("安全",), True, safe_page.text, rank=1),
                        safe_page.text, (1,), "theory", .5, {}, (Hit(safe_page, 1., 1., .9, ("安全",), True, safe_page.text, rank=1),))
    responsibility = CaseEvidence(2, Hit(responsibility_page, 1., 1., .9, ("责任",), True,
                                         responsibility_page.text, rank=2),
                                  responsibility_page.text, (1,), "theory", .5, {},
                                  (Hit(responsibility_page, 1., 1., .9, ("责任",), True,
                                       responsibility_page.text, rank=2),))
    from src.case_solver import _near_duplicate
    assert not _near_duplicate(safe.text, responsibility.text)


class SupplementRetriever:
    def __init__(self):
        self.calls = 0
        self.queries = []

    def search(self, query, *, mode="expanded", top_k=4):
        self.calls += 1
        self.queries.append(query)
        if self.calls < 3:
            return SimpleNamespace(hits=[])
        page = make_page(
            "可接受风险与风险评价：组织应评估风险容忍度并建立风险决策程序。",
            category="A", filename="风险补充理论.pdf", page_number=44,
        )
        hit = Hit(page, 1., 1., .9, ("风险",), True, page.text, rank=1)
        return SimpleNamespace(hits=[hit])


def test_missing_theory_triggers_limited_local_supplement_search():
    retriever = SupplementRetriever()
    questions = [_question(1, "可接受风险如何判断？")]
    content = json.dumps({"answers": [_answer(1, "依据可接受风险和风险评价分析。", [])]},
                         ensure_ascii=False)
    client = FakeCaseClient(content)
    result = solve_case(
        "某工程存在风险。", questions, retriever=retriever,
        settings=Settings(deepseek_api_key="synthetic-case-key", api_enabled=True),
        allow_api=True, client=client,
    )
    assert result.status == "ok"
    assert retriever.calls >= 3
    assert result.evidence and result.evidence[0].kind == "theory"
    assert not any("缺少直接课件理论依据" in warning for warning in result.warnings)


class AdmissionRetriever:
    def __init__(self):
        self.queries = []

    def search(self, query, *, mode="expanded", top_k=4):
        self.queries.append(query)
        e_page = make_page(
            "E类页面：挑战者号案例只有标题，正文无法确认。",
            category="E", filename="E类.pdf", page_number=58,
        )
        title_page = make_page(
            "挑战者号案例介绍", category="A", filename="标题页.pdf", page_number=10,
        )
        low_same = make_page(
            "挑战者号责任分析", category="A", filename="低相关同案.pdf", page_number=61,
        )
        good = make_page(
            "职业责任伦理原则：工程师应保护公众安全并履行职业责任。",
            category="A", filename="理论.pdf", page_number=31,
        )
        def hit(page, coverage):
            return Hit(page, 1., 1., coverage, ("责任",), True, page.text, rank=1)
        return SimpleNamespace(hits=[hit(e_page, .9), hit(title_page, .5), hit(low_same, 0.), hit(good, .9)])


def test_e_title_and_relevance_zero_same_case_are_excluded_but_diagnosed():
    retriever = AdmissionRetriever()
    questions = [_question(1, "挑战者号工程师职业责任是什么？")]
    content = json.dumps({"answers": [_answer(1, "依据职业责任理论。", ["S1"])]}, ensure_ascii=False)
    client = FakeCaseClient(content)
    result = solve_case(
        "挑战者号航天飞机事故：工程师发现风险。", questions, retriever=retriever,
        settings=Settings(deepseek_api_key="synthetic-case-key", api_enabled=True),
        allow_api=True, client=client,
    )
    excluded = {(x["filename"], x["reason"]) for x in result.excluded_evidence}
    assert any("E类.pdf" in name and "E 类" in reason for name, reason in excluded)
    assert any("标题页.pdf" in name for name, reason in excluded)
    assert any("低相关同案.pdf" in name and "relevance=0" in reason for name, reason in excluded)
    assert all(e.hit.page.filename == "理论.pdf" for e in result.evidence)


def test_structured_points_have_per_point_citations_and_old_format_still_works():
    questions = [_question(1, "安全责任是什么？")]
    structured = {
        "answers": [{
            "index": 1, "question": "安全责任是什么？",
            "points": [
                {"title": "安全优先", "analysis": "安全优先原则要求保护公众安全。",
                 "evidence_ids": ["S1"], "source_type": "ppt"},
                {"title": "模型补充", "analysis": "可结合一般工程伦理知识补充。",
                 "evidence_ids": [], "source_type": "model_knowledge"},
            ],
        }]
    }
    result = _solve(questions, json.dumps(structured, ensure_ascii=False),
                    client=FakeCaseClient(json.dumps(structured, ensure_ascii=False)),
                    retriever=FakeCaseRetriever())
    assert result.status == "ok"
    point = result.answers[0].points[0]
    assert point.evidence_ids == (1,)
    assert point.source_type == "ppt"
    assert result.answers[0].points[1].source_type == "model_knowledge"
    assert any("语义支持" in warning for warning in result.warnings)
    assert "模型补充" in case_answer_markdown(result)
    old = _answer(1, "旧版整段答案。", ["S1"])
    old_result = _solve(questions, json.dumps({"answers": [old]}, ensure_ascii=False),
                        client=FakeCaseClient(json.dumps({"answers": [old]}, ensure_ascii=False)),
                        retriever=FakeCaseRetriever())
    assert old_result.status == "ok"
    assert old_result.answers[0].points == ()
    assert "旧版整段答案" in old_result.answers[0].answer


def test_point_citation_must_be_associated_with_current_question():
    questions = [_question(1, "安全责任是什么？")]
    content = {
        "answers": [{
            "index": 1, "question": questions[0].text,
            "points": [{"title": "错误引用", "analysis": "引用其他设问证据。",
                        "evidence_ids": ["S9"], "source_type": "ppt"}],
        }]
    }
    raw = json.dumps(content, ensure_ascii=False)
    result = _solve(questions, raw, client=FakeCaseClient(raw), retriever=FakeCaseRetriever())
    assert result.status == "incomplete"
    assert any("未关联当前设问" in error or "不存在" in error for error in result.errors)


def test_hypothetical_advice_does_not_trigger_signing_or_reporting_flags():
    questions = [_question(1, "工程师应如何行动？")]
    content = json.dumps({"answers": [
        _answer(1, "如果我是工程师，必要时拒绝签署放行；建议向监管部门报告。", []),
    ]}, ensure_ascii=False)
    result = _custom_case(content, "工程师发现隐患但继续施工。", questions, None)
    assert result.status == "ok"
    assert not any("签署" in flag or "报告" in flag for flag in result.answers[0].fact_flags)


def test_definitive_unknown_fact_still_triggers_risk():
    questions = [_question(1, "工程师做了什么？")]
    content = json.dumps({"answers": [
        _answer(1, "工程师未向监管部门报告，并拒绝签署文件。", []),
    ]}, ensure_ascii=False)
    result = _custom_case(content, "工程师发现隐患但继续施工。", questions, None)
    assert any("报告" in flag for flag in result.answers[0].fact_flags)
    assert any("签署" in flag for flag in result.answers[0].fact_flags)


class ChallengeEvidenceRetriever:
    def __init__(self):
        self.queries = []

    def search(self, query, *, mode="expanded", top_k=4):
        self.queries.append(query)
        pages = [
            make_page("挑战者号航天飞机事故案例介绍：发射后爆炸。", category="A",
                      filename="挑战者号案例.pdf", page_number=10),
            make_page("挑战者号事故影响与反思：安全研究中的常见案例。", category="A",
                      filename="挑战者号影响.pdf", page_number=68),
            make_page("挑战者号工程师职业责任：职业工程判断、保护公众安全。", category="A",
                      filename="挑战者号责任.pdf", page_number=66),
            make_page("挑战者号案例分析标题", category="E",
                      filename="挑战者号E类.pdf", page_number=58),
            make_page("挑战者号公共安全分析：公众健康和安全。", category="A",
                      filename="挑战者号公共安全.pdf", page_number=61),
            make_page("职业责任与伦理责任原则：工程师应履行职业责任。", category="A",
                      filename="职业责任理论.pdf", page_number=31),
        ]
        hits = [Hit(p, 1., 1., .8, ("责任",), True, p.text, rank=i)
                for i, p in enumerate(pages, 1)]
        return SimpleNamespace(hits=hits)


def test_challenge_four_questions_get_per_question_evidence_and_e_page_excluded():
    questions = [
        _question(1, "案例中有哪些工程伦理问题？"),
        _question(2, "工程师应承担什么责任？"),
        _question(3, "组织决策存在什么问题？"),
        _question(4, "应如何改进？"),
    ]
    content = json.dumps({"answers": [
        _answer(1, "答案一。", []), _answer(2, "答案二。", []),
        _answer(3, "答案三。", []), _answer(4, "答案四。", []),
    ]}, ensure_ascii=False)
    client = FakeCaseClient(content)
    result = solve_case(
        "1986年挑战者号航天飞机爆炸，工程师发现密封圈风险。", questions,
        retriever=ChallengeEvidenceRetriever(),
        settings=Settings(deepseek_api_key="synthetic-case-key", api_enabled=True),
        allow_api=True, client=client,
    )
    assert result.status == "ok"
    by_page = {e.hit.page.page_number: e for e in result.evidence}
    assert 58 not in by_page
    assert any("挑战者号E类.pdf" in item["filename"] for item in result.excluded_evidence)
    assert 66 in by_page
    assert by_page[66].kind == "same_case_analysis"
    assert set(by_page[66].questions) == {2, 4}
    # 纯背景不应自动关联全部设问；允许被某个需要背景的设问单独使用。
    if 68 in by_page:
        assert set(by_page[68].questions) != {1, 2, 3, 4}
    assert 10 in by_page and by_page[10].kind == "background"
    assert not any(3 in e.questions for e in result.evidence if e.hit.page.page_number in {10, 66})
    if 31 in by_page:
        assert {2, 4}.issubset(set(by_page[31].questions))
    if 61 in by_page:
        assert by_page[61].kind != "theory"
    assert any("风险正常化" in warning for warning in result.warnings)


class PublicSafetyRetriever:
    def search(self, query, *, mode="expanded", top_k=4):
        page = make_page(
            "挑战者号公共安全分析：保护公众健康和安全。",
            category="A", filename="公共安全案例.pdf", page_number=61,
        )
        hit = Hit(page, 1., 1., .8, ("安全",), True, page.text, rank=1)
        return SimpleNamespace(hits=[hit])


def test_public_safety_case_cannot_be_risk_normalization_theory():
    questions = [_question(1, "组织决策中的风险正常化问题是什么？")]
    content = json.dumps({"answers": [_answer(1, "答案。", [])]}, ensure_ascii=False)
    client = FakeCaseClient(content)
    result = solve_case(
        "挑战者号航天飞机事故。", questions, retriever=PublicSafetyRetriever(),
        settings=Settings(deepseek_api_key="synthetic-case-key", api_enabled=True),
        allow_api=True, client=client,
    )
    assert result.status == "ok"
    assert not any(e.kind == "theory" for e in result.evidence)
    assert any("风险正常化" in warning for warning in result.warnings)


def test_inline_citation_is_cleaned_and_rendered_from_evidence_ids_only():
    questions = [_question(1, "安全责任是什么？")]
    payload = {
        "answers": [{
            "index": 1,
            "points": [{
                "title": "安全优先（S1）",
                "analysis": "依据安全优先原则分析（S1）。",
                "evidence_ids": ["S1"],
                "source_type": "ppt",
            }],
        }]
    }
    raw = json.dumps(payload, ensure_ascii=False)
    result = _solve(questions, raw, client=FakeCaseClient(raw), retriever=FakeCaseRetriever())
    assert result.status == "ok"
    point = result.answers[0].points[0]
    assert "S1" not in point.title and "S1" not in point.analysis
    assert point.evidence_ids == (1,)
    assert any("内联引用" in warning for warning in result.warnings)
    copied = case_answer_markdown(result)
    assert "安全优先" in copied and "[S1]" in copied
    assert "分析（S1）" not in copied


def test_unauthorized_inline_citation_is_not_promoted_to_evidence_ids():
    questions = [_question(1, "安全责任是什么？")]
    payload = {
        "answers": [{
            "index": 1,
            "points": [{
                "title": "模型补充",
                "analysis": "可参考通用知识（S3、S4）。",
                "evidence_ids": [],
                "source_type": "model_knowledge",
            }],
        }]
    }
    raw = json.dumps(payload, ensure_ascii=False)
    result = _solve(questions, raw, client=FakeCaseClient(raw), retriever=FakeCaseRetriever())
    assert result.status == "incomplete"
    point = result.answers[0].points[0]
    assert point.evidence_ids == ()
    assert "S3" not in point.analysis and "S4" not in point.analysis
    assert any("不在 evidence_ids" in error for error in result.errors)
    assert "S3" not in case_answer_markdown(result)


def test_model_knowledge_with_evidence_ids_is_rejected_and_cleared():
    questions = [_question(1, "安全责任是什么？")]
    payload = {
        "answers": [{
            "index": 1,
            "points": [{
                "title": "模型补充",
                "analysis": "参考通用知识。",
                "evidence_ids": ["S1"],
                "source_type": "model_knowledge",
            }],
        }]
    }
    raw = json.dumps(payload, ensure_ascii=False)
    result = _solve(questions, raw, client=FakeCaseClient(raw), retriever=FakeCaseRetriever())
    assert result.status == "incomplete"
    point = result.answers[0].points[0]
    assert point.evidence_ids == ()
    assert any("model_knowledge" in error for error in result.errors)
