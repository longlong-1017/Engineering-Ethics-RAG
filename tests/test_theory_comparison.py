"""理论比较题：合成编号与文件名，防止用真实课件页码作规则。"""
from src.query_expansion import expand_query,comparison_sides
from src.retriever import Retriever
from src.evidence import plan_evidence
from tests.helpers import make_corpus,make_page

Q='工程伦理中的功利主义与义务论有什么区别？'


def make_test_corpus():
    return make_corpus(
        make_page('研究方法包括功利主义、权利伦理与义务伦理、美德伦理等理论，用于分析工程中的责任与权利。',category='A',filename='名单.pdf',page_number=5),
        make_page('功利论聚焦于行为的后果，以行为的后果判断行为是否是善的，也被称为后果论或效益论。',category=None,filename='甲.pdf',page_number=172),
        make_page('义务论者强调，行为本身具有道德意义；义务论也称道义论，强调遵守道德准则而非只看后果。',category=None,filename='乙.pdf',page_number=901))


def test_aliases_preserve_original_and_expand_both_sides():
    queries=expand_query(Q)
    assert queries[0]==Q and len(queries)<=6
    assert all(t in queries for t in ('功利主义','功利论','义务论','义务伦理','道义论'))


def test_comparison_expanded_combines_two_real_pages_but_strict_rejects_name_list():
    r=Retriever(make_test_corpus())
    result=r.search(Q,mode='expanded',top_k=10)
    assert {h.page.filename for h in result.hits[:2]}=={'甲.pdf','乙.pdf'}
    assert {h.page.page_number for h,t in plan_evidence(Q,result.hits).quotes}=={172,901}
    strict=r.search(Q,mode='strict',top_k=10)
    assert not strict.enough_evidence
    assert all(h.page.filename=='名单.pdf' for h in strict.hits)


def test_one_explanation_does_not_satisfy_two_sided_question():
    c=make_test_corpus()
    r=Retriever(make_corpus(*c.pages[:2]))
    assert not r.search(Q,mode='expanded').enough_evidence


def test_other_comparison_questions_are_untouched():
    assert not comparison_sides('环境工程安全与社会公正之间有什么关系？')
    assert not comparison_sides('责任伦理与法律责任有什么区别？')
    assert expand_query('工程伦理规范是什么？')==('工程伦理规范是什么？',)
