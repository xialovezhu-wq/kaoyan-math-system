"""Answer-safe discovery metadata, distinct from personal learning evidence.

This classifier never removes canonical concepts or rewrites their history.
It quarantines source/navigation placeholders from discovery and adds neutral
mathematical vocabulary. Method conclusions, formulas, hints and personal prose
are deliberately not exported as search text.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

VERSION = 'math-precision-catalog-v2-typed-names'
BASE = Path('错题知识网络/个人知识点索引/做题方法')
POLICY = Path('错题知识网络/schema/relationship_signal_policy.json')

BROAD = {
    '数学', '高等数学', '线性代数', '概率论', '概率论与数理统计', '函数', '矩阵',
    '概率', '概率分布', '随机变量', '连续型随机变量', '离散型随机变量',
    '积分', '导数', '微分方程', '一阶微分方程', '级数', '数列', '极限与连续',
    '一元函数微分学应用', '多元函数微分学', '矩阵运算', '定积分', '不定积分',
    '反常积分', '广义积分', '大数定律', '中心极限定理',
    '二重积分', '三重积分', '幂级数和函数',
}

# Neutral terms identify an object/operation; they do not prescribe a solution.
OBJECTS = (
    '一阶线性微分方程', '常系数微分方程', '微分方程', '方程组', '解集',
    '零空间', '核空间', '行空间', '列空间', '矩阵', '行列式', '特征值',
    '特征向量', '二次型', '线性变换', '向量组', '向量', '基',
    '满行秩', '满列秩', '行满秩', '列满秩', '行向量', '列向量', '非零行',
    '特解', '通解', '基础解系', '仿射', '齐次方向', '线性空间',
    '条件密度', '边缘密度', '联合密度', '分布函数', '密度', '随机变量',
    '正态分布', '均匀分布', '指数分布', '二项分布', '泊松分布', '卡方分布',
    '统计量', '估计量', '样本', '总体', '期望', '方差', '协方差', '概率',
    '原点矩', '中心矩', '混合矩', '样本矩', '矩估计', '矩母函数',
    '二维正态', '二元正态', '联合正态', '正态边缘', '大数定律', '中心极限定理',
    '二维函数', '随机变量函数', '支持区域', '积分区域', '积分变量',
    '傅里叶级数', '幂级数', '数项级数', '级数', '数列', '函数', '极限',
    '偏导数', '导数', '梯度', '方向导数', '微分', '二重积分', '三重积分',
    '曲线积分', '曲面积分', '积分', '曲线', '曲面', '切平面', '法线', '面积', '体积',
    '反常积分', '广义积分', '无穷限积分', '瑕积分', '原函数',
)
OPERATIONS = (
    '标准型', '通解公式', '积分因子', '降阶', '变量代换', '分离变量', '凑微分',
    '求秩', '秩', '包含', '同解', '公共解', '线性表示', '线性相关', '线性无关',
    '判秩', '消去', '消因子', '保秩', '阶梯形', '非零行数',
    '对角化', '正交化', '相似', '合同', '逆矩阵', '伴随', '迹', '分块',
    '条件分布', '边缘分布', '固定取值', '条件期望', '全概率', '分支加权',
    '协方差', '相关系数', '独立性', '归一化', '卷积', '标准化', '无偏性',
    '一致性', '有效性', '极大似然', '矩估计', '置信区间', '假设检验',
    '换序', '积分次序', '积分区域', '投影', '参数方程', '散度', '旋度',
    '判敛', '收敛半径', '收敛区间', '端点', '逐项积分', '逐项求导',
    '左右极限', '奇偶性', '周期延拓', '傅里叶系数', '点值', '极值', '最值',
    '隐函数', '反函数', '复合函数', '泰勒', '等价无穷小', '洛必达',
    '支撑', '支持范围', '分母非零', '分母为正', '分段', '不放回', '放回',
    '边缘概率', '奇端点', '有限端点', '无穷远', '上端', '下端', '双线性', '线性组合',
    '分区', '取交', '定限', '积分变量', '门槛', '通解结构', '仿射结构', '参数表示',
    '系数提取', '配项', '降维', '矩阵幂', '高次幂', '分解', '概率界', '保证界',
    '等价替换', '展开阶数', '计数', '乘法计数', '分步计数',
)
CONDITIONS = (
    '非齐次', '齐次', '非零', '不独立', '独立', '不相关', '相关', '非正态', '正态',
    '连续', '离散', '联合正态', '对称', '正交', '正定', '半正定', '不可逆', '可逆',
    '一阶', '二阶', '高阶', '常系数', '变系数', '同列数', '同阶',
    '有界', '无界', '单调', '非空', '可微', '连续可导',
    '同分布', '独立同分布', '非同分布', '方差有界', '方差一致有界', '阶梯形', '非阶梯形',
    '不可微', '不可导', '可导', '不连续', '非单调', '非线性', '线性', '不收敛', '收敛',
    '非正交', '非对称', '非独立', '不可积', '可积',
)

# Search vocabulary includes standard names and ordinary descriptions. This is
# not a theorem-level assertion of equivalence or a weakened applicability rule.
EQUIVALENCES = (
    ('零空间', '核空间', '齐次解空间', '齐次方程组解集'),
    ('条件密度', '条件概率密度', '固定取值条件'),
    ('分布函数', 'CDF', '累计概率'),
    ('支撑', '支持范围', '取值范围'),
    ('方差', '二阶中心矩'),
    ('特征值', '特征根'),
    ('逆矩阵', '矩阵求逆'),
    ('换序', '交换积分次序'),
    ('全概率', '分支加权'),
    ('极大似然', '最大似然', 'MLE'),
    ('满行秩', '行满秩'),
    ('满列秩', '列满秩'),
    ('二维正态', '二元正态'),
    ('反常积分', '广义积分'),
    ('方差一致有界', '方差有界'),
)


def normalize(value):
    return re.sub(r'\s+', '', str(value)).casefold()


def identity_names(title, candidates):
    """Old lookup rows include navigation descriptions, not only synonyms.

    Keep those descriptions searchable, but reserve identity priority for the
    canonical title and an explicitly known equivalent mathematical name.
    """
    def key(value):
        value=normalize(value).replace('的','')
        for group in EQUIVALENCES:
            for term in sorted(group,key=len,reverse=True):
                value=value.replace(normalize(term),normalize(group[0]))
        return value
    wanted=key(title)
    return sorted(set([title,*[value for value in candidates if _safe_name(value) and key(value)==wanted]]))


def classify_title(title):
    text = normalize(title)
    if (re.match(r'^20\d{2}(?:[-/.年]\d{1,2})', text)
            or text in {'知识点簇索引', '知识点索引', '方法簇索引', '错因簇索引',
                        '今日复盘', '晚间复盘', '复盘总结', '学习记录', '未分类'}
            or re.fullmatch(r'(?:\d+[-_])?(?:今日|当日|每日|晚间|晨间)?(?:学习|复盘)(?:总结|记录|索引|导航)', text)):
        return {'kind': 'artifact', 'reason': 'navigation_or_date_is_not_a_mathematical_point'}
    if any(word in text for word in ('仅按来源', '非原子来源待拆分', '待精分', '知识点待补')):
        return {'kind': 'unclassified', 'reason': 'source_placeholder_requires_classification'}
    if title in BROAD:
        return {'kind': 'parent', 'reason': 'broad_topic_not_a_specific_operation'}
    return {'kind': 'concept', 'reason': 'mathematical_catalog_entry'}


def _terms(text, vocabulary):
    found = []
    for term in vocabulary:
        # A negative mathematical predicate is an indivisible qualifier.
        positive_condition = vocabulary is CONDITIONS and not term.startswith(('非','不','无','未'))
        if positive_condition or term in {'齐次', '独立', '相关', '正态', '可逆', '正定', '放回', '同分布', '阶梯形',
                    '可微', '可导', '单调', '线性', '收敛', '连续', '有界'}:
            hit = re.search(r'(?<!非)(?<!不)(?<!无)(?<!半)' + re.escape(term), text)
        else:
            hit = term in text
        if hit:
            found.append(term)
    return sorted(set(found), key=lambda s: (-len(s), s))


def _safe_name(value):
    return (isinstance(value, str) and 1 < len(value) <= 60
            and not re.search(r'[=\\\n\r<>≤≥⊆⊂∫]', value)
            and not any(word in value for word in ('先', '再', '应当', '必须', '不能', '即可', '个人断点', '讲题入口')))


def _stem(value):
    text = re.split('[:：]', value, maxsplit=1)[0]
    for word in ('微分', '方程组', '求解', '基本', '的', '与', '关系', '性质', '定义'):
        text = text.replace(word, '')
    return text


def _shared_primary(label, method_name):
    """A parent binding must not inherit every child's route as an exact alias."""
    a, b = _stem(label), _stem(method_name)
    return len(a) >= 4 and len(b) >= 4 and (a == b or a.startswith(b) or b.startswith(a))


