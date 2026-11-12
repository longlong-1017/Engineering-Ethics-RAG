"""独立题库合成JSON/PDF测试；不访问生产语料、配置或网络。"""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pymupdf
import pytest

from src.quiz_bank import (QuizError, check_sources, import_bank, query_questions,
                           validate_payload, unique_keys)


def payload():
    return dict(source='合成截图记录，测试专用',questions=[
        dict(id='9.4-01',chapter='9.4',number=1,type='单选',question='哪项属于责任？',
             options=dict(A='甲选项',B='乙选项',C='丙选项',D='丁选项'),
             correct_answer='B',answer_status='confirmed_from_screenshot',user_answer='A',score=0),
        dict(id='9.4-02',chapter='9.4',number=2,type='多选',question='应考虑哪些事项？',
             options=dict(A='公众安全',B='利益关系',C='伦理责任',D='环境风险'),
             correct_answer='AC',answer_status='confirmed_from_screenshot',user_answer='ABC',score=2.5),
        dict(id='9.4-03',chapter='9.4',number=3,type='判断',question='测试命题是否正确？',
             options={},correct_answer=None,answer_status='not_visible_in_screenshot',user_answer='错',score=None),
    ])


def write_pair(directory, data):
    jp,pp=directory/'questions.json',directory/'questions.pdf'
    jp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    with pymupdf.open() as doc:
        page=doc.new_page()
        lines=['9.4 章节测试 题目']
        for q in data['questions']:
            lines.append(f"{q['number']}. [{q['type']}] {q['question']}")
            lines.extend(f'{k}. {v}' for k,v in q['options'].items())
        for i,line in enumerate(lines):page.insert_text((35,45+i*25),line,fontname='china-s',fontsize=11)
        page=doc.new_page();lines=['9.4 章节测试 答案速查']
        for q in data['questions']:
            answer=q['correct_answer'] if q['correct_answer'] is not None else '待核实（截图未显示）'
            line=f"第{q['number']}题 [{q['type']}] {answer}"
            if q.get('user_answer') is not None:line+=f" 原作答：{q['user_answer']}"
            lines.append(line)
        for i,line in enumerate(lines):page.insert_text((35,45+i*25),line,fontname='china-s',fontsize=11)
        doc.save(pp)
    return jp,pp


@pytest.fixture
def bank(tmp_path):
    jp,pp=write_pair(tmp_path,payload())
    return jp,pp,tmp_path/'questions.sqlite3'


def test_crosscheck_import_and_null_without_guessing(bank):
    jp,pp,db=bank
    checked=check_sources(jp,pp,expected_count=3)
    assert checked['pdf_pages']==2 and not checked['screenshot_independently_verified']
    result=import_bank(jp,pp,db,expected_count=3)
    assert result['added']==3 and result['pending']==['9.4-03']
    rows=query_questions(db)
    assert len(rows)==3 and rows[2]['correct_answer'] is None
    assert rows[2]['verification_status']=='pending' and rows[2]['options']=={}
    assert rows[1]['options']==payload()['questions'][1]['options']
    assert rows[1]['correct_answer']=='AC' and rows[1]['history'][0]['user_answer']=='ABC'
    assert rows[1]['history'][0]['score']==2.5
    assert rows[1]['history'][0]['answered_at'] is None
    assert rows[0]['pdf_sources'][0]['question_pages']==[1]
    assert rows[0]['pdf_sources'][0]['answer_page']==2


def test_repeat_import_and_format_only_changes_do_not_duplicate(bank):
    jp,pp,db=bank
    import_bank(jp,pp,db)
    result=import_bank(jp,pp,db)
    assert result['added']==result['history_added']==0
    jp.write_text(json.dumps(payload(),ensure_ascii=False,indent=3))
    result=import_bank(jp,pp,db)
    assert result['added']==result['history_added']==0
    with sqlite3.connect(db) as conn:
        assert conn.execute('select count(*) from questions').fetchone()[0]==3
        assert conn.execute('select count(*) from attempts').fetchone()[0]==3


