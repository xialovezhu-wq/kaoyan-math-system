"""Conservative, local concept selection over neutral discovery metadata.

This is a locator, not a learner assessment or mathematical applicability judge.
It does not read source bodies, infer missing descriptors, or fill a result count.
Scores order supported matches; they are not truth/confidence probabilities.
"""
from __future__ import annotations

from collections import Counter
import math
from functools import lru_cache
import re
import unicodedata

REVISION = 'math-neutral-retrieval-v2.6-qualified-exclusions'

_BROAD = frozenset(('数学', '高等数学', '线性代数', '概率论', '概率', '统计', '函数',
    '矩阵', '向量', '方程', '方程组', '微分方程', '积分', '微分', '导数', '极限',
    '级数', '数列', '随机变量', '分布', '概率分布', '分布函数', '事件', '公式',
    '性质', '方法', '条件', '证明', '计算', '求解', '解集', '非零解'))
_GENERIC = _BROAD | frozenset(('知识点', '具体', '这道题', '那道题', '题目', '问题',
    '理解', '掌握', '独立', '正确', '错误', '记录', '原话', '反馈', '学习', '复盘',
    '检查', '判断', '步骤', '思路', '过程', '运算', '变换', '化简', '代入', '求值'))
_GENERIC_OP = frozenset(('求导', '积分', '求解', '计算', '证明', '代入', '变换',
    '判断', '化简', '公式', '性质', '条件', '检查', '运算', '求值', '理解'))
_GRAMMATICAL = frozenset(('不是','不能','没有','可以','所以','怎么','到底','这个','那个',
    '如果','当时','需要','用于','关于','考虑','出现','想查','我问','我想','只要','而是','是不是'))
_DATE = re.compile(r'^(?:19|20)\d{2}(?:年|[-/.])\d{1,2}(?:(?:月|[-/.])\d{1,2})?')
_NAV_ONLY = re.compile(r'^(?:(?:今日|每日|本周|本月|当天|当前|个人|全部|全库|数学|学习|错题|知识点|方法|资料|历史|来源|总)+)?(?:复盘(?:总结)?|总结|回顾|笔记|记录|入口|索引|目录|导航|清单|待办|报告|暂存|待拆分)$')
_NAV_SUFFIX = re.compile(r'(?:个人断点导航|知识点簇索引|方法簇索引|错因簇索引|来源暂存|待拆分|复盘总结|学习记录|个人学习记录|总索引|检索入口)$')
_IDENTITY = re.compile(r'(?i)^(?:math-concept-|math-method-|(?:gs|la|pr|mx)-|math[123]-|fce-|method:|step:|conclusion:)')
_FORMAL_ID = re.compile(r'(?i)(?<![a-z0-9])(?:gs|la|pr|mx)-\d{1,5}(?!\d)')
_CLAUSE = re.compile(r'[，,。；;！？!?\n]+')
_ROUTE_NEG = re.compile(r'不想(?:再)?(?:使用|采用|通过|用|按|走)?|不要(?:再)?(?:使用|采用|通过|用|按)?|不用(?:再)?|不采用|不使用|不查询|不检索|不查|不找|不看|不判(?:断)?|不讨论|排除|别(?:再)?(?:使用|采用|查询|查|找|看|用)')
_TURN_POSITIVE = re.compile(r'而是|改用|改成|换成|只想|但是(?:我)?(?:想|要)|但(?:我)?(?:想|要)|希望|想(?:按|用|走)|要(?:按|用|走)')
_QUESTION_NEG = re.compile(r'为什么(?:不能|不用)|为何(?:不能|不用)|能不能(?:用|使用|采用)|是否(?:能用|适用)|不是.+(?:吗|么|[?？])')
_MATH_NEG_BASES = ('齐次', '零', '独立', '相关', '连续', '可逆', '正态', '对称', '正定',
    '有偏', '放回', '可微', '可导', '可积', '单调', '线性', '同分布', '收敛', '发散',
    '有界', '一致', '绝对收敛', '正交', '相似', '等价', '同解', '可对角化',
    '可交换', '可分离', '有限', '相等')
_MATH_BROAD_HINTS = (_BROAD - {'公式', '性质', '方法', '条件', '证明', '计算', '求解', '事件'}) | frozenset(('一阶', '二阶', '三阶', '高阶'))
_SCOPED_OBJECT_TOO_BROAD = frozenset(('矩阵', '概率', '函数', '方程', '方程组', '积分',
    '导数', '随机变量', '分布', '方法', '条件', '公式', '事件', '题目', '向量', '数列',
    '级数', '极限', '微分方程', '线性代数', '高等数学', '概率论'))
