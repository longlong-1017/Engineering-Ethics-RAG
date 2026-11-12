"""独立章节题库：JSON为导入源，PDF仅交叉核对；不依赖RAG、配置或模型。"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'data/quiz_bank'
DEFAULT_JSON = DIRECTORY / '工程伦理_学习通章节测试题库.json'
DEFAULT_PDF = DIRECTORY / '工程伦理_学习通章节测试题库_文字版.pdf'
DEFAULT_DB = DIRECTORY / 'questions.sqlite3'
TYPES = ('单选', '多选', '判断')


class QuizError(ValueError):
    pass


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise QuizError(f'JSON重复键：{key}')
        result[key] = value
    return result


def validate_payload(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('source'), str) or not payload['source'].strip():
        raise QuizError('缺少来源说明')
    rows = payload.get('questions')
    if not isinstance(rows, list) or not rows:
        raise QuizError('questions必须是非空列表')
    ids, numbers, validated = set(), set(), []
    for row in rows:
        if not isinstance(row, dict):
            raise QuizError('题目必须是对象')
        q = dict(row)
        chapter, number = q.get('chapter'), q.get('number')
        if not isinstance(chapter, str) or not re.fullmatch(r'\d+(?:\.\d+)+', chapter):
            raise QuizError('章节编号无效')
        if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
            raise QuizError('原始题号无效')
        if q.get('id') != f'{chapter}-{number:02d}':
            raise QuizError('题目ID与章节/题号不一致')
        if q['id'] in ids or (chapter, number) in numbers:
            raise QuizError('题目ID或章节题号重复')
        ids.add(q['id']); numbers.add((chapter, number))
        if q.get('type') not in TYPES or not isinstance(q.get('question'), str) or not q['question'].strip():
            raise QuizError(f"{q['id']}题型或题干无效")
        options = q.get('options')
        if not isinstance(options, dict):
            raise QuizError('options必须是对象，判断题使用空对象')
        if q['type'] == '判断':
            if options:
                raise QuizError('判断题不得擅自生成选项')
        elif (len(options) < 2 or set(options) != set('ABCDEFGHIJKLMNOPQRSTUVWXYZ'[:len(options)])
              or any(not isinstance(v, str) or not v.strip() for v in options.values())):
            raise QuizError(f"{q['id']}选项缺失、标签不连续或文本为空")
        for key in ('correct_answer', 'user_answer'):
            value = q.get(key)
            if value == '':
                value = None
            if value is not None:
                if not isinstance(value, str):
                    raise QuizError('答案必须是原始字符串或NULL')
                if q['type'] == '判断':
                    valid = value in ('对', '错')
                else:
                    valid = (all(c in options for c in value) and len(set(value)) == len(value)
                             and (len(value) == 1 if q['type'] == '单选' else len(value) >= 1))
                if not valid:
                    raise QuizError(f"{q['id']}答案包含无效选项")
            q[key] = value
        status = q.get('answer_status')
        if not isinstance(status, str) or not status:
            raise QuizError('缺少答案核实状态')
        if (q['correct_answer'] is not None) != (status == 'confirmed_from_screenshot'):
            raise QuizError(f"{q['id']}正确答案与截图确认状态矛盾，需人工处理")
        score = q.get('score')
        if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or score < 0):
            raise QuizError('分数无效')
        q['score'] = score
        validated.append(q)
    return validated


def pdf_records(content):
    import pymupdf  # 仅在显式PDF交叉核对时加载本地已安装依赖
    questions, answers = {}, {}
    current, target, chapter, mode = None, None, None, None
    with pymupdf.open(stream=content, filetype='pdf') as doc:
        if doc.needs_pass:
            raise QuizError('PDF加密，无法核对')
        for page_number, page in enumerate(doc, 1):
            text = page.get_text('text', sort=True)
            if not text.strip():
                raise QuizError(f'PDF物理第{page_number}页无文字，不能完成交叉核对')
            for raw in text.splitlines():
                line = raw.strip()
                if not line or re.fullmatch(r'工程伦理\s+学习通章节测试题库(?:\s+\d+)?', line):
                    continue
                header = re.fullmatch(r'(\d+(?:\.\d+)+)\s*章节测试\s*(题目|答案速查)', line)
                if header:
                    chapter, mode = header.groups(); current = target = None
                    continue
                if line == '数据说明':
                    mode = None; continue
                if mode == '题目':
                    match = re.fullmatch(r'(\d+)\.\s*\[(单选|多选|判断)\]\s*(.*)', line)
                    if match:
                        number, kind, stem = match.groups(); key = (chapter, int(number))
                        if key in questions:
                            raise QuizError('PDF出现重复题号')
                        current = dict(type=kind, question=stem, options={}, pages=[page_number])
                        questions[key] = current; target = 'question'; continue
                    if current is None:
                        continue
                    option = re.fullmatch(r'([A-Z])\.\s*(.*)', line)
                    if option:
                        target, value = option.groups()
                        if target in current['options']:
                            raise QuizError('PDF出现重复选项')
                        current['options'][target] = value
                    elif target == 'question':
                        current['question'] += '\n' + line
                    elif target:
                        current['options'][target] += '\n' + line
                    if page_number not in current['pages']:
                        current['pages'].append(page_number)
                elif mode == '答案速查':
                    match = re.fullmatch(r'第(\d+)题\s*\[(单选|多选|判断)\]\s*(.+)', line)
                    if not match:
                        continue
                    number, kind, rest = match.groups(); key = (chapter, int(number))
                    if key in answers:
                        raise QuizError('PDF答案出现重复题号')
                    history = re.search(r'原作答[:：]\s*(\S+)', rest)
                    value = None if rest.startswith('待核实') else re.match(r'(?:[A-Z]+|对|错)', rest)
                    if value is None and not rest.startswith('待核实'):
                        raise QuizError('PDF正确答案无法识别')
                    answers[key] = dict(type=kind, correct_answer=value[0] if value else None,
                                        user_answer=history[1] if history else None, page=page_number)
        return questions, answers, len(doc)


def check_sources(json_path=DEFAULT_JSON, pdf_path=DEFAULT_PDF, expected_count=None):
    json_path, pdf_path = Path(json_path), Path(pdf_path)
    raw = json_path.read_bytes(); pdf = pdf_path.read_bytes()
    try:
        payload = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QuizError('JSON无法解析') from exc
    rows = validate_payload(payload)
    if expected_count is not None and len(rows) != expected_count:
        raise QuizError('实际题数与要求不符')
    questions, answers, pdf_pages = pdf_records(pdf)
    expected = {(q['chapter'], q['number']) for q in rows}
    if expected != set(questions) or expected != set(answers):
        raise QuizError('JSON与PDF题目/答案数量或题号不一致')
    compact = lambda text: re.sub(r'\s+', '', text)
    mappings = {}
    for q in rows:
        key = q['chapter'], q['number']; p, a = questions[key], answers[key]
        if (p['type'] != q['type'] or a['type'] != q['type'] or compact(p['question']) != compact(q['question'])
                or set(p['options']) != set(q['options'])
                or any(compact(p['options'][k]) != compact(v) for k, v in q['options'].items())
                or a['correct_answer'] != q['correct_answer']
                or a['user_answer'] is not None and a['user_answer'] != q['user_answer']):
            raise QuizError(f"JSON与PDF内容不一致：{q['id']}，禁止自动改写")
        mappings[q['id']] = dict(question_pages=p['pages'], answer_page=a['page'],
                                  history_crosschecked=a['user_answer'] is not None)
    return dict(source=payload['source'], questions=rows, mappings=mappings, pdf_pages=pdf_pages,
                json_sha256=hashlib.sha256(raw).hexdigest(), pdf_sha256=hashlib.sha256(pdf).hexdigest(),
                json_filename=json_path.name, pdf_filename=pdf_path.name,
                screenshot_independently_verified=False)


SCHEMA = [
    '''CREATE TABLE questions (
      id TEXT PRIMARY KEY, chapter TEXT NOT NULL, number INTEGER NOT NULL CHECK(number>0),
      type TEXT NOT NULL CHECK(type IN ('单选','多选','判断')), question TEXT NOT NULL,
      options_json TEXT NOT NULL, correct_answer TEXT, answer_status TEXT NOT NULL,
      verification_status TEXT NOT NULL CHECK(verification_status IN ('source_reported_confirmed','pending')),
      fingerprint TEXT NOT NULL, UNIQUE(chapter,number))''',
    '''CREATE TABLE imports (
      id TEXT PRIMARY KEY, source TEXT NOT NULL, json_filename TEXT NOT NULL, json_sha256 TEXT NOT NULL,
      pdf_filename TEXT NOT NULL, pdf_sha256 TEXT NOT NULL, question_count INTEGER NOT NULL,
      screenshot_independently_verified INTEGER NOT NULL DEFAULT 0 CHECK(screenshot_independently_verified=0),
      imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''',
    '''CREATE TABLE question_sources (
      import_id TEXT NOT NULL REFERENCES imports(id), question_id TEXT NOT NULL REFERENCES questions(id),
      question_pages_json TEXT NOT NULL, answer_page INTEGER NOT NULL,
      PRIMARY KEY(import_id,question_id))''',
    '''CREATE TABLE attempts (
      id INTEGER PRIMARY KEY, question_id TEXT NOT NULL REFERENCES questions(id), user_answer TEXT,
      score REAL, history_fingerprint TEXT NOT NULL, import_id TEXT NOT NULL REFERENCES imports(id),
      answered_at TEXT, UNIQUE(question_id,history_fingerprint))''',
    'CREATE INDEX questions_chapter_type ON questions(chapter,type)',
]


def import_bank(json_path=DEFAULT_JSON, pdf_path=DEFAULT_PDF, db_path=DEFAULT_DB, expected_count=None):
    checked = check_sources(json_path, pdf_path, expected_count)
    db_path = Path(db_path)
    if db_path.resolve() in {Path(json_path).resolve(), Path(pdf_path).resolve()}:
        raise QuizError('数据库路径不能覆盖输入文件')
    if db_path.exists():
        try:
            with closing(sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)) as existing:
                if existing.execute('PRAGMA user_version').fetchone()[0] != 1 or {r[0] for r in existing.execute("SELECT name FROM sqlite_master WHERE type='table'")} != {'questions','imports','question_sources','attempts'}:
                    raise QuizError('现有文件不是本模块题库，拒绝修改')
        except (sqlite3.DatabaseError, OSError) as exc:
            if isinstance(exc, QuizError):
                raise
            raise QuizError('现有文件不是本模块题库，拒绝修改') from exc
    db_path.parent.mkdir(parents=True, exist_ok=True)
    import_id = digest([checked['source'],checked['json_sha256'],checked['pdf_sha256']])
    added = history_added = 0
    with closing(sqlite3.connect(db_path)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        with db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('PRAGMA user_version').fetchone()[0] == 0:
                for statement in SCHEMA:db.execute(statement)
                db.execute('PRAGMA user_version=1')
            db.execute('INSERT OR IGNORE INTO imports(id,source,json_filename,json_sha256,pdf_filename,pdf_sha256,question_count) VALUES (?,?,?,?,?,?,?)',
                       (import_id,checked['source'],checked['json_filename'],checked['json_sha256'],checked['pdf_filename'],checked['pdf_sha256'],len(checked['questions'])))
            for q in checked['questions']:
                core={k:q[k] for k in ('id','chapter','number','type','question','options','correct_answer','answer_status')}
                fingerprint=digest(core)
                row=db.execute('SELECT fingerprint FROM questions WHERE id=?',(q['id'],)).fetchone()
                if row and row[0] != fingerprint:
                    raise QuizError(f"{q['id']}已存在但内容或答案改变，需人工核实，未覆盖")
                if row is None:
                    db.execute('INSERT INTO questions VALUES (?,?,?,?,?,?,?,?,?,?)',
                               (q['id'],q['chapter'],q['number'],q['type'],q['question'],json.dumps(q['options'],ensure_ascii=False),q['correct_answer'],q['answer_status'],
                                'source_reported_confirmed' if q['correct_answer'] is not None else 'pending',fingerprint))
                    added+=1
                m=checked['mappings'][q['id']]
                db.execute('INSERT OR IGNORE INTO question_sources VALUES (?,?,?,?)',
                           (import_id,q['id'],json.dumps(m['question_pages']),m['answer_page']))
                if q['user_answer'] is not None or q['score'] is not None:
                    history_added+=db.execute('INSERT OR IGNORE INTO attempts(question_id,user_answer,score,history_fingerprint,import_id) VALUES (?,?,?,?,?)',
                                             (q['id'],q['user_answer'],q['score'],digest([q['user_answer'],float(q['score']) if q['score'] is not None else None]),import_id)).rowcount
    return dict(database=str(db_path.resolve()),source_count=len(checked['questions']),added=added,
                history_added=history_added,pending=[q['id'] for q in checked['questions'] if q['correct_answer'] is None],
                crosschecked=len(checked['questions']),pdf_pages=checked['pdf_pages'],
                json_sha256=checked['json_sha256'],pdf_sha256=checked['pdf_sha256'],screenshot_independently_verified=False)


def query_questions(db_path=DEFAULT_DB, *, chapter=None, question_type=None, keyword=None, pending_only=False):
    if question_type is not None and question_type not in TYPES:
        raise QuizError('未知题型')
    clauses, args = [], []
    if chapter is not None:clauses.append('chapter=?');args.append(chapter)
    if question_type is not None:clauses.append('type=?');args.append(question_type)
    if keyword:
        clauses.append('(instr(question,?)>0 OR instr(options_json,?)>0)');args.extend([keyword,keyword])
    if pending_only:clauses.append("verification_status='pending'")
    path=Path(db_path).resolve()
    if not path.is_file():raise QuizError('题库尚未导入')
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute('PRAGMA user_version').fetchone()[0] != 1 or {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} != {'questions','imports','question_sources','attempts'}:
                raise QuizError('现有文件不是本模块题库，拒绝读取')
            db.row_factory=sqlite3.Row
            rows=db.execute('SELECT * FROM questions'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY chapter,number',args).fetchall()
            results=[]
            for row in rows:
                item=dict(row);item['options']=json.loads(item.pop('options_json'));item.pop('fingerprint')
                item['history']=[dict(a) for a in db.execute('SELECT user_answer,score,answered_at FROM attempts WHERE question_id=? ORDER BY id',(item['id'],))]
                item['pdf_sources']=[dict(s) for s in db.execute('SELECT i.pdf_filename,i.pdf_sha256,s.question_pages_json,s.answer_page FROM question_sources s JOIN imports i ON i.id=s.import_id WHERE s.question_id=?',(item['id'],))]
                for source in item['pdf_sources']:source['question_pages']=json.loads(source.pop('question_pages_json'))
                item['verification_note']='按导入文件保留截图确认标记，本工具未独立查看原截图；未与教材核验'
                results.append(item)
        return results
    except (sqlite3.DatabaseError, OSError) as exc:
        if isinstance(exc, QuizError):
            raise
        raise QuizError(f'题库读取失败：{exc}') from exc


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for command in ('check','import'):
        p=sub.add_parser(command);p.add_argument('--json',type=Path,default=DEFAULT_JSON);p.add_argument('--pdf',type=Path,default=DEFAULT_PDF)
        p.add_argument('--expected-count',type=int,default=35)
        if command=='import':p.add_argument('--db',type=Path,default=DEFAULT_DB)
    p=sub.add_parser('query');p.add_argument('--db',type=Path,default=DEFAULT_DB);p.add_argument('--chapter');p.add_argument('--type',choices=TYPES,dest='question_type');p.add_argument('--keyword');p.add_argument('--pending',action='store_true')
    args=parser.parse_args(argv)
    for field in ('json','pdf','db'):
        path=getattr(args,field,None)
        if path is not None and not path.resolve().is_relative_to(DIRECTORY.resolve()):parser.error('CLI仅允许访问项目data/quiz_bank目录')
    try:
        if args.command=='query':result=query_questions(args.db,chapter=args.chapter,question_type=args.question_type,keyword=args.keyword,pending_only=args.pending)
        elif args.command=='import':result=import_bank(args.json,args.pdf,args.db,args.expected_count)
        else:
            result=check_sources(args.json,args.pdf,args.expected_count)
            result={k:v for k,v in result.items() if k not in ('questions','mappings')}
            result['count']=args.expected_count
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (QuizError,OSError,sqlite3.Error) as exc:
        parser.exit(1,f'题库操作失败：{exc}\n')


if __name__=='__main__':raise SystemExit(main())
