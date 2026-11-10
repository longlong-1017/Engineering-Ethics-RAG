"""本地检索线索。扩展词绝不作为事实或生成答案依据。"""
import re

RULES = (
    (r'废水|污水|排放|生态|环境|污染', ('环境工程中的安全','环境工程中的社会公正','环境风险评估与预防')),
    (r'公众|居民|周边|健康|福利', ('公众安全与健康','工程活动中的公众利益','环境工程中的社会公正')),
    (r'工程师|管理层|施工|职业', ('工程师的伦理责任','工程师职业伦理规范')),
    (r'风险|隐患|长期|不可逆|可能', ('工程风险','工程师的伦理责任')),
    (r'经济收益|利益|公正|公平|伦理决策', ('工程中的价值与利益','工程活动中的环境伦理原则')),
)


def expand_query(question, limit=6):
    result=[question.strip()] if question.strip() else []
    sides=comparison_sides(question)
    if sides:
        for group in sides:
            for alias in group:
                if alias not in result:result.append(alias)
        return tuple(result[:max(1,limit)])
    matched=[queries for pattern,queries in RULES if re.search(pattern,question)]
    # 轮询知识点组，防止环境同义词耗尽全部槽位，挤掉责任/风险。
    for position in range(max((len(group) for group in matched),default=0)):
        for group in matched:
            if position<len(group) and group[position] not in result:result.append(group[position])
    return tuple(result[:max(1,limit)])


def is_case_question(question):
    return bool(re.search(r'某|虽然|但|管理层|不可逆',question) and re.search(r'如何|怎样|应|判断|决策|处理',question))


THEORY_ALIASES = (('功利主义','功利论'), ('义务论','义务伦理','道义论'))


def comparison_sides(question):
    if not re.search(r'区别|不同|异同|对比|比较',question):return ()
    sides=[group for group in THEORY_ALIASES if any(alias in question for alias in group)]
    return tuple(sorted(sides,key=lambda group:min(question.find(a) for a in group if a in question))) if len(sides)==2 else ()


def theory_explanation_strength(text, aliases):
    """名称后必须是解释性谓词，不接受‘甲、乙等理论’名单。无页码特例。"""
    compact=re.sub(r'\s+','',text)
    best=0
    for alias in aliases:
        for match in re.finditer(re.escape(alias),compact):
            tail=compact[match.end():match.end()+220]
            if re.match(r'[、，,与和]',tail):continue
            clause=re.split(r'[。；;]',tail)[0]
            verbs=re.findall(r'聚焦|强调|是指|也称|被称为|本质|核心|以.{0,40}判断',clause)
            if len(clause)>=15:best=max(best,len(verbs))
    return best
