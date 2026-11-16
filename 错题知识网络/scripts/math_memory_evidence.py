"""Bounded identity/date routing and exact personal-record locators.

This reader never opens a raw conversation, derives a new assessment, or writes
learning state.  Protected queries return before touching private record rows.
"""
from __future__ import annotations

from contextlib import closing
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata

INDEX = Path('错题知识网络/个人知识点索引/index.sqlite3')
FORMAL = re.compile(r'(?<![A-Za-z0-9])((?:GS|LA|PR|MX))\s*[-_－]?\s*(\d{1,4})(?!\d)', re.I)
RAW_ID = r'(?:GS|LA|PR|MX)\s*[-_－]?\s*\d{1,4}'
KEY = re.compile(r'MATH-CONCEPT-[0-9a-f]{24}\Z')
QUOTED = re.compile(r'[“「‘]([^”」’]{2,120})[”」’]|(?<![A-Za-z0-9])[\"\']([^\"\']{2,120})[\"\'](?![A-Za-z0-9])')
# These are lexical variants of the same mathematical condition. They never
# rewrite variables, operators, signs, or the polarity of a statement.
MATH_WORD_EQUIVALENCES = (('行满秩','满行秩'), ('列满秩','满列秩'))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def requested_personal_history(query):
    return bool(re.search(r'原话|首答|哪次|那次|上次|第一次|最早|最近一次|最新.*反馈|个人.*记录|学习记录|旧卡|旧题|作答记录|错因记录|历史|讲法|偏好|'
                          r'(?:我|本人)(?:当时|之前|以前|曾|说|报|有没有|能否|是否|已经|理解了|懂了)|'
                          r'我(?:真正|亲自|当时|实际){0,3}写(?:过|了)', query or ''))


def _quote_normalize(text):
    text=_math_normalize(text)
    kept=[];depth=0
    for position,char in enumerate(text):
        if char in '([{':depth+=1
        if char in ')]}':depth=max(0,depth-1)
        derivative_prime=char=="'" and position>0 and text[position-1] in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'" and position+1<len(text) and text[position+1] in "('"
        if char in '，,。；;：:“”\"\'？?！!' and depth==0 and not derivative_prime:
            continue
        kept.append(char)
    text=''.join(kept)
    for source,target in (('拆开','拆分'),('分拆','拆分'),('不要求','不需要'),('不必','不需要'),('不用','不需要'),('无须','不需要'),('相同','相等')):
        text=text.replace(source,target)
    for group in MATH_WORD_EQUIVALENCES:
        for source in group[1:]:text=text.replace(source,group[0])
    text=re.sub(r'不(?:影响|改变)(?:矩阵的|其)?秩','不改变秩',text)
    text=re.sub(r'独立(?:的)?(?:、|且|和)?同分布(?:的)?','独立同分布',text)
    return text


def _target_quotations(query):
    """Exclude quotations used only to qualify the requested evidence.

    For example, a request can locate a teaching preference while explicitly
    warning not to treat a second quoted conjecture as a correct condition.
    That warning neither changes the target utterance nor asserts its truth.
    """
    result=[]
    for match in QUOTED.finditer(query):
        prefix=re.split(r'[，,。；;！？?]',query[:match.start()])[-1]
        suffix=query[match.end():match.end()+36]
        interpretive_warning=(re.search(r'(?:不要|别|不能|不应)(?:把|将).{0,16}$',prefix)
                              and re.search(r'(?:当成|当作|视为|认为|作为).{0,12}(?:正确|事实|条件|结论|掌握)',suffix))
        if not interpretive_warning:
            result.append(match)
    return result


def _teaching_actions(text):
    """Small compositional locators for reported teaching instructions.

    These identify an action, its direction, and any named operands; they do
    not establish a current preference. They deliberately do not turn a bare
    mathematical topic or a generic refusal into a unique user statement.
    """
    definitions=(
        ('rename',r'(?:换|改|起|另取)[^，,。；;！？?]{0,10}(?:名字|名称|称呼)|重命名',('名字','名称','称呼','重命名')),
        ('substitute',r'替代|替换|代换|代替',('替代','替换','代换','代替')),
        ('derive_or_prove',r'推导(?:证明)?|证明',('推导','证明')),
        ('apply',r'应用',('应用',)),
        ('show_calculation',r'算出来|算给[^，,。；;！？?]{0,6}看|计算过程',('算出来','算给','计算过程')),
    )
    result=[]
    for clause in re.split(r'[，,。；;！？?\n、]|而(?=要|希望)|但(?=要|希望)',_math_normalize(text)):
        for action,pattern,surfaces in definitions:
            for match in re.finditer(pattern,clause):
                prefix=clause[:match.start()]
                # Restrict proof/application mentions to an instruction about
                # explanation. A theorem's mathematical content is not style.
                if action in {'derive_or_prove','apply'} and not re.search(r'讲|解释|看|展示|学习',prefix):
                    continue
                negative=list(re.finditer(r'不想|不要|不用|不使用|不需要|不必|无需|别|不讲|不看|不愿',prefix))
                positive=list(re.finditer(r'想|要|希望|用|讲|看|请|直接|只',prefix))
                if negative:
                    last=negative[-1]
                    if re.search(r'不(?:是|想|要)?(?:说|表示|认为|觉得)?$',prefix[:last.start()]):
                        state='uncertain'
                    else:state='negative'
                elif positive or action=='show_calculation':state='positive'
                else:continue
                objects=[]
                if action=='substitute':
                    objects.extend(a+b for a,b in re.findall(r'(?<![A-Za-z])([A-Za-z])(?:和|与|跟|及)([A-Za-z])(?![A-Za-z])',clause))
                if action=='rename':
                    target=re.search(r'(?:给|把)(.{1,30})$',prefix)
                    if target:objects.append(target.group(1))
                result.append({'action':action,'state':state,'objects':objects,'surfaces':list(surfaces)})
    return result


def _teaching_match(wanted,source):
    requested=_teaching_actions(wanted);available=_teaching_actions(source)
    normalized=_math_normalize(source)
    supported=[]
    conflict=False
    for request in requested:
        same=[v for v in available if v['action']==request['action']]
        states={v['state'] for v in same}
        operands=True
        for obj in request['objects']:
            if request['action']=='substitute':
                operands &= any(obj in v['objects'] for v in same)
            else:operands &= obj in normalized
        matched=bool(states=={request['state']} and request['state']!='uncertain' and operands)
        if matched:supported.append(request['action'])
        else:conflict=True
    return {'supported':bool(requested) and not conflict,
            'conflict':conflict,'actions':requested,'matched_actions':supported}


def _quote_targets(query):
    """Literal historical utterances are targets, not route exclusions."""
    targets=[m.group(1) or m.group(2) for m in _target_quotations(query)]
    for match in re.finditer(r'(?:只卡(?:在)?|只(?:有)?这(?:一)?步)([^，,。；;！？?]{2,40})',query):
        phrase=match.group(1)
        phrase=re.sub(r'^(?:这一步|这步|如何|怎么|怎样)+','',phrase)
        phrase=re.split(r'找|查|那条|那次|记录',phrase)[0]
        phrase=re.sub(r'(?:这一步|这步|那项|这一项|的问题|这件事)$','',phrase)
        targets.append(phrase)
    for match in re.finditer(r'我说(?:过)?(?:的)?([^，,。；;！？?]{2,30})',query):
        phrase=re.split(r'之后|以后|后|那条|那次|记录|可以|能否|是否|能把',match.group(1))[0]
        if not phrase.startswith('只卡') and not re.fullmatch(r'(?:过)?(?:什么|哪些|哪句|啥|什么内容|哪些话)(?:了|呢|吗)?',phrase):
            targets.append(phrase)
    return list(dict.fromkeys(_quote_normalize(t) for t in targets if len(_quote_normalize(t))>=2))[:4]