_CONCRETE_ACTION = re.compile(r'求导|微分|积分|展开|换元|代换|代入|替换|消元|换序|交换|'
    r'取交|定限|分区|分段|求和|累加|相加|相减|相乘|相除|通分|约分|配方|'
    r'因式分解|移项|行变换|列变换|投影|参数化|关于.{0,5}参数|对.{0,5}参数|'
    r'化成|化为|变成|转换成|先.{1,20}(?:再|然后)|计算|算出|求(?:极限|值|导|积|和|解)')


@lru_cache(maxsize=32768)
def normalize(value: str) -> str:
    value = unicodedata.normalize('NFKC', value).casefold()
    value = re.sub(r'(?<![a-z])cov(?:ariance)?(?![a-z])', '协方差', value)
    for abbreviation, term in (('cdf', '分布函数'), ('pdf', '概率密度')):
        if not re.search(r'\.' + abbreviation + r'\b|' + abbreviation + r'(?:文件|文档|阅读器|格式|下载)', value):
            value = re.sub(r'(?<![a-z])' + abbreviation + r'(?![a-z])', term, value)
    value = value.replace('行满秩', '满行秩').replace('列满秩', '满列秩')
    # These result complements do not identify a mathematical topic. Removing
    # the grammatical connector lets the same declared operation be found
    # without adding a query-to-concept synonym or inventing a descriptor.
    value = re.sub(r'(展开|拆分|分解|改写)(?:成为|成|为)', r'\1', value)
    return re.sub(r'\s+', '', value)


def exclusion_reason(doc: dict) -> str | None:
    """Exclude indexing artifacts without deleting their historical identity."""
    if not isinstance(doc, dict):
        return 'invalid_document'
    if doc.get('discovery_eligible') is False:
        return str(doc.get('discovery_exclusion_reason') or 'declared_ineligible')
    if doc.get('knowledge_type') in {'artifact', 'navigation', 'source', 'report'}:
        return 'artifact_type'
    title = normalize(str(doc.get('title') or ''))
    if not title:
        return 'empty_title'
    if (_DATE.match(title) or re.fullmatch(r'\d+(?:[-/.]\d+)+', title)
            or re.fullmatch(r'\d{1,8}(?:年|月|日)?', title)):
        return 'date_heading'
    if _NAV_ONLY.fullmatch(title) or _NAV_SUFFIX.search(title):
        return 'navigation_or_staging'
    if re.search(r'(?:知识网络|知识点簇|方法簇|错因簇|全库|资料库).*(?:导航|入口|索引|目录|清单|报告)$', title):
        return 'navigation_or_staging'
    return None


def is_discovery_eligible(doc: dict) -> bool:
    return exclusion_reason(doc) is None


def _strings(value):
    if isinstance(value, str):
        return [value]
    return [v for v in value if isinstance(v, str)] if isinstance(value, (list, tuple)) else []


def _names(doc):
    signature = doc.get('retrieval_signature') or {}
    if not isinstance(signature, dict):
        signature = {}
    values = [doc.get('title', ''), *_strings(doc.get('aliases')), *_strings(signature.get('aliases'))]
    return tuple(dict.fromkeys(normalize(v) for v in values if isinstance(v, str) and v.strip()
                               and not _DATE.match(normalize(v)) and not _NAV_ONLY.fullmatch(normalize(v))
                               and not _NAV_SUFFIX.search(normalize(v))))


def _title_components(title):
    """Surface subtopics of a compound heading, not invented identity aliases."""
    title = normalize(title)
    scope = re.split(r'(?:中的|下的)', title, maxsplit=1)
    parent, body = (scope[0], scope[1]) if len(scope) == 2 else ('', title)
    pieces = re.split(r'[、，,/]|与|及|和', body)
    result = []
    for piece in pieces:
        piece = re.sub(r'^的|(?:的定义|的性质|的结构|的规则)$', '', piece)
        if 3 <= len(piece) <= 24 and piece not in _GENERIC and piece != title:
            # Keep the qualifier attached. A condition such as "不相关" is
            # not a standalone alias for a point restricted to joint normality.
            result.append(parent + '中的' + piece if parent else piece)
    return tuple(dict.fromkeys(result))


def _title_scope(title, signature):
    title = normalize(title)
    if not isinstance(signature, dict):
        signature = {}
    pieces = re.split(r'(?:中的|下的)', title, maxsplit=1)
    if len(pieces) != 2:
        return None
    parent = pieces[0]
    aliases = [parent, *[normalize(v) for v in _strings(signature.get('scope_aliases'))]]
    # A noun mentioned elsewhere in the compound heading is not a scope alias.
    aliases.extend(normalize(v) for v in _strings(signature.get('objects'))
                   if len(normalize(v)) >= 3 and normalize(v) in parent
                   and normalize(v) not in _SCOPED_OBJECT_TOO_BROAD)
    return {'parent': parent, 'aliases': tuple(dict.fromkeys(aliases))}


