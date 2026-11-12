"""双版本隔离：每版独立检索、缓存和来源；只用单版充分证据生成答案。"""
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import re

from src.corpus import Corpus, CorpusError, load_corpus
from src.dense_index import DenseIndex
from src.evidence import analyze_question, has_payload, topic_match, plan_evidence, heading
from src.query_expansion import comparison_sides, theory_explanation_strength
from src.retriever import Retriever

NEW_VERSION = 'exam_2026'
NEW_FIRST = 'new_first'
RELEASE = 'dual-exam-2026-v1'
ROOT = Path(__file__).resolve().parents[1]


def source_pdf(page, root=ROOT):
    if page.dataset_version == 'textbook':
        directory = Path(root) / 'data/textbooks'
    elif page.dataset_version == 'quiz':
        directory = Path(root) / 'data/quiz_bank'
    else:
        directory = Path(root) / ('data/pdfs_new' if page.dataset_version == NEW_VERSION else 'data/pdfs')
    target = (directory / page.filename).resolve()
    if target.parent != directory.resolve():
        raise ValueError('PDF来源路径越界')
    return target


def load_versions(root=ROOT):
    root = Path(root)
    old = load_corpus(root / 'data/processed_v3')
    old = replace(old, pages=tuple(replace(p, dataset_version='old', versioned_source=True) for p in old.pages))
    manifest = json.loads((root / 'data/versions/exam_2026.json').read_text('utf-8'))
    files = []
    for item in manifest['documents']:
        for folder, name, digest in [('data/pdfs_new', item['filename'], item['sha256']),
                                     ('data/processed_exam_2026', item['json_filename'], item['json_sha256'])]:
            path = root / folder / name
            if Path(name).name != name or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise CorpusError('新版清单与来源哈希不匹配')
        files.append(root / 'data/processed_exam_2026' / item['json_filename'])
    new = load_corpus(source_files=files)
    if len(new.pages) != manifest['page_count']:
        raise CorpusError('新版总页数不匹配')
    expected = {item['filename']: item for item in manifest['documents']}
    for doc in new.documents:
        item = expected.get(doc.filename)
        if item is None or doc.document_id != item['sha256'] or doc.page_count != item['page_count']:
            raise CorpusError('新版文档标识或页数与发布清单不匹配')
    for page in new.pages:
        item = expected.get(page.filename)
        if item is None or page.document_id != item['sha256'] or not 1 <= page.page_number <= item['page_count']:
            raise CorpusError('新版物理页码或来源标识不匹配')
        if page.review_category is not None or page.repair_applied:
            raise CorpusError('新版未审核发布不得携带历史审核标签')
    new = replace(new, pages=tuple(replace(p, dataset_version=NEW_VERSION, versioned_source=True) for p in new.pages))
    return old, new


def combined_corpus(old, new):
    return Corpus(new.pages + old.pages, new.documents + old.documents, new.source_files + old.source_files)


def load_version_indexes(old, new, root=ROOT):
    """仅本地模型、只读两份缓存；某版失败不影响另一版及BM25。"""
    root = Path(root)
    try:
        from sentence_transformers import SentenceTransformer
        model = root / 'models/bge-small-zh-v1.5'
        encoder = SentenceTransformer(str(model), device='cpu', local_files_only=True,
                                      token=False, trust_remote_code=False)
        stamp = ';'.join(f'{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}'
                         for p in sorted(model.rglob('*')) if p.is_file())
        identity = 'bge-small-zh-v1.5:' + hashlib.sha256(stamp.encode()).hexdigest()
    except Exception as exc:
        return {v: (None, dict(state='failed', reason='本地模型不可用：' + type(exc).__name__))
                for v in ('old', NEW_VERSION)}
    result = {}
    for version, corpus, name in [('old', old, 'vectors.sqlite3'), (NEW_VERSION, new, 'exam_2026.sqlite3')]:
        try:
            index = DenseIndex.from_cache(corpus.expanded_pages, encoder, identity,
                                          root / 'data/retrieval_cache' / name)
            result[version] = index, index.status
        except Exception as exc:
            result[version] = None, dict(state='failed', reason='版本缓存不可用：' + type(exc).__name__)
    return result


def substantive(question, hit):
    sides = comparison_sides(question)
    if sides:
        return any(theory_explanation_strength(hit.page.text, side) > 0 for side in sides)
    profile = analyze_question(question)
    return topic_match(profile, hit.page.text) and has_payload(profile, hit.page.text)