def request_intent(query):
    """Quoted past speech is evidence content, never a current route ban."""
    query=str(query or '')
    spans=[]
    reported_spans=[]
    history_cue=bool(re.search(r'原话|那句|那条|那次|记录|说过|写过|曾说',query)
        or re.search(r'(?:我|本人)(?:当时|之前|以前|曾经|那时)',query))
    for match in _target_quotations(query):
        prefix=query[max(0,match.start()-18):match.start()]
        current_topic=bool(re.search(r'(?:我|本人)(?:现在|当前|这次|本次)?(?:问|说|指|强调)(?:的)?是[^，,。；;]{0,8}$',prefix))
        if history_cue and not current_topic and (re.search(r'(?:我|本人).{0,12}(?:说|写|提|问|报)[^，,。；;]{0,6}$',prefix)
                            or re.search(r'原话|原句|逐字|那句',query)):
            spans.append({'start':match.start(),'end':match.end(),'text':match.group(1) or match.group(2)})
    if history_cue:
        pattern=r'(?:我|本人)(?:当时|之前|以前|曾经|曾|那时|有没有|是否|是不是){0,2}(?:说过|写过|提过|问过|报过|要求|希望|强调|提醒|坚持|说|写|问|报)(?:的)?([^，,。；;！？?]{2,100})'
        for match in re.finditer(pattern,query):
            # "我问的是 X" declares this request's topic. A later "找记录"
            # does not turn it into a quotation of a past user turn.
            if re.match(r'(?:我|本人)(?:问|说|强调)(?:的)?是',match.group()):
                continue
            start,end=match.span(1)
            if any(start>=s['start'] and start<s['end'] for s in spans):
                continue
            text=re.split(r'那次|那条|的记录|记录|能否|是否|可以|能把',match.group(1))[0]
            if len(text)>=2 and not re.fullmatch(r'(?:过)?(?:什么|哪些|哪句|啥|什么内容|哪些话)(?:了|呢|吗)?',text):
                span={'start':start,'end':start+len(text),'text':text.strip('“”\"\'')}
                spans.append(span);reported_spans.append(span)
    # An unquoted report can coordinate several method preferences. Preserve
    # each one, but stop before an explicitly current search instruction.
    for reported in reported_spans:
        position=reported['end']
        for _ in range(3):
            following=re.match(r'\s*[，,；;]\s*([^，,。；;！？?]{2,100})',query[position:])
            if not following:break
            phrase=following.group(1)
            if re.match(r'(?:我)?(?:现在|当前|这次|本次)|(?:请|帮我)?(?:不查询?|不检索|不找|不要查|别查|排除|找|查|检索|返回)',phrase):
                break
            if not _method_polarities(phrase) and not _teaching_actions(phrase):break
            start=position+following.start(1);end=position+following.end(1)
            if any(start<s['end'] and end>s['start'] for s in spans):break
            spans.append({'start':start,'end':end,'text':phrase})
            position=end
    current=query
    for span in sorted(spans,key=lambda v:v['start'],reverse=True):
        current=current[:span['start']]+'历史表述'+current[span['end']:]
    explicit_current=bool(re.search(r'不查(?:询)?|不检索|不找|不要查|别查|排除|不要用|不想(?:再)?(?:用)?|不用|不采用|别用|不是.+而是',current))
    history_search=bool(re.search(r'原话|首答|哪次|那次|上次|说过|写过|提过|问过|报过|学习记录|旧卡|旧题|作答记录|错因记录|记录|历史|讲法|偏好',query)
        or re.search(r'(?:我|本人)(?:当时|之前|以前|曾经|那时)|(?:找|查|定位|返回|回看).{0,30}(?:第一次|最早)',query)
        or re.search(r'(?:我|本人).{0,12}(?:掌握|理解了|懂了|会了|学过|做过|会不会|独立(?:做|完成|解决|复现|写|算)|无提示(?:做|完成|解决|复现|写|算))',query))
    quote_lookup=bool(re.search(r'原话|原句|逐字|一字不差|确切措辞',query))
    verify_claim=bool(history_search and re.search(
        r'(?:核实|验证|查证|证实|能否确认).{0,32}(?:我|本人|说|写|断言|表述|当时)|'
        r'(?:我|本人)(?:当时|以前|之前|曾经|那时)?(?:是否|有没有|是不是|能否)|'
        r'(?:是否|有没有|是不是).{0,12}(?:说过|写过|曾说|断言)',query))
    history_goal=('quote_lookup' if quote_lookup else 'claim_verification' if verify_claim
                  else 'record_lookup' if history_search else 'general')
    pinpoint=bool(spans or re.search(r'原话|那句|那条|那次|哪次|首答|具体记录|只卡|取错|用错|漏减|漏了|写错',query)
                  or history_search and re.search(r'(?:找|查|定位|对应)[^。！？?]{0,80}记录',query)
                  or history_search and _math_atoms(query))
    return {'historical_statement':bool(spans),'history_search':history_search,
            'pinpoint_record':pinpoint,
            'history_goal':history_goal,'requires_statement_verification':history_goal in {'quote_lookup','claim_verification'},
            'historical_spans':spans,'current_constraint_text':current,
            'current_constraint_active':explicit_current,
            'mode':'historical_statement' if spans and history_search else 'personal_record' if history_search else 'general'}


def _math_normalize(text):
    text=unicodedata.normalize('NFKC',str(text))
    text=re.sub(r'\\(?:operatorname|mathrm|mathbb)\{(rank|cov|var|dim|det|E|D|P|B|N)\}',
                lambda m:'r' if m.group(1).lower()=='rank' else m.group(1).lower() if len(m.group(1))>1 else m.group(1),text,flags=re.I)
    text=re.sub(r'(?<![A-Za-z])(rank|cov|var|dim|det)(?=\()',
                lambda m:'r' if m.group(1).lower()=='rank' else m.group(1).lower(),text,flags=re.I)
    for source,target in ((r'\operatorname{rank}','r'),(r'\mathrm{rank}','r'),('rank(','r('),
            (r'\left',''),(r'\right',''),(r'\lambda','λ'),('lambda','λ'),
            (r'\leq','≤'),(r'\le','≤'),('<=','≤'),(r'\geq','≥'),(r'\ge','≥'),('>=','≥'),
            (r'\neq','≠'),('!=','≠'),('−','-'),('－','-'),(r'\mid','|'),
            (r'\cdot','*'),(r'\times','*'),(r'\(','') ,(r'\)','')):
        text=text.replace(source,target)
    return re.sub(r'\s+','',text)


def _math_atoms(text):
    text=_math_normalize(FORMAL.sub(' ',str(text)))
    found=[]
    for match in re.finditer(r'(?<![A-Za-z])(?:cov|var|dim|det|r|E|D|P|f[\'′]?|g|h|B|N)\(',text):
        start=match.start();position=match.end();depth=1
        while position<len(text) and position-start<90 and depth:
            depth += (text[position]=='(')-(text[position]==')')
            position+=1
        atom=text[start:position]
        if not depth and re.search('[A-Za-zλ0-9]',atom[atom.index('(')+1:-1]) and len(atom)>3:
            found.append(atom)
    found.extend(match.group() for match in re.finditer(r'(?<![A-Za-z])[A-Z]-(?:λ|\d+(?:\.\d+)?)I(?![A-Za-z])',text))
    # The operands alone cannot establish an equality, inequality, or an
    # arithmetic operation. Keep the complete visible expression as another
    # required anchor, while excluding saved IDs and calendar dates.
    for match in re.finditer(r"[A-Za-zλ0-9][A-Za-zλ0-9_+\-*/^().,'′|<>=≤≥≠]*",text):
        expression=match.group().strip('.,')
        if (re.search(r'[A-Za-zλ]',expression) and re.search(r'[+\-*/^<>=≤≥≠]',expression)
                and not FORMAL.fullmatch(expression) and not KEY.fullmatch(expression)
                and len(expression)<=160):
            found.append(expression)
    return list(dict.fromkeys(found))[:8]


def _record_comparison_content(query, intent):
    """Separate a current contrast from the utterance being located.

    In a record search, "I wrote A, rather than B" uses B to describe the
    distinction; it does not require one saved user sentence to contain both.
    Explicit quotations and verification requests keep every expression.
    """
    if intent.get('history_goal')!='record_lookup':
        return query,[]
    spans=intent.get('historical_spans',[])
    comparison=[];content=query
    pattern=r'[，,；;]\s*(?:而不是|而非)([^，,。；;！？?\n]+)'
    matches=list(re.finditer(pattern,query))
    for match in reversed(matches):
        if any(match.start()<s['end'] and match.end()>s['start'] for s in spans):
            continue
        comparison.extend(_math_atoms(match.group(1)))
        content=content[:match.start()]+'，当前对比项'+content[match.end():]
    return content,list(dict.fromkeys(comparison))


def evidence_anchors(query):
    """Neutral mathematical anchors for retrieval, not new learner claims."""
    import math_memory_catalog as catalog
    intent=request_intent(query)
    literals=_quote_targets(query)
    literals += [_quote_normalize(s['text']) for s in intent['historical_spans']]
    literals=list(dict.fromkeys(v for v in literals if 2<=len(v)<=100))[:6]
    # Current exclusions constrain which record is requested. Past quoted
    # negatives remain literal evidence targets and retain their polarity.
    current=intent['current_constraint_text']
    from math_memory_retrieval import analyze_query
    if current.strip():
        analyzed=analyze_query(current)
        positive=analyzed.get('positive_text',current)
    else:
        positive=current
    content=' '.join([positive,*[s['text'] for s in intent['historical_spans']]])
    normalized=_math_normalize(content)
    math_content,comparison_atoms=_record_comparison_content(query,intent)
    math_atoms=_math_atoms(math_content if comparison_atoms else content)
    vocab=[v for v in (*catalog.OBJECTS,*catalog.OPERATIONS,*catalog.CONDITIONS)
           if len(v)>=3 and v not in catalog.BROAD]
    vocab += [term for group in catalog.EQUIVALENCES for term in group if len(term)>=3 and term not in catalog.BROAD]
    # These are operation descriptions, independent of question IDs/dates.
    vocab += ['维数','拆分','展开','取错矩阵','矩阵选取','取错对象','无穷远','端点','上端','下端','平方','系数','二项','近似']
    vocab += [term for group in MATH_WORD_EQUIVALENCES for term in group]
    terms=sorted({term for term in vocab if _quote_normalize(term) in _quote_normalize(content)},key=lambda s:(-len(s),s))
    terms=list(dict.fromkeys(_quote_normalize(term) for term in terms))
    terms=[term for i,term in enumerate(terms) if not any(term in other for other in terms[:i])]
    required=[]
    if '二项' in normalized or any(atom.startswith('B(') for atom in math_atoms):
        required.append('binomial')
    if '维数' in normalized or '维度' in normalized or any(atom.startswith('dim(') for atom in math_atoms):
        required.append('dimension')
    return {'literals':literals,'math_atoms':math_atoms,'comparison_math_atoms':comparison_atoms,'terms':terms[:12],
            'required_objects':required,'intent':intent,
            'teaching_actions':_teaching_actions('；'.join(s['text'] for s in intent['historical_spans']))}