def _dimension_conflict(parent, query):
    dimensions = re.findall(r'([一二三四五六七八九十\dn]+)维', parent)
    if not dimensions:
        return False
    translate = {'一': '1', '二': '2', '两': '2', '三': '3', '四': '4',
                 '五': '5', '六': '6', '七': '7', '八': '8', '九': '9', '十': '10'}
    expected = {translate.get(value, value) for value in dimensions}
    explicit = {translate.get(value, value) for value in re.findall(r'([一二三四五六七八九十\dn]+)维', query)}
    if explicit and not explicit <= expected:
        return True
    return bool(re.search(r'多元|多维', query) and not {'n'} & expected)


def special_scope_reason(doc, query):
    """Keep a special operator/support from posing as its general neighbour.

    These are object signatures, not conditions asserted true of the problem.
    Definition-shaped descriptions are supported as well as standard names.
    """
    title=normalize(str(doc.get('title','')));query=normalize(query)
    if re.search(r'取整|整值函数|高斯取整',title) and not re.search(
            r'取整|整值函数|高斯函数|floor|lfloor|不超过.{0,12}最大整数|\[[a-z0-9+*/^\-]+\]',query):
        return 'integer_part_object_not_requested'
    if re.search(r'两点|二点|二值|两值',title) and not re.search(
            r'两点|二点|二值|两值|两个值|两种取值|0和1|0与1|0,1|0、1|伯努利|0-1',query):
        return 'two_value_special_case_not_requested'
    return None


def _operation_request(text, matched_names):
    """Detect an additional action even if it is absent from the catalog.

    Removing the named object prevents '积分' inside '二重积分' from turning
    a definition query into an execution request. This does not guess which
    method should perform an unknown action.
    """
    remainder = text
    for name in sorted(set(matched_names), key=len, reverse=True):
        remainder = remainder.replace(name, '')
    return bool(_CONCRETE_ACTION.search(remainder))


def _contains(text, term):
    """Do not count the positive base inside a mathematical negative term."""
    if not term:
        return False
    start = 0
    while True:
        position = text.find(term, start)
        if position < 0:
            return False
        previous = text[max(0, position - 2):position]
        negated_base = any(term.startswith(base) for base in _MATH_NEG_BASES)
        if not (negated_base and (previous.endswith('非') or previous.endswith('不')
                                 or term.startswith('偏') and previous.endswith('无'))):
            return True
        start = position + 1


def _longest_terms(text, terms):
    """Retain specific terms instead of counting every substring as evidence."""
    hits = [term for term in terms if term and _contains(text, term)]
    hits.sort(key=lambda term: (-len(term), term))
    return [term for i, term in enumerate(hits) if not any(term in prior for prior in hits[:i])]


