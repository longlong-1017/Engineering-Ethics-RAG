# PDF高风险页面审查报告

审查日期：2026-11-08（Asia/Shanghai）。阶段：高风险文本定向审查与局部阅读顺序修复。

## 结论与范围

**本次实际检查145个此前未检查的风险页，覆盖全部10份PDF；50页得到定向顺序修复。可以用明确合格的正文准备范围受限的第一版知识库，但不能声称已覆盖全部考试核心知识点。**

已读取既有质量报告、第一轮修复报告及全部10份processed_v2 JSON。四类风险共216次命中（短文本50、顺序59、图表96、重复11），按文档/物理页去重为171页；此前46个已检查页中26页属于该风险集合，全部排除，留下145页。本轮未以初筛中“607页均有图像风险”的误报清单为依据，而采用已修正的reviewed_page_metrics.csv。

145页全部完成程序检查和助手页面图像对照：逐页生成140 DPI PNG，实际打开29张带物理页标识的联系表，对照原JSON、text/blocks、dict显示坐标与候选阅读顺序；对模糊字、覆盖画面、视频范围、复杂结构等不确定之处明确保留E或未修复B。不是人工视觉签核，也不是逐字校勘或外部课程事实核验。

顺序上先审查01至10文档的85个核心主题候选，再检查绪论00的60个候选。检查内容包括概念/原则、风险安全责任、公正利益、环境伦理、职业伦理、典型事故及案例。没有按短字数自动判断正常或异常，没有将图片猜测文字填入text。

此前46页不重复计数；两轮累计查看191个不同物理页，仍有416页未做页面图像审查。v3中的462个非本轮审查页（含此前46页）整条页记录不变，不能自动视为合格。纯空白字符占比风险未单独纳入本次四类队列；例如仅命中该类的05-p080仍需后续按实际需求检查。

## A/B/C/D/E统计

| 类别 | 含义 | 本次页数 | 处理 |
|---|---|---:|---|
| A | 在本次可见证据范围内，核心文字与阅读顺序完整 | 31 | 文字可作首版候选；含标题/目录，须区分正文价值 |
| B | 文字顺序或结构异常 | 55 | 50页已定向修复；5页仍待结构/关系核准 |
| C | 重要文字/图表内容在栅格图片中 | 21 | 保留原文，待局部OCR或人工补录及关系校核 |
| D | 非核心配图或结束页 | 12 | 不需要OCR，不作为核心知识正文 |
| E | 可见性、视频范围、字形、源资料冲突等无法可靠确认 | 26 | 保留待人工确认，不标记已修复 |
| 合计 | 去重后的本次实际检查页 | 145 | 无自动扩展至其余页面 |

A指考试相关的主要可见文字保真，允许不提取纯装饰水印、音频图标和辅助照片；不等于整张图片所有微小文字都已转录。B的类别记录保留原始问题类型，不因修复后可作候选就改写为A。C、E及未修复B均hold，不能当成完整文本。D的原始内容保留，不删除源页。

## 各文档情况

| PDF | 本轮页数 | A | B | C | D | E | 已修复B |
|---|---:|---:|---:|---:|---:|---:|---:|
| 00工程伦理第一讲绪论(ver1.1).pdf | 60 | 1 | 51 | 3 | 2 | 3 | 48 |
| 01工程伦理第二讲工程伦理概念(ver1.1).pdf | 16 | 3 | 0 | 9 | 2 | 2 | 0 |
| 02工程伦理第三讲工程中的风险、责任与安全(ver1.1).pdf | 10 | 4 | 1 | 1 | 1 | 3 | 0 |
| 03工程伦理第四讲工程中的价值、利益与公正(ver1.1).pdf | 13 | 2 | 1 | 2 | 1 | 7 | 0 |
| 04工程伦理第五讲工程活动中的环境伦理(ver1.1).pdf | 2 | 1 | 0 | 0 | 1 | 0 | 0 |
| 05工程伦理第六讲工程师的职业伦理(ver1.1).pdf | 11 | 8 | 0 | 0 | 1 | 2 | 0 |
| 06工程伦理第七讲土木工程伦理(ver1.1) .pdf | 8 | 4 | 1 | 0 | 1 | 2 | 1 |
| 07工程伦理第七讲化学工程伦理(ver1.1) .pdf | 8 | 2 | 0 | 2 | 1 | 3 | 0 |
| 09工程伦理第十讲环境工程伦理(ver1.1) .pdf | 9 | 3 | 0 | 3 | 1 | 2 | 0 |
| 10工程伦理生物医药第十讲工程伦理(ver1.1) .pdf | 8 | 3 | 1 | 1 | 1 | 2 | 1 |

## 考试核心内容与重要遗漏

| 主题 | 已有可用正文举例 | 仍需补齐或确认的关键内容 |
|---|---|---|
| 概念与基本原则 | 修复的00-p016/017/018等伦理意识、规范、决策能力定义 | 01-p036/042/043/044/048/049/050/054缺伦理立场解释、伦理困境与选择、伦理关系、辨识条件、三项基本原则及应对流程；另上轮01-p040契约论仍未解决 |
| 风险、安全与责任 | 02-p008/009技术因素正文；00-p035安全健康福利优先；06-p004时间地点顺序修复 | 02-p029伦理与法律责任、事前/事后责任区别缺图片正文；02-p017竖排图注仍需核准 |
| 利益冲突与公正 | 05-p068五种应对方式及说明；09-p034环境公正正文 | 03-p030目标人群与攸关方对比表待结构化复核；03-p021/022遮挡；01-p050基本原则遗漏 |
| 环境伦理 | 09-p034分配公正、00-p027相关发展领域文字 | 03-p016生态价值配图数据；09-p004/010/011地图位置及缺词；上轮09-p037环境责任缺词仍未补录 |
| 工程师职业伦理 | 00-p031/034/035及05-p068等可见规范/冲突正文 | 00-p032 ASCE基本原则和准则表、00-p033职业伦理共性要求表为图片，不能只留表题 |
| 事故及案例 | 01-p007挑战者号描述、05-p005奶制品、06-p004/005大桥、07-p015青岛事故、10-p004/005反应停、10-p061风险受益说明 | 07-p004缺时间地点；大量视频仅有封面，无法取得全片；07-p005源标题/正文冲突；07-p016损失数字疑点；上轮10-p056/063仍未解决 |

下列21个C类逐页列出已见的缺口；补录任务需从原页核准，不将本报告描述自动写进知识库。此处图表“文字与关系”均可能重要，OCR只能补文字，不能保证箭头、表格列或地图位置关系正确。

