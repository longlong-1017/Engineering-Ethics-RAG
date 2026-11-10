"""根据本次提取对比证据和已查看的页面生成修复报告，拒绝覆盖。"""

from collections import Counter
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DETAILS = {
    '00-p015': (
        '标题、G6/G7/G8标签落到正文之后，并产生大量空格。',
        '页面rotation=90，dict行方向为(0,-1)。原提取按未旋转坐标排序；显示坐标中标题y≈97、G6≈163、G7≈290、G8≈372、页脚≈509，足以恢复阅读层级。',
        'text(sort=False)、blocks和dict默认保留较连贯的正文，但页脚排在最前，标题在末尾；blocks(sort=True)仍按未旋转坐标排序。dict行框乘rotation_matrix后，按显示y/x排序最接近本页。',
        '已修复阅读顺序；标题→G6及说明→G7及说明→G8及说明→页脚。203个非空白字符全部保留。'),
    '00-p021': (
        '两行章节标题被倒置。上次质量报告声称缺少“工程伦理”，本次核对发现原JSON其实包含该词，这是先前审查误判，本次明确更正。',
        'rotation=90；显示坐标第一行y≈200，第二行y≈257。原JSON为“教育发展四、国内外工程伦理”，非字符缺失。',
        'text(sort=False)、blocks默认和dict默认已是正确两行顺序；显示坐标dict也正确，且与同文档另两页修复策略一致。text(sort=True)与未旋转坐标排序不符阅读方向。',
        '已修复为“四、国内外工程伦理\n教育发展”，13个非空白字符保留，未补字。'),
    '00-p029': (
        '正文续行提前，标题和“美国”侧栏穿插到正文后部，页脚混入。',
        'rotation=90；显示标题y≈97，正文条目3-6依次y≈165/264/319/417；侧栏“美”“国”x≈25，与正文x≈80分开。',
        'text(sort=False)、blocks/dict默认的条目正文较连贯，但页脚在前、侧栏在最后。单纯显示坐标y/x会把侧栏拆进正文；采用本页已审查区域：顶部24%为标题，x<7%且位于正文高度的侧栏先读，底部18%为页脚，正文按y/x。',
        '已修复阅读顺序；标题→侧栏“美/国”→3-6条正文及续行→页脚。183个非空白字符全部保留；这只是本页约定，不推广为多栏通用规则。'),
    '01-p040': (
        '“契约论”标题及大量正文未提取，首句开头只剩“论通过…”。',
        '嵌入图像分布在标题、首句开头及后续段落。例：image number=8、xref=232、bbox≈(117.7,128.5,175.6,158.9)，对应已查看的“契约”图片区域；texttrace只有后续“论通过一个”等真实文字，没有该缺失词对应字符。',
        'text、blocks和dict都只有相同39个非空白字符；不论调整裁剪、忽略ActualText、使用精确边框都无法读出图片内文字。没有一种纯文本提取模式可恢复全部正文。',
        '未修复，保留原提取文本，标记局部OCR或人工补录候选。缺失片段不从画面笔记自动写入正文。'),
    '07-p001': (
        '原JSON提取出“工程伦理”、日期和页码，但画面只见幕布。',
        'texttrace显示文字绘制序号5-13且opacity=1；bboxlog显示之后序号15、16绘制两块接近全高的图像，覆盖全部文字边框。结合本次150DPI渲染和上次独立Poppler预览，确认是后绘制幕布遮挡，非仅按文字透明度可筛除。',
        'text、blocks和dict均返回14个非空白字符，默认提取不等同最终可见性检测；更换排序或裁剪不会消除遮挡后的字。未使用通用bbox重叠规则去删除其他页文字。',
        '采取可逆隔离：v2 text为空，status=visibility_quarantined，原文完整保留original_text；标记quarantined_pending_manual_confirmation。不是完整修复，也不是空白页；是否保留被遮挡内容仍需人工决定，暂不建议OCR。'),
    '09-p037': (
        '正文缺“环保工程改善环境”“不合理性”，造成句子断裂。',
        '三个嵌入小图分别位于≈(376.7,283.3,508.0,318.2)、(506.1,283.2,636.5,318.2)、(369.8,341.2,499.9,375.6)。texttrace在对应行的前后文字之间有坐标间隙，缺词不在文字层；第一图xref=149，对应可见“环保工程”。',
        '各模式都只有同一组161个非空白字符；sort=True至少将标题放在正文前，blocks/dict默认会把标题放最后。其他模式未补回缺词，保持原方法更稳妥。',
        '未修复，保留原文字及布局，标记局部OCR或人工补录候选。'),
    '10-p056': (
        '定义开头“制药工程”、列表中的“包括”及各制药类别缺失。',
        '第一处缺词是xref=189的小图，bbox≈(207.0,140.7,338.4,175.6)，本次放大图可见“制药工程”；其余列表缺词也与小图边框对应，texttrace不含这些缺失字符。原报告提及“工程专业”缺失不准确：原JSON实际已有“的工程专业”，本次不将此片段计为缺词。',
        'text、blocks、dict及其他参数均只有62个非空白字符；排序只能重排现存文字，不能读取这些栅格字。原sort=True保留标题在前，继续保留原文。',
        '未修复，标记局部OCR或人工补录候选；未凭定义常识补写任何类别。'),
    '10-p063': (
        '“企业编造…和产品检验记录”中缺“生产记录”；右侧信息图的表格和说明未提取。',
        '缺词对应image number=11、xref=216、bbox≈(173.8,212.7,304.9,247.6)，放大可见“生产记录”；右侧整张信息图bbox≈(518.5,103.0,936.2,489.2)。缺词不是相邻文字拼接错误，位于独立栅格图中。',
        '各模式均只有相同101个非空白字符；dict保留图像位置但不能直接给出图像内文本。原sort=True的标题在前，默认blocks/dict标题在末，切换反而会引入顺序变化。',
        '未修复，标记局部OCR/人工补录；信息图需额外表格结构复核，不能只补一个词就宣布整页完整。'),
}


