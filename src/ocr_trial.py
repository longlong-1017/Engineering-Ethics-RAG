"""最多5个已审查C类页的本地Vision OCR试验；只生成待审候选。"""

from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import subprocess
import unicodedata

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
SELECTION = [
    ('01-p050', '工程伦理基本原则'),
    ('01-p042', '伦理困境：电车难题'),
    ('02-p029', '风险与伦理/法律、事前/事后责任区分'),
    ('00-p032', 'ASCE工程师职业伦理基本原则/准则表'),
    ('07-p004', '吉林石化双苯厂爆炸案例'),
]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def normalize(text):
    """仅用于比对，不改写OCR原文；保留数字与标点，不做语义替换。"""
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if not c.isspace())


def flag_duplicate_lines(lines, existing_text):
    """识别重复与混合重叠；不把OCR直接拼接到已有正文。"""
    existing = normalize(existing_text)
    seen = set()
    ledger = []
    for line in lines:
        normalized = normalize(line['text'])
        longest = SequenceMatcher(None, normalized, existing, autojunk=False).find_longest_match()
        if len(normalized) >= 4 and normalized in existing:
            state = 'duplicate_of_existing'
        elif len(normalized) >= 4 and normalized in seen:
            state = 'duplicate_within_ocr'
        elif longest.size >= 8:
            state = 'partial_overlap_manual_merge'
        else:
            state = 'new_text_candidate'
        seen.add(normalized)
        ledger.append(dict(**line, deduplication=state,
                           longest_existing_match_chars=longest.size,
                           needs_manual_confirmation=True, approved_for_ingestion=False))
    return ledger


def spatial_lines(observations):
    """仅提供通用上到下、左到右展示；表格行列关系不因此获得认证。"""
    lines = []
    for observation in observations:
        if not observation['candidates']:
            continue
        candidate = observation['candidates'][0]
        lines.append(dict(observation_id=observation['observation_id'], text=candidate['text'],
                          confidence=candidate['confidence'], pixel_bbox_top_left=observation['pixel_bbox_top_left']))
    return sorted(lines, key=lambda line: (line['pixel_bbox_top_left'][1], line['pixel_bbox_top_left'][0]))


def refine_ledger(lines, existing_text, native_pixel_boxes, width, height):
    """坐标仅辅助判重/边缘噪声标记，不能作为内容正确或可入库依据。"""
    ledger = flag_duplicate_lines(lines,existing_text)
    for line in ledger:
        box = pymupdf.Rect(line['pixel_bbox_top_left'])
        coverage = min(1.,sum((box&pymupdf.Rect(native)).get_area() for native in native_pixel_boxes)/max(1.,box.get_area()))
        line['native_region_overlap_fraction'] = coverage
        if line['deduplication']=='new_text_candidate' and coverage>=.5 and line['longest_existing_match_chars']>=3:
            line['deduplication']='native_region_overlap_manual_review'
        text=line['text']
        logo = box.x0>width*.86 and box.y0<height*.2 and len(normalize(text))<=3
        footer = box.y0>height*.9 and '电子信息工程学院' in text
        if logo or footer:
            line['deduplication']='noncore_margin_candidate'
            line['region_note']='图标/单位页脚区域候选；仅标记，不改写原始OCR'
    return ledger