| 页面 | 重要遗漏/处理建议 | 原页证据 |
|---|---|---|
| 01-p036 | 不同伦理立场页的解释段落为图片，JSON仅留四种立场名称，缺伦理规范应用与立场形成说明。 | [PNG](high_risk_review/previews/01-p036.png) / [文字块坐标](high_risk_review/evidence/01-p036.json) |
| 01-p042 | 伦理困境定义及电车难题正文均在图片，JSON仅有标题，属于考试核心遗漏。 | [PNG](high_risk_review/previews/01-p042.png) / [文字块坐标](high_risk_review/evidence/01-p042.json) |
| 01-p043 | 伦理选择正文含个人美德、规则反思和实践说明，JSON只剩标题。 | [PNG](high_risk_review/previews/01-p043.png) / [文字块坐标](high_risk_review/evidence/01-p043.json) |
| 01-p044 | 自主与责任、效率与公正、个人与集体、环境与社会四类伦理关系正文未提取。 | [PNG](high_risk_review/previews/01-p044.png) / [文字块坐标](high_risk_review/evidence/01-p044.json) |
| 01-p046 | 历史性、社会性、复杂性的概述和历史性说明遗漏；后两条虽存在，不代表整页完整。 | [PNG](high_risk_review/previews/01-p046.png) / [文字块坐标](high_risk_review/evidence/01-p046.json) |
| 01-p048 | 工程伦理问题辨识中何者面临问题、实践主体和时代局限性正文未提取。 | [PNG](high_risk_review/previews/01-p048.png) / [文字块坐标](high_risk_review/evidence/01-p048.json) |
| 01-p049 | 何时出现伦理问题的三条辨识条件正文未提取。 | [PNG](high_risk_review/previews/01-p049.png) / [文字块坐标](high_risk_review/evidence/01-p049.json) |
| 01-p050 | 公众安全健康福利优先及人道主义、社会公正、人与自然和谐三项基本原则正文未提取。 | [PNG](high_risk_review/previews/01-p050.png) / [文字块坐标](high_risk_review/evidence/01-p050.json) |
| 01-p054 | 应对工程伦理问题的流程图仅标题可提取，节点和箭头关系需补录及结构复核。 | [PNG](high_risk_review/previews/01-p054.png) / [文字块坐标](high_risk_review/evidence/01-p054.json) |
| 02-p029 | 伦理责任与法律责任、事前/事后责任对比段落是图片，原JSON缺核心定义与区分。 | [PNG](high_risk_review/previews/02-p029.png) / [文字块坐标](high_risk_review/evidence/02-p029.json) |
| 03-p013 | 政治价值正文在文字层，但右侧网页引文图片不可提取，整页补充论据未完整保留。 | [PNG](high_risk_review/previews/03-p013.png) / [文字块坐标](high_risk_review/evidence/03-p013.json) |
| 03-p016 | 生态价值正文存在，右侧防护林图表包含额外数据与说明，JSON未包含，不能声明整页完整。 | [PNG](high_risk_review/previews/03-p016.png) / [文字块坐标](high_risk_review/evidence/03-p016.json) |
| 07-p004 | 爆炸案例时间、地点及结果标签以图片出现，JSON缺少时间地点，事故信息不完整。 | [PNG](high_risk_review/previews/07-p004.png) / [文字块坐标](high_risk_review/evidence/07-p004.json) |
| 07-p024 | 事故起数/死亡人数年度柱图的年份、轴标和数据不在JSON，不能只留趋势一句就称完整。 | [PNG](high_risk_review/previews/07-p024.png) / [文字块坐标](high_risk_review/evidence/07-p024.json) |
| 09-p004 | 项目简介正文存在，但地图内周边学校/生活区等风险位置标注未提取，案例空间影响信息不完整。 | [PNG](high_risk_review/previews/09-p004.png) / [文字块坐标](high_risk_review/evidence/09-p004.json) |
| 09-p010 | 环评结论开头的海沧南部等文字缺失，右侧规划地图含额外图文信息，需要补录核对。 | [PNG](high_risk_review/previews/09-p010.png) / [文字块坐标](high_risk_review/evidence/09-p010.json) |
| 09-p011 | 污染披露段落存在，覆盖标题的地图包含生活区及污染源位置文字，未保留图文关系；兼有遮挡需人工确认。 | [PNG](high_risk_review/previews/09-p011.png) / [文字块坐标](high_risk_review/evidence/09-p011.json) |
| 10-p069 | 企业社会责任正文存在，但右侧假药案例新闻与反思文章含新增论据文字，尚未提取。 | [PNG](high_risk_review/previews/10-p069.png) / [文字块坐标](high_risk_review/evidence/10-p069.json) |
| 00-p032 | ASCE基本原则及基本准则整张表为图片，JSON只有页眉等，公众安全优先等核心条目未提取。 | [PNG](high_risk_review/previews/00-p032.png) / [文字块坐标](high_risk_review/evidence/00-p032.json) |
| 00-p033 | 工程师职业伦理共性要求表为图片，公众利益、胜任、正直等条目不在JSON。 | [PNG](high_risk_review/previews/00-p033.png) / [文字块坐标](high_risk_review/evidence/00-p033.json) |
| 00-p040 | 会议新闻主体段落是图片，原JSON只保留标题页脚等；背景性内容低优先级，不必为覆盖率立即OCR。 | [PNG](high_risk_review/previews/00-p040.png) / [文字块坐标](high_risk_review/evidence/00-p040.json) |

### 源资料和可见性问题

- 07-p005：标题是吉化双苯厂爆炸，正文和配图却是桥梁参数，与06-p005重复。该冲突在源画面就存在，不能通过重新提取或凭常识替换成爆炸事故资料，应请课程教师确认。
- 07-p016：源画面与JSON均呈现“6866亿元”，存在重要金额疑点。没有联网核实，也没有擅自改为其他数字，暂不列为合格考试依据。
- 多份首张幕布、黑色视频区域和覆盖正文的照片存在“文字层有字但最终画面看不到”的情况，不能只按文字不为空认定合格；保留E，不扩大上轮隔离策略。
- 视频内容不在静态PDF里，OCR截图不能恢复完整案例过程、事故调查和分析；需人工取得关联视频或经确认的案例材料。

## 修复方法与前后对比

本轮只对白名单中50个B类页修改text：文档内容SHA-256+物理页码绑定；原v2文本SHA-256必须匹配已审查证据；根据显示坐标重排dict文字行，或对已核实侧栏/左右区域分组。每次都校验全部非空白字符的多重集合一致。没有新增、删除、改写任何非空白文字，也没有触及A/C/D/E页面正文。

候选检查中发现10-p061的图注起点在x≈518，55%页宽会把它错误分到左栏，因此最终在本页使用已核实的50%页宽分界：先读左栏完整正文，再读右侧图注。这个边界只应用于该白名单页，回归测试验证“是第一要务”必须位于图注前。00-p065虽然顺序可改善，但管长变化的箭头关系尚需复核，最终未修复，不把格式改善冒充完整解决。

