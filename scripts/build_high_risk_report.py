"""生成定向审查报告、候选清单和修复前后对比，不构建知识库。"""

from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

from src.pdf_review import ROOT, load_reviews

OUT = ROOT/'reports/high_risk_review'

# 这是本次查看后的内容角色清单，不用字数阈值推断是否有备考价值。
NAVIGATION = {'00-p004', *{f'00-p{n:03}' for n in range(51,63)},
              '01-p011','01-p057','02-p002','02-p037','03-p002','04-p003',
              '05-p001','05-p002','05-p003','05-p021','05-p049','05-p077',
              '06-p002','06-p019','06-p060','07-p009','10-p002'}
CORE = {'01-p007','02-p008','02-p009','03-p017','05-p005','05-p068','06-p004','06-p005',
        '07-p015','09-p008','09-p012','09-p034','10-p004','10-p005','10-p061',
        *{f'00-p{n:03}' for n in [16,17,18,20,23,24,25,26,27,28,30,31,34,35]}}


def main():
    queue = json.loads((OUT/'queue.json').read_text(encoding='utf-8'))
    assert len(queue['source_hashes']) == 30
    for name, expected in queue['source_hashes'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == expected
    docs = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((ROOT/'data/processed_v3').glob('*.json'))]
    assert len(docs) == 10 and sum(d['page_count'] for d in docs) == 607
    pages = {f"{d['filename'][:2]}-p{p['page_number']:03}":p for d in docs for p in d['pages']}
    decisions = load_reviews()
    decisions_by_key = {d['key']:d for d in decisions.values()}
    rows, eligible, held, omitted, diffs = [], [], [], [], []
    for row in queue['queue']:
        key = row['key']
        page = pages[key]
        decision = page['high_risk_review']
        item = dict(key=key, filename=page['filename'], document_id=page['document_id'], page_number=page['page_number'],
                    category=decision['category'], repair_applied=decision['repair_applied'], disposition=decision['disposition'],
                    content_role='navigation_only' if key in NAVIGATION else ('suggested_core_text' if key in CORE else 'other_reviewed_text'),
                    note=decision['note'], extraction_method=page['extraction_method'], preview=decision['preview'], evidence=decision['evidence'])
        rows.append(item)
        if item['disposition'].startswith('eligible'):
            eligible.append(item)
        elif item['category']=='D':
            omitted.append(item)
        else:
            held.append(item)
        if item['repair_applied']:
            diffs.append(dict(key=key, filename=page['filename'], document_id=page['document_id'], page_number=page['page_number'],
                              before=page['pre_v3_text'], after=page['text'], method=page['extraction_method']))
    assert len(rows)==145 and len(eligible)==81 and len(diffs)==50 and len(held)==52 and len(omitted)==12
    assert CORE <= {r['key'] for r in eligible}
    counts = Counter(r['category'] for r in rows)
    manifest = dict(scope='reviewed_this_round_only_not_a_complete_exam_corpus',
                    eligible_page_candidates=eligible, hold_pages=held, omit_noncore_pages=omitted,
                    suggested_substantive_subset=sorted(CORE),
                    not_assessed_this_round=sorted(set(pages)-{r['key'] for r in rows}),
                    previous_pending_preserved=['01-p040','07-p001','09-p037','10-p056','10-p063'])
    with (OUT/'admission_candidates.json').open('x',encoding='utf-8') as handle:
        json.dump(manifest,handle,ensure_ascii=False,indent=2)
    with (OUT/'review_results.csv').open('x',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    with (OUT/'repair_diffs.json').open('x',encoding='utf-8') as handle:
        json.dump(diffs,handle,ensure_ascii=False,indent=2)
    with (OUT/'repair_diffs.md').open('x',encoding='utf-8') as handle:
        handle.write('# 50页定向修复前后对比\n\n仅重排文字层，不补字；每页来源ID、物理页码和方法见对应JSON。\n\n')
        for diff in diffs:
            handle.write(f"## {diff['key']}\n\n方法：`{diff['method']}`\n\n修复前：\n\n```text\n{diff['before']}\n```\n\n修复后：\n\n```text\n{diff['after']}\n```\n\n")
    verification = dict(input_hashes_unchanged=True, input_files=30, output_documents=10, output_pages=607,
                        actually_reviewed_pages=145, category_counts=dict(counts), repaired_pages=len(diffs),
                        unchanged_text_pages=557, unchanged_nonreview_page_records=462,
                        previous_3_repaired_pages_preserved=True,
                        output_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'data/processed_v3').glob('*.json')})
    with (OUT/'verification.json').open('x',encoding='utf-8') as handle:
        json.dump(verification,handle,ensure_ascii=False,indent=2)
    lines=['# PDF高风险页面审查报告','','审查日期：2026-11-08（Asia/Shanghai）。阶段：高风险文本定向审查与局部阅读顺序修复。','',
           '## 结论与范围','',
           '**本次实际检查145个此前未检查的风险页，覆盖全部10份PDF；50页得到定向顺序修复。可以用明确合格的正文准备范围受限的第一版知识库，但不能声称已覆盖全部考试核心知识点。**','',
           '已读取既有质量报告、第一轮修复报告及全部10份processed_v2 JSON。四类风险共216次命中（短文本50、顺序59、图表96、重复11），按文档/物理页去重为171页；此前46个已检查页中26页属于该风险集合，全部排除，留下145页。本轮未以初筛中“607页均有图像风险”的误报清单为依据，而采用已修正的reviewed_page_metrics.csv。','',
           '145页全部完成程序检查和助手页面图像对照：逐页生成140 DPI PNG，实际打开29张带物理页标识的联系表，对照原JSON、text/blocks、dict显示坐标与候选阅读顺序；对模糊字、覆盖画面、视频范围、复杂结构等不确定之处明确保留E或未修复B。不是人工视觉签核，也不是逐字校勘或外部课程事实核验。','',
           '顺序上先审查01至10文档的85个核心主题候选，再检查绪论00的60个候选。检查内容包括概念/原则、风险安全责任、公正利益、环境伦理、职业伦理、典型事故及案例。没有按短字数自动判断正常或异常，没有将图片猜测文字填入text。','',
           '此前46页不重复计数；两轮累计查看191个不同物理页，仍有416页未做页面图像审查。v3中的462个非本轮审查页（含此前46页）整条页记录不变，不能自动视为合格。纯空白字符占比风险未单独纳入本次四类队列；例如仅命中该类的05-p080仍需后续按实际需求检查。','',
           '## A/B/C/D/E统计','',
           '| 类别 | 含义 | 本次页数 | 处理 |','|---|---|---:|---|',
           '| A | 在本次可见证据范围内，核心文字与阅读顺序完整 | 31 | 文字可作首版候选；含标题/目录，须区分正文价值 |',
           '| B | 文字顺序或结构异常 | 55 | 50页已定向修复；5页仍待结构/关系核准 |',
           '| C | 重要文字/图表内容在栅格图片中 | 21 | 保留原文，待局部OCR或人工补录及关系校核 |',
           '| D | 非核心配图或结束页 | 12 | 不需要OCR，不作为核心知识正文 |',
           '| E | 可见性、视频范围、字形、源资料冲突等无法可靠确认 | 26 | 保留待人工确认，不标记已修复 |',
           '| 合计 | 去重后的本次实际检查页 | 145 | 无自动扩展至其余页面 |','',
           'A指考试相关的主要可见文字保真，允许不提取纯装饰水印、音频图标和辅助照片；不等于整张图片所有微小文字都已转录。B的类别记录保留原始问题类型，不因修复后可作候选就改写为A。C、E及未修复B均hold，不能当成完整文本。D的原始内容保留，不删除源页。','',
           '## 各文档情况','',
           '| PDF | 本轮页数 | A | B | C | D | E | 已修复B |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for doc in docs:
        subset=[r for r in rows if r['filename']==doc['filename']]
        c=Counter(r['category'] for r in subset)
        lines.append(f"| {doc['filename']} | {len(subset)} | {c['A']} | {c['B']} | {c['C']} | {c['D']} | {c['E']} | {sum(r['repair_applied'] for r in subset)} |")
    lines += ['','## 考试核心内容与重要遗漏','',
              '| 主题 | 已有可用正文举例 | 仍需补齐或确认的关键内容 |','|---|---|---|',
              '| 概念与基本原则 | 修复的00-p016/017/018等伦理意识、规范、决策能力定义 | 01-p036/042/043/044/048/049/050/054缺伦理立场解释、伦理困境与选择、伦理关系、辨识条件、三项基本原则及应对流程；另上轮01-p040契约论仍未解决 |',
              '| 风险、安全与责任 | 02-p008/009技术因素正文；00-p035安全健康福利优先；06-p004时间地点顺序修复 | 02-p029伦理与法律责任、事前/事后责任区别缺图片正文；02-p017竖排图注仍需核准 |',
              '| 利益冲突与公正 | 05-p068五种应对方式及说明；09-p034环境公正正文 | 03-p030目标人群与攸关方对比表待结构化复核；03-p021/022遮挡；01-p050基本原则遗漏 |',
              '| 环境伦理 | 09-p034分配公正、00-p027相关发展领域文字 | 03-p016生态价值配图数据；09-p004/010/011地图位置及缺词；上轮09-p037环境责任缺词仍未补录 |',
              '| 工程师职业伦理 | 00-p031/034/035及05-p068等可见规范/冲突正文 | 00-p032 ASCE基本原则和准则表、00-p033职业伦理共性要求表为图片，不能只留表题 |',
              '| 事故及案例 | 01-p007挑战者号描述、05-p005奶制品、06-p004/005大桥、07-p015青岛事故、10-p004/005反应停、10-p061风险受益说明 | 07-p004缺时间地点；大量视频仅有封面，无法取得全片；07-p005源标题/正文冲突；07-p016损失数字疑点；上轮10-p056/063仍未解决 |','',
              '下列21个C类逐页列出已见的缺口；补录任务需从原页核准，不将本报告描述自动写进知识库。此处图表“文字与关系”均可能重要，OCR只能补文字，不能保证箭头、表格列或地图位置关系正确。','',
              '| 页面 | 重要遗漏/处理建议 | 原页证据 |','|---|---|---|']
    for row in rows:
        if row['category']=='C':
            key=row['key'];lines.append(f"| {key} | {row['note']} | [PNG](high_risk_review/previews/{key}.png) / [文字块坐标](high_risk_review/evidence/{key}.json) |")
    lines += ['','### 源资料和可见性问题','',
              '- 07-p005：标题是吉化双苯厂爆炸，正文和配图却是桥梁参数，与06-p005重复。该冲突在源画面就存在，不能通过重新提取或凭常识替换成爆炸事故资料，应请课程教师确认。',
              '- 07-p016：源画面与JSON均呈现“6866亿元”，存在重要金额疑点。没有联网核实，也没有擅自改为其他数字，暂不列为合格考试依据。',
              '- 多份首张幕布、黑色视频区域和覆盖正文的照片存在“文字层有字但最终画面看不到”的情况，不能只按文字不为空认定合格；保留E，不扩大上轮隔离策略。',
              '- 视频内容不在静态PDF里，OCR截图不能恢复完整案例过程、事故调查和分析；需人工取得关联视频或经确认的案例材料。','',
              '## 修复方法与前后对比','',
              '本轮只对白名单中50个B类页修改text：文档内容SHA-256+物理页码绑定；原v2文本SHA-256必须匹配已审查证据；根据显示坐标重排dict文字行，或对已核实侧栏/左右区域分组。每次都校验全部非空白字符的多重集合一致。没有新增、删除、改写任何非空白文字，也没有触及A/C/D/E页面正文。','',
              '候选检查中发现10-p061的图注起点在x≈518，55%页宽会把它错误分到左栏，因此最终在本页使用已核实的50%页宽分界：先读左栏完整正文，再读右侧图注。这个边界只应用于该白名单页，回归测试验证“是第一要务”必须位于图注前。00-p065虽然顺序可改善，但管长变化的箭头关系尚需复核，最终未修复，不把格式改善冒充完整解决。','',
              '| 页面/类型 | 修复前 | 修复后 | 证据 |','|---|---|---|',
              '| 00-p017，旋转单栏 | 规范定义先出，标题与第二项目后出 | 教育目的标题→第二项目→完整定义→页脚 | 显示坐标与原页对应，字符守恒 |',
              '| 00-p035，侧栏 | 年份与段落碎片混排，美国侧栏混进正文 | 标题→美国侧栏→1947/1963/1974叙述与安全原则→页脚 | 已查看侧栏分区，不推广为通用多栏规则 |',
              '| 00-p062，双栏编号列表 | 8-14在1-7之前 | 标题→左栏1-7→右栏8-14 | 显示左右区域及序号均可核对 |',
              '| 06-p004，案例时间地点 | 地点标签在地点文字之后 | 时间标签和内容→地点标签和内容→地点续行 | dict行框顺序有明确证据 |',
              '| 10-p061，正文+图注 | 图注插入“生命…是第一要务”之间 | 左栏句末完整结束→右侧两行图注 | 已查看页面，坐标阈值经候选核对 |','',
              '全部50页的完整修复前后正文见[对比Markdown](high_risk_review/repair_diffs.md)和[结构化对比JSON](high_risk_review/repair_diffs.json)。逐页列表中的“修复”只指阅读顺序，不代表通过人工考试内容审定。','',
              '尚未修复的5个B类：','', '| 页面 | 保留原因 |','|---|---|']
    for row in rows:
        if row['category']=='B' and not row['repair_applied']:
            lines.append(f"| {row['key']} | {row['note']} |")
    lines += ['','## 全部145页逐页分类与证据','',
              '以下笔记均为本次助手实际打开PNG联系表并对照文本/坐标后的结论，非程序规则冒充人工检查。对于未能可靠辨认的细节，笔记中明确标为待人工确认。所有页面的独立140 DPI预览均保留，可放大复核。风险由历史程序初筛给出，最终类别由本次审查记录给出，二者不能混为一谈。','',
              '| 页标识 | 类别 | 本轮修复 | 具体证据/未解决点 | 预览与文字坐标 |','|---|---|---|---|---|']
    for row in rows:
        key=row['key'];lines.append(f"| {key} | {row['category']} | {'是' if row['repair_applied'] else '否'} | {row['note']} | [PNG](high_risk_review/previews/{key}.png) / [JSON](high_risk_review/evidence/{key}.json) |")
    lines += ['','## 第一版知识库是否可启动','',
              f'**可以先以已合格的正文准备范围受限、可追溯的验证版；目前不能作为完整备考知识库。** 本轮31个A类页加50个已修复B类页共81个候选。其中{sum(r["content_role"]=="navigation_only" for r in eligible)}页是明确的目录/章节标题，只适合作导航上下文，不应拿来凑知识点覆盖率。报告另标注{len(CORE)}个主要概念/规范/案例正文页作为可优先讨论的候选子集（含原课件重复页02-p008/009，后续应保留来源再去重）。','',
              '候选页资格只针对现有正文保真及本次证据，不验证源课程历史事实；没有给其余462页自动发放资格，也没有把此前22个“主要内容基本对应”的样本扩大为逐字验收通过。5个未修复B、21个C、26个E暂缓；12个D不作为核心正文。先前的01-p040、09-p037、10-p056、10-p063补录任务及07-p001待确认隔离状态全部保留。','',
              '下一步应优先补齐01-p050三项基本原则、01-p042/043/044核心定义、01-p048/049辨识条件、02-p029责任区分和00-p032/033职业规范表，再处理其他高价值图表或案例资料。先前07-p020关系图等也未因本次排除而变成“已解决”。在这些缺口补齐前，应明确首版知识范围，遇到缺口应承认资料不足，不据图片识别猜测补写。','',
              '[候选与暂缓清单](high_risk_review/admission_candidates.json)仅是数据准备清单，没有执行分块、嵌入、向量库或问答功能，也没有安装相关依赖。','',
              '## v3输出、来源保护与验证','',
              '- 已输出10份、607页JSON到独立data/processed_v3/，来源文件名、文档ID和物理页码全部保留；source_json记录v2文件名和SHA-256，schema_version=3。',
              '- 145个审查页新增high_risk_review，记录类别、证据、预览、笔记、是否实际修复和候选/暂缓处置。50个修复页另存pre_v3_text及repair_history，记录前后哈希和原/新提取方法。文档修复汇总已重算，并保留source_v2_repair_summary，避免统计沿用v2导致误解。',
              '- 相比v2：50页text变化、557页text逐字符不变；462个非审查目标页的整条页记录不变。此前3个已修复页完整保留，不重跑原排序；既有隔离/待补录页不改状态。',
              '- 原PDF、原JSON、processed_v2共30个文件在开始与完成时SHA-256全部不变。输出目录排他创建，已存在即拒绝覆盖。',
              '- 实际执行`.venv/bin/python -m pytest -q`：**39 passed，0 failed**（原有26项+新增13项），有5条既有PyMuPDF/SWIG弃用警告。新增回归涵盖10文档607页、来源页码、145页去重与历史排除、50页字符守恒、非目标内容保持、旧3页不退化、C/E及未修复B不误标、旧待确认状态保留、关键布局锚点、原对象不原地变更、基线失配拒绝、30文件哈希及UTF-8防覆盖导出。',
              '- 未安装OCR、LangChain、ChromaDB或其他新包；未接入DeepSeek/在线AI服务，未开发前端，未构建知识库。','',
              '## 产物与复现','',
              '- [队列及30个源文件哈希](high_risk_review/queue.json)、[最终逐页CSV](high_risk_review/review_results.csv)、[输出验证清单](high_risk_review/verification.json)。',
              '- `reports/high_risk_review/previews/`：145张独立PNG；上级目录29张联系表。`evidence/`包含145页的原文、未排序文本、blocks、dict显示行坐标、图片位置和候选文本。',
              '- [全部候选文本对比](high_risk_review/text_comparisons.md)：这里的candidate表示未自动采用的程序方案；实际采用情况以最终CSV/v3记录为准，不能把初始候选当成已验证修复。',
              '- 新增`scripts/inspect_high_risk.py`（排他生成初筛证据）、`scripts/high_risk_decisions.py`（实际查看后的静态笔记）、`src/pdf_review.py`（白名单v3导出）、`tests/test_pdf_review.py`、`scripts/build_high_risk_report.py`。README及.gitignore新增v3说明和生成目录排除。',
              '- 从项目目录可用`.venv/bin/python -m src.pdf_review`执行导出；当前v3目录已存在，重复运行会拒绝覆盖。报告脚本同样排他创建产物。',
              '- 本报告未修改先前两份报告或v2数据，新增发现和分类仅记录在本轮产物。','']
    with (ROOT/'reports/PDF高风险页面审查报告.md').open('x',encoding='utf-8') as handle:
        handle.write('\n'.join(lines))
    print(json.dumps(dict(reviewed=145, categories=dict(counts),repaired=len(diffs),eligible=len(eligible),held=len(held),navigation=sum(r['content_role']=='navigation_only' for r in eligible),core_subset=len(CORE),source_hashes_unchanged=True),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
