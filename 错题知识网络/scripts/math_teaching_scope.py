"""Scope labels for already-reviewed math evidence. No source I/O or inference of mastery."""
import re
import unicodedata

# Only the authored empty-profile sentence has this meaning. An independently
# verified preference or observation in another field keeps its own evidence.
NO_PERSONAL_SENTENCE = '当前无可归属本点的具体作答判断，熟悉程度待核。'
NUMBERS = dict(zip('一二三四五六七八九十', map(str, range(1, 11))))
ROMAN = {roman: str(i) for i, roman in enumerate(('I','II','III','IV','V','VI','VII','VIII','IX','X'), 1)}
PART = r'(?:10|[1-9一二三四五六七八九十]|VIII|VII|VI|IV|IX|III|II|I|V|X)'
PART_MARKER = re.compile(
    rf'(?:第\s*\(?\s*({PART})\s*\)?\s*(?:小)?问|(?:小问|问)\s*\(\s*({PART})\s*\)|'
    rf'(?<![\w)])\(\s*({PART})\s*\)(?=\s*小?问)|'
    rf'^\s*\(\s*({PART})\s*\)(?=\s*[求证算写画设、])|(?:只看|只问|只讲|针对|小题)\s*\(\s*({PART})\s*\))')


def part_scope(text):
    """Return positively scoped and explicitly excluded subquestions."""
    included, excluded = set(), set()
    for clause in re.split(r'[，,。；;！？!?\n]', unicodedata.normalize('NFKC', text or '')):
        for match in PART_MARKER.finditer(clause):
            token = next(token for token in match.groups() if token is not None)
            number = NUMBERS.get(token, ROMAN.get(token, token))
            before, after = clause[:match.start()], clause[match.end():]
            outside = (re.search(r'(?:不(?:含|覆盖|涉及|讨论|展开|处理|含有|讲|看)|跳过|略过|排除)\s*$', before)
                       or re.match(r'\s*(?:先不(?:讲|看|做)|不(?:用|必|需要)(?:再|重新)?(?:讲|看|做|展开|重复)|除外|跳过)', after))
            (excluded if outside else included).add(number)
    return included, excluded


# A recorded outcome in an atom such as “并求a=b=-1” can disclose
# the current answer. Avoid interpreting a general condition “当 a=0 时” as one.
RECORDED_VALUE = re.compile(
    r'(?:解得|求得|算出|解出|得到|得出|并求|并解|算得|第[一二三四五1-5]问)'
    r'\s*[a-zA-Zα-ωθμλ](?:_[a-zA-Z0-9]+)?\s*(?:=\s*[a-zA-Zα-ωθμλ]\s*)*[=≠]\s*[-−+]?\d')


def summary_role(summary):
    if summary == '本题历史摘要含已解出的数值；本轮先接当前已展示的步骤。':
        return 'scoped_result_withheld'
    if NO_PERSONAL_SENTENCE in (summary or '').splitlines():
        return 'reference_only_no_attributed_attempt'
    return 'concept_history'