| 页面/类型 | 修复前 | 修复后 | 证据 |
|---|---|---|
| 00-p017，旋转单栏 | 规范定义先出，标题与第二项目后出 | 教育目的标题→第二项目→完整定义→页脚 | 显示坐标与原页对应，字符守恒 |
| 00-p035，侧栏 | 年份与段落碎片混排，美国侧栏混进正文 | 标题→美国侧栏→1947/1963/1974叙述与安全原则→页脚 | 已查看侧栏分区，不推广为通用多栏规则 |
| 00-p062，双栏编号列表 | 8-14在1-7之前 | 标题→左栏1-7→右栏8-14 | 显示左右区域及序号均可核对 |
| 06-p004，案例时间地点 | 地点标签在地点文字之后 | 时间标签和内容→地点标签和内容→地点续行 | dict行框顺序有明确证据 |
| 10-p061，正文+图注 | 图注插入“生命…是第一要务”之间 | 左栏句末完整结束→右侧两行图注 | 已查看页面，坐标阈值经候选核对 |

全部50页的完整修复前后正文见[对比Markdown](high_risk_review/repair_diffs.md)和[结构化对比JSON](high_risk_review/repair_diffs.json)。逐页列表中的“修复”只指阅读顺序，不代表通过人工考试内容审定。

尚未修复的5个B类：

| 页面 | 保留原因 |
|---|---|
| 02-p017 | 正文可提取，但三条竖排配图标签被交错输出，需要分列重排；复杂标签暂待人工核准，不应用通用y排序。 |
| 03-p030 | 目标人群/攸关方对比表文字存在，纯文本粘连使行列含义有歧义；暂不自动重构表格，需结构复核。 |
| 00-p011 | 微观目标/人生目标与四种伦理能力的连线图语义不宜用单纯行排序恢复；保留B待结构核准，不自动修复。 |
| 00-p050 | 放射状目录的节点被串排，无法用普通y/x顺序表达章节次序，待结构核准，未自动修复。 |
| 00-p065 | 刹车案例有阅读顺序问题，但管长变化的矢量箭头不在文字层；需同时复核关系表达，暂不自动修复或标记合格。 |

## 全部145页逐页分类与证据

以下笔记均为本次助手实际打开PNG联系表并对照文本/坐标后的结论，非程序规则冒充人工检查。对于未能可靠辨认的细节，笔记中明确标为待人工确认。所有页面的独立140 DPI预览均保留，可放大复核。风险由历史程序初筛给出，最终类别由本次审查记录给出，二者不能混为一谈。

