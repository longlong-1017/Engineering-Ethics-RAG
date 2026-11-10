# BGE本地接入验证（2026-11-10）

真实问题没有人工金标，不计算或声称Recall/MRR提升。

索引状态：

```json
{
  "state": "ready",
  "model_id": "bge-small-zh-v1.5:9bbe5f6fa190e30a42a0367a64ca9771035929da8a8beb1417a8f0c88c21bd64",
  "index_path": "/Users/along/Projects/Engineering-Ethics-RAG/data/retrieval_cache/vectors.sqlite3",
  "dimension": 512,
  "blocks": 590,
  "cache_hits": 590,
  "encoded_blocks": 0
}
```

## 某化工企业排放废水虽然满足现行标准，但可能长期影响周边居民健康。工程师应该如何进行伦理判断？

BM25基线也使用相同的查询扩展与覆盖重排；差别仅为是否接入BGE通道。

|通道|名次|真实课件|物理页|排序分类型|排序分|Dense余弦最大值|
|---|---:|---|---:|---|---:|---:|
|BM25扩展+RRF|1|09工程伦理第十讲环境工程伦理(ver1.1) .pdf|28|rrf|0.03230|None|
|BM25扩展+RRF|2|07工程伦理第七讲化学工程伦理(ver1.1) .pdf|43|rrf|0.01640|None|
|BM25扩展+RRF|3|02工程伦理第三讲工程中的风险、责任与安全(ver1.1).pdf|31|rrf|0.01590|None|
|BM25扩展+RRF|4|02工程伦理第三讲工程中的风险、责任与安全(ver1.1).pdf|8|rrf|0.01640|None|
|BM25扩展+RRF|5|09工程伦理第十讲环境工程伦理(ver1.1) .pdf|34|rrf|0.03230|None|
|BM25+BGE+RRF|1|09工程伦理第十讲环境工程伦理(ver1.1) .pdf|28|rrf|0.04870|0.7852575980346262|
|BM25+BGE+RRF|2|07工程伦理第七讲化学工程伦理(ver1.1) .pdf|43|rrf|0.03200|0.593393471607246|
|BM25+BGE+RRF|3|02工程伦理第三讲工程中的风险、责任与安全(ver1.1).pdf|31|rrf|0.03200|0.838413372624808|
|BM25+BGE+RRF|4|02工程伦理第三讲工程中的风险、责任与安全(ver1.1).pdf|8|rrf|0.03280|0.7531091938226947|
|BM25+BGE+RRF|5|09工程伦理第十讲环境工程伦理(ver1.1) .pdf|34|rrf|0.04810|0.7635340907572058|
## 某工程项目能够带来显著经济收益，但可能对当地生态环境造成不可逆损害，应如何进行伦理决策？

BM25基线也使用相同的查询扩展与覆盖重排；差别仅为是否接入BGE通道。

|通道|名次|真实课件|物理页|排序分类型|排序分|Dense余弦最大值|
|---|---:|---|---:|---|---:|---:|
|BM25扩展+RRF|1|09工程伦理第十讲环境工程伦理(ver1.1) .pdf|20|rrf|0.01520|None|
|BM25扩展+RRF|2|09工程伦理第十讲环境工程伦理(ver1.1) .pdf|28|rrf|0.03230|None|
|BM25扩展+RRF|3|02工程伦理第三讲工程中的风险、责任与安全(ver1.1).pdf|8|rrf|0.01640|None|
|BM25扩展+RRF|4|00工程伦理第一讲绪论(ver1.1).pdf|5|rrf|0.01640|None|
|BM25扩展+RRF|5|09工程伦理第十讲环境工程伦理(ver1.1) .pdf|34|rrf|0.03230|None|
|BM25+BGE+RRF|1|09工程伦理第十讲环境工程伦理(ver1.1) .pdf|20|rrf|0.02940|0.6540881160720825|
|BM25+BGE+RRF|2|09工程伦理第十讲环境工程伦理(ver1.1) .pdf|28|rrf|0.04870|0.7852575980346262|
|BM25+BGE+RRF|3|02工程伦理第三讲工程中的风险、责任与安全(ver1.1).pdf|8|rrf|0.03280|0.7531091938226947|
|BM25+BGE+RRF|4|00工程伦理第一讲绪论(ver1.1).pdf|5|rrf|0.01640|None|
|BM25+BGE+RRF|5|09工程伦理第十讲环境工程伦理(ver1.1) .pdf|34|rrf|0.04810|0.7635340907572058|
## 当工程师发现项目存在安全隐患，但管理层要求继续施工时，应如何处理？

BM25基线也使用相同的查询扩展与覆盖重排；差别仅为是否接入BGE通道。