def _literal_supported(wanted, source):
    """A positive fragment inside its explicit negation is not confirmation."""
    for match in re.finditer(re.escape(wanted),source):
        prefix=source[max(0,match.start()-14):match.start()]
        if not re.search(r'(?:并非|不是|没有(?:说|写|认为)?|没|不(?:一定|是|能|会|想|要)?|未必|不见得|非)(?:说|写|认为|觉得)?$',prefix):
            return True
    return False


def user_evidence_match(query, text):
    """Support from one source sentence; callers preserve role and ambiguity.

    For formal annotations the caller must label the result annotation-only;
    this function never asserts the learner said an annotation's text.
    """
    anchors=evidence_anchors(query)
    raw=_math_normalize(text);natural=_quote_normalize(text)
    literal=[value for value in anchors['literals'] if _literal_supported(value,natural)]
    math_hits=[value for value in anchors['math_atoms'] if value in raw]
    import math_memory_catalog as catalog
    term_hits=[]
    for term in anchors['terms']:
        options=[term]
        for group in (*catalog.EQUIVALENCES,*MATH_WORD_EQUIVALENCES):
            if term in group:options.extend(group)
        if term=='维数':options.extend(('维度','n-r(','dim('))
        if term=='二项':options.extend(('B(','二项分布'))
        if term=='联合正态':options.extend(('二维正态','二元正态'))
        if term=='拆分':options.extend(('拆开','分拆'))
        if term=='取错矩阵':options.extend(('哪个矩阵','矩阵取错','用错矩阵'))
        if any(_quote_normalize(value) in natural for value in options):term_hits.append(term)
    missing=[]
    if 'binomial' in anchors['required_objects'] and not re.search(r'二项|(?<![A-Za-z])B\(|np\(1-p\)',raw):missing.append('binomial')
    if 'dimension' in anchors['required_objects'] and not re.search(r'维数|维度|dim\(|[A-Za-z0-9]-r\(',raw):missing.append('dimension')
    # Different operands or function arguments are not made equivalent by a
    # common word such as "matrix". A specific expression needs exact support.
    formula_conflict=bool(anchors['math_atoms'] and len(math_hits)<len(anchors['math_atoms']))
    quoted=[_quote_normalize(m.group(1) or m.group(2)) for m in _target_quotations(query)]
    wanted_text='；'.join(s['text'] for s in anchors['intent']['historical_spans'])
    teaching=_teaching_match(wanted_text or '；'.join(quoted),text)
    refusal_query=_declined_routes(wanted_text or ' '.join(quoted))
    refusal_source=_declined_routes(text)
    same_refusal=bool(refusal_query and refusal_query<=refusal_source)
    opposite_refusal=bool(refusal_query and not same_refusal)
    states_q=_ability_states(wanted_text or ' '.join(quoted))
    states_s=_ability_states(text)
    state_conflict=bool(states_q and states_s and states_q.isdisjoint(states_s))
    methods_q=_method_polarities(wanted_text or '；'.join(quoted))
    methods_s=_method_polarities(text)
    method_conflict=any(states!=methods_s.get(method) or 'uncertain' in states
                        for method,states in methods_q.items())
    compatible=not missing and not formula_conflict and not state_conflict and not opposite_refusal and not method_conflict and not teaching['conflict']
    supported=bool(compatible and (
        literal or math_hits or teaching['supported'] or len(term_hits)>=2 or
        len(term_hits)==1 and len(anchors['terms'])==1 and
            (len(term_hits[0])>=4 or term_hits[0] in {'行满秩','列满秩'})))
    if quoted:
        supported=bool((any(_literal_supported(value,natural) for value in quoted) or same_refusal or teaching['supported'])
                       and compatible)
        if anchors['intent']['requires_statement_verification'] and len(quoted)>1:
            supported=bool(compatible and (all(_literal_supported(value,natural) for value in quoted)
                                           or teaching['supported']))
    elif same_refusal:
        supported=compatible
    if anchors['intent']['requires_statement_verification'] and wanted_text:
        # A shared technical noun can locate a record, but it cannot verify
        # that the requested assertion was ever made by the learner.
        supported=bool(supported and (literal or math_hits or same_refusal or teaching['supported']))
    kind='literal' if literal else 'historical_preference' if same_refusal or teaching['supported'] else 'math_expression' if math_hits else 'scoped_action' if supported else 'insufficient'
    return {'supported':supported,'score':sum(len(v) for v in literal)*4+len(math_hits)*10+len(term_hits)*2,
            'kind':kind,'matched_anchors':literal+math_hits+term_hits,
            'required_anchors':anchors['math_atoms']+anchors['required_objects'],
            'missing_objects':missing,'expression_not_supported':formula_conflict,
            'historical_polarity_conflict':state_conflict or opposite_refusal or method_conflict or teaching['conflict'],
            'method_polarity_conflict':method_conflict,
            'teaching_action_supported':teaching['supported'],
            'teaching_action_conflict':teaching['conflict'],
            'explicit_quoted_request':bool(quoted),
            'reason':'source_anchor_supported' if supported else 'insufficient_or_incompatible_source_anchor',
            'is_truth_or_mastery_probability':False}


def _method_polarities(text):
    """Bind affirmative/refusal language to its own method, never a substring.

    Opposite directions in one source stay ambiguous. This is evidence
    qualification, so a bare method mention cannot prove a stated preference.
    """
    import math_memory_catalog as catalog
    methods={term:term for term in catalog.OPERATIONS if len(term)>=2}
    for group in catalog.EQUIVALENCES:
        anchor=next((term for term in group if term in methods),None)
        if anchor:
            methods.update({term:anchor for term in group})
    negative=r'(?:不(?:太|怎么|很|再|那么|特别)?(?:想|愿意?|喜欢|打算)|不要|别|不用|不采用|不使用|不选择|放弃|没有用|没用|不是用|不能|不可以|不应该?|不必|无需|无须|不需要|不得|禁止|不适合)'
    positive=r'(?:想要?|要|希望|愿意|喜欢|打算|选择|使用|采用|套用|用|按|走)'
    suffix=r'(?:再|继续|直接|先|去)?(?:使用|采用|选择|套用|用|按|走)?(?:这个|这种|一下)?\s*$'
    negative_pattern=re.compile(negative+suffix)
    positive_pattern=re.compile(positive+suffix)
    result={}
    for clause in re.split(r'[，,。；;！？?\n]',str(text)):
        hits=[]
        for term,canonical_method in methods.items():
            hits.extend((match.start(),match.end(),canonical_method) for match in re.finditer(re.escape(term),clause))
        previous_end=-1;previous_state=None
        for start,end,method in sorted(hits,key=lambda row:(row[0],-row[1])):
            if start<previous_end:continue
            prefix=clause[:start]
            negative_hit=negative_pattern.search(prefix)
            positive_hit=positive_pattern.search(prefix)
            if negative_hit:
                state='negative';prefix_start=negative_hit.start()
            elif positive_hit:
                state='positive';prefix_start=positive_hit.start()
            elif previous_state and re.fullmatch(r'\s*(?:和|与|以及|及|、)\s*',clause[previous_end:start]):
                state=previous_state;prefix_start=previous_end
            else:
                previous_end=end;previous_state=None
                continue
            if re.search(r'(?:不|没|没有|不是|并非|不想|不要|不愿意?|不能|不一定|未必|不见得|不确定|没有决定|没决定)(?:说|表示|认为|觉得|真的|完全)?\s*$',prefix[:prefix_start]):
                state='uncertain'
            result.setdefault(method,set()).add(state)
            previous_end=end;previous_state=state
    return result


def _declined_routes(text):
    return {method for method,states in _method_polarities(text).items() if states=={'negative'}}


def _ability_states(text):
    values=set()
    if re.search(r'还不会|不会|不懂|没懂|不理解|没理解|没学过|不能独立',str(text)):
        values.add('not_yet_demonstrated_or_not_understood')
    if re.search(r'已经会|(?<!不)会了|(?<!不)(?<!没)懂了|(?<!不)(?<!没)理解了|明白了|(?<!不)能独立',str(text)):
        values.add('reported_understood_or_capable')
    return values