def analyze_query(query: str, vocabulary=()):
    """Separate clear route choices from mathematical/epistemic negation."""
    if not isinstance(query, str) or not query.strip() or len(query) > 4000:
        raise ValueError('retrieval_query_invalid')
    original = unicodedata.normalize('NFKC', query)
    original = re.sub(r'(不是[^，,。；;！？!?\n]+)[，,]\s*(而是|而要|而用|而应)', r'\1\2', original)
    original = re.sub(r'(不是[^，,。；;！？!?\n]+)[，,]\s*(?:我)?(?:要|想|希望)(?:查|找|看|用|按|把|将)', r'\1而是', original)
    original = re.sub(r'(不是[^，,。；;！？!?\n]+)[，,]\s*是', r'\1而是', original)
    original = re.sub(r'(不是[^，,。；;！？!?\n]+)[，,]\s*(?:只是|应该是|实际是|要的是)', r'\1而是', original)
    positive, excluded, uncertain = [], [], []
    for clause in _CLAUSE.split(original):
        if not clause.strip():
            continue
        if _QUESTION_NEG.search(clause):
            positive.append(clause)
            continue
        replacement = re.search(r'(?:不要|别)(?:拿|用|以)?(.+?)(?:替代|代替|替换)(.+)', clause)
        if replacement:
            excluded.append({'text': normalize(replacement.group(1)), 'scope': 'route', 'marker': '不要以A替代B'})
            positive.extend((clause[:replacement.start()], replacement.group(2)))
            continue
        contrast = re.search(r'不是(.+?)(?:而是|而要|而用|而应)(.+)', clause)
        if contrast:
            negative = contrast.group(1).strip()
            excluded.append({'text': normalize(negative), 'scope': 'route', 'marker': '不是…而是'})
            positive.extend((clause[:contrast.start()], contrast.group(2)))
            continue
        opposite = re.search(r'(.+?)(?:而不是|而非)(.+)', clause)
        if opposite:
            excluded.append({'text': normalize(opposite.group(2)), 'scope': 'route', 'marker': 'A而不是B'})
            positive.append(opposite.group(1))
            continue
        match = _ROUTE_NEG.search(clause)
        if not match or (_QUESTION_NEG.search(clause) and match.group().startswith('不用')):
            positive.append(clause)
            continue
        tail = clause[match.end():]
        if re.match(r'(?:不|非|别|不要|不用|排除|删除|忽略|避免|否定|禁止)', tail.strip()):
            uncertain.append('double_or_scoped_negation')
            positive.append(clause)
            continue
        switch = _TURN_POSITIVE.search(tail)
        negative = tail[:switch.start()] if switch else tail
        if not negative.strip():
            positive.append(clause)
            continue
        label_scope = bool(re.search(r'返回|宽泛|大类|泛泛|候选|标签', negative))
        excluded.append({'text': normalize(negative), 'scope': 'label' if label_scope else 'route',
                         'marker': match.group()})
        positive.append(clause[:match.start()])
        if switch:
            positive.append(tail[switch.end():])
    positive_text = '，'.join(positive)
    normalized = normalize(positive_text)
    formal_ids = sorted({m.group().upper() for m in _FORMAL_ID.finditer(normalized)})
    excluded_formal_ids = sorted({m.group().upper() for item in excluded for m in _FORMAL_ID.finditer(item['text'])})
    # Dates and printed IDs constrain evidence lookup, not topic similarity.
    normalized = _FORMAL_ID.sub('', normalized)
    normalized = re.sub(r'(?:19|20)\d{2}(?:年|[-/.])\d{1,2}(?:(?:月|[-/.])\d{1,2})?(?:日)?', '', normalized)
    normalized = re.sub(r'\d{1,2}月\d{1,2}日|(?<!\d)\d{1,2}/\d{1,2}(?!\d)', '', normalized)
    for item in excluded:
        negative_text=item['text']
        if re.search(r'判(?:断)?|讨论',negative_text+str(item.get('marker',''))):
            # Declining a judgement task does not reject its whole object.
            # "收不收敛" names the judged property, not a negative premise.
            for base in _MATH_NEG_BASES:
                negative_text=negative_text.replace(base[0]+'不'+base,base)
            found=[term for term in _longest_terms(negative_text,vocabulary) if term not in _BROAD]
        else:
            found = _longest_terms(negative_text, vocabulary)
            # A qualifier not covered by our vocabulary must not disappear:
            # rejecting "普通奇偶对称" is not rejecting every symmetry rule.
            precise=re.sub(r'^(?:普通|一般|通常|常见|那种|这种|这个|那个)+','',negative_text)
            found=[term for term in found if len(term)>=3 or term==precise]
            negative_text=precise
        item['terms'] = found or ([negative_text] if 2 <= len(negative_text) <= 40 else [])
    return {'positive': normalized, 'positive_text': positive_text, 'excluded': excluded, 'uncertain': uncertain,
            'formal_ids': formal_ids, 'excluded_formal_ids': excluded_formal_ids,
            'questioning_applicability': bool(_QUESTION_NEG.search(original)),
            'semantic_negation_preserved': True}


def _bare_request(text):
    text = re.sub(r'^[，,:：]+|[，,:：。?？!！]+$', '', text)
    text = re.sub(r'^(?:请(?:帮我)?(?:查找|定位|解释|说明)?|帮我(?:查找|定位)|什么是|解释一下|解释|复习一下|我想复习|我不理解|不理解|我想用|想用|定位)', '', text)
    return re.sub(r'(?:是什么|怎么理解|的定义|一下|吗|呢|吧)$', '', text)


def _term_weight(term, df, count):
    return 1.0 + math.log((count + 1) / (df.get(term, 0) + 1))


def _lexical_text(value):
    # A grammatical connector is not an extra mathematical condition. Keep
    # negations, numbers, variables and word order intact.
    return normalize(value).replace('的', '')