def signature(title, aliases=(), *, broad=False, subject=None, method_cues=()):
    names = [title, *[a for a in aliases if _safe_name(a)]]
    body = ' '.join(names)
    objects, operations, conditions = _terms(body, OBJECTS), _terms(body, OPERATIONS), _terms(body, CONDITIONS)
    # A neutral method title can supply an operation term without publishing
    # its formula, detailed steps or the learner's preferred solution.
    for cue in method_cues:
        operations.extend(_terms(cue, OPERATIONS))
    expanded_objects = list(objects)
    for group in EQUIVALENCES:
        if any(t in objects or t in operations or t in body for t in group):
            expanded_objects.extend(group)
    return {'objects': sorted(set(expanded_objects)), 'operations': sorted(set(operations)),
            'conditions': conditions, 'aliases': sorted(set(a for a in names if _safe_name(a))),
            'subject': subject, 'granularity': 'parent' if broad else 'specific' if operations else 'concept',
            'broad': bool(broad)}


def build_descriptors(root, documents):
    root = Path(root)
    catalog_path, binding_path = root/BASE/'catalog.json', root/BASE/'bindings.json'
    catalog = json.loads(catalog_path.read_text()) if catalog_path.is_file() else {}
    bindings = json.loads(binding_path.read_text()) if binding_path.is_file() else {}
    if catalog or bindings:
        index = root/'错题知识网络/个人知识点索引/index.sqlite3'
        with closing(sqlite3.connect(index.resolve().as_uri()+'?mode=ro', uri=True)) as conn:
            for path in (catalog_path, binding_path):
                if not path.is_file():
                    raise ValueError('retrieval_method_registry_incomplete')
                expected = conn.execute('SELECT sha256 FROM sources WHERE path=?',
                                        (str(path.relative_to(root)),)).fetchone()
                if not expected or expected[0] != hashlib.sha256(path.read_bytes()).hexdigest():
                    raise ValueError('retrieval_method_registry_not_current')
    methods = {m['method_id']: m for m in catalog.get('methods', [])}
    broad = set(BROAD)
    if (root/POLICY).is_file():
        broad.update(json.loads((root/POLICY).read_text()).get('broad_knowledge', []))
    quarantine, result = [], []
    for document in documents:
        doc = dict(document)
        classification = classify_title(doc['title'])
        if classification['kind'] in {'artifact', 'unclassified'}:
            quarantine.append({'concept_key': doc['concept_key'], 'label': doc['title'], **classification})
            continue
        is_broad = doc['title'] in broad
        cues, names, references = [], list(doc.get('aliases', [])), []
        for item in bindings.get('concept_bindings', {}).get(doc['concept_key'], []):
            method = methods.get(item.get('method_id'), {})
            method_names = [method.get('name', ''), *method.get('aliases', [])]
            if not is_broad and any(_shared_primary(doc['title'], name) for name in method_names if isinstance(name, str)):
                cues.append(method['name'])
                prefix = re.split('[:：]', method['name'], maxsplit=1)[0]
                if prefix != method['name'] and _safe_name(prefix):
                    names.append(prefix)
                # A method cue is not an identity alias: "通解公式" alone
                # must not uniquely identify a particular differential equation.
                cues.extend(a for a in method.get('aliases', []) if _safe_name(a))
                references.append(item['method_id'])
        subjects = {fid.split('-')[0] for fid in doc.get('formal_ids', []) if isinstance(fid, str) and '-' in fid}
        original_names=sorted(set(names))
        strong_names=identity_names(doc['title'],original_names)
        doc['aliases'] = strong_names
        doc['search_descriptions'] = [name for name in original_names if name not in strong_names]
        doc['alias_policy'] = 'canonical_or_declared_mathematical_equivalence_only'
        doc['knowledge_type'] = 'parent' if is_broad else 'concept'
        doc['discovery_eligible'] = True
        doc['retrieval_signature'] = signature(doc['title'], strong_names, broad=is_broad,
            subject=next(iter(subjects)) if len(subjects)==1 else None, method_cues=cues)
        doc['retrieval_signature']['primary_operations']=_terms(' '.join(strong_names),OPERATIONS)
        # Keep the complete neutral names available for lexical discrimination;
        # the fixed object/operation vocabulary is intentionally not exhaustive.
        # These are weaker search descriptions, never alternative identities.
        doc['retrieval_signature']['search_phrases'] = sorted(set(
            value for value in [doc['title'], *original_names, *cues] if _safe_name(value)))
        doc['retrieval_signature']['trusted_phrases'] = sorted(set(
            value for value in [doc['title'],*strong_names,*cues] if _safe_name(value)))
        doc['retrieval_signature']['named_condition_sources'] = []
        doc['method_identity_names'] = []
        for method_id in references:
            method=methods.get(method_id,{})
            doc['method_identity_names'].extend(value for value in
                [re.split('[:：]',method.get('name',''),maxsplit=1)[0],*method.get('aliases',[])] if _safe_name(value))
        doc['text']='数学知识点：'+doc['title']+'\n身份名称：'+'；'.join(strong_names)
        if doc['search_descriptions']:
            doc['text']+='\n相关检索描述（不作为同义名）：'+'；'.join(doc['search_descriptions'])
        # A named clause in an already-bound method can add neutral prerequisite
        # vocabulary for that named theorem, without inheriting sibling clauses.
        for item in bindings.get('concept_bindings', {}).get(doc['concept_key'], []):
            method = methods.get(item.get('method_id'), {})
            for condition in method.get('conditions', []):
                parts = re.split('[:：]', condition, maxsplit=1)
                if len(parts) != 2:
                    continue
                qualifier = parts[0].replace('版本', '').strip()
                if len(qualifier) >= 2 and qualifier in doc['title']:
                    doc['retrieval_signature']['conditions'].extend(_terms(parts[1], CONDITIONS))
                    doc['retrieval_signature']['objects'].extend(_terms(parts[1], OBJECTS))
                    doc['retrieval_signature']['named_condition_sources'].append(
                        {'method_id':item['method_id'],'named_branch':qualifier,'text':parts[1],
                         'objects':_terms(parts[1],OBJECTS),
                         'conditions':[term for term in _terms(parts[1],CONDITIONS)
                            if not any(term!=other and term in other for other in _terms(parts[1],CONDITIONS))],
                         'goal_terms':[term for term in _terms(method.get('name',''),(*OBJECTS,*OPERATIONS))
                            if term not in _terms(parts[1],OBJECTS) and term not in _terms(parts[1],CONDITIONS)],
                         'zero_one_required':bool(re.search(r'0[—－-]1',parts[1]))})
                    references.append(item['method_id'])
        doc['retrieval_signature']['conditions'] = sorted(set(doc['retrieval_signature']['conditions']))
        bound_ids = {x.get('method_id') for x in bindings.get('concept_bindings', {}).get(doc['concept_key'], [])}
        # Source-bound operation descriptions are cues, never exact identity
        # aliases or instructions claiming a theorem applies to the new task.
        if '协方差' in doc['title'] and '双线性' in doc['title'] and bound_ids.intersection({'PR-M56','LM-B-M-225'}):
            doc['retrieval_signature']['operations'].extend(['双线性展开','两侧展开','展开和差','展开四项','四项展开'])
            references.extend(sorted(bound_ids.intersection({'PR-M56','LM-B-M-225'})))
        if '二重积分' in doc['title'] and '轮换' in doc['title'] and 'GS14-06' in bound_ids:
            doc['retrieval_signature']['objects'].append('积分区域')
            doc['retrieval_signature']['operations'].extend(['变量交换','交换变量','变量轮换','轮换变量'])
            doc['retrieval_signature']['conditions'].append('区域不变')
            references.append('GS14-06')
        if '分布函数法' in doc['title'] and '分区' in doc['title'] and 'PR-M39' in bound_ids:
            doc['retrieval_signature']['objects'].extend(['支持区域','积分变量'])
            doc['retrieval_signature']['operations'].extend(['区域取交','取交','积分定限','定限'])
            references.append('PR-M39')
        for field in ('objects','operations','conditions'):
            doc['retrieval_signature'][field] = sorted(set(doc['retrieval_signature'][field]))
        # "X中的A/B" retains its actual subject domain. These neutral names
        # identify the topic being discussed, not facts assumed of a new task.
        scope = re.split(r'中的|下的|时的', doc['title'], maxsplit=1)[0]
        if scope != doc['title']:
            doc['retrieval_signature']['scope_objects'] = [scope]
            if scope == '二维正态' and any(x.get('method_id') == 'PR-M47' for x in
                    bindings.get('concept_bindings', {}).get(doc['concept_key'], [])):
                doc['retrieval_signature']['scope_aliases'] = ['二元正态', '联合正态']
                doc['retrieval_signature']['scope_note'] = '二维讨论范围；出现联合正态一词不证明题设满足它。'
        doc['descriptor_method_ids'] = sorted(set(references))
        doc['method_identity_names']=sorted(set(doc['method_identity_names']))
        result.append(doc)
    return result, quarantine


def source_revision(root):
    root = Path(root)
    paths = [Path(__file__), root/BASE/'catalog.json', root/BASE/'bindings.json', root/POLICY]
    h = hashlib.sha256(VERSION.encode())
    for path in paths:
        h.update(str(path.name).encode())
        h.update(path.read_bytes() if path.is_file() else b'missing')
    return h.hexdigest()