| 页标识 | 类别 | 本轮修复 | 具体证据/未解决点 | 预览与文字坐标 |
|---|---|---|---|---|
| 01-p001 | E | 否 | 幕布遮住原JSON标题/日期，存在可见性不一致；保留待人工确认，不擅自扩大隔离规则。 | [PNG](high_risk_review/previews/01-p001.png) / [JSON](high_risk_review/evidence/01-p001.json) |
| 01-p007 | A | 否 | 挑战者号事故时间、地点、7名宇航员及事件描述与文字对应；右侧人物与发射照片为辅助配图。 | [PNG](high_risk_review/previews/01-p007.png) / [JSON](high_risk_review/evidence/01-p007.json) |
| 01-p008 | D | 否 | 人物合影及案例标题，未见需补录的核心正文；照片无需OCR。 | [PNG](high_risk_review/previews/01-p008.png) / [JSON](high_risk_review/evidence/01-p008.json) |
| 01-p011 | A | 否 | 工程、伦理章节过渡标题与文本对应，短文本属正常标题。 | [PNG](high_risk_review/previews/01-p011.png) / [JSON](high_risk_review/evidence/01-p011.json) |
| 01-p036 | C | 否 | 不同伦理立场页的解释段落为图片，JSON仅留四种立场名称，缺伦理规范应用与立场形成说明。 | [PNG](high_risk_review/previews/01-p036.png) / [JSON](high_risk_review/evidence/01-p036.json) |
| 01-p042 | C | 否 | 伦理困境定义及电车难题正文均在图片，JSON仅有标题，属于考试核心遗漏。 | [PNG](high_risk_review/previews/01-p042.png) / [JSON](high_risk_review/evidence/01-p042.json) |
| 01-p043 | C | 否 | 伦理选择正文含个人美德、规则反思和实践说明，JSON只剩标题。 | [PNG](high_risk_review/previews/01-p043.png) / [JSON](high_risk_review/evidence/01-p043.json) |
| 01-p044 | C | 否 | 自主与责任、效率与公正、个人与集体、环境与社会四类伦理关系正文未提取。 | [PNG](high_risk_review/previews/01-p044.png) / [JSON](high_risk_review/evidence/01-p044.json) |
| 01-p046 | C | 否 | 历史性、社会性、复杂性的概述和历史性说明遗漏；后两条虽存在，不代表整页完整。 | [PNG](high_risk_review/previews/01-p046.png) / [JSON](high_risk_review/evidence/01-p046.json) |
| 01-p048 | C | 否 | 工程伦理问题辨识中何者面临问题、实践主体和时代局限性正文未提取。 | [PNG](high_risk_review/previews/01-p048.png) / [JSON](high_risk_review/evidence/01-p048.json) |
| 01-p049 | C | 否 | 何时出现伦理问题的三条辨识条件正文未提取。 | [PNG](high_risk_review/previews/01-p049.png) / [JSON](high_risk_review/evidence/01-p049.json) |
| 01-p050 | C | 否 | 公众安全健康福利优先及人道主义、社会公正、人与自然和谐三项基本原则正文未提取。 | [PNG](high_risk_review/previews/01-p050.png) / [JSON](high_risk_review/evidence/01-p050.json) |
| 01-p054 | C | 否 | 应对工程伦理问题的流程图仅标题可提取，节点和箭头关系需补录及结构复核。 | [PNG](high_risk_review/previews/01-p054.png) / [JSON](high_risk_review/evidence/01-p054.json) |
| 01-p057 | A | 否 | 案例分析章节标题，未见额外正文，短文本正常。 | [PNG](high_risk_review/previews/01-p057.png) / [JSON](high_risk_review/evidence/01-p057.json) |
| 01-p058 | E | 否 | 页面为黑色视频区域，JSON的案例标题未见于当前画面；视频实际内容待人工提供或确认。 | [PNG](high_risk_review/previews/01-p058.png) / [JSON](high_risk_review/evidence/01-p058.json) |
| 01-p071 | D | 否 | 结束页五条通用学习目标，与其他文档重复，非独立核心知识正文，无需OCR。 | [PNG](high_risk_review/previews/01-p071.png) / [JSON](high_risk_review/evidence/01-p071.json) |
| 02-p001 | E | 否 | 幕布与原提取标题/日期可见性不一致，待人工确认。 | [PNG](high_risk_review/previews/02-p001.png) / [JSON](high_risk_review/evidence/02-p001.json) |
| 02-p002 | A | 否 | 风险责任安全目录2.1至2.5完整对应；蓝色箭头为装饰。 | [PNG](high_risk_review/previews/02-p002.png) / [JSON](high_risk_review/evidence/02-p002.json) |
| 02-p003 | E | 否 | 视频截图遮挡案例标题；视频过程不能从静态页确认，不能据标题当成完整事故案例。 | [PNG](high_risk_review/previews/02-p003.png) / [JSON](high_risk_review/evidence/02-p003.json) |
| 02-p008 | A | 否 | 风险技术因素三条完整对应，与下一物理页相同内容属于原课件重复，保留来源不自动删页。 | [PNG](high_risk_review/previews/02-p008.png) / [JSON](high_risk_review/evidence/02-p008.json) |
| 02-p009 | A | 否 | 风险技术因素三条与前页在源画面也重复，不是JSON串页；可后续按来源去重。 | [PNG](high_risk_review/previews/02-p009.png) / [JSON](high_risk_review/evidence/02-p009.json) |
| 02-p017 | B | 否 | 正文可提取，但三条竖排配图标签被交错输出，需要分列重排；复杂标签暂待人工核准，不应用通用y排序。 | [PNG](high_risk_review/previews/02-p017.png) / [JSON](high_risk_review/evidence/02-p017.json) |
| 02-p029 | C | 否 | 伦理责任与法律责任、事前/事后责任对比段落是图片，原JSON缺核心定义与区分。 | [PNG](high_risk_review/previews/02-p029.png) / [JSON](high_risk_review/evidence/02-p029.json) |
| 02-p037 | A | 否 | 案例分析章节标题完整，对应短文本页。 | [PNG](high_risk_review/previews/02-p037.png) / [JSON](high_risk_review/evidence/02-p037.json) |
| 02-p038 | E | 否 | 调查报告视频截图，不含完整事故过程，JSON的视频标题与当前画面不一致；需关联视频，OCR不能恢复全片。 | [PNG](high_risk_review/previews/02-p038.png) / [JSON](high_risk_review/evidence/02-p038.json) |
| 02-p041 | D | 否 | 与其他文档相同的结语学习目标页，无需OCR。 | [PNG](high_risk_review/previews/02-p041.png) / [JSON](high_risk_review/evidence/02-p041.json) |
| 03-p001 | E | 否 | 幕布遮挡标题/日期，待人工确认可见性。 | [PNG](high_risk_review/previews/03-p001.png) / [JSON](high_risk_review/evidence/03-p001.json) |
| 03-p002 | A | 否 | 价值利益公正目录3.1至3.6与提取文本对应；星形装饰无需OCR。 | [PNG](high_risk_review/previews/03-p002.png) / [JSON](high_risk_review/evidence/03-p002.json) |
| 03-p003 | E | 否 | 南水北调视频封面遮挡原标题，无法从封面取得案例过程，需人工核实视频范围。 | [PNG](high_risk_review/previews/03-p003.png) / [JSON](high_risk_review/evidence/03-p003.json) |
| 03-p013 | C | 否 | 政治价值正文在文字层，但右侧网页引文图片不可提取，整页补充论据未完整保留。 | [PNG](high_risk_review/previews/03-p013.png) / [JSON](high_risk_review/evidence/03-p013.json) |
| 03-p016 | C | 否 | 生态价值正文存在，右侧防护林图表包含额外数据与说明，JSON未包含，不能声明整页完整。 | [PNG](high_risk_review/previews/03-p016.png) / [JSON](high_risk_review/evidence/03-p016.json) |
| 03-p017 | A | 否 | 工程价值综合性段落完整；下方建筑照片为示例配图，无新增重要文字。 | [PNG](high_risk_review/previews/03-p017.png) / [JSON](high_risk_review/evidence/03-p017.json) |
| 03-p021 | E | 否 | 示威照片覆盖大部分原JSON案例说明，不能将遮挡文字当作最终可见正文；需人工确认。 | [PNG](high_risk_review/previews/03-p021.png) / [JSON](high_risk_review/evidence/03-p021.json) |
| 03-p022 | E | 否 | 整页案例照片遮住原正文和标题，照片内标语是否纳入需人工取舍。 | [PNG](high_risk_review/previews/03-p022.png) / [JSON](high_risk_review/evidence/03-p022.json) |
| 03-p023 | E | 否 | 主要段落存在，但截图文字与JSON的个别字疑点无法在联系表可靠定论，需逐字人工复核。 | [PNG](high_risk_review/previews/03-p023.png) / [JSON](high_risk_review/evidence/03-p023.json) |
| 03-p030 | B | 否 | 目标人群/攸关方对比表文字存在，纯文本粘连使行列含义有歧义；暂不自动重构表格，需结构复核。 | [PNG](high_risk_review/previews/03-p030.png) / [JSON](high_risk_review/evidence/03-p030.json) |
| 03-p046 | E | 否 | 南水北调视频封面，不能据封面确认移民利益案例正文完整。 | [PNG](high_risk_review/previews/03-p046.png) / [JSON](high_risk_review/evidence/03-p046.json) |
| 03-p047 | E | 否 | 怒江水电视频封面含双语文字，但实际视频内容未取得，待人工确认，不能用OCR代替视频。 | [PNG](high_risk_review/previews/03-p047.png) / [JSON](high_risk_review/evidence/03-p047.json) |
| 03-p048 | D | 否 | 结束学习目标页，跨文档重复，无需OCR。 | [PNG](high_risk_review/previews/03-p048.png) / [JSON](high_risk_review/evidence/03-p048.json) |
| 04-p003 | A | 否 | 环境伦理观念确立章节标题，短文本与画面一致。 | [PNG](high_risk_review/previews/04-p003.png) / [JSON](high_risk_review/evidence/04-p003.json) |
| 04-p032 | D | 否 | 通用结语页，重复内容不当成新正文，无需OCR。 | [PNG](high_risk_review/previews/04-p032.png) / [JSON](high_risk_review/evidence/04-p032.json) |
| 05-p001 | A | 否 | 工程师职业伦理章节标题对应，短文本正常。 | [PNG](high_risk_review/previews/05-p001.png) / [JSON](high_risk_review/evidence/05-p001.json) |
| 05-p002 | A | 否 | 职业伦理5.1至5.5目录文字对应；星形/音频图标不是正文。 | [PNG](high_risk_review/previews/05-p002.png) / [JSON](high_risk_review/evidence/05-p002.json) |
| 05-p003 | A | 否 | 2008奶制品事件章节标题完整，不是正文漏提取。 | [PNG](high_risk_review/previews/05-p003.png) / [JSON](high_risk_review/evidence/05-p003.json) |
| 05-p004 | E | 否 | 新闻视频静态画面，无法核验全片内容，原视频标签未在最终画面显示。 | [PNG](high_risk_review/previews/05-p004.png) / [JSON](high_risk_review/evidence/05-p004.json) |
| 05-p005 | A | 否 | 奶制品事件召回日期、污染物及健康影响主要正文完整；右侧照片不承担新增核心说明。 | [PNG](high_risk_review/previews/05-p005.png) / [JSON](high_risk_review/evidence/05-p005.json) |
| 05-p021 | A | 否 | 工程职业伦理章节标题与文本对应。 | [PNG](high_risk_review/previews/05-p021.png) / [JSON](high_risk_review/evidence/05-p021.json) |
| 05-p049 | A | 否 | 工程师职业伦理规范两行标题完整。 | [PNG](high_risk_review/previews/05-p049.png) / [JSON](high_risk_review/evidence/05-p049.json) |
| 05-p068 | A | 否 | 利益冲突五种方式及拒绝、放弃、披露区别整段对应，风险来自下划线等矢量装饰。 | [PNG](high_risk_review/previews/05-p068.png) / [JSON](high_risk_review/evidence/05-p068.json) |
| 05-p077 | A | 否 | 案例分析标题页，没有额外正文，短文本正常。 | [PNG](high_risk_review/previews/05-p077.png) / [JSON](high_risk_review/evidence/05-p077.json) |
| 05-p078 | E | 否 | 事件处理结果视频截图，字幕过小且完整视频未取得，待人工确认，不转录猜测字幕。 | [PNG](high_risk_review/previews/05-p078.png) / [JSON](high_risk_review/evidence/05-p078.json) |
| 05-p081 | D | 否 | 通用结语目标页，与其他文档相同，无需OCR。 | [PNG](high_risk_review/previews/05-p081.png) / [JSON](high_risk_review/evidence/05-p081.json) |
| 06-p001 | E | 否 | 幕布遮挡原JSON标题/日期，待人工确认。 | [PNG](high_risk_review/previews/06-p001.png) / [JSON](high_risk_review/evidence/06-p001.json) |
| 06-p002 | A | 否 | 土木工程伦理目录各条完整；箭头为装饰。 | [PNG](high_risk_review/previews/06-p002.png) / [JSON](high_risk_review/evidence/06-p002.json) |
| 06-p003 | E | 否 | 黑色视频区域遮住标题，事故视频内容需人工取得或核验。 | [PNG](high_risk_review/previews/06-p003.png) / [JSON](high_risk_review/evidence/06-p003.json) |
| 06-p004 | B | 是 | 时间和地点均存在，但地点标签跑到地点内容之后；显示坐标dict能恢复标签先行。 | [PNG](high_risk_review/previews/06-p004.png) / [JSON](high_risk_review/evidence/06-p004.json) |
| 06-p005 | A | 否 | 大桥长度、宽度、跨度和结构数据与正文对应；桥示意照片不需要OCR。 | [PNG](high_risk_review/previews/06-p005.png) / [JSON](high_risk_review/evidence/06-p005.json) |
| 06-p019 | A | 否 | 土木工程类型与特点章节标题完整。 | [PNG](high_risk_review/previews/06-p019.png) / [JSON](high_risk_review/evidence/06-p019.json) |
| 06-p060 | A | 否 | 重庆綦江彩虹桥事故章节标题完整；不代表后续事故过程已覆盖。 | [PNG](high_risk_review/previews/06-p060.png) / [JSON](high_risk_review/evidence/06-p060.json) |
| 06-p079 | D | 否 | 结语五条通用学习目标，无需OCR。 | [PNG](high_risk_review/previews/06-p079.png) / [JSON](high_risk_review/evidence/06-p079.json) |
| 07-p003 | E | 否 | 黑色视频区域，无法确认引导案例视频的实际内容。 | [PNG](high_risk_review/previews/07-p003.png) / [JSON](high_risk_review/evidence/07-p003.json) |
| 07-p004 | C | 否 | 爆炸案例时间、地点及结果标签以图片出现，JSON缺少时间地点，事故信息不完整。 | [PNG](high_risk_review/previews/07-p004.png) / [JSON](high_risk_review/evidence/07-p004.json) |
| 07-p005 | E | 否 | 源页面标题为吉化爆炸，正文及图片却是桥梁参数，与06-p005相同；属于原课件内容冲突，需教师确认，不能用提取修复改写。 | [PNG](high_risk_review/previews/07-p005.png) / [JSON](high_risk_review/evidence/07-p005.json) |
| 07-p009 | A | 否 | 化工工程伦理问题章节标题两行完整。 | [PNG](high_risk_review/previews/07-p009.png) / [JSON](high_risk_review/evidence/07-p009.json) |
| 07-p015 | A | 否 | 青岛输油管道事故名称、伤亡及损失文字与画面对应，照片为辅助；未验证源文事实。 | [PNG](high_risk_review/previews/07-p015.png) / [JSON](high_risk_review/evidence/07-p015.json) |
| 07-p016 | E | 否 | 源画面与JSON均显示损失6866亿元，数值存在重大疑点；不凭常识改数，待人工核对原课程或权威事故资料。 | [PNG](high_risk_review/previews/07-p016.png) / [JSON](high_risk_review/evidence/07-p016.json) |
| 07-p024 | C | 否 | 事故起数/死亡人数年度柱图的年份、轴标和数据不在JSON，不能只留趋势一句就称完整。 | [PNG](high_risk_review/previews/07-p024.png) / [JSON](high_risk_review/evidence/07-p024.json) |
| 07-p062 | D | 否 | 通用结语学习目标页，重复不需OCR。 | [PNG](high_risk_review/previews/07-p062.png) / [JSON](high_risk_review/evidence/07-p062.json) |
| 09-p001 | E | 否 | 幕布遮挡标题/日期，需人工确认最终可见性，未扩大v2隔离规则。 | [PNG](high_risk_review/previews/09-p001.png) / [JSON](high_risk_review/evidence/09-p001.json) |
| 09-p004 | C | 否 | 项目简介正文存在，但地图内周边学校/生活区等风险位置标注未提取，案例空间影响信息不完整。 | [PNG](high_risk_review/previews/09-p004.png) / [JSON](high_risk_review/evidence/09-p004.json) |
| 09-p008 | A | 否 | 缓建事件日期和发布信息完整，右侧现场照片为辅助说明，不需新增OCR正文。 | [PNG](high_risk_review/previews/09-p008.png) / [JSON](high_risk_review/evidence/09-p008.json) |
| 09-p010 | C | 否 | 环评结论开头的海沧南部等文字缺失，右侧规划地图含额外图文信息，需要补录核对。 | [PNG](high_risk_review/previews/09-p010.png) / [JSON](high_risk_review/evidence/09-p010.json) |
| 09-p011 | C | 否 | 污染披露段落存在，覆盖标题的地图包含生活区及污染源位置文字，未保留图文关系；兼有遮挡需人工确认。 | [PNG](high_risk_review/previews/09-p011.png) / [JSON](high_risk_review/evidence/09-p011.json) |
| 09-p012 | A | 否 | 公众参与座谈会的时间、行为、标题完整，照片图注重复该事件，无需为装饰水印OCR。 | [PNG](high_risk_review/previews/09-p012.png) / [JSON](high_risk_review/evidence/09-p012.json) |
| 09-p030 | E | 否 | 新闻截图与照片覆盖安全定义正文，无法直接把底层文字视为最终可见内容，图片中的细节需人工确认。 | [PNG](high_risk_review/previews/09-p030.png) / [JSON](high_risk_review/evidence/09-p030.json) |
| 09-p034 | A | 否 | 环境公正、公平分配及癌症村案例正文完整；配图为相同主题的辅助照片。 | [PNG](high_risk_review/previews/09-p034.png) / [JSON](high_risk_review/evidence/09-p034.json) |
| 09-p043 | D | 否 | 通用结语学习目标，跨文档重复无需OCR。 | [PNG](high_risk_review/previews/09-p043.png) / [JSON](high_risk_review/evidence/09-p043.json) |
| 10-p001 | E | 否 | 幕布遮挡标题及日期，待人工确认。 | [PNG](high_risk_review/previews/10-p001.png) / [JSON](high_risk_review/evidence/10-p001.json) |
| 10-p002 | A | 否 | 生物医药伦理目录10.1至10.5完整，箭头图标不属于核心正文。 | [PNG](high_risk_review/previews/10-p002.png) / [JSON](high_risk_review/evidence/10-p002.json) |
| 10-p003 | E | 否 | 视频封面包含画面文字但完整案例过程不在本页，标题与画面范围不一致，需人工核实视频。 | [PNG](high_risk_review/previews/10-p003.png) / [JSON](high_risk_review/evidence/10-p003.json) |
| 10-p004 | A | 否 | 反应停/沙利度胺介绍主要正文完整，药品包装仅作配图；不据此给出现实医疗建议。 | [PNG](high_risk_review/previews/10-p004.png) / [JSON](high_risk_review/evidence/10-p004.json) |
| 10-p005 | A | 否 | 案例年份、宣传用语和畸形后果与正文对应，图片是辅助案例照片；源文事实未经外部核查。 | [PNG](high_risk_review/previews/10-p005.png) / [JSON](high_risk_review/evidence/10-p005.json) |
| 10-p061 | B | 是 | 左栏句末“是第一要务”被插入右侧图片说明中，需按已核实左右区域先正文后图注。 | [PNG](high_risk_review/previews/10-p061.png) / [JSON](high_risk_review/evidence/10-p061.json) |
| 10-p069 | C | 否 | 企业社会责任正文存在，但右侧假药案例新闻与反思文章含新增论据文字，尚未提取。 | [PNG](high_risk_review/previews/10-p069.png) / [JSON](high_risk_review/evidence/10-p069.json) |
| 10-p075 | D | 否 | 通用结语学习目标页，无需OCR。 | [PNG](high_risk_review/previews/10-p075.png) / [JSON](high_risk_review/evidence/10-p075.json) |
| 00-p001 | E | 否 | 幕布遮挡源标题与日期，不能将底层文本当作最终可见内容，待人工确认。 | [PNG](high_risk_review/previews/00-p001.png) / [JSON](high_risk_review/evidence/00-p001.json) |
| 00-p002 | E | 否 | 新闻视频截图含字幕，JSON仅页脚，无法确认完整案例；需要关联视频，不以单帧OCR替代案例。 | [PNG](high_risk_review/previews/00-p002.png) / [JSON](high_risk_review/evidence/00-p002.json) |
| 00-p003 | B | 是 | 问题标签落在两条问题后；显示坐标可恢复问题标签先行。 | [PNG](high_risk_review/previews/00-p003.png) / [JSON](high_risk_review/evidence/00-p003.json) |
| 00-p004 | A | 否 | 课程安排五项顺序与标题对应，风险为块位置/格式候选，未发现需修复的语义错序。 | [PNG](high_risk_review/previews/00-p004.png) / [JSON](high_risk_review/evidence/00-p004.json) |
| 00-p005 | B | 是 | 课程性质与地位标题落后于正文，单栏文字可按显示坐标重排。 | [PNG](high_risk_review/previews/00-p005.png) / [JSON](high_risk_review/evidence/00-p005.json) |
| 00-p006 | B | 是 | 考核方式标题与平时/期末两段错序；恢复显示顺序，保留40%、60%及800-1000字要求。 | [PNG](high_risk_review/previews/00-p006.png) / [JSON](high_risk_review/evidence/00-p006.json) |
| 00-p007 | B | 是 | 课程目的标题在后，恢复标题、开课问题、宏观及微观目标顺序。 | [PNG](high_risk_review/previews/00-p007.png) / [JSON](high_risk_review/evidence/00-p007.json) |
| 00-p008 | B | 是 | 时代呼唤和工程学科时代需求层次错序，显示坐标可恢复两组条目。 | [PNG](high_risk_review/previews/00-p008.png) / [JSON](high_risk_review/evidence/00-p008.json) |
| 00-p009 | B | 是 | ABET段落和英文名称因旋转坐标乱序，按显示行恢复标题及两段正文。 | [PNG](high_risk_review/previews/00-p009.png) / [JSON](high_risk_review/evidence/00-p009.json) |
| 00-p010 | B | 是 | 工程教育要求的标题、24字方针与三进规划被打散，按显示行恢复层次。 | [PNG](high_risk_review/previews/00-p010.png) / [JSON](high_risk_review/evidence/00-p010.json) |
| 00-p011 | B | 否 | 微观目标/人生目标与四种伦理能力的连线图语义不宜用单纯行排序恢复；保留B待结构核准，不自动修复。 | [PNG](high_risk_review/previews/00-p011.png) / [JSON](high_risk_review/evidence/00-p011.json) |
| 00-p012 | B | 是 | 定量目标三条及标题倒序，显示坐标可恢复1-3条。 | [PNG](high_risk_review/previews/00-p012.png) / [JSON](high_risk_review/evidence/00-p012.json) |
| 00-p013 | B | 是 | 工程专业认证说明的标题与正文乱序，按显示坐标恢复。 | [PNG](high_risk_review/previews/00-p013.png) / [JSON](high_risk_review/evidence/00-p013.json) |
| 00-p014 | B | 是 | 华盛顿协议与专业认证说明乱序，恢复标题、说明及页脚。 | [PNG](high_risk_review/previews/00-p014.png) / [JSON](high_risk_review/evidence/00-p014.json) |
| 00-p016 | B | 是 | 意识培养的标题、第一条和广义/狭义意识解释错序，恢复显示阅读顺序。 | [PNG](high_risk_review/previews/00-p016.png) / [JSON](high_risk_review/evidence/00-p016.json) |
| 00-p017 | B | 是 | 基本规范的标题与定义错序，恢复工程伦理规范定义的完整段落。 | [PNG](high_risk_review/previews/00-p017.png) / [JSON](high_risk_review/evidence/00-p017.json) |
| 00-p018 | B | 是 | 决策能力标题与定义错序，按显示坐标恢复完整上下文。 | [PNG](high_risk_review/previews/00-p018.png) / [JSON](high_risk_review/evidence/00-p018.json) |
| 00-p019 | B | 是 | 教育目的标题落后于五个目标，按显示顺序恢复标题先行。 | [PNG](high_risk_review/previews/00-p019.png) / [JSON](high_risk_review/evidence/00-p019.json) |
| 00-p020 | B | 是 | 伦理素养、可持续发展、利益协调三项意义顺序错乱，箭头仅作项目装饰，按显示行恢复。 | [PNG](high_risk_review/previews/00-p020.png) / [JSON](high_risk_review/evidence/00-p020.json) |
| 00-p022 | B | 是 | 工程伦理发展起源与教育段落错序，单栏可按显示坐标恢复。 | [PNG](high_risk_review/previews/00-p022.png) / [JSON](high_risk_review/evidence/00-p022.json) |
| 00-p023 | B | 是 | 发展及工程界定第一思路段落错序，恢复标题和论述。 | [PNG](high_risk_review/previews/00-p023.png) / [JSON](high_risk_review/evidence/00-p023.json) |
| 00-p024 | B | 是 | 工程界定第二思路及多元研究方法错序，恢复单栏段落。 | [PNG](high_risk_review/previews/00-p024.png) / [JSON](high_risk_review/evidence/00-p024.json) |
| 00-p025 | B | 是 | 研究对象、责任问题和角色冲突等段落乱序，按显示行恢复标题、说明和条目。 | [PNG](high_risk_review/previews/00-p025.png) / [JSON](high_risk_review/evidence/00-p025.json) |
| 00-p026 | B | 是 | 案例研究与理论分析两种方法乱序，按显示行恢复包含英文人名的原文，不校订源文。 | [PNG](high_risk_review/previews/00-p026.png) / [JSON](high_risk_review/evidence/00-p026.json) |
| 00-p027 | B | 是 | 工程伦理发展趋势单栏段落错序，恢复标题、领域及全球性问题说明。 | [PNG](high_risk_review/previews/00-p027.png) / [JSON](high_risk_review/evidence/00-p027.json) |
| 00-p028 | B | 是 | NASW条目与美国侧栏混入正文；经页面对照可用已核实侧栏分区恢复。 | [PNG](high_risk_review/previews/00-p028.png) / [JSON](high_risk_review/evidence/00-p028.json) |
| 00-p030 | B | 是 | 六类伦理责任及美国侧栏混排，按已核实侧栏分区恢复。 | [PNG](high_risk_review/previews/00-p030.png) / [JSON](high_risk_review/evidence/00-p030.json) |
| 00-p031 | B | 是 | ASCE原则说明及美国侧栏混排，按已核实侧栏分区恢复，不补写标准全文。 | [PNG](high_risk_review/previews/00-p031.png) / [JSON](high_risk_review/evidence/00-p031.json) |
| 00-p032 | C | 否 | ASCE基本原则及基本准则整张表为图片，JSON只有页眉等，公众安全优先等核心条目未提取。 | [PNG](high_risk_review/previews/00-p032.png) / [JSON](high_risk_review/evidence/00-p032.json) |
| 00-p033 | C | 否 | 工程师职业伦理共性要求表为图片，公众利益、胜任、正直等条目不在JSON。 | [PNG](high_risk_review/previews/00-p033.png) / [JSON](high_risk_review/evidence/00-p033.json) |
| 00-p034 | B | 是 | 土木工程师责任说明与美国侧栏混排，按已核实侧栏分区恢复；人名保持源文。 | [PNG](high_risk_review/previews/00-p034.png) / [JSON](high_risk_review/evidence/00-p034.json) |
| 00-p035 | B | 是 | 跨学科伦理准则历史段落及年份乱序，按已核实侧栏分区恢复公众安全健康福利优先上下文。 | [PNG](high_risk_review/previews/00-p035.png) / [JSON](high_risk_review/evidence/00-p035.json) |
| 00-p036 | B | 是 | 伦理学纳入认证规划说明与侧栏混排，按已核实侧栏分区恢复。 | [PNG](high_risk_review/previews/00-p036.png) / [JSON](high_risk_review/evidence/00-p036.json) |
| 00-p037 | B | 是 | 日本/台湾伦理教育条目和标题错序，可按显示行重排。 | [PNG](high_risk_review/previews/00-p037.png) / [JSON](high_risk_review/evidence/00-p037.json) |
| 00-p038 | B | 是 | 国内研究与教育时间线错序，按显示行恢复1999/2007/2008条目。 | [PNG](high_risk_review/previews/00-p038.png) / [JSON](high_risk_review/evidence/00-p038.json) |
| 00-p039 | B | 是 | 研讨会议题段落错序，按显示行恢复标题、说明和议题。 | [PNG](high_risk_review/previews/00-p039.png) / [JSON](high_risk_review/evidence/00-p039.json) |
| 00-p040 | C | 否 | 会议新闻主体段落是图片，原JSON只保留标题页脚等；背景性内容低优先级，不必为覆盖率立即OCR。 | [PNG](high_risk_review/previews/00-p040.png) / [JSON](high_risk_review/evidence/00-p040.json) |
| 00-p041 | B | 是 | 2011/2014会议背景段落错序，按显示行恢复，不加入图片推断。 | [PNG](high_risk_review/previews/00-p041.png) / [JSON](high_risk_review/evidence/00-p041.json) |
| 00-p043 | B | 是 | 课程建设背景两段错序，恢复标题与显示段落顺序。 | [PNG](high_risk_review/previews/00-p043.png) / [JSON](high_risk_review/evidence/00-p043.json) |
| 00-p044 | B | 是 | 2016/2017课程建设段落错序，按显示行恢复原文。 | [PNG](high_risk_review/previews/00-p044.png) / [JSON](high_risk_review/evidence/00-p044.json) |
| 00-p046 | B | 是 | 左侧研修班说明与页眉页脚顺序异常，正文可按显示行恢复，右侧合影不补写身份。 | [PNG](high_risk_review/previews/00-p046.png) / [JSON](high_risk_review/evidence/00-p046.json) |
| 00-p048 | B | 是 | 高校课程推广背景段落错序，恢复单栏显示顺序，原文相对时间不作更新。 | [PNG](high_risk_review/previews/00-p048.png) / [JSON](high_risk_review/evidence/00-p048.json) |
| 00-p049 | B | 是 | 高校开课说明段落错序，按显示行恢复，不核查源文历史事实。 | [PNG](high_risk_review/previews/00-p049.png) / [JSON](high_risk_review/evidence/00-p049.json) |
| 00-p050 | B | 否 | 放射状目录的节点被串排，无法用普通y/x顺序表达章节次序，待结构核准，未自动修复。 | [PNG](high_risk_review/previews/00-p050.png) / [JSON](high_risk_review/evidence/00-p050.json) |
| 00-p051 | B | 是 | 概念与基本原则目录标题后置，按显示行恢复标题及1-5条。 | [PNG](high_risk_review/previews/00-p051.png) / [JSON](high_risk_review/evidence/00-p051.json) |
| 00-p052 | B | 是 | 风险安全责任目录标题后置，按显示行恢复案例、来源、防范、评估与责任条目。 | [PNG](high_risk_review/previews/00-p052.png) / [JSON](high_risk_review/evidence/00-p052.json) |
| 00-p053 | B | 是 | 价值利益公正目录标题后置，按显示行恢复1-5条。 | [PNG](high_risk_review/previews/00-p053.png) / [JSON](high_risk_review/evidence/00-p053.json) |
| 00-p054 | B | 是 | 环境伦理目录及案例的跨行续文错序，恢复标题与条目连续顺序。 | [PNG](high_risk_review/previews/00-p054.png) / [JSON](high_risk_review/evidence/00-p054.json) |
| 00-p055 | B | 是 | 职业伦理目录及奶粉视频提示续行错序，恢复标题与1-4条。 | [PNG](high_risk_review/previews/00-p055.png) / [JSON](high_risk_review/evidence/00-p055.json) |
| 00-p056 | B | 是 | 土木工程伦理目录标题后置，恢复标题及案例、工程师、建设管理人员条目。 | [PNG](high_risk_review/previews/00-p056.png) / [JSON](high_risk_review/evidence/00-p056.json) |
| 00-p057 | B | 是 | 化工事故目录中根源分析续行先于条目，恢复标题与案例、过失、预防应急条目。 | [PNG](high_risk_review/previews/00-p057.png) / [JSON](high_risk_review/evidence/00-p057.json) |
| 00-p058 | B | 是 | 信息数据伦理目录标题后置，恢复显示目录顺序。 | [PNG](high_risk_review/previews/00-p058.png) / [JSON](high_risk_review/evidence/00-p058.json) |
| 00-p059 | B | 是 | 环境工程伦理目录末条续行先行，恢复标题与四个条目。 | [PNG](high_risk_review/previews/00-p059.png) / [JSON](high_risk_review/evidence/00-p059.json) |
| 00-p060 | B | 是 | 生物医药伦理目录标题后置，恢复标题与五条目录。 | [PNG](high_risk_review/previews/00-p060.png) / [JSON](high_risk_review/evidence/00-p060.json) |
| 00-p061 | B | 是 | 其他工程伦理目录标题后置，恢复标题及水利、核、计算机、AI条目。 | [PNG](high_risk_review/previews/00-p061.png) / [JSON](high_risk_review/evidence/00-p061.json) |
| 00-p062 | B | 是 | 案例目录原文先输出右栏8-14再左栏1-7；按已查看左右列先左后右恢复编号顺序。 | [PNG](high_risk_review/previews/00-p062.png) / [JSON](high_risk_review/evidence/00-p062.json) |
| 00-p063 | D | 否 | 结语目标页，与其他文档重复；不为标题错序进行无意义正文扩充，无需OCR。 | [PNG](high_risk_review/previews/00-p063.png) / [JSON](high_risk_review/evidence/00-p063.json) |
| 00-p064 | E | 否 | 天龙刹车案例视频封面，案例过程需人工关联视频，不能由画面猜写。 | [PNG](high_risk_review/previews/00-p064.png) / [JSON](high_risk_review/evidence/00-p064.json) |
| 00-p065 | B | 否 | 刹车案例有阅读顺序问题，但管长变化的矢量箭头不在文字层；需同时复核关系表达，暂不自动修复或标记合格。 | [PNG](high_risk_review/previews/00-p065.png) / [JSON](high_risk_review/evidence/00-p065.json) |
| 00-p066 | D | 否 | END及单位页脚结束页，排除正文无需OCR。 | [PNG](high_risk_review/previews/00-p066.png) / [JSON](high_risk_review/evidence/00-p066.json) |