def write_json(path, data):
    with Path(path).open('x', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def result_text_fields(raw, existing_text):
    ledger = flag_duplicate_lines(spatial_lines(raw.get('observations',[])),existing_text) if raw.get('status')=='ok' else []
    return dict(ocr_text_engine_order='\n'.join(o['candidates'][0]['text'] for o in raw.get('observations',[]) if o['candidates']),
                ocr_text_spatial_order='\n'.join(line['text'] for line in ledger),
                deduplication_ledger=ledger,
                new_text_candidates=[line for line in ledger if line['deduplication']=='new_text_candidate'],
                partial_overlap_candidates=[line for line in ledger if line['deduplication']=='partial_overlap_manual_merge'])


def retry_vision(root=ROOT):
    """仅重试已有清单及原PNG，不追加第6页，不覆盖首次失败记录。"""
    root = Path(root)
    output = root/'data/ocr_candidates'
    manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    selection = manifest['selection']
    if selection != [list(item) for item in SELECTION]:
        raise ValueError('重试清单必须与本次已授权5页完全相同')
    engine = root/'.build/vision_ocr'
    if digest(engine.read_bytes()) != manifest['engine_binary_sha256']:
        raise ValueError('重试引擎发生变化')
    for name, expected in manifest['source_hashes'].items():
        if digest((root/name).read_bytes()) != expected:
            raise ValueError('原数据发生变化，拒绝重试')
    for key, _ in selection:
        if (output/key/'candidate_retry.json').exists() or (output/key/'vision_retry_raw.json').exists():
            raise FileExistsError('重试结果已存在，拒绝覆盖')
    statuses = []
    for key, _ in selection:
        folder = output/key
        result = json.loads((folder/'candidate.json').read_text(encoding='utf-8'))
        png = folder/'page_300dpi.png'
        if digest(png.read_bytes()) != result['png_sha256']:
            raise ValueError('PNG与首次渲染哈希不匹配')
        run = subprocess.run([str(engine),str(png)],capture_output=True,text=True,timeout=120)
        try:
            raw = json.loads(run.stdout)
        except json.JSONDecodeError:
            raw = dict(status='error',error='重试未返回合法JSON',stdout=run.stdout)
        raw.update(returncode=run.returncode,stderr=run.stderr)
        write_json(folder/'vision_retry_raw.json',raw)
        result.update(result_text_fields(raw,result['original_text']))
        result.update(ocr_status=raw.get('status'),ocr_error=raw.get('error'),attempt=2,
                      retry_reason='sandbox nilError; local Vision service access retry',
                      review_status='pending_visual_and_manual_confirmation')
        write_json(folder/'candidate_retry.json',result)
        with (folder/'ocr_retry_raw.txt').open('x',encoding='utf-8') as handle:
            handle.write(result['ocr_text_engine_order']+'\n')
        status=dict(key=key,status=result['ocr_status'],observations=len(result['deduplication_ledger']),
                    elapsed_seconds=raw.get('elapsed_seconds'),error=result['ocr_error'])
        statuses.append(status)
        print(json.dumps(status,ensure_ascii=False),flush=True)
    if any(digest((root/name).read_bytes()) != expected for name,expected in manifest['source_hashes'].items()):
        raise RuntimeError('重试期间源数据发生变化')
    write_json(output/'retry_summary.json',dict(pages=statuses,source_hashes_unchanged=True))
    return statuses


def run_trial(root=ROOT, engine=None, selection=None):
    root = Path(root)
    selection = SELECTION if selection is None else selection
    keys = [key for key, _ in selection]
    if not 1 <= len(keys) <= 5 or len(set(keys)) != len(keys):
        raise ValueError('仅允许1-5个不重复目标页，禁止批量OCR')
    engine = Path(engine or root/'.build/vision_ocr').resolve()
    output = root/'data/ocr_candidates'
    if output.exists():
        raise FileExistsError('OCR候选目录已存在，拒绝覆盖或追加未授权页面')
    documents = {}
    source_paths = []
    for directory in ['data/pdfs','data/processed','data/processed_v2','data/processed_v3']:
        source_paths.extend(p for p in (root/directory).iterdir() if p.suffix.lower() in {'.pdf','.json'})
    hashes = {str(p.relative_to(root)): digest(p.read_bytes()) for p in source_paths}
    for path in (root/'data/processed_v3').glob('*.json'):
        document = json.loads(path.read_text(encoding='utf-8'))
        documents[document['filename'][:2]] = (document, path)
    targets = []
    for key, topic in selection:
        prefix, number = key.split('-p')
        document, json_path = documents[prefix]
        number = int(number)
        record = document['pages'][number-1]
        if record['high_risk_review']['category'] != 'C':
            raise ValueError(f'{key}不在v3 C类清单中')
        pdf_path = root/'data/pdfs'/document['filename']
        if digest(pdf_path.read_bytes()) != document['document_id'] or record['page_number'] != number:
            raise ValueError('来源PDF哈希/物理页码不匹配')
        targets.append((key, topic, document, record, json_path, pdf_path))
    probe = subprocess.run([str(engine),'--probe'],check=True,capture_output=True,text=True,timeout=60)
    probe_data = json.loads(probe.stdout)
    output.mkdir(exist_ok=False)
    write_json(output/'manifest.json',dict(selection=selection, source_hashes=hashes, engine=probe_data,
                                         engine_binary_sha256=digest(engine.read_bytes()),
                                         swift_source_sha256=digest((root/'scripts/vision_ocr.swift').read_bytes()),
                                         max_pages=5, rendering_dpi=300))
    statuses = []
    for key, topic, document, record, json_path, pdf_path in targets:
        folder = output/key
        folder.mkdir(exist_ok=False)
        png = folder/'page_300dpi.png'
        with pymupdf.open(pdf_path) as pdf:
            page = pdf[record['page_number']-1]
            pixmap = page.get_pixmap(dpi=300,alpha=False)
            pixmap.save(png)
            width,height = pixmap.width,pixmap.height
        run = subprocess.run([str(engine), str(png)],capture_output=True,text=True,timeout=120)
        try:
            raw = json.loads(run.stdout)
        except json.JSONDecodeError:
            raw = dict(status='error',error='引擎未返回合法JSON',stdout=run.stdout)
        raw['returncode'] = run.returncode
        raw['stderr'] = run.stderr
        write_json(folder/'vision_raw.json',raw)
        success = run.returncode==0 and raw.get('status')=='ok'
        ledger = flag_duplicate_lines(spatial_lines(raw.get('observations',[])),record['text']) if success else []
        result = dict(schema_version=1, key=key, topic=topic, filename=document['filename'],
                      document_id=document['document_id'], page_number=record['page_number'],
                      source_dataset='processed_v3', source_json=str(json_path.relative_to(root)),
                      source_json_sha256=digest(json_path.read_bytes()), original_extraction_method=record['extraction_method'],
                      original_text=record['text'], png_sha256=digest(png.read_bytes()), rendering_dpi=300,
                      image_width=width,image_height=height,
                      ocr_status=raw.get('status'), ocr_error=raw.get('error'),
                      ocr_text_engine_order='\n'.join(o['candidates'][0]['text'] for o in raw.get('observations',[]) if o['candidates']),
                      ocr_text_spatial_order='\n'.join(line['text'] for line in ledger),
                      deduplication_ledger=ledger,
                      new_text_candidates=[line for line in ledger if line['deduplication']=='new_text_candidate'],
                      partial_overlap_candidates=[line for line in ledger if line['deduplication']=='partial_overlap_manual_merge'],
                      approved_for_ingestion=False, review_status='pending_visual_and_manual_confirmation',
                      merged_text=None)
        write_json(folder/'candidate.json',result)
        with (folder/'ocr_raw.txt').open('x',encoding='utf-8') as handle:
            handle.write(result['ocr_text_engine_order']+'\n')
        statuses.append(dict(key=key,status=result['ocr_status'],observations=len(ledger),error=result['ocr_error']))
        print(json.dumps(statuses[-1],ensure_ascii=False),flush=True)
    if any(digest((root/name).read_bytes()) != expected for name,expected in hashes.items()):
        raise RuntimeError('源数据哈希改变')
    write_json(output/'run_summary.json',dict(pages=statuses, source_hashes_unchanged=True))
    return statuses


if __name__=='__main__':
    import sys
    if sys.argv[1:] == ['--retry-vision']:
        retry_vision()
    elif sys.argv[1:]:
        raise SystemExit('仅支持默认5页试验或--retry-vision')
    else:
        run_trial()
