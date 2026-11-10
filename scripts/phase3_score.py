"""沿用第二阶段评分实现，输出到独立第三阶段目录，不改题库/阈值。

先运行 acceptance_eval.py --output reports/phase3_acceptance；逐题复核后维护
该目录 labels.json，再运行本脚本。标签不是模型推理逻辑的输入。
"""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import acceptance_score


def main():
    output=ROOT/'reports/phase3_acceptance'
    source=ROOT/'reports/phase2_acceptance/questions.json'
    target=output/'questions.json'
    if target.exists() and target.read_bytes()!=source.read_bytes():
        raise SystemExit('第三阶段题库与原题库不同，停止评分。')
    if not target.exists():target.write_bytes(source.read_bytes())
    acceptance_score.ROOT=output
    acceptance_score.QUESTIONS=source
    acceptance_score.RAW=output/'raw_results.json'
    acceptance_score.LABELS=output/'labels.json'
    result=acceptance_score.main()
    # 只校正输出标题/复核身份；评分计算与阈值全部沿用原实现。
    for name in ('逐题结果表.md','failure_analysis.md','evidence_risk_register.md','review_packet.md'):
        path=output/name
        if path.exists():
            text=path.read_text(encoding='utf-8')
            text=text.replace('# 第二阶段验收','# 第三阶段复测')
            text=text.replace('`判定` 为人工逐题判读','`判定` 为助手逐题对照文字层复核（非人类教师签核）')
            text=text.replace('| 人工说明 |','| 复核说明 |')
            path.write_text(text,encoding='utf-8')
    return result


if __name__=='__main__':raise SystemExit(main())
