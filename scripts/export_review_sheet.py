
from pathlib import Path
import csv
import re

ROOT = Path(__file__).resolve().parents[1]

REPORT_DIR = (
    ROOT
    / "reports/retrieval_phase3_20261112_170432"
    / "precision_review_20261112_173449"
)

SOURCE = REPORT_DIR / "人工逐对核对材料.md"
OUTPUT = REPORT_DIR / "人工审核工作表_61对.csv"
QUESTION_OUTPUT = REPORT_DIR / "12题证据充分性审核表.csv"

FIELDS = [
    "候选编号", "题目编号", "问题", "来源类型",
    "证据ID", "章节", "小节", "来源文件",
    "PDF物理页", "印刷页", "原审核状态",
    "证据原文", "人工相关性_0_1_2",
    "人工片段贡献_完整_部分_不足",
    "缺失知识点", "审核备注", "标注者",
]


def extract(pattern, text, default=""):
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else default


def parse_blocks(text):
    # 按 Markdown 标题 ## P01 / Q01 切分
    pattern = r"(?m)^##\s+(P\d+)\s*/\s*(Q\d+)\s*$"
    matches = list(re.finditer(pattern, text))
    records = []

    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end]

        # 只提取 ```text ... ``` 中的证据
        evidence = extract(
            r"```text\s*\n(.*?)\n```",
            block,
        )
        if not evidence:
            evidence_match = re.search(
                r"```text\s*\n(.*?)\n```",
                block,
                re.DOTALL,
            )
            evidence = evidence_match.group(1).strip() if evidence_match else ""

        source = extract(
            r"^\[([^\]]+\.pdf)\]\([^\n]+\)",
            block,
        )

        records.append({
            "候选编号": match.group(1),
            "题目编号": match.group(2),
            "问题": extract(r"^问题：(.+)$", block),
            "来源类型": extract(r"来源类型：([^；\n]+)", block),
            "证据ID": extract(r"证据ID：`([^`]+)`", block),
            "章节": extract(r"章节：([^；\n]+)", block),
            "小节": extract(r"小节：([^。\n]+)", block),
            "来源文件": source,
            "PDF物理页": extract(r"PDF物理第(\d+)页", block),
            "印刷页": extract(r"印刷页=([^；\n]+)", block),
            "原审核状态": extract(r"原审核状态：([^；\n]+)", block),
            "证据原文": evidence,
            "人工相关性_0_1_2": "",
            "人工片段贡献_完整_部分_不足": "",
            "缺失知识点": "",
            "审核备注": "",
            "标注者": "",
        })

    return records


def save_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    text = SOURCE.read_text(encoding="utf-8")
    records = parse_blocks(text)

    if len(records) != 61:
        raise ValueError(
            f"预期61个候选对，实际解析到{len(records)}个，"
            "请检查Markdown标题格式。"
        )

    if any(not row["问题"] or not row["证据ID"] for row in records):
        raise ValueError("存在缺少问题或证据ID的候选记录，请检查解析结果。")

    save_csv(OUTPUT, records, FIELDS)

    questions = {}
    for row in records:
        questions[row["题目编号"]] = row["问题"]

    question_fields = [
        "题目编号", "问题", "人工整体充分性_完整_部分_不足",
        "缺失知识点", "审核备注", "标注者",
    ]

    question_rows = [
        {
            "题目编号": qid,
            "问题": question,
            "人工整体充分性_完整_部分_不足": "",
            "缺失知识点": "",
            "审核备注": "",
            "标注者": "",
        }
        for qid, question in sorted(questions.items())
    ]

    if len(question_rows) != 12:
        raise ValueError(
            f"预期12道题，实际解析到{len(question_rows)}道。"
        )

    save_csv(QUESTION_OUTPUT, question_rows, question_fields)

    print(f"候选记录：{len(records)}")
    print(f"独立题目：{len(question_rows)}")
    print(f"已生成：{OUTPUT}")
    print(f"已生成：{QUESTION_OUTPUT}")
    print("人工标注字段全部留空。")


if __name__ == "__main__":
    main()

