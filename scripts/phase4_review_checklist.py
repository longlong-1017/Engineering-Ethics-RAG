"""从冻结的第三阶段结果生成14题人工核对底稿；不会替人工填写结论。"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.corpus import load_corpus

OUT=ROOT/'reports/phase4_integration'
SOURCE=ROOT/'reports/phase3_acceptance'


def main():
    labels=json.loads((SOURCE/'labels.json').read_text(encoding='utf-8'))['labels']
    pending={x['id']:x for x in labels if x['mode']=='expanded' and x['answer_verdict']=='correct_pending_manual'}
    results=json.loads((SOURCE/'raw_results.json').read_text(encoding='utf-8'))['results']
    pages={(p.filename,p.page_number):p for p in load_corpus().pages}
    questions=[]
    lines=['# 第三阶段14道待复核题：逐题人工核对清单','',
           '本清单是自动整理的人工验收底稿，**没有页面已因生成清单而获得人工确认**。原文取自冻结的processed_v3文字层，可能含错字/错序/遗漏；不是图片转写，也不是已确认标准答案。',
           '', '页码统一为PDF物理页，从1开始；不要用幻灯片印刷页码替代。下载PDF后在阅读器跳转指定物理页，放大至文字清晰，逐项与文字层比对。PDF链接为本地路径，在支持本地链接的Markdown阅读器打开；也可直接用文件名在data/pdfs中查找。',
           '', '每题均需核对：主体/事件是否一致、每项答案是否有原文支持、编号清单是否完整、阅读顺序、数字/单位/范围及图中文字是否漏提取。遇到看不清/证据不足保持待确认，不凭常识补写。核对结果只记录在新验收材料中，本轮不改PDF/JSON或评分标准。',
           '', '|题号|问题|第三阶段来源风险|人工状态|','|---|---|---|---|']
    selected=[x for x in results if x['mode']=='expanded' and x['id'] in pending]
    assert len(selected)==14
    for x in selected:
        risks=sorted({pages[v['filename'],v['page_number']].review_category or '未审核' for v in x['cited_verifications']})
        lines.append(f"|{x['id']}|{x['question']}|{'、'.join(risks)}|待确认|")
    for x in selected:
        source_keys={(v['filename'],v['page_number']) for v in x['gold_pages']} | {(v['filename'],v['page_number']) for v in x['cited_verifications']}
        cited={(v['filename'],v['page_number']) for v in x['cited_verifications']}
        item=dict(id=x['id'],question=x['question'],human_status='pending',reviewer='',review_date='',notes=pending[x['id']]['notes'],sources=[])
        lines += ['',f"## {x['id']}：{x['question']}",'', '- 复核人：________　日期：________',
                  '- 结论：☐ 待确认　☐ 通过　☐ 需修复　☐ 不通过',
                  '- 待核对疑点：'+pending[x['id']]['notes'],
                  '- 核对方法：先独立阅读原PDF并写出要点，再查看以下文字层摘录和第三阶段回答，避免被现有答案引导；按事实逐项核对来源。',
                  '- 签核范围：☐ 来源/物理页　☐ 核心文字　☐ 阅读顺序　☐ 数字单位　☐ 编号/表格/图像　☐ 答案支持',
                  '- 答案要点核对（沿用原题库事实组，不改评分）：']
        for group in x['expected_points']:lines.append('  - ☐ '+ ' / '.join(group))
        if x['id']=='Q28':
            lines.append('- 专项疑点：文字层为“6866亿元以上”。必须先核对PDF可见金额及小数点，再查权威调查资料核实；未经确认不得作为确定事实。请分别记录“课件所写”和“外部核实结果”，不要悄悄改金标。')
        if x['id']=='Q29':lines.append('- 专项疑点：“尽快排除 的故障”存在断词/多余字；确认PDF实际写法，记录其与原词串评分不匹配的原因。')
        for filename,number in sorted(source_keys):
            page=pages[filename,number]
            role='第三阶段实际引用' if (filename,number) in cited else '原题库金标补充页（第三阶段未引用）'
            if page.review_category=='C':method='重点查看图片中的所有重要文字，确认当前文字层是否遗漏考试知识点；看不清则标记需OCR或人工补录，不猜测。'
            elif page.review_category=='E':method='先检查PDF可见性、数字/小数点与单位；文字层不能代替图像确认，无法判定时保持待确认。'
            elif page.review_category=='B':method='按页面视觉阅读顺序逐段对应文字层，重点检查标题/正文、编号与图注是否错位；不能只比较字符集合。'
            else:method='逐段对照PDF可见文字与摘录，特别核对数字、单位、编号和图片漏字；不能只凭文字长度或相关词认定通过。'
            item['sources'].append(dict(filename=filename,page_number=number,role=role,review_category=page.review_category,review_note=page.review_note,text=page.text,method=method))
            link=quote(str(ROOT/'data/pdfs'/filename),safe='/')+f'#page={number}'
            lines += ['',f'### {filename}｜物理第{number}页','',f'- 来源：[{filename}]({link})；{role}。',
                      '- 证据状态：'+page.review_label,'- 既有疑点：'+(page.review_note or '该页尚未完成人工逐段验收，需确认核心内容及顺序。'),
                      '- 本页方法：'+method,'','原文（processed_v3文字层，待与PDF图像核对）：','', '```text',page.text.rstrip(),'```','',
                      '本页人工记录：________________（请标出不一致位置及建议，勿直接改原JSON）']
        lines += ['','第三阶段实际回答（仅供对照，非标准答案）：','','```text',x['answer'],'```']
        questions.append(item)
    OUT.mkdir(exist_ok=True)
    # 防止重复运行覆盖人工填写后的核对结果。
    for name,content in [('人工核对清单.md','\n'.join(lines)+'\n'),('human_review_checklist.json',json.dumps({'source':'phase3_acceptance','question_count':len(questions),'questions':questions},ensure_ascii=False,indent=2)+'\n')]:
        path=OUT/name
        if path.exists():raise SystemExit(f'{name}已存在，避免覆盖人工记录，停止。')
        path.write_text(content,encoding='utf-8')
    print(f'已整理{len(questions)}题，{sum(len(q["sources"]) for q in questions)}个题目来源页次；所有状态均待人工确认。')


if __name__=='__main__':main()