def potential_conflicts(new_hits, old_hits):
    """有限、可解释的冲突线索，不声称完成语义一致性审核。"""
    issues = []
    for a in new_hits:
        for b in old_hits:
            at, bt = a.page.text, b.page.text
            same = heading(at) == heading(bt) and len(heading(at)) >= 4
            an = set(re.findall(r'\d+(?:\.\d+)?\s*(?:人|万元|亿元|%)', at))
            bn = set(re.findall(r'\d+(?:\.\d+)?\s*(?:人|万元|亿元|%)', bt))
            opposite = any(x in at and y in bt or y in at and x in bt
                           for x, y in [('必须公开', '不得公开'), ('应当报告', '不得报告'),
                                        ('应当停止', '应当继续'), ('允许排放', '禁止排放')])
            if same and (an and bn and an != bn or opposite):
                issues.append(f'潜在冲突：{a.citation} 与 {b.citation}，数字或规范表述不同，需人工核对。')
    return list(dict.fromkeys(issues))


class VersionedRetriever:
    def __init__(self, old, new, *, indexes=None):
        indexes = indexes or {}
        self.old = Retriever(old, dense_index=indexes.get('old', (None, None))[0],
                             dense_status=indexes.get('old', (None, None))[1])
        self.new = Retriever(new, dense_index=indexes.get(NEW_VERSION, (None, None))[0],
                             dense_status=indexes.get(NEW_VERSION, (None, None))[1])
        self.corpus = combined_corpus(old, new)

    def search(self, query, *, mode='strict', top_k=6):
        if mode != NEW_FIRST:
            # 新版本次全部待审核；原严格/扩展旧版入口保持原边界。
            return self.old.search(query, mode=mode, top_k=top_k)
        limit = max(1, min(30, top_k))
        new = self.new.search(query, mode='expanded', top_k=max(10, limit))
        old = self.old.search(query, mode='expanded', top_k=max(10, limit))
        new_good = [h for h in new.hits if substantive(query, h)]
        old_good = [h for h in old.hits if substantive(query, h)]
        new_ready = plan_evidence(query, new_good).supported
        old_ready = plan_evidence(query, old_good).supported
        selected = NEW_VERSION if new_ready else 'old' if old_ready else 'none'
        # 版本优先是实质正文门槛后的分层，不比较两个索引的原始分数。
        primary = new_good if selected == NEW_VERSION else old_good if selected == 'old' else new_good + old_good
        secondary = old_good if selected == NEW_VERSION else new_good
        unique = {}
        for hit in primary + secondary + list(new.hits) + list(old.hits):
            unique.setdefault(hit.evidence_id, hit)
        hits = tuple(replace(h, rank=i) for i, h in enumerate(list(unique.values())[:limit], 1))
        # Top-K截断后再次验证，不能声称有实际未传入的充分证据。
        if selected != 'none' and not plan_evidence(query, [h for h in hits if h.page.dataset_version == selected]).supported:
            selected = 'none'
        # 即便正文尚不够独立作答，候选中的明显差异也必须提示。
        conflicts = potential_conflicts(new.hits, old.hits)
        note = ('新版有实质性证据，优先使用新版；旧版候选保留供核对。' if selected == NEW_VERSION else
                '新版证据不足，使用旧版补充；不把新版线索当作已验证依据。' if selected == 'old' else
                '两版均无独立充分证据；不自动拼接未经一致性核对的跨版结论。')
        diagnostics = dict(active_mode='new_first_separate_bm25_bge_rrf', original_question=query,
                           answer_version=selected, version_note=note, conflicts=conflicts,
                           consistency_policy='单次答案使用单一版本；未做完整语义冲突检测',
                           versions={NEW_VERSION: new.diagnostics, 'old': old.diagnostics},
                           selected_pages=[dict(version=h.page.dataset_version, filename=h.page.filename,
                                                page_number=h.page.page_number, evidence_id=h.evidence_id) for h in hits])
        return replace(new, mode=NEW_FIRST, hits=hits, pool_size=new.pool_size + old.pool_size,
                       strict_pool_size=old.strict_pool_size,
                       expanded_pool_size=new.expanded_pool_size + old.expanded_pool_size,
                       diagnostics=diagnostics)