def main():
    evidence_dir = ROOT / 'reports/pdf_repair'
    evidence = [json.loads((evidence_dir / f'{key}.json').read_text(encoding='utf-8')) for key in DETAILS]
    originals = {p.name: json.loads(p.read_text(encoding='utf-8')) for p in (ROOT / 'data/processed').glob('*.json')}
    outputs = {p.name: json.loads(p.read_text(encoding='utf-8')) for p in (ROOT / 'data/processed_v2').glob('*.json')}
    assert originals.keys() == outputs.keys() and len(outputs) == 10
    states = Counter()
    changed, unchanged = [], 0
    for name, before in originals.items():
        after = outputs[name]
        assert before['page_count'] == after['page_count'] and len(before['pages']) == len(after['pages'])
        for old, new in zip(before['pages'], after['pages']):
            assert all(old[k] == new[k] for k in ('filename', 'document_id', 'page_number'))
            states[new['repair_status']] += 1
            if old['text'] != new['text']:
                changed.append(f"{before['filename'][:2]}-p{old['page_number']:03}")
            else:
                unchanged += 1
    assert len(changed) == 4 and unchanged == 603 and sum(states.values()) == 607
    source_hashes = json.loads((ROOT / 'reports/pdf_quality/source_hashes.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == sha for path, sha in source_hashes.items())
    manifest = dict(source_hashes_unchanged=True, source_file_count=len(source_hashes), documents=10, pages=607,
                    changed_text_pages=changed, unchanged_text_pages=unchanged, repair_status_counts=dict(states),
                    output_hashes={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / 'data/processed_v2').glob('*.json')})
    with (evidence_dir / 'verification.json').open('x', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    comparison = ['# 8页文本提取方式完整对比', '', '所有内容来自本地原PDF提取。dict结果只拼接文字span，图像对象保留在同页证据JSON的images中，不执行OCR。', '']
    for item in evidence:
        comparison += [f"## {item['key']}", '']
        for method, text in item['methods'].items():
            comparison += [f'### {method}', '', '```text', text, '```', '']
    with (evidence_dir / 'method_comparison.md').open('x', encoding='utf-8') as handle:
        handle.write('\n'.join(comparison))
    lines = ['# PDF文本提取修复报告', '', '日期：2026-11-08（Asia/Shanghai）。范围：质量报告确认的8个异常抽查页。', '',
             '## 结果', '',
             '**已修复3页阅读顺序；1页遮挡文字已可逆隔离、待人工确认；4页图片缺词无法用纯文本提取恢复。未完整解决的页面共5页。**', '',
             '已在独立 `data/processed_v2/` 输出10份JSON、607页，保留原文件名、文档标识及1起物理页码。只有00-p015、00-p021、00-p029的阅读顺序和07-p001的隔离text发生变化；603页text逐字符不变，其中599个非目标页的全部既有字段均不变。为全部页面新增提取方法和修复状态，不代表对其余599页进行了重新质量验收。', '',
             '原10份PDF和原10份JSON均与此前质量检查的SHA-256一致；原通用解析器 `src/pdf_loader.py` 未修改。没有OCR、在线AI、LangChain或ChromaDB，没有安装新依赖。', '',
             '## 提取方法比较与判定规则', '',
             '逐页比较text(sort=True)、text(sort=False)、blocks默认、blocks(sort=True)、dict默认，并检查dict行框、方向、rotation_matrix和必要的绘制顺序。额外试验无限裁剪、TEXT_IGNORE_ACTUALTEXT、TEXT_ACCURATE_BBOXES；在这8页上均未恢复更多非空白字符。', '',
             '下表数字仅为非空白字符数，不作为正确性依据。各模式字符集合一致而顺序不同，说明“字符数相同”仍可能存在阅读顺序问题。选择结论来自本次实际打开150DPI原页PNG、文字坐标与具体段落对照；这些是助手视觉检查，不是人工签核。', '',
             '| 物理页 | text排序 | text不排序 | blocks默认/排序 | dict默认 | 显示坐标dict | 采用方案 |', '|---|---:|---:|---:|---:|---:|---|']
    for item in evidence:
        counts = {k: len(''.join(v.split())) for k, v in item['methods'].items()}
        key = item['key']
        choice = '显示坐标dict行排序' if key in ('00-p015','00-p021') else ('显示坐标dict+已核实侧栏区域' if key == '00-p029' else ('原文留档、隔离待确认' if key == '07-p001' else '保留原text，标记未解决'))
        lines.append(f"| {key} | {counts['text_sort_true']} | {counts['text_sort_false']} | {counts['blocks_default']}/{counts['blocks_sort_true']} | {counts['dict_default']} | {counts.get('dict_display_coordinates','未采用')} | {choice} |")
    lines += ['', '全部提取结果见[完整方式对比](pdf_repair/method_comparison.md)。每页证据JSON包含各模式全文、dict文字span和原坐标、变换后行坐标、嵌入图片xref与bbox、texttrace、bboxlog；不包含OCR推测。', '',
              '## 8个异常页的原因、方案与结果', '']
    for item in evidence:
        key = item['key']
        problem, reason, contrast, outcome = DETAILS[key]
        lines += [f'### {key}：{item["filename"]}，物理第{item["page_number"]}页', '',
                  f'问题：{problem}', '', f'原因与证据：{reason}', '', f'方式对比与选择：{contrast}', '', f'处理结果：{outcome}', '',
                  f'[本次原页预览](pdf_repair/{key}.png) · [提取/坐标证据](pdf_repair/{key}.json)', '']
        if key in ('01-p040','09-p037','10-p056','10-p063'):
            lines += [f'[缺词对应嵌入图像bbox的300DPI页面局部预览](pdf_repair/{key}_raster_word.png)。该图是按嵌入图像边框渲染的原页区域，不是OCR输出。', '']
        if 'dict_display_coordinates' in item['methods']:
            lines += ['修复后的正文（来自原文字层，仅重排行，不补写）：', '', '```text', item['methods']['dict_display_coordinates'], '```', '']
    lines += ['## 修复实现与保护措施', '',
              '- `src/pdf_repair.py`是独立修复入口：` .venv/bin/python -m src.pdf_repair `。当前输出已存在，重复运行会拒绝覆盖；若要重做，应先由用户另行安排已有产物。',
              '- 白名单同时绑定文档SHA-256和物理页码；只对目标页尝试修改。输入PDF文件名、内容哈希、页数、页面元数据必须与原JSON一致，目标页原文必须与当前原提取一致，否则拒绝套用策略。',
              '- 旋转重排前要求rotation=90，并验证重排前后全部非空白字符的多重集合完全一致。页29侧栏分区仅适用于已查看的这一页，不批量推广给607页。',
              '- 所有v2页记录 `extraction_method` 和 `repair_status`；8个目标页保留 `original_text`、`repair_action`、`repair_note`。`schema_version=2`，文档增加修复汇总；原status和warning在未修改页不变。',
              '- 非目标页方法标记为 `original_json:get_text(text,sort=True)`，即沿用原结果，不伪称重新提取或视觉验证过。缺词页保留原method并记录未解决候选状态。',
              '- 幕布页status为 `visibility_quarantined` 而不是blank，text为空但原字串完整留档；`quarantined_pending_manual_confirmation`不等同修复完成。没有把被遮挡文字转录成可见正文。',
              '- 输出目录必须独立于原JSON目录，且排他创建；任何已有v2目录都拒绝覆盖。中文JSON以UTF-8、ensure_ascii=False写入。', '',
              '## 回归测试与实际输出验证', '',
              '**26项测试通过：原有9项全部保留，新增17项回归测试全部通过，0失败。** 存在5条现有PyMuPDF/SWIG弃用警告，不影响结果。', '',
              '实际运行：`.venv/bin/python -m pytest -q`；新增测试文件 `tests/test_pdf_repair.py`。覆盖3页标题/条目/续行/侧栏/页脚顺序、字符守恒、4个图片页不补写、幕布页可逆隔离与后绘制图像覆盖坐标证据、599页所有既有字段不变、607页来源元数据和method完整、原对象不被原地改写、来源哈希和目标原文失配拒绝、输出UTF-8重读及防覆盖、未审查相似文件不应用修复、非90度拒绝策略。', '',
              '另外实际运行修复入口生成10份v2文件，并逐页复核：607页来源信息保持，4页text变化、603页text完全不变；20个原文件哈希不变。[验证清单及v2文件哈希](pdf_repair/verification.json)。', '',
              '## 未解决页与OCR必要性', '',
              '| 页面 | 下一步建议 | 当前状态 |', '|---|---|---|',
              '| 01-p040 | 对标题与栅格正文局部OCR或人工补录，随后逐段核对契约论全部正文 | 未修复 |',
              '| 09-p037 | 补录3处嵌入图片文字，核对整句连接 | 未修复 |',
              '| 10-p056 | 补录定义开头和制药类别等图片文字，核对全部段落 | 未修复 |',
              '| 10-p063 | 补录“生产记录”及右侧信息图；后者需核对表格、数字和说明 | 未修复 |',
              '| 07-p001 | 人工决定是否保留幕布后文字；OCR最终画面不能恢复被遮挡信息，当前无需OCR | 已隔离，待人工确认 |', '',
              '表内出现的缺词只用于解释已见的页面证据，没有凭这些笔记填入v2正文。OCR尚未安装或执行；人工补录也尚未实施。前期16个无文本页未纳入本次修复白名单，其原文和状态全部保持，不因这次输出就消除此前OCR/人工检查建议。', '',
              '## 是否继续处理其他高风险页', '',
              '**建议继续定向处理，但不建议把这套局部规则直接用于全部页面。** 先抽查绪论其余顺序风险页，确认旋转与布局类型，尤其识别侧栏、多栏和图注；再选择代表页验证后扩大白名单。对有文本但句子缺成分的页面应排查嵌入文字小图，它们可能没有达到此前图像面积阈值，不能只检查96个图像风险候选。', '',
              '建议优先处理本次4个已证实的正文图片缺词页及前次07-p020关系图，再复核其余高风险候选。当前只完成3页局部阅读顺序修复与1页可逆隔离，仍不建议将全部v2数据直接认定为完整可信知识正文。', '',
              '## 本次新增/修改文件', '',
              '- 新增：`src/pdf_repair.py`、`tests/test_pdf_repair.py`、`scripts/analyze_pdf_repairs.py`、`scripts/build_pdf_repair_report.py`。',
              '- 新增：`data/processed_v2/`下10份JSON；`reports/pdf_repair/`下8份提取证据JSON、8张原页PNG、4张局部PNG、方法对比及验证清单；本Markdown报告。',
              '- 修改：README增加局部修复入口说明，.gitignore排除生成的processed_v2目录。依赖及系统Python未变，既有质量报告保留不改，误判在本报告中更正。', '']
    path = ROOT / 'reports/PDF文本提取修复报告.md'
    with path.open('x', encoding='utf-8') as handle:
        handle.write('\n'.join(lines))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