def _catalog_phrase_evidence(positive, prepared):
    """Query-local phrases from the catalog, not a fixed mathematical lexicon.

    Only phrases actually shared with a declared neutral name are considered.
    Corpus frequency removes broad vocabulary; overlapping substrings are one
    piece of evidence. This does not expand a query or invent a condition.
    """
    text=_lexical_text(positive)
    grams={part[start:start+size] for part in re.findall(r'[\w\u3400-\u9fff]+',text)
           for size in range(2,min(8,len(part))+1) for start in range(len(part)-size+1)}
    grams={term for term in grams if term not in _GENERIC and term not in _GENERIC_OP
           and term not in _GRAMMATICAL and re.search(r'[\u3400-\u9fff]',term)
           and not re.search(r'^[与及和中在把将]|[与及和中在把将相]$',term)
           and _contains(text,term)}
    # Invert this query's vocabulary instead of comparing every query phrase
    # against every catalog document. Only exact substrings can become shared
    # evidence; keep the existing document-frequency and span rules below.
    by_length = {}
    for term in grams:
        by_length.setdefault(len(term), set()).add(term)
    pools={};frequency=Counter()
    for doc,names,components,facets,broad in prepared:
        signature=doc.get('retrieval_signature') or {}
        bodies=[_lexical_text(value) for value in [*names,*_strings(signature.get('search_phrases'))]]
        shared = set()
        for body in set(bodies):
            for length, terms in by_length.items():
                shared.update(terms.intersection(
                    body[start:start + length] for start in range(len(body) - length + 1)))
        identity=str(doc.get('id') or doc.get('concept_key') or '')
        pools[identity]=shared;frequency.update(shared)
    result={};count=len(prepared);rare_limit=max(3,math.ceil(count*.025))
    for identity,shared in pools.items():
        terms=sorted((term for term in shared if frequency[term]<=rare_limit),
                     key=lambda term:(-len(term),frequency[term],term))
        selected=[];used=set()
        for term in terms:
            if any(term in prior for prior in selected):
                continue
            position=text.find(term)
            while position>=0:
                span=set(range(position,position+len(term)))
                if not span&used:
                    selected.append(term);used.update(span);break
                position=text.find(term,position+1)
        result[identity]={'terms':selected,'characters':len(used),
            'weight':sum(len(term)*_term_weight(term,frequency,count) for term in selected)}
    return result


def _strict_phrase_superset(first,second):
    a=first.get('catalog_phrase_evidence',[]);b=second.get('catalog_phrase_evidence',[])
    return (len(a)>=2 and len(b)>=2
            and all(any(term in own for own in a) for term in b)
            and any(not any(term in other for other in b) for term in a))


def _named_condition_support(signature,positive):
    supported=[]
    for clause in signature.get('named_condition_sources',[]):
        objects=clause.get('objects',[]);conditions=clause.get('conditions',[])
        if not objects or not conditions or not clause.get('goal_terms'):
            continue
        if clause.get('zero_one_required') and not re.search(r'0[—－-]1|伯努利|指示变量|0和1|0与1',positive):
            continue
        if not any(_contains(positive,normalize(value)) for value in objects):
            continue
        def present(value):
            value=normalize(value)
            if value=='独立同分布':
                return _contains(positive,'独立同分布') or (_contains(positive,'独立') and _contains(positive,'同分布'))
            if value=='方差一致有界':
                return _contains(positive,value) or _contains(positive,'方差有界')
            return _contains(positive,value)
        if all(present(value) for value in conditions) and any(
                _contains(positive,normalize(value)) for value in clause['goal_terms']):
            supported.append({'method_id':clause['method_id'],'branch':clause['named_branch']})
    return supported