@pytest.mark.parametrize('criteria,expected', [
    ({'chapter':'9.4'},3),({'chapter':'0.0'},0),({'question_type':'判断'},1),
    ({'question_type':'多选','keyword':'公众安全'},1),({'keyword':'责任'},2),
    ({'keyword':'利益关系'},1),({'chapter':'9.4','pending_only':True},1),
    ({'chapter':'0.0','pending_only':True},0),({'question_type':'单选','pending_only':True},0),
    ({'pending_only':True},1),({'keyword':"' OR 1=1 --"},0),({'keyword':'%'},0),
])
def test_queries_are_filtered_and_parameterized(bank,criteria,expected):
    jp,pp,db=bank;import_bank(jp,pp,db)
    assert len(query_questions(db,**criteria))==expected


@pytest.mark.parametrize('field,value', [
    ('correct_answer','A'),('type','多选'),('question','擅自改写题干'),
    ('options',dict(A='已修改',B='乙选项',C='丙选项',D='丁选项')),
])
def test_json_pdf_mismatch_is_rejected_before_creating_database(bank,field,value):
    jp,pp,db=bank;data=payload();data['questions'][0][field]=value
    jp.write_text(json.dumps(data,ensure_ascii=False))
    with pytest.raises(QuizError):import_bank(jp,pp,db)
    assert not db.exists()


def test_answer_change_requires_manual_verification_and_rolls_back(bank,tmp_path):
    jp,pp,db=bank;import_bank(jp,pp,db)
    data=payload();data['questions'][0]['correct_answer']='A'
    other=tmp_path/'changed';other.mkdir();newj,newp=write_pair(other,data)
    with pytest.raises(QuizError,match='需人工核实'):import_bank(newj,newp,db)
    assert query_questions(db)[0]['correct_answer']=='B'
    with sqlite3.connect(db) as conn:assert conn.execute('select count(*) from imports').fetchone()[0]==1


@pytest.mark.parametrize('change', ['duplicate','missing_option','bad_answer','contradictory_status','empty_stem','bad_number'])
def test_invalid_structure_and_duplicate_ids_are_rejected(change):
    data=payload();q=data['questions'][0]
    if change=='duplicate':data['questions'].append(deepcopy(q))
    elif change=='missing_option':del q['options']['B']
    elif change=='bad_answer':q['correct_answer']='Z'
    elif change=='contradictory_status':q['correct_answer']=None
    elif change=='empty_stem':q['question']=' '
    elif change=='bad_number':q['number']=True
    with pytest.raises(QuizError):validate_payload(data)


def test_duplicate_json_object_keys_rejected():
    with pytest.raises(QuizError):json.loads('{"A":"one","A":"two"}',object_pairs_hook=unique_keys)


def test_count_mismatch_missing_db_and_foreign_database_are_safe(bank):
    jp,pp,db=bank
    with pytest.raises(QuizError):import_bank(jp,pp,db,expected_count=35)
    assert not db.exists()
    with pytest.raises(QuizError):query_questions(db)
    assert not db.exists()
    with sqlite3.connect(db) as conn:conn.execute('create table foreign_data(value)')
    before=db.read_bytes()
    with pytest.raises(QuizError):import_bank(jp,pp,db)
    assert before==db.read_bytes()


def test_changed_history_appends_but_does_not_change_correct_answer(bank,tmp_path):
    jp,pp,db=bank;import_bank(jp,pp,db)
    data=payload();data['questions'][0]['user_answer']='B';data['questions'][0]['score']=5
    other=tmp_path/'history';other.mkdir();newj,newp=write_pair(other,data)
    result=import_bank(newj,newp,db)
    assert result['added']==0 and result['history_added']==1
    row=query_questions(db)[0]
    assert row['correct_answer']=='B' and [h['user_answer'] for h in row['history']]==['A','B']


def test_import_rejects_overwriting_input_sources(bank):
    jp,pp,db=bank
    with pytest.raises(QuizError,match='数据库路径不能覆盖输入文件'):
        import_bank(jp,pp,jp)
    with pytest.raises(QuizError,match='数据库路径不能覆盖输入文件'):
        import_bank(jp,pp,pp)