def _date_constraints(query):
    query=request_intent(query).get('current_constraint_text',query)
    values = []
    excluded=[]
    pattern = re.compile(r'(?<![A-Za-z0-9])(?:(20\d{2})[年/-])?(\d{1,2})[月/-](\d{1,2})(?:日|号)?(?![A-Za-z0-9])')
    for match in pattern.finditer(query or ''):
        year, month, day = match.groups()
        try:
            dt.date(int(year or 2000), int(month), int(day))
        except ValueError:
            continue
        # A cutoff is handled as a range, not as equality to one study day.
        before = (query or '')[max(0, match.start()-12):match.start()]
        after = (query or '')[match.end():match.end()+10]
        if not year and '月' not in match.group(0):
            math_prefix=re.search(r'(?:=|等于|分母|分子|系数|概率|密度|区间|比值|比例|比率|乘|除|因子|端点)\s*$',before)
            date_context=(re.search(r'日期|学习日|记录于|记于|截至|截止',before) or
                          re.match(r'那天|那次|当天|日|号|的学习记录|的复盘|那道题|那题',after))
            if math_prefix or not date_context:
                continue
        mode = 'through' if re.search(r'截至|截止|到$', before) or re.match(r'之前|以前|前', after) else 'on'
        value = {'year': int(year) if year else None, 'month': int(month), 'day': int(day), 'mode': mode}
        negated=bool(re.search(r'(?:不是|不在|不要(?:再)?(?:查|找|用|看)?|不查|不找|排除|别(?:再)?(?:查|找|用|看)?)\s*(?:日期|截至|截止)?$',before))
        destination=excluded if negated else values
        if value not in destination:
            destination.append(value)
    return values[:8],excluded[:8]


def _dates(query):
    return _date_constraints(query)[0]


def invalid_date_scope(query):
    current=request_intent(query)['current_constraint_text']
    pattern=re.compile(r'(?<![A-Za-z0-9])(?:(20\d{2})[年/-])?(\d{1,2})[月/-](\d{1,2})(?:日|号)?(?![A-Za-z0-9])')
    for match in pattern.finditer(current):
        year,month,day=match.groups()
        before=current[max(0,match.start()-12):match.start()];after=current[match.end():match.end()+8]
        explicit=bool(year or '月' in match.group() or re.search(r'日期|学习日|截至|截止',before) or re.match(r'那天|那次|当天|日|号',after))
        if not explicit:continue
        try:dt.date(int(year or 2000),int(month),int(day))
        except ValueError:return True
    return False


def query_scope(repo_root, query='', *, formal_id=None, source_id=None):
    """Resolve explicit identifiers before semantic matching, never guess IDs."""
    root = Path(repo_root)
    query = query or ''
    intent=request_intent(query)
    constraints_query=intent['current_constraint_text']
    if invalid_date_scope(query):
        return {'status':'invalid_date_scope','formal_ids':[],'dates':[],
                'request_intent':intent,'personal_requested':intent['history_search']}
    embedded = list(dict.fromkeys(f'{m.group(1).upper()}-{int(m.group(2)):03d}' for m in FORMAL.finditer(constraints_query)))
    from math_memory_retrieval import analyze_query
    excluded = analyze_query(constraints_query).get('excluded', []) if constraints_query.strip() else []
    rejected_ids = {f'{m.group(1).upper()}-{int(m.group(2)):03d}' for item in excluded
                    for m in FORMAL.finditer(item.get('text', ''))}
    positive_overrides = set()
    identity_patterns = (
        rf'不是\s*(?P<bad>{RAW_ID})\s*[，,]?\s*(?:而)?是\s*(?P<good>{RAW_ID})',
        rf'(?P<good>{RAW_ID})\s*而不是\s*(?P<bad>{RAW_ID})',
        rf'不要(?:拿|用)?\s*(?P<bad>{RAW_ID})(?:[^，,。；;]{{0,20}}?)(?:替代|代替|替换)\s*(?P<good>{RAW_ID})',
    )
    for pattern in identity_patterns:
        for match in re.finditer(pattern, constraints_query, re.I):
            normalize_id = lambda text: next(f'{m.group(1).upper()}-{int(m.group(2)):03d}' for m in FORMAL.finditer(text))
            rejected_ids.add(normalize_id(match['bad']))
            positive_overrides.add(normalize_id(match['good']))
    rejected_ids -= positive_overrides
    embedded = [value for value in embedded if value not in rejected_ids]
    if formal_id and embedded and embedded != [formal_id]:
        return {'status': 'identity_conflict', 'formal_ids': [], 'dates': _dates(query)}
    if len(embedded) > 3:
        return {'status': 'identity_scope_too_large', 'formal_ids': embedded, 'dates': _dates(query)}
    multi = len(embedded)>1 and bool(re.search(r'对比|比较|分别|差异|变化|和|与', constraints_query))
    if len(embedded)>1 and not multi:
        return {'status': 'multiple_identities', 'formal_ids': embedded, 'dates': _dates(query)}
    target = formal_id or (embedded[0] if embedded else None)
    printed = source_id
    if not printed:
        match = re.search(r'(?:原题号|来源号|来源题号)\s*[:：]?\s*([A-Za-z0-9_.-]{2,60})', constraints_query)
        if match and not FORMAL.fullmatch(match.group(1)):
            printed = match.group(1)
    date_values,date_exclusions=_date_constraints(query)
    result = {'status': 'unscoped', 'formal_ids': [], 'dates': date_values,
              'excluded_dates':date_exclusions,
              'request_intent':intent,
              'personal_requested': intent['history_search'] or bool(_dates(query)),
              'explicit_personal_requested': intent['history_search'],
              'exact_identity': False, 'source_question_id': printed,
              'excluded_formal_ids':sorted(rejected_ids),
              'latest_requested': bool(re.search(r'最近|最新|最后|上次', constraints_query)),
              'earliest_requested': bool(re.search(r'首次|第一次|最早', constraints_query)),
              'subquestion': None}
    if result['personal_requested'] and not result['dates'] and re.search(r'今天|昨天|前天|昨晚|今早|上周|本周|去年|今年',constraints_query):
        result['date_gap']='relative_date_requires_explicit_client_reference'
    match = re.search(r'第([一二三四五六七八九十1-9])(?:小)?问', constraints_query)
    if match:
        result['subquestion'] = match.group(1)
    if not target and not printed and not multi:
        return result
    path = root / INDEX
    if not path.is_file():
        return {**result, 'status': 'index_unavailable'}
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as conn:
            conn.execute('BEGIN')
            if target or multi:
                matches = embedded if multi else [target]
                if any(conn.execute('SELECT 1 FROM records WHERE formal_id=? LIMIT 1', (fid,)).fetchone() is None for fid in matches):
                    return {**result, 'status': 'unknown_formal_id'}
            else:
                matches = sorted({row[0] for row in conn.execute(
                    'SELECT formal_id FROM source_identities WHERE source_id=?', (printed,))})
                if len(matches) != 1:
                    return {**result, 'status': 'ambiguous_identity' if matches else 'unknown_source_id'}
            scope_keys = [row[0] for row in conn.execute(
                'SELECT DISTINCT m.key FROM membership m JOIN records r ON r.id=m.record_id '
                'WHERE r.formal_id IN ('+','.join('?' for _ in matches)+') ORDER BY m.key', matches)]
    except sqlite3.Error:
        return {**result, 'status': 'index_unavailable'}
    return {**result, 'status': 'resolved_multi' if multi else 'resolved', 'formal_ids': matches,
            'concept_keys': scope_keys, 'exact_identity': True}