## 第一版知识库是否可启动

**可以先以已合格的正文准备范围受限、可追溯的验证版；目前不能作为完整备考知识库。** 本轮31个A类页加50个已修复B类页共81个候选。其中30页是明确的目录/章节标题，只适合作导航上下文，不应拿来凑知识点覆盖率。报告另标注29个主要概念/规范/案例正文页作为可优先讨论的候选子集（含原课件重复页02-p008/009，后续应保留来源再去重）。

候选页资格只针对现有正文保真及本次证据，不验证源课程历史事实；没有给其余462页自动发放资格，也没有把此前22个“主要内容基本对应”的样本扩大为逐字验收通过。5个未修复B、21个C、26个E暂缓；12个D不作为核心正文。先前的01-p040、09-p037、10-p056、10-p063补录任务及07-p001待确认隔离状态全部保留。

下一步应优先补齐01-p050三项基本原则、01-p042/043/044核心定义、01-p048/049辨识条件、02-p029责任区分和00-p032/033职业规范表，再处理其他高价值图表或案例资料。先前07-p020关系图等也未因本次排除而变成“已解决”。在这些缺口补齐前，应明确首版知识范围，遇到缺口应承认资料不足，不据图片识别猜测补写。

[候选与暂缓清单](high_risk_review/admission_candidates.json)仅是数据准备清单，没有执行分块、嵌入、向量库或问答功能，也没有安装相关依赖。