|通道|名次|真实课件|物理页|排序分类型|排序分|Dense余弦最大值|
|---|---:|---|---:|---|---:|---:|
|BM25扩展+RRF|1|09工程伦理第十讲环境工程伦理(ver1.1) .pdf|42|rrf|0.01640|None|
|BM25扩展+RRF|2|02工程伦理第三讲工程中的风险、责任与安全(ver1.1).pdf|31|rrf|0.01590|None|
|BM25扩展+RRF|3|02工程伦理第三讲工程中的风险、责任与安全(ver1.1).pdf|8|rrf|0.01640|None|
|BM25扩展+RRF|4|05工程伦理第六讲工程师的职业伦理(ver1.1).pdf|50|rrf|0.01640|None|
|BM25扩展+RRF|5|05工程伦理第六讲工程师的职业伦理(ver1.1).pdf|40|rrf|0.03020|None|
|BM25+BGE+RRF|1|09工程伦理第十讲环境工程伦理(ver1.1) .pdf|42|rrf|0.01640|None|
|BM25+BGE+RRF|2|02工程伦理第三讲工程中的风险、责任与安全(ver1.1).pdf|31|rrf|0.03200|0.838413372624808|
|BM25+BGE+RRF|3|02工程伦理第三讲工程中的风险、责任与安全(ver1.1).pdf|8|rrf|0.03280|0.7531091938226947|
|BM25+BGE+RRF|4|05工程伦理第六讲工程师的职业伦理(ver1.1).pdf|50|rrf|0.03280|0.8463374529250871|
|BM25+BGE+RRF|5|05工程伦理第六讲工程师的职业伦理(ver1.1).pdf|40|rrf|0.05960|0.7997854126019798|

保护检查：25个原始资料/关键源码文件未变化：True。

二次加载缓存状态：
```json
{
  "state": "ready",
  "model_id": "bge-small-zh-v1.5:9bbe5f6fa190e30a42a0367a64ca9771035929da8a8beb1417a8f0c88c21bd64",
  "index_path": "/Users/along/Projects/Engineering-Ethics-RAG/data/retrieval_cache/vectors.sqlite3",
  "dimension": 512,
  "blocks": 590,
  "cache_hits": 590,
  "encoded_blocks": 0
}
```

索引单元沿用现有页级文本块；非空有文本页参与编码，空白页不编造向量。Dense余弦和RRF分数仅用于召回，不代表审核状态或事实验证。


## 启用状态与原因判定

本次独立离线进程证实BGE可用并真正参与查询；不能由此追溯此前运行中的Streamlit会话。旧界面仅显示BM25数值、加载失败时吞掉异常，且cache_resource可能保留模型下载之前的运行时，因此原界面不足以判断Dense是否启用。此次590条向量已存在且hash匹配，复用了缓存，并补写文件名、页码、正文hash和原文元数据；未声称本轮重新生成全部向量。

现在诊断明确显示active_mode、dense_enabled、vector_index（路径/状态/维度/块数/缓存复用）、bm25_hits、dense_hits、融合候选数及降级原因。Hit.score_type区分bm25_adjusted与rrf；dense_cosine_max仅表示各子查询中最高的BGE余弦值。案例题仍沿用知识点覆盖重排，所以RRF分数与最终名次不必严格递减；Top-5相同也不等于Dense没有参与。

真实课件没有人工金标，本报告不计算Recall@5、Recall@10或MRR，也不宣称混合检索质量提升。排序变化只是定性比较材料。

## 测试与变更

受限Mock回归：220 passed、2 deselected。两项涉及配置/Git检查的测试按安全边界排除。新增覆盖向量元数据持久化、缓存命中、实际Dense参与、分数类型、损坏索引及查询失败降级。真实模型与真实课件另在净化环境、禁网进程验证，没有加载Settings或.env，没有调用生成模型。

修改：src/dense_index.py、src/retriever.py、src/app.py；新增scripts/verify_local_bge.py、tests/test_bge_status.py，更新受限测试入口。没有新增依赖或下载模型；使用用户已下载模型与现有依赖。校验器及阈值、API预算/参数、Tailscale和远程监听设置未修改。原资料和关键源码共25项哈希校验通过。

## 如何使用和回退

停止并重新启动现有Streamlit进程，保持原启动命令/远程访问参数不变，使cache_resource不再保留旧运行时。提问后展开“检索诊断”：确认active_mode为bm25+bge+rrf、dense_enabled为true、vector_index.state为ready且dense_hits大于0。分数卡片显示RRF排序分和BGE余弦，两者不混称。

本地独立复验：`.venv/bin/python scripts/verify_local_bge.py`。Mock回归：`.venv/bin/python tests/run_api_diagnostics.py`。两者都禁止真实HTTP，不会自动下载模型。

纯BM25扩展回退：构造`Retriever(corpus,dense_index=None)`；旧检索方式可用`Retriever(corpus,retrieval_mode="legacy")`。模型缺失、加载/索引损坏或Dense查询异常时会自动回退BM25，失败类型或原因显示在诊断中，不需要修改预算或凭据。缺失索引可在本地重建；损坏索引本轮选择显式降级，不自动删除用户缓存。

限制：索引沿用原页级文本单元，长页仍受BGE最大输入长度限制；相似度不能代替事实校验或来源审核。当前运行中的网页是否持有旧缓存，需要重启后从新诊断核对，本轮未访问真实网页配置。