def observed_point_scope(repo_root, scope, *, view='protected', valid_at=None, known_at=None):
    """A precise question/date can identify actual observed points without NLP."""
    date_scope = scope.get('explicit_personal_requested') and any(d['year'] and d['mode']=='on' for d in scope.get('dates', []))
    if view == 'protected' or not (scope.get('exact_identity') or date_scope) or not scope.get('personal_requested'):
        return []
    with closing(sqlite3.connect((Path(repo_root)/INDEX).resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        where="json_extract(r.payload,'$.kind') IN ('formal_concept_observation','concept_review')"
        parameters=[]
        if scope.get('excluded_formal_ids'):
            where += ' AND r.formal_id NOT IN ('+','.join('?' for _ in scope['excluded_formal_ids'])+')'
            parameters.extend(scope['excluded_formal_ids'])
        if scope.get('formal_ids'):
            where += ' AND r.formal_id IN ('+','.join('?' for _ in scope['formal_ids'])+')'
            parameters.extend(scope['formal_ids'])
        else:
            dates=[f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}" for d in scope['dates'] if d['year'] and d['mode']=='on']
            where += " AND json_extract(r.payload,'$.summary.study_date') IN ("+','.join('?' for _ in dates)+')'
            parameters.extend(dates)
        rows = conn.execute("SELECT DISTINCT m.key,json_extract(r.payload,'$.summary.study_date'),"
            "json_extract(r.payload,'$.summary.recorded_at') FROM records r JOIN membership m ON r.id=m.record_id "
            'WHERE '+where,parameters)
        found = []
        from math_memory_pending import _before, _cutoff
        for key, study_date, recorded_at in rows:
            if not _matches_date(study_date, scope.get('dates', []), scope.get('excluded_dates', [])):
                continue
            if valid_at and not _before(study_date, _cutoff(valid_at)):
                continue
            if known_at and not _before(recorded_at, _cutoff(known_at)):
                continue
            if key not in found:
                found.append(key)
        return sorted(found)[:32]


def _matches_date(value, dates, excluded_dates=()):
    if not dates and not excluded_dates:
        return True
    if not isinstance(value, str):
        return False
    try:
        current = dt.date.fromisoformat(value[:10])
    except ValueError:
        return False
    if any(d.get('mode')=='on' and (not d.get('year') or current.year==d['year']) and
           current.month==d['month'] and current.day==d['day'] for d in excluded_dates):
        return False
    exact = [d for d in dates if d['mode'] == 'on']
    cutoffs = [d for d in dates if d['mode'] == 'through']
    if exact and not any((not d['year'] or current.year == d['year']) and
                         current.month == d['month'] and current.day == d['day'] for d in exact):
        return False
    return all(current <= dt.date(d['year'] or current.year, d['month'], d['day']) for d in cutoffs)


def _safe_refs(refs):
    values = []
    for ref in refs or []:
        if not isinstance(ref, dict):
            continue
        path, sha = ref.get('path'), ref.get('sha256')
        if (not isinstance(path, str) or '..' in Path(path).parts or
                not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)):
            continue
        values.append({'path': path, 'sha256': sha})
    return values


def _event_row(record):
    summary = record.get('summary', {})
    return {'event_id': summary.get('event_id'), 'study_date': summary.get('study_date'),
            'recorded_at': summary.get('recorded_at'),
            'episode_id': summary.get('episode_id', summary.get('event_id')),
            'observations': summary.get('observations', []),
            'source_refs': record.get('source_refs', []),
            'related_formal_ids': summary.get('related_formal_ids', [])}


def _quote_locators(observation, source_refs, *, formal_id, concept_key):
    """Keep exact roles/positions; never return answer-bearing quote text."""
    handles = []
    for field, role in (('user_evidence', 'user'), ('hint_evidence', 'assistant')):
        for quote in observation.get(field, []):
            if not isinstance(quote, dict) or type(quote.get('sequence')) is not int:
                continue
            for source in source_refs[:2]:
                handles.append({'source_handle_ref': 'source:'+digest(source['path'])[:24],
                    'role': role, 'sequence': quote['sequence'],
                    'quote_sha256': hashlib.sha256(str(quote.get('quote', '')).encode()).hexdigest(),
                    'locator': {'capture_event_id': observation.get('capture_event_id'),
                        'field': field, 'sequence': quote['sequence']},
                    'binding': 'accepted_point_observation', 'raw_text_returned': False})
    for field, role in (('user_turn_indices', 'user'), ('hint_turn_indices', 'assistant')):
        for number in observation.get(field, []):
            if type(number) is int:
                for source in source_refs[:2]:
                    handles.append({'source_handle_ref': 'source:'+digest(source['path'])[:24],
                        'role': role, 'sequence': number+1,
                        'locator': {'observation_id': observation.get('observation_id'),
                                    'zero_based_turn_index': number},
                        'binding': 'accepted_concept_review', 'raw_text_returned': False})
    return handles


def _original_conversation_handles(conn, record_id, observations):
    """Read saved package references, not embedded conversation bodies."""
    handles=[]
    capture_ids=list(dict.fromkeys(row.get('capture_event_id') for row in observations if row.get('capture_event_id')))
    for capture_id in capture_ids[:4]:
        row=conn.execute("SELECT json_extract(p.value,'$.source_refs') FROM records r,"
                         "json_each(r.payload,'$.history.packages') p WHERE r.id=? AND p.key=?",
                         (record_id,capture_id)).fetchone()
        if not row:
            continue
        relevant=[r for r in observations if r.get('capture_event_id')==capture_id]
        for ref in _safe_refs(json.loads(row[0] or '[]')):
            if Path(ref['path']).name not in ('conversation.json','session.json'):
                continue
            handles.append({**ref,'source_kind':'original_conversation',
                'locator':{'record_id':record_id,'capture_event_id':capture_id,
                    'user_sequences':sorted({x['sequence'] for r in relevant for x in r.get('user_evidence',[]) if type(x.get('sequence')) is int}),
                    'hint_sequences':sorted({x['sequence'] for r in relevant for x in r.get('hint_evidence',[]) if type(x.get('sequence')) is int})},
                'binding':'immutable_accepted_package_reference',
                'availability':'exact_saved_locator;original_may_require_archive_resolution',
                'raw_text_returned':False})
            break
    return handles[:2]


def _raw_references(root, conn, version, keys, scope, targets, limit=4, *, valid_at=None, known_at=None):
    """Supplement exact scopes from the maintained Capture binding projection."""
    if not scope.get('formal_ids') and not scope.get('dates'):
        return [], []
    try:
        import math_memory_record_scopes as scopes
        found=scopes.lookup(root,version,concept_keys=keys,formal_ids=scope.get('formal_ids',()),
                            dates=scope.get('dates',()),limit=16)
    except (ImportError,OSError,ValueError,sqlite3.Error) as error:
        return [],[{'reason':'raw_scope_projection_unavailable','detail':type(error).__name__}]
    if found.get('status')!='available':
        return [],[{'reason':found.get('reason','raw_scope_projection_unavailable')}]
    result,gaps=[],[]
    for row in found.get('records',[])[:16]:
        from math_memory_pending import _before, _cutoff
        bindings=[]
        for binding in row.get('bindings',[]):
            if not _matches_date(binding.get('study_date'),scope.get('dates',()),scope.get('excluded_dates',())):
                continue
            if valid_at and not _before(binding.get('study_date'),_cutoff(valid_at)):
                continue
            if known_at and not _before(binding.get('recorded_at'),_cutoff(known_at)):
                if not binding.get('recorded_at'):
                    gaps.append({'record_id':row['record_id'],'reason':'raw_capture_known_time_unknown'})
                continue
            bindings.append(binding)
        if not bindings:
            continue
        raw=conn.execute('SELECT payload FROM records WHERE id=?',(row['record_id'],)).fetchone()
        if not raw or hashlib.sha256(raw[0].encode()).hexdigest()!=row.get('record_sha256'):
            gaps.append({'record_id':row['record_id'],'reason':'raw_record_binding_changed'})
            continue
        value=json.loads(raw[0]);meta=value.get('metadata',{})
        refs=_safe_refs(value.get('source_refs',[]))
        handles=[]
        matched_turns=[]
        path=meta.get('user_turn_cache');sha=meta.get('user_turn_cache_sha256')
        if isinstance(path,str) and isinstance(sha,str):
            safe=_safe_refs([{'path':path,'sha256':sha}])
            if safe and not targets:
                for turn in meta.get('user_turn_provenance',[])[:8]:
                    if turn.get('role')=='user' and type(turn.get('sequence')) is int:
                        handles.append({'path':path,'sha256':sha,'role':'user','sequence':turn['sequence'],
                            'quote_sha256':turn.get('raw_text_sha256'),
                            'locator':{'sequence':turn['sequence'],'role':'user'},
                            'binding':'indexed_user_provenance;verify_bytes_before_raw_read',
                            'raw_text_returned':False})
            elif safe and not Path(path).is_absolute() and not (root/path).is_symlink():
                source=(root/path).resolve()
                try:
                    if not source.is_relative_to(root.resolve()) or source.stat().st_size>512*1024:
                        raise ValueError('raw_user_cache_scope_or_budget')
                    data=source.read_bytes()
                    if hashlib.sha256(data).hexdigest()!=sha:
                        raise ValueError('raw_user_cache_changed')
                    turns=json.loads(data)
                    if not isinstance(turns,list):
                        raise ValueError('raw_user_cache_invalid')
                    users=[turn for turn in turns if isinstance(turn,dict) and turn.get('role')=='user'
                           and type(turn.get('sequence')) is int and isinstance(turn.get('text'),str)]
                    if targets:
                        users=[turn for turn in users if any(target in _quote_normalize(turn['text']) for target in targets)]
                    for turn in users[:8]:
                        matched_turns.append(turn['sequence'])
                        handles.append({'path':path,'sha256':sha,'role':'user','sequence':turn['sequence'],
                            'quote_sha256':hashlib.sha256(turn['text'].encode()).hexdigest(),
                            'locator':{'sequence':turn['sequence'],'role':'user'},'raw_text_returned':False})
                except (OSError,ValueError,TypeError):
                    gaps.append({'record_id':row['record_id'],'reason':'raw_user_cache_unavailable'})
        if targets and not matched_turns:
            continue
        if not handles:
            handles=[{**ref,'locator':{'record_id':row['record_id']},'raw_text_returned':False} for ref in refs[:2]]
        for binding in bindings[:2]:
            result.append({'record_id':row['record_id'],'formal_id':binding.get('formal_id'),
                'concept_key':keys[0] if len(keys)==1 else None,
                'concept_association':'card_association_only',
                'kind':row['kind'],'evidence_role':'raw_unadjudicated_reference',
                'capture_id':binding.get('capture_id'),'event_id':binding.get('closeout_id'),
                'study_date':binding.get('study_date'),'recorded_at':binding.get('recorded_at'),
                'accepted_at':binding.get('accepted_at'),
                'known_at_semantics':'original_capture_recorded_at',
                'source_handles':handles,'user_sequences':matched_turns,
                'utterance_match':{'status':'matched' if targets and matched_turns else 'scope_only'},
                'not_mastery_evidence':True,'not_a_new_learning_event':True,
                'point_observation_confirmed':False,'requires_operation_scope_check':True})
        if len(result)>=limit:
            break
    return result[:limit],gaps


def locate(repo_root, concept_keys, *, query='', scope=None, view='protected',
           expected_version=None, valid_at=None, known_at=None, max_bytes=4500, limit=4,
           profile_rows=(), source_first=False, preferred_concept_keys=(), record_ids=(),
           teaching_annotation=False):
    """Locate bounded saved personal events after point/identity qualification."""
    if view == 'protected':
        return {'status': 'protected', 'records': []}
    if view not in {'after_attempt', 'direct'}:
        raise ValueError('invalid evidence view')
    scope = scope or query_scope(repo_root, query)
    if not scope.get('personal_requested'):
        return {'status': 'not_requested', 'records': []}
    if scope.get('date_gap'):
        return {'status':'date_scope_required','records':[], 'reason':scope['date_gap'],
                'does_not_prove_no_learning':True}
    if scope.get('status') in {'identity_conflict', 'multiple_identities', 'unknown_formal_id','invalid_date_scope',
                               'unknown_source_id', 'ambiguous_identity', 'index_unavailable'}:
        return {'status': scope['status'], 'records': []}
    keys = list(dict.fromkeys(k for k in concept_keys if isinstance(k, str) and KEY.fullmatch(k)))
    requested_keys=list(keys)
    if source_first and (scope.get('exact_identity') or scope.get('dates')):
        actual=observed_point_scope(repo_root,scope,view=view,valid_at=valid_at,known_at=known_at)
        if actual:
            keys=actual
    if not keys and not scope.get('formal_ids'):
        return {'status': 'point_scope_required', 'records': []}
    date_scope=scope.get('explicit_personal_requested') and any(d['year'] and d['mode']=='on' for d in scope.get('dates', []))
    if len(keys) > (32 if scope.get('exact_identity') or date_scope else 3) or type(limit) is not int or not 1 <= limit <= 8:
        raise ValueError('personal evidence scope must be bounded')
    root = Path(repo_root)
    formal_ids = scope.get('formal_ids', [])
    if teaching_annotation and (len(formal_ids) != 1 or len(keys) != 1 or not expected_version
                                or not scope.get('exact_identity') or query or valid_at or known_at):
        raise ValueError('teaching observations require one verified question and point')
    dates = scope.get('dates', [])
    quote_targets = _quote_targets(query)
    anchors=evidence_anchors(query)
    intent=anchors['intent']
    has_source_anchors=bool(anchors['literals'] or anchors['math_atoms'] or anchors['terms'])
    literal_request=intent['requires_statement_verification']
    record_lookup=intent['history_goal']=='record_lookup'
    specific_utterance = bool(quote_targets or re.search(r'原话|那条|我说|只卡|哪次|首答',query))
    comparison_requested = bool(re.search(r'比较|对比|变化|分别|两次|两条',query) or
                                len(formal_ids)>1 or len([d for d in dates if d['mode']=='on'])>1)
    rows, gaps = [], []
    raw_references,raw_gaps=[],[]
    import math_memory_projection as projection
    import math_memory_lifecycle as lifecycle
    import math_concept_index as native
    with closing(sqlite3.connect((root/INDEX).resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        conn.execute('BEGIN')
        freshness = projection.check_query_dependencies(root, conn, keys)
        version = freshness.get('version')
        if freshness.get('status') != 'ready' or (expected_version is not None and version != expected_version):
            return {'status': 'stale', 'reason': 'personal_evidence_snapshot_changed', 'records': []}
        parameters = list(keys)
        where = 'm.key IN ('+','.join('?' for _ in keys)+')' if keys else '1=1'
        if formal_ids:
            where += ' AND r.formal_id IN ('+','.join('?' for _ in formal_ids)+')'
            parameters.extend(formal_ids)
        if scope.get('excluded_formal_ids'):
            where += ' AND r.formal_id NOT IN ('+','.join('?' for _ in scope['excluded_formal_ids'])+')'
            parameters.extend(scope['excluded_formal_ids'])
        if record_ids:
            if len(record_ids)>64 or not all(isinstance(value,str) for value in record_ids):
                raise ValueError('personal_record_id_scope_invalid')
            where += ' AND r.id IN ('+','.join('?' for _ in record_ids)+')'
            parameters.extend(record_ids)
        # Filter event date in SQL before deserializing any quote-bearing
        # summary. A year in an exam ID is never used as a study date.
        equality = [d for d in dates if d['mode']=='on']
        if equality:
            clauses=[]
            for day in equality:
                if day['year']:
                    clauses.append("json_extract(r.payload,'$.summary.study_date')=?")
                    parameters.append(f"{day['year']:04d}-{day['month']:02d}-{day['day']:02d}")
                else:
                    clauses.append("substr(json_extract(r.payload,'$.summary.study_date'),6,5)=?")
                    parameters.append(f"{day['month']:02d}-{day['day']:02d}")
            where += ' AND ('+' OR '.join(clauses)+')'
        for day in [d for d in scope.get('excluded_dates',[]) if d['mode']=='on']:
            if day['year']:
                where += " AND json_extract(r.payload,'$.summary.study_date')<>?"
                parameters.append(f"{day['year']:04d}-{day['month']:02d}-{day['day']:02d}")
            else:
                where += " AND substr(json_extract(r.payload,'$.summary.study_date'),6,5)<>?"
                parameters.append(f"{day['month']:02d}-{day['day']:02d}")
        for day in [d for d in dates if d['mode']=='through' and d['year']]:
            where += " AND json_extract(r.payload,'$.summary.study_date')<=?"
            parameters.append(f"{day['year']:04d}-{day['month']:02d}-{day['day']:02d}")
        if valid_at:
            where += " AND json_extract(r.payload,'$.summary.study_date')<=?"
            parameters.append(valid_at[:10])
        if known_at:
            from math_memory_pending import _cutoff
            unknown = conn.execute("SELECT r.id FROM records r JOIN membership m ON r.id=m.record_id WHERE "+where+
                " AND json_extract(r.payload,'$.summary.recorded_at') IS NULL LIMIT 8",parameters).fetchall()
            gaps.extend({'record_id':r[0],'reason':'known_time_unknown'} for r in unknown)
            where += " AND datetime(json_extract(r.payload,'$.summary.recorded_at'))<=datetime(?)"
            parameters.append(_cutoff(known_at))
        # JSON extraction drops the embedded full conversation before material
        # enters this reader. General learning material is not learner evidence.
        sql = ("SELECT DISTINCT r.id,r.formal_id,m.key,json_extract(r.payload,'$.kind'),"
               "json_extract(r.payload,'$.summary'),json_extract(r.payload,'$.source_refs') "
               "FROM records r JOIN membership m ON r.id=m.record_id WHERE "+where+
               " AND json_extract(r.payload,'$.kind') IN ('formal_concept_observation','concept_review','personal_card') "
               "ORDER BY json_extract(r.payload,'$.summary.study_date') "+('ASC' if scope.get('earliest_requested') else 'DESC')+" LIMIT 257")
        candidates = list(conn.execute(sql, parameters))
        scan_truncated = len(candidates)>256
        candidates = candidates[:256]
        import math_memory_catalog
        classifications = {key:math_memory_catalog.classify_title(row[0]).get('kind') for key in keys
                           if (row:=conn.execute('SELECT label FROM concepts WHERE key=?',(key,)).fetchone())}
        preferred_specific_keys={key for key in preferred_concept_keys if classifications.get(key)=='concept'}
        exact_record_scope=bool(record_lookup and len(preferred_specific_keys)==1 and
                               (scope.get('exact_identity') or date_scope))
        for rid, fid, key, kind, summary_json, refs_json in candidates:
            summary = json.loads(summary_json or '{}')
            refs = _safe_refs(json.loads(refs_json or '[]'))
            if kind == 'personal_card':
                # No day-specific raw event can be manufactured from card prose.
                if not teaching_annotation and not dates and formal_ids and not any(r['record_id']==rid for r in rows):
                    rows.append({'record_id': rid, 'formal_id': fid, 'concept_key': key if keys else None,
                        'kind': kind, 'evidence_role': 'legacy_summary',
                        'source_handles': [{**r, 'locator': {'formal_id': fid},
                            'raw_text_returned': False} for r in refs[:2]],
                        'not_point_observation': True, 'rank': 0})
                continue
            if not _matches_date(summary.get('study_date'), dates, scope.get('excluded_dates', [])):
                continue
            if (teaching_annotation and not refs) or any(not (stored := conn.execute('SELECT stamp,sha256 FROM sources WHERE path=?', (r['path'],)).fetchone())
                   or stored[1] != r['sha256'] or native._stamp(root/r['path']) != json.loads(stored[0]) for r in refs):
                gaps.append({'record_id': rid, 'reason': 'source_changed'})
                continue
            record = {'summary': summary, 'source_refs': refs}
            effective = lifecycle.apply_observation_corrections(root, [_event_row(record)],
                valid_at=valid_at, known_at=known_at, concept_key=key)
            if not effective:
                continue
            event = effective[0]
            if event.get('memory_status') == 'known_time_unknown':
                gaps.append({'record_id': rid, 'reason': 'known_time_unknown'})
                continue
            observations = []
            relevance = 0
            quote_matches = []
            source_matches=[]
            for observation in event.get('observations', []):
                if observation.get('concept_key', key) != key:
                    continue
                # Subquestion constraints are positive scope, not a broad text
                # search over all saved conversations.
                sub = scope.get('subquestion')
                text = observation.get('error_detail', '')+' '+ ' '.join(str(v.get('quote', '')) for v in observation.get('user_evidence', []))
                subquestion_binding='not_requested'
                if sub:
                    aliases = {'一':'1','二':'2','三':'3','四':'4','五':'5'}
                    number = aliases.get(sub, sub)
                    chinese = next((k for k,v in aliases.items() if v == number), sub)
                    marker='第[（(]?['+re.escape(number+chinese)+'][）)]?(?:小)?问'
                    details=observation.get('error_detail','')
                    explicit=re.findall(r'第[（(]?([一二三四五1-5])[）)]?(?:小)?问',details)
                    if explicit and not re.search(marker,details):
                        continue
                    if not explicit:
                        quoted=re.findall(r'第[（(]?([一二三四五1-5])[）)]?(?:小)?问',text)
                        if quoted and not re.search(marker,text):
                            continue
                    subquestion_binding='explicit' if re.search(marker,details) else 'point_and_date_only;raw_scope_check_required'
                user = [q['sequence'] for q in observation.get('user_evidence', []) if type(q.get('sequence')) is int]
                hints = [q['sequence'] for q in observation.get('hint_evidence', []) if type(q.get('sequence')) is int]
                user += [n+1 for n in observation.get('user_turn_indices', []) if type(n) is int]
                hints += [n+1 for n in observation.get('hint_turn_indices', []) if type(n) is int]
                texts=[(v.get('sequence'),_quote_normalize(v.get('quote',''))) for v in observation.get('user_evidence',[]) if isinstance(v,dict)]
                matched_sequences=[seq for seq,text_value in texts if any(target in text_value for target in quote_targets)]
                user_matches=[(v.get('sequence'),user_evidence_match(query,v.get('quote','')))
                              for v in observation.get('user_evidence',[]) if isinstance(v,dict)]
                user_supported=[(seq,match) for seq,match in user_matches if match['supported']]
                annotation_match=user_evidence_match(query,observation.get('error_detail',''))
                label_row=conn.execute('SELECT label FROM concepts WHERE key=?',(key,)).fetchone()
                binding_match=user_evidence_match(query,(label_row[0] if label_row else '')+' '+observation.get('error_detail',''))
                chosen=max((m for _,m in user_supported),key=lambda m:m['score'],default=None)
                match_basis='user_quote'
                if chosen is None and not binding_match.get('missing_objects'):
                    # The utterance can name the exact operand while the
                    # accepted annotation supplies its operation's scope.
                    partial=[(seq,m) for seq,m in user_matches if
                        not m.get('expression_not_supported') and not m.get('historical_polarity_conflict')
                        and (not m.get('explicit_quoted_request') or m.get('kind')=='literal')
                        and m.get('matched_anchors') and (
                            m.get('kind') in {'literal','math_expression'} or
                            any(atom in m.get('matched_anchors',[]) for atom in anchors['math_atoms']))]
                    if partial and (annotation_match['supported'] or anchors['required_objects']):
                        chosen=max((m for _,m in partial),key=lambda m:m['score'])
                        user_supported=partial
                        match_basis='user_anchor_with_accepted_annotation_scope'
                if chosen is None and not literal_request and annotation_match['supported']:
                    chosen=annotation_match
                    match_basis='formal_annotation_not_user_quote'
                if (chosen is None and record_lookup and source_first and
                        (scope.get('exact_identity') or date_scope) and
                        classifications.get(key)=='concept' and binding_match['supported']):
                    # The saved point label plus accepted annotation can locate
                    # an event. Neither is relabelled as the user's own speech.
                    chosen=binding_match
                    match_basis='formal_point_and_annotation_scope'
                if (chosen is None and exact_record_scope and key in preferred_specific_keys and
                        not anchors['math_atoms'] and not binding_match.get('missing_objects') and
                        not any(m.get('historical_polarity_conflict') for _,m in user_matches)):
                    # A qualified fine point and exact identity/date can locate
                    # one real event even when the question paraphrases it.
                    # Uniqueness is still checked below over the full result.
                    chosen={'supported':True,'score':0,'kind':'exact_record_scope',
                            'matched_anchors':[],'reason':'qualified_point_and_exact_event_scope',
                            'is_truth_or_mastery_probability':False}
                    match_basis='exact_record_scope_not_statement_verification'
                if chosen and binding_match.get('missing_objects'):
                    chosen=None
                if source_first and has_source_anchors and chosen is None:
                    continue
                if chosen:
                    source_matches.append({**chosen,'match_basis':match_basis,
                        'annotation_supports_operation':annotation_match['supported'],
                        'user_sequences':[seq for seq,_ in user_supported],
                        'not_a_quote_of_annotation':True,
                        'query_statement_verified':False})
                    matched_sequences=list(dict.fromkeys([*matched_sequences,*[seq for seq,_ in user_supported]]))
                quote_matches.extend(matched_sequences)
                observations.append({'observation_sha256': observation.get('observation_sha256') or lifecycle.observation_hash(observation),
                    'outcome': observation.get('outcome'),
                    'memory_status': observation.get('memory_status'),
                    'memory_correction_ids': observation.get('memory_correction_ids', []),
                    'user_sequences': user, 'hint_sequences': hints,
                    'hint_precedes_user': min(hints)<max(user) if user and hints else None,
                    'hint_evidence_status':'recorded' if hints else 'not_recorded_in_this_observation',
                    'subquestion_binding':subquestion_binding,
                    'utterance_match':bool(matched_sequences),
                    'source_match':source_matches[-1] if chosen else None,
                    'source_handles': _quote_locators(observation, refs, formal_id=fid, concept_key=key)})
                # Free-text annotations sometimes include the correct option or
                # derived limits. An attempt alone does not unlock that prose.
                if teaching_annotation and view == 'direct' and 0 < len(observation.get('error_detail', '').encode()) <= 540:
                    observations[-1]['accepted_annotation'] = observation['error_detail']
                if re.search(r'原话|说|复述|理解', query) and user:
                    relevance += 1
            if not observations:
                continue
            content_observations=[o for o in observations if o.get('source_match') and
                o['source_match']['match_basis']!='exact_record_scope_not_statement_verification']
            if content_observations:
                observations=content_observations
                source_matches=[o['source_match'] for o in observations]
            original_handles=[] if teaching_annotation else _original_conversation_handles(conn,rid,event.get('observations',[]))
            correction_handles=[]
            for correction in event.get('memory_corrections', []):
                for ref in _safe_refs(correction.get('source_refs', [])):
                    correction_handles.append({**ref,'source_kind':'observation_correction',
                        'locator':{'correction_id':correction.get('correction_id'),
                                   'target':correction.get('target')},'raw_text_returned':False})
            rows.append({'record_id': rid, 'formal_id': fid, 'concept_key': key,
                'kind': kind, 'evidence_role': kind,
                'point_classification':classifications.get(key,'unclassified'),
                'not_a_qualified_knowledge_point':classifications.get(key) not in {'concept','parent'},
                'event_id': event.get('event_id'), 'study_date': event.get('study_date'),
                'recorded_at': event.get('recorded_at'),
                'utterance_match':{'status':'matched' if quote_matches else 'not_matched' if quote_targets else 'not_requested',
                                   'user_sequences':sorted(set(quote_matches)), 'target_phrase_count':len(quote_targets)},
                'source_match':max(source_matches,key=lambda match:match['score']) if source_matches else None,
                'correction_source_handles':correction_handles[:4],
                'known_at_semantics': 'formal_acceptance_not_first_capture',
                'observations': observations,
                'source_handles': [{**r, 'source_kind':'accepted_event_projection',
                     'source_key':'source:'+digest(r['path'])[:24],
                     'locator': {'record_id': rid, 'event_id': event.get('event_id'),
                     'formal_id': fid, 'concept_key': key}, 'raw_text_returned': False} for r in refs[:2]]+original_handles,
                'rank': 10+relevance})
        if not teaching_annotation and (scope.get('formal_ids') or scope.get('dates')) and (
                re.search(r'原话|首答|那句|那条',query) or not any(r['kind'] in {'formal_concept_observation','concept_review'} for r in rows)):
            raw_references,raw_gaps=_raw_references(root,conn,version,keys,scope,quote_targets,limit=2,
                                                   valid_at=valid_at,known_at=known_at)
    if re.search(r'偏好|喜欢|讲法|希望.*讲|按.*讲', query) and not known_at:
        for profile in profile_rows:
            key = profile.get('concept_key')
            if key not in keys:
                continue
            for preference in profile.get('teaching_preferences', []):
                handles = []
                dates_seen = set()
                for ref in preference.get('source_refs', []):
                    if not _safe_refs([ref]) or ref.get('role') != 'user':
                        continue
                    locator = ref.get('locator', '')
                    date_match = re.search(r'20\d{2}-\d{2}-\d{2}', locator)
                    date = date_match.group(0) if date_match else None
                    if not _matches_date(date, dates, scope.get('excluded_dates', [])):
                        continue
                    if valid_at:
                        from math_memory_pending import _before, _cutoff
                        if not _before(date, _cutoff(valid_at)):
                            continue
                    # A point-wide preference cannot silently be assigned to a
                    # particular question when its source lacks that binding.
                    if formal_ids and not any(fid in locator or fid in ref['path'] for fid in formal_ids):
                        continue
                    if date:
                        dates_seen.add(date)
                    handles.append({**{f:ref[f] for f in ('path','sha256','role','sequence','locator') if f in ref},
                        'quote_sha256': hashlib.sha256(str(ref.get('quote','')).encode()).hexdigest(),
                        'raw_text_returned': False})
                if handles:
                    rows.append({'record_id': 'preference:'+digest([key,preference])[:24],
                        'concept_key': key, 'formal_id': formal_ids[0] if formal_ids else None,
                        'kind':'teaching_preference', 'evidence_role': preference.get('basis'),
                        'study_date': max(dates_seen) if dates_seen else None,
                        'recorded_at': None, 'source_handles': handles,
                        'not_mastery_evidence': True, 'rank': 20})
    accepted_kinds={'formal_concept_observation','concept_review'}
    accepted=[row for row in rows if row['kind'] in accepted_kinds]
    if source_first and record_lookup and preferred_specific_keys and not has_source_anchors:
        # An empty lexical anchor list cannot authorize every adjacent point
        # on the same card. Preserve the already qualified point's actual
        # events; same-point duplicates still undergo the uniqueness check.
        accepted=[row for row in accepted if row['concept_key'] in preferred_specific_keys]
        rows=accepted+[row for row in rows if row['kind'] not in accepted_kinds]
    if source_first and has_source_anchors:
        accepted=[row for row in accepted if row.get('source_match')]
        preferred=set(preferred_concept_keys)
        preferred_specific=[r for r in accepted if r['concept_key'] in preferred and classifications.get(r['concept_key'])=='concept']
        if record_lookup and len({r['concept_key'] for r in preferred_specific})==1:
            # A record lookup asks for events under its qualified point. A
            # quote lookup instead keeps every honest source-to-point binding.
            accepted=preferred_specific
        if preferred_specific:
            def user_bindings(row):
                return {(row.get('formal_id'),row.get('event_id'),
                         handle.get('locator',{}).get('capture_event_id') or handle.get('source_handle_ref'),
                         handle.get('sequence'),handle.get('quote_sha256'))
                        for observation in row.get('observations',[]) for handle in observation.get('source_handles',[])
                        if handle.get('role')=='user' and handle.get('quote_sha256')}
            preferred_bindings=set().union(*(user_bindings(row) for row in preferred_specific))
            accepted=[row for row in accepted if row in preferred_specific or (
                classifications.get(row['concept_key'])!='parent'
                and not preferred_bindings.intersection(user_bindings(row)))]
        scoped_specific=[r for r in accepted if classifications.get(r['concept_key'])=='concept' and
                         r.get('source_match',{}).get('annotation_supports_operation')]
        if scoped_specific:
            accepted=[r for r in accepted if classifications.get(r['concept_key'])!='parent']
        rows=accepted+[r for r in rows if r['kind'] not in accepted_kinds]
    if accepted and not re.search(r'旧卡|错题卡',query):
        rows=[r for r in rows if r['kind']!='personal_card']
    content_matched=[row for row in accepted if row.get('utterance_match',{}).get('status')=='matched']
    if content_matched:
        rows=content_matched
        for row in rows:
            matched=[o for o in row['observations'] if o['utterance_match']]
            row['observations_omitted_for_utterance']=len(row['observations'])-len(matched)
            row['observations']=matched
        accepted=content_matched
    ambiguous_records=False
    if len(accepted)>1 and not comparison_requested and (specific_utterance or source_first and
            (has_source_anchors or preferred_specific_keys) or scope.get('latest_requested') or scope.get('earliest_requested')):
        if scope.get('latest_requested') or scope.get('earliest_requested'):
            actual_days=[r['study_date'] for r in accepted if r.get('study_date')]
            day=min(actual_days) if scope.get('earliest_requested') else max(actual_days)
            accepted=[r for r in accepted if r.get('study_date')==day]
            rows=accepted
        ambiguous_records=len(accepted)>1
    if scan_truncated and (specific_utterance or scope.get('latest_requested') or scope.get('earliest_requested')):
        ambiguous_records=True
    rows.sort(key=lambda row: (row.get('study_date') or '', row.get('recorded_at') or '', row['record_id']),
              reverse=not scope.get('earliest_requested'))
    rows.sort(key=lambda row: row['rank'], reverse=True)
    total = len(rows)
    selected = [] if ambiguous_records else rows[:limit]
    for row in selected:
        row.pop('rank', None)
        for observation in row.get('observations',[]):
            if observation.get('source_match') and observation['source_match']==row.get('source_match'):
                observation['source_match']={'match_basis':row['source_match']['match_basis'],
                    'record_match_ref':'source_match','query_statement_verified':False}
    ambiguous_years = any(not day['year'] and len({r.get('study_date','')[:4] for r in rows
        if r.get('study_date') and r['study_date'][5:]==f"{day['month']:02d}-{day['day']:02d}"})>1 for day in dates)
    result = {'status': 'ambiguous_date' if ambiguous_years and not (scope.get('latest_requested') or scope.get('earliest_requested')) else
                       'ambiguous_records' if ambiguous_records else
                       'partial' if gaps or scan_truncated else 'available' if selected else 'raw_reference_only' if raw_references else 'not_recorded_in_scope',
              'source_version': version, 'scope': {'concept_keys': keys, 'formal_ids': formal_ids,
                'study_dates': dates, 'excluded_dates':scope.get('excluded_dates',[]), 'subquestion': scope.get('subquestion')},
              'records': selected, 'matched_record_count': total, 'omitted_count': total-len(selected),
              'matched_concept_keys':sorted({r['concept_key'] for r in rows if r['kind'] in accepted_kinds}),
              'record_selection_status':'ambiguous' if ambiguous_records else 'matched' if len(selected)==1 else 'record_set_matched' if selected else 'no_match',
              'gaps': gaps, 'raw_text_returned': False,
              'raw_references':raw_references, 'raw_reference_gaps':raw_gaps,
              'raw_references_are_not_point_observations':True,
              'record_scan_truncated':scan_truncated,
              'ordering':'study_date;within_day_order_is_not_established',
              'same_day_order_unverified':any(sum(r.get('study_date')==day for r in rows)>1
                    for day in {r.get('study_date') for r in rows if r.get('study_date')}),
              'not_global_mastery': True, 'absence_does_not_prove_no_learning': True}
    result['source_first']=source_first
    result['history_goal']=intent['history_goal']
    result['query_statement_verified']=False
    result['record_match_does_not_verify_query_paraphrase']=True
    result['concept_hint_was_not_record_filter']=bool(source_first and set(keys)!=set(requested_keys))
    if ambiguous_records:
        result['record_choices']=[{k:r.get(k) for k in ('record_id','formal_id','concept_key','study_date','event_id')} for r in accepted[:2]]
        result['reason']='same_scope_multiple_events_without_unique_user_utterance_binding'
    if result['status']=='ambiguous_date':
        result['records']=selected=[]
        result['record_selection_status']='ambiguous'
        result['omitted_count']=total
        result['record_choices']=[{k:r.get(k) for k in ('record_id','formal_id','concept_key','study_date','event_id')} for r in rows[:2]]
        result['reason']='month_day_matches_multiple_actual_study_years'
    while result['raw_references'] and len(canonical(result).encode()) > max_bytes:
        result['raw_references'].pop()
        result['raw_references_omitted']=result.get('raw_references_omitted',0)+1
    while selected and len(canonical(result).encode()) > max_bytes:
        selected.pop()
        result['omitted_count'] += 1
    if total and not selected and not ambiguous_records and result['status']!='ambiguous_date':
        result['status'] = 'budget_too_small'
        result['required_min_bytes'] = min(len(canonical(row).encode()) for row in rows)+600
    return result