## v3输出、来源保护与验证

- 已输出10份、607页JSON到独立data/processed_v3/，来源文件名、文档ID和物理页码全部保留；source_json记录v2文件名和SHA-256，schema_version=3。
- 145个审查页新增high_risk_review，记录类别、证据、预览、笔记、是否实际修复和候选/暂缓处置。50个修复页另存pre_v3_text及repair_history，记录前后哈希和原/新提取方法。文档修复汇总已重算，并保留source_v2_repair_summary，避免统计沿用v2导致误解。
- 相比v2：50页text变化、557页text逐字符不变；462个非审查目标页的整条页记录不变。此前3个已修复页完整保留，不重跑原排序；既有隔离/待补录页不改状态。
- 原PDF、原JSON、processed_v2共30个文件在开始与完成时SHA-256全部不变。输出目录排他创建，已存在即拒绝覆盖。
- 实际执行`.venv/bin/python -m pytest -q`：**39 passed，0 failed**（原有26项+新增13项），有5条既有PyMuPDF/SWIG弃用警告。新增回归涵盖10文档607页、来源页码、145页去重与历史排除、50页字符守恒、非目标内容保持、旧3页不退化、C/E及未修复B不误标、旧待确认状态保留、关键布局锚点、原对象不原地变更、基线失配拒绝、30文件哈希及UTF-8防覆盖导出。
- 未安装OCR、LangChain、ChromaDB或其他新包；未接入DeepSeek/在线AI服务，未开发前端，未构建知识库。

## 产物与复现

- [队列及30个源文件哈希](high_risk_review/queue.json)、[最终逐页CSV](high_risk_review/review_results.csv)、[输出验证清单](high_risk_review/verification.json)。
- `reports/high_risk_review/previews/`：145张独立PNG；上级目录29张联系表。`evidence/`包含145页的原文、未排序文本、blocks、dict显示行坐标、图片位置和候选文本。
- [全部候选文本对比](high_risk_review/text_comparisons.md)：这里的candidate表示未自动采用的程序方案；实际采用情况以最终CSV/v3记录为准，不能把初始候选当成已验证修复。
- 新增`scripts/inspect_high_risk.py`（排他生成初筛证据）、`scripts/high_risk_decisions.py`（实际查看后的静态笔记）、`src/pdf_review.py`（白名单v3导出）、`tests/test_pdf_review.py`、`scripts/build_high_risk_report.py`。README及.gitignore新增v3说明和生成目录排除。
- 从项目目录可用`.venv/bin/python -m src.pdf_review`执行导出；当前v3目录已存在，重复运行会拒绝覆盖。报告脚本同样排他创建产物。
- 本报告未修改先前两份报告或v2数据，新增发现和分类仅记录在本轮产物。
