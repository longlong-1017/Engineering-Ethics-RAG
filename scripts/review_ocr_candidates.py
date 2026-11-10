"""对同5页已保存的OCR做判重和视觉笔记汇总，不再次运行OCR。"""

from collections import Counter
import json
from pathlib import Path

import pymupdf

from src.ocr_trial import ROOT, SELECTION, digest, refine_ledger, spatial_lines, write_json
from src.pdf_repair import display_lines

# 实际查看300DPI原页并逐项对照后的助手笔记，不是人工签核。
OBSERVATIONS = {
    '01-p050': dict(assessment='三项原则识别正确，正文有漏字，需复核后才可补录',
        terms=['人道主义','社会公正','人与自然和谐发展'],
        comparison='三项原则及对应的人与人/工程与社会/工程与自然均与画面对应；原始JSON只有标题。单栏基本按从上到下顺序识别。',
        issues=[dict(source='公众的安全健康和福祉',ocr='公众安全健康和福祉',kind='漏字',note='漏“的”，未按高置信度1判定为逐字正确。')],
        layout='单栏；无表格。三条条目置信度0.3/0.3/0.5仍然识别正确，说明不能简单按置信度阈值筛选。'),
    '01-p042': dict(assessment='主要正文及中英术语对应，装饰页脚误字',
        terms=['伦理困境','电车悖论','Philippa Foot','功利主义'],
        comparison='困境定义、电车五人与一人的情境及哲学家名称均可在原页核对。源页“常常导致的具体情景”等用语也按原样识别，不以常识润色。',
        issues=[dict(source='电子信息工程学院自动化教研室',ocr='电子信息工程学院自动化教研宝',kind='错字',note='单位页脚“室→宝”，不属于考试正文；保留原始OCR并在候选中标记非核心区域。')],
        layout='单栏段落，阅读顺序与画面基本一致；跨行单词与句子尚未做合并编辑，不提供零误差保证。'),
    '02-p029': dict(assessment='缺失段落有恢复，但多处错字漏字，暂不适合直接入库',
        terms=['伦理责任','法律责任','事后责任','事先责任'],
        comparison='事先/事后责任关键词可识别，但正文使用楷体/下划线，识别质量明显下降。已有可靠文字层的引文被OCR误读，不能用OCR替换它。',
        issues=[dict(source='指的是对已发事件的事后追究',ocr='后是对已发事件时事后追究',kind='错字及漏字',note='“指的是”等开头及“的”被误识。'),
                dict(source='的事先决定',ocr='約事先决定',kind='错字',note='简体“的”被误成“約”。'),
                dict(source='伦理学',ocr='伦理字',kind='专业术语错字',note='该行OCR置信度为1，仍有“学→字”。'),
                dict(source='的立法则是一般地指向',ocr='购立法则是一般地捐向',kind='多处错字',note='“的→购”“指→捐”。'),
                dict(source='它把行为的动',ocr='飞把行为时动',kind='多处错字',note='“它”“的”等误识，不能据OCR推导引文。'),
                dict(source='朱葆伟',ocr='朱菜伟',kind='人名错字',note='作者名应对照原PDF及既有文字层，未自动改写候选。'),
                dict(source='校徽图形',ocr='U',kind='非正文额外字符',note='由校徽读出U，标记页边图形噪声；不是课程新术语。')],
        layout='单栏，但OCR拆行、误标点和重复逗号破坏句子；已有引文重复/部分重叠需保留文字层、逐句人工合并。'),
    '00-p032': dict(assessment='大部分表格内容被识别，存在错漏及跨行列关系问题',
        terms=['ASCE','基本原则','基本准则','利益冲突','可持续'],
        comparison='识别出4条基本原则、7条基本准则的大部分文字；表格照片原本分辨率有限，300DPI渲染不能生成原图没有的细节。',
        issues=[dict(source='人类的福祉',ocr='人类钓福祉',kind='错字',note='“的→钓”。'),
                dict(source='以专业的方式',ocr='以专业钓方式',kind='错字',note='“的→钓”。'),
                dict(source='公众的安全',ocr='公众安全',kind='漏字',note='漏“的”。'),
                dict(source='客观、真实的方式',ocr='客观、真实方式',kind='漏字',note='漏“的”。'),
                dict(source='受托人的身份',ocr='受托人身份',kind='漏字',note='漏“的”。'),
                dict(source='专业发展的机会',ocr='专业发展机会',kind='漏字',note='漏“的”。')],
        layout='合并单元格双列表格。引擎先输出左列“层面/基本原则/基本准则”再输出右列正文；简单y/x排序又将“基本原则/基本准则”插在条目中间。两种序列都不能作为已验证表结构，需逐格复核行归属及续行。'),
    '07-p004': dict(assessment='时间地点等缺失信息恢复，需人工与原文合并，不能重复已有结果段落',
        terms=['吉林石化','双苯厂爆炸','2005年11月13日','6908万元','80km'],
        comparison='画面时间2005年11月13日、地点吉林石化公司与OCR一致；8人死、60多人伤、6908万元、约100吨、80km和700多公里与源页/已有文字层对应。只验证提取保真，不外部核实事故事实。',
        issues=[dict(source='校徽图形',ocr='U',kind='非正文额外字符',note='不是事故内容，已标记非核心页边图形。'),
                dict(source='标题连接号',ocr='-———',kind='标点差异',note='标题连字符变化导致简单精确判重不能完全命中，需作为部分重叠行处理。')],
        layout='左侧文字、右侧照片。没有把照片内容猜写成文本；正文顺序基本匹配，结果标签与已有伤亡数据同一OCR行，必须人工合并而非再次追加整段。'),
}