def rank(query: str, docs: list[dict], limit: int = 3) -> dict:
    """Return one supported selection, two ambiguous choices, or no match.

    A keyword/bigram overlap alone never qualifies. Optional neutral descriptors
    provide explicit objects, operations and conditions. The caller must still
    authenticate the selected source and independently interpret personal facts.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 12:
        raise ValueError('retrieval_limit_invalid')
    prepared, excluded_docs, terms, df = [], Counter(), set(), Counter()
    for doc in docs:
        why = exclusion_reason(doc)
        if why:
            excluded_docs[why] += 1
            continue
        names = _names(doc)
        components = _title_components(str(doc.get('title', '')))
        signature = doc.get('retrieval_signature') or {}
        if not isinstance(signature, dict):
            signature = {}
        facets = {key: tuple(dict.fromkeys(normalize(v) for v in _strings(signature.get(key)) if v.strip()))
                  for key in ('objects', 'operations', 'conditions', 'required_conditions', 'excluded_conditions')}
        vocabulary = set(names) | set(components)
        for key in ('objects', 'operations', 'conditions'):
            vocabulary.update(facets[key])
        terms.update(vocabulary)
        df.update(vocabulary)
        broad = (doc.get('knowledge_type') in {'parent', 'chapter', 'broad'}
                 or signature.get('broad') is True or signature.get('granularity') in {'parent', 'broad', 'chapter'}
                 or normalize(str(doc.get('title', ''))) in _BROAD)
        prepared.append((doc, names, components, facets, broad))
    constraints = analyze_query(query, terms)
    positive = constraints['positive']
    phrase_evidence=_catalog_phrase_evidence(positive,prepared)
    explicit_focus=[_lexical_text(match.group(1)) for match in re.finditer(
        r'(?:我问(?:的)?(?:是)?|我要查(?:的)?(?:是)?|只查|重点(?:是|在))([^，,。；;！？!?\n]+)',positive)]
    bare = _bare_request(positive)
    meaningful = {term for term in terms if len(term) >= 2 and term not in _GENERIC}
    query_terms = _longest_terms(positive, meaningful)
    count = len(prepared)
    weights = {term: _term_weight(term, df, count) for term in query_terms}
    query_weight = sum(weights.values())
    positive_ids = set(constraints['formal_ids'])
    identity_scoped = bool(positive_ids and prepared and all(
        positive_ids <= set(doc.get('formal_ids', [])) for doc, *_ in prepared))
    object_owners = {}
    for doc, names, components, facets, broad in prepared:
        for term in facets['objects']:
            if not broad and len(term) >= 3 and term not in _SCOPED_OBJECT_TOO_BROAD:
                object_owners.setdefault(term, set()).add(str(doc.get('id') or doc.get('concept_key')))
    candidates, rejected = [], Counter()
    normalized_query = normalize(query)
    identity_query = bool(_IDENTITY.match(normalized_query) and re.fullmatch(r'[a-z0-9_.:/-]+', normalized_query))
    for doc, names, components, facets, broad in prepared:
        identity = str(doc.get('id') or doc.get('concept_key') or '')
        if not identity or not names:
            continue
        exact_id = normalized_query in {normalize(identity), normalize(str(doc.get('concept_key', '')))}
        if identity_query and not exact_id:
            continue
        special_reason=special_scope_reason(doc,positive)
        if special_reason and not exact_id:
            rejected[special_reason]+=1
            continue
        all_terms = set(names) | set(components)
        for key in ('objects', 'operations', 'conditions'):
            all_terms.update(facets[key])
        route_terms = [term for item in constraints['excluded'] if item['scope'] == 'route' for term in item['terms']]
        label_terms = [term for item in constraints['excluded'] if item['scope'] == 'label' for term in item['terms']]
        rejected_identity = any(any(_contains(term, excluded) for term in names) for excluded in route_terms)
        remaining_components = [term for term in components if not any(_contains(term, excluded) for excluded in route_terms)]
        positive_component = any(_contains(positive, term) for term in remaining_components)
        if rejected_identity and not positive_component:
            rejected['excluded_route'] += 1
            continue
        if normalize(str(doc.get('title', ''))) in label_terms:
            rejected['excluded_label'] += 1
            continue
        conflict = any(_contains(positive, term) for term in facets['excluded_conditions'])
        for term in facets['required_conditions']:
            if term in route_terms or any(_contains(positive, prefix + term) for prefix in ('非', '不', '无')):
                conflict = True
        if conflict and not constraints['questioning_applicability']:
            rejected['condition_conflict'] += 1
            continue
        hits = {key: _longest_terms(positive, facets[key]) for key in ('objects', 'operations', 'conditions')}
        # Rejecting one presentation cue does not delete its entire knowledge
        # point (e.g. an ODE has both integral-factor and general-form routes).
        hits['operations'] = [term for term in hits['operations'] if not any(_contains(term, excluded) for excluded in route_terms)]
        # Repeating the same noun in two descriptor fields is one piece of
        # evidence, not an object+operation pair.
        hits['operations'] = [term for term in hits['operations'] if not any(term == obj for obj in hits['objects'])]
        named = [name for name in names if _contains(positive, name)]
        component_hits = [term for term in remaining_components if _contains(positive, term)]
        exact_name = bare in names
        exact_title = bare == normalize(str(doc.get('title', '')))
        signature = doc.get('retrieval_signature') or {}
        named_condition_support=_named_condition_support(signature,positive)
        title_scope = _title_scope(str(doc.get('title', '')), signature)
        scope_mentions = []
        if title_scope and not exact_id:
            scope_supported = any(term in positive for term in title_scope['aliases'])
            if not scope_supported or _dimension_conflict(title_scope['parent'], positive):
                rejected['parent_scope_not_supported'] += 1
                continue
            # Explicitly discussing the scope is object evidence, not a claim
            # that its assumptions hold. Do not count a repeated scope word
            # ("正态" inside "联合正态") again as a separate condition.
            scope_mentions = _longest_terms(positive, title_scope['aliases'])
            hits['objects'] = list(dict.fromkeys([*hits['objects'], *scope_mentions]))
        hits['operations'] = [term for term in hits['operations']
                              if not any(term in scope for scope in scope_mentions)]
        hits['conditions'] = [term for term in hits['conditions']
                              if not any(term in obj for obj in hits['objects'])]
        covered = [term for term in query_terms if any(term == own or term in own for own in all_terms)]
        coverage = sum(weights[term] for term in covered) / query_weight if query_weight else 0.0
        rare_ops = [term for term in hits['operations'] if term not in _GENERIC_OP
                    and df[term] <= max(3, math.ceil(count * 0.025))]
        specific_named = [name for name in named if len(name) >= 4 and name not in _BROAD]
        if broad and not exact_name and not exact_id:
            rejected['broad_without_explicit_request'] += 1
            continue
        kind = None
        if exact_id:
            kind = 'exact_identity'
        elif exact_name:
            kind = 'exact_title' if exact_title else 'exact_declared_alias'
        elif named_condition_support:
            kind = 'source_named_condition_and_goal'
        elif specific_named and coverage >= .72:
            kind = 'specific_name_in_request'
        elif component_hits and coverage >= .72:
            kind = 'specific_compound_subtopic'
        elif hits['objects'] and hits['operations'] and coverage >= .55:
            kind = 'object_and_operation'
        elif hits['objects'] and hits['conditions'] and coverage >= .65:
            kind = 'object_and_condition'
        elif len(rare_ops) >= 2 and coverage >= .60:
            if identity_scoped or hits['objects']:
                kind = 'distinctive_operation_pair'
            else:
                rejected['operation_pair_requires_object_or_identity'] += 1
        elif len(hits['conditions']) >= 2 and coverage >= .75:
            kind = 'explicit_condition_combination'
        elif identity_scoped and not conflict and any(object_owners.get(term) == {identity} for term in hits['objects']):
            kind = 'unique_specific_object_in_exact_question_scope'
        lexical=phrase_evidence.get(identity,{'terms':[],'characters':0,'weight':0})
        # Two fragments of the same object are not an object+operation proof.
        discriminators=[term for term in lexical['terms']
                        if not any(term in obj for obj in hits['objects'])]
        unsupported_route_pair=(len(rare_ops)>=2 and not identity_scoped and not hits['objects'])
        focus_supported=(not explicit_focus or any(
            term in focus for focus in explicit_focus for term in lexical['terms']))
        title_objects=[term for term in facets['objects']
                       if len(term)>=3 and term in normalize(str(doc.get('title','')))]
        title_object_supported=not title_objects or bool(hits['objects'])
        lexical_supported=(not broad and len(lexical['terms'])>=2 and lexical['characters']>=6
                           and bool(discriminators) and not unsupported_route_pair
                           and focus_supported and title_object_supported)
        if kind is None and lexical_supported:
            kind='distinctive_catalog_phrases'
        if kind is None:
            rejected['insufficient_specific_evidence'] += 1
            continue
        # Known-term coverage can be 1 merely because the rest of a concrete
        # action is out of vocabulary. It cannot promote an object name into a
        # precise operation. Complete definition/name requests remain usable.
        object_only = kind in {'specific_name_in_request', 'specific_compound_subtopic',
                               'unique_specific_object_in_exact_question_scope'}
        matched_names = [*named, *component_hits]
        extra_action = _operation_request(positive, matched_names)
        independent_action_support = [term for term in [*hits['operations'], *hits['conditions']]
                                      if not any(term in name for name in matched_names)]
        if object_only and extra_action and not independent_action_support:
            rejected['additional_operation_not_supported'] += 1
            continue
        if constraints['uncertain'] and kind not in {'exact_identity', 'exact_title', 'exact_declared_alias'}:
            rejected['negation_needs_discrimination'] += 1
            continue
        score = (1000.0 if exact_id else 960.0 if exact_title else 920.0 if exact_name else
                 40.0 + 30.0 * coverage +
                 12.0 * min(2, len(hits['objects'])) + 17.0 * min(2, len(hits['operations'])) +
                 9.0 * min(2, len(hits['conditions'])) +
                 (min(24, max(map(len, specific_named))) if specific_named else 0))
        if not exact_name and not exact_id:
            score += min(15.0, sum(_term_weight(term, df, count) for term in set(covered)))
            if lexical_supported:
                score += lexical['weight']
        reasons = [kind, 'declared_neutral_metadata_only']
        if named_condition_support:
            reasons.append('source_named_condition_and_goal_supported')
        reference_only = bool(broad)
        if reference_only:
            reasons.append('explicit_parent_reference_not_fine_point')
        if title_scope:
            reasons.append('parent_scope_mentioned_not_asserted')
        if constraints['excluded']:
            reasons.append('requested_route_exclusions_applied')
        if conflict:
            reasons.append('applicability_question_not_route_approval')
        candidates.append({'id': identity, 'concept_key': doc.get('concept_key'), 'score': round(score, 6),
                           'reasons': reasons, 'match_kind': kind, 'coverage': round(coverage, 6),
                           'catalog_phrase_evidence':lexical['terms'] if lexical_supported else [],
                           'facet_counts': {key: len(value) for key, value in hits.items()},
                           'operation_matches':[term for term in hits['operations'] if term not in _GENERIC_OP],
                           'primary_operation_matches':_longest_terms(positive,signature.get('primary_operations',[])),
                           'named_condition_support':named_condition_support,
                           'record_scope_required': kind == 'unique_specific_object_in_exact_question_scope',
                           'reference_only': reference_only, 'fine_point': not reference_only,
                           'personal_evidence_eligible': not reference_only,
                           'requires_scope_check': True, 'not_proof_of_current_error': True,
                           'applicability_confirmed': False})
    candidates.sort(key=lambda row: (row['match_kind'] not in {'exact_identity','exact_title','exact_declared_alias'},
        not bool(row.get('named_condition_support')),-row['score'],row['id']))
    if not candidates:
        vague_history = (bool(re.search(r'(?:我|本人).{0,6}(?:说过|做过|学过)|(?:上次|那次).*(?:题|记录)|(?:找|查).{0,5}(?:记录|原话)', positive))
                         and any(_contains(positive, term) for term in ('条件', '公式', '方法', '步骤', '过程')))
        mathematical = any(_contains(positive, term) for term in _MATH_BROAD_HINTS)
        pseudo_query = exclusion_reason({'title': normalize(query)}) is not None
        underspecified_operations = bool(rejected['operation_pair_requires_object_or_identity'])
        status = 'ambiguous' if not identity_query and not pseudo_query and (mathematical or vague_history or underspecified_operations) and not constraints['uncertain'] else 'no_match'
        ranked = []
    else:
        top = candidates[0]
        gap = top['score'] - candidates[1]['score'] if len(candidates) > 1 else None
        minimum_gap = max(8.0, top['score'] * .10)
        # A declared exact title has priority over a noncanonical alias, but
        # duplicate aliases/identities remain ambiguous rather than arbitrarily
        # resolving by the stable-ID sort order.
        title_priority = (top['match_kind'] in {'exact_identity', 'exact_title'} and len(candidates) > 1
                          and candidates[1]['match_kind'] != top['match_kind'])
        discriminator_priority=(len(candidates)>1 and not top['reference_only']
            and top['match_kind'] not in {'exact_declared_alias'}
            and all(other['match_kind'] not in {'exact_identity','exact_title','exact_declared_alias'}
                    and _strict_phrase_superset(top,other) for other in candidates[1:]))
        operation_priority=(len(candidates)>1 and bool(top.get('operation_matches'))
            and all(not other.get('operation_matches') and other['match_kind'] not in
                    {'exact_identity','exact_title','exact_declared_alias'} for other in candidates[1:]))
        named_condition_priority=bool(top.get('named_condition_support') and
            all(not other.get('named_condition_support') for other in candidates[1:]))
        ambiguous = gap is not None and gap < minimum_gap and not title_priority and not discriminator_priority and not operation_priority and not named_condition_priority
        status = 'ambiguous' if ambiguous else 'matched'
        ranked = candidates[:min(limit, 2)] if ambiguous else candidates[:1]
    return {'schema': REVISION, 'status': status, 'ranked': ranked,
            'constraints': constraints, 'query_term_count': len(query_terms),
            'exact_question_scope': identity_scoped,
            'reference_only': bool(status == 'matched' and ranked and ranked[0]['reference_only']),
            'personal_evidence_eligible': bool(status == 'matched' and ranked and ranked[0]['personal_evidence_eligible']),
            'excluded_document_counts': dict(excluded_docs), 'rejected_counts': dict(rejected),
            'score_semantics': 'ordering_only_not_truth_or_mastery_probability',
            'requires_discrimination': status == 'ambiguous', 'result_count_is_not_a_goal': True}