def test_import_and_query_reject_corrupted_or_foreign_database(bank,tmp_path):
    jp,pp,db=bank
    bad_db=tmp_path/'corrupted.sqlite3'
    bad_db.write_text('this is not a sqlite database')
    with pytest.raises(QuizError,match='现有文件不是本模块题库'):
        import_bank(jp,pp,bad_db)
    with pytest.raises(QuizError,match='题库读取失败|现有文件不是本模块题库'):
        query_questions(bad_db)

    foreign_db=tmp_path/'foreign.sqlite3'
    with sqlite3.connect(foreign_db) as conn:
        conn.execute('CREATE TABLE foreign_tbl (id INT)')
    with pytest.raises(QuizError,match='现有文件不是本模块题库'):
        query_questions(foreign_db)

    # Directory target
    dir_target=tmp_path/'dir_db'
    dir_target.mkdir()
    with pytest.raises(QuizError,match='题库尚未导入'):
        query_questions(dir_target)


@pytest.mark.parametrize('empty_answer,status,should_pass', [
    ('', 'confirmed_from_screenshot', False),
    (None, 'confirmed_from_screenshot', False),
    ('A', 'not_visible_in_screenshot', False),
    ('', 'not_visible_in_screenshot', True),
    (None, 'not_visible_in_screenshot', True),
])
def test_empty_and_null_correct_answers_validation(empty_answer,status,should_pass):
    data=payload()
    data['questions'][0]['correct_answer']=empty_answer
    data['questions'][0]['answer_status']=status
    if should_pass:
        rows=validate_payload(data)
        assert rows[0]['correct_answer'] is None
    else:
        with pytest.raises(QuizError):
            validate_payload(data)


def test_empty_and_null_user_answer_normalization():
    data=payload()
    data['questions'][0]['user_answer']=''
    rows=validate_payload(data)
    assert rows[0]['user_answer'] is None


@pytest.mark.parametrize('bad_value', [
    ' ', '   ', '\t', '\n', 'AB', 'AA', 'Z',
])
def test_single_choice_invalid_answer_formats(bad_value):
    data=payload()
    data['questions'][0]['correct_answer']=bad_value
    with pytest.raises(QuizError):
        validate_payload(data)


@pytest.mark.parametrize('bad_value', [
    ' ', 'ABA', 'AAC', 'Z', 'AZ',
])
def test_multi_choice_invalid_answer_formats(bad_value):
    data=payload()
    data['questions'][1]['correct_answer']=bad_value
    with pytest.raises(QuizError):
        validate_payload(data)


@pytest.mark.parametrize('bad_value', [
    ' ', 'A', 'B', 'True', 'False', 'yes',
])
def test_judgment_invalid_answer_formats(bad_value):
    data=payload()
    data['questions'][2]['correct_answer']=bad_value
    data['questions'][2]['answer_status']='confirmed_from_screenshot'
    with pytest.raises(QuizError):
        validate_payload(data)


@pytest.mark.parametrize('bad_score', [
    -1, -0.5, True, False, float('nan'), float('inf'), '10'
])
def test_invalid_score_rejected(bad_score):
    data=payload()
    data['questions'][0]['score']=bad_score
    with pytest.raises(QuizError):
        validate_payload(data)


def test_repeat_import_with_partial_history_and_float_scores(bank,tmp_path):
    jp,pp,db=bank;import_bank(jp,pp,db)
    # Add history with score only (user_answer=None)
    data=payload()
    data['questions'][0]['user_answer']=None
    data['questions'][0]['score']=3.0
    other=tmp_path/'history2';other.mkdir();newj,newp=write_pair(other,data)
    res=import_bank(newj,newp,db)
    assert res['added']==0 and res['history_added']==1
    row=query_questions(db)[0]
    assert len(row['history'])==2
    assert row['history'][1]['user_answer'] is None and row['history'][1]['score']==3.0

    # Repeating the exact same attempt with integer score (3 vs 3.0) should be deduplicated
    data['questions'][0]['score']=3
    other2=tmp_path/'history3';other2.mkdir();newj2,newp2=write_pair(other2,data)
    res2=import_bank(newj2,newp2,db)
    assert res2['added']==0 and res2['history_added']==0
    assert len(query_questions(db)[0]['history'])==2


def test_query_invalid_question_type_raises(bank):
    jp,pp,db=bank;import_bank(jp,pp,db)
    with pytest.raises(QuizError,match='未知题型'):
        query_questions(db,question_type='问答')
    with pytest.raises(QuizError,match='未知题型'):
        query_questions(db,question_type=123)