def main():
    out=ROOT/'data/ocr_candidates'
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    assert len(manifest['selection'])==5
    summaries=[]
    for key,topic in SELECTION:
        folder=out/key
        result=json.loads((folder/'candidate_retry.json').read_text(encoding='utf-8'))
        raw=json.loads((folder/'vision_retry_raw.json').read_text(encoding='utf-8'))
        assert result['ocr_status']=='ok'
        with pymupdf.open(ROOT/'data/pdfs'/result['filename']) as doc:
            page=doc[result['page_number']-1]
            scale_x=result['image_width']/page.rect.width
            scale_y=result['image_height']/page.rect.height
            native_boxes=[[l['bbox'][0]*scale_x,l['bbox'][1]*scale_y,l['bbox'][2]*scale_x,l['bbox'][3]*scale_y] for l in display_lines(page)]
        ledger=refine_ledger(spatial_lines(raw['observations']),result['original_text'],native_boxes,result['image_width'],result['image_height'])
        result['deduplication_ledger']=ledger
        result['new_text_candidates']=[l for l in ledger if l['deduplication']=='new_text_candidate']
        result['partial_overlap_candidates']=[l for l in ledger if l['deduplication'] in {'partial_overlap_manual_merge','native_region_overlap_manual_review'}]
        result['assistant_visual_review']=OBSERVATIONS[key]
        result['review_status']='assistant_compared_to_png_pending_human_confirmation'
        result['approved_for_ingestion']=False
        assert result['merged_text'] is None
        write_json(folder/'candidate_reviewed.json',result)
        summary=dict(key=key,topic=topic,page_number=result['page_number'],observations=len(ledger),
                     dedup_counts=dict(Counter(l['deduplication'] for l in ledger)),
                     raw_chars=len(result['ocr_text_engine_order']),existing_chars=len(result['original_text']),
                     elapsed_seconds=raw['elapsed_seconds'],assessment=OBSERVATIONS[key]['assessment'])
        summaries.append(summary)
    for name,expected in manifest['source_hashes'].items():
        assert digest((ROOT/name).read_bytes())==expected
    write_json(out/'review_summary.json',dict(pages=summaries,source_hashes_unchanged=True,approved_pages=0))
    print(json.dumps(summaries,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
