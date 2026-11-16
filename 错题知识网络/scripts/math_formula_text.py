"""Deterministic display notation cleanup; never supplies mathematical content."""
from __future__ import annotations

import re

# Existing superscript groups must remain intact. A regex applied inside a
# command name would corrupt f^{\\prime\\prime} into nested superscripts.
MATH_SPAN = re.compile(r'(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|(?<![\\$])\$(?!\$)[^$\n]+?\$(?!\$))')
TEX_MARKER = re.compile(r'\\[A-Za-z]+|[_^]')
CJK = re.compile(r'[\u3400-\u9fff，。；：、！？“”‘’]')


def _normalize_primes(value):
    result, stack = [], []
    superscript_next = False
    i = 0
    while i < len(value):
        char = value[i]
        if char == '^':
            result.append(char); superscript_next = True; i += 1; continue
        if char.isspace():
            result.append(char); i += 1; continue
        if char == '{':
            stack.append(superscript_next or any(stack))
            superscript_next = False; result.append(char); i += 1; continue
        if char == '}':
            if stack:
                stack.pop()
            superscript_next = False; result.append(char); i += 1; continue
        if char == '\\':
            command = re.match(r'\\[A-Za-z]+|\\.', value[i:])
            token = command[0] if command else char
            if token == r'\prime' and not any(stack):
                run = re.match(r'(?:\\prime\s*)+', value[i:])[0]
                primes = re.findall(r'\\prime', run)
                previous = ''.join(result).rstrip()
                has_base = bool(previous) and (previous[-1].isalnum() or previous[-1] in ')]}')
                if superscript_next and len(primes) > 1:
                    result.append('{' + ''.join(primes) + '}')
                    i += len(run); superscript_next = False; continue
                if not superscript_next and has_base:
                    result.append('^{' + ''.join(primes) + '}')
                    i += len(run); superscript_next = False; continue
            result.append(token)
            i += len(token); superscript_next = False; continue
        result.append(char); superscript_next = False; i += 1
    return ''.join(result)


def _separate_row_brackets(value):
    # In array/cases TeX, \\[... ] is optional row spacing. An interval or a
    # bracketed expression after a row break instead needs an empty group.
    if not re.search(r'\\begin\{(?:cases|[pbvBV]?matrix|array|aligned|gathered)', value):
        return value
    def replace(match):
        content = match[2].strip()
        dimension = re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*(?:pt|em|ex|mu|cm|mm|in|bp|pc|dd|cc|sp)', content)
        if dimension:
            return match[0]
        return match[1] + '{}[' + match[2] + ']'
    return re.sub(r'(\\\\)\[([^\]]*)\]', replace, value)


def _parenthesized_exponents(value):
    """Convert an explicitly grouped legacy exponent, never infer an exponent."""
    parts, start, position = [], 0, 0
    while position < len(value):
        match = re.search(r'(?<!\\)\^\s*\(', value[position:])
        if match is None:
            break
        caret = position + match.start()
        opening = position + match.end() - 1
        depth, closing = 1, opening + 1
        while closing < len(value) and depth:
            if value[closing] == '(' and value[closing - 1] != '\\':
                depth += 1
            elif value[closing] == ')' and value[closing - 1] != '\\':
                depth -= 1
            closing += 1
        if depth:
            position = opening + 1
            continue
        body = value[opening + 1:closing - 1]
        if body.strip():
            parts.extend((value[start:caret], '^{' + body + '}'))
            start = closing
        position = closing
    parts.append(value[start:])
    return ''.join(parts)


def normalize_latex(value):
    if not isinstance(value, str):
        raise ValueError('formula_latex_string_required')
    value = value.strip()
    for left, right in [('$$', '$$'), ('\\[', '\\]'), ('\\(', '\\)'), ('$', '$')]:
        if value.startswith(left) and value.endswith(right) and len(value) > len(left) + len(right):
            value = value[len(left):-len(right)].strip()
            break
    value = value.replace(r'\centernot', r'\not')
    value = _parenthesized_exponents(value).replace('−', '-')
    return _separate_row_brackets(_normalize_primes(value))


GREEK_NAMES = {
    'alpha', 'beta', 'gamma', 'delta', 'epsilon', 'varepsilon', 'zeta', 'eta',
    'theta', 'vartheta', 'iota', 'kappa', 'lambda', 'mu', 'nu', 'xi', 'pi',
    'rho', 'varrho', 'sigma', 'tau', 'upsilon', 'phi', 'varphi', 'chi', 'psi', 'omega',
    'Gamma', 'Delta', 'Theta', 'Lambda', 'Pi', 'Sigma', 'Upsilon', 'Phi', 'Psi', 'Omega',
}
OPERATORS = {'Cov', 'cov', 'sgn', 'arctan', 'arcsin', 'arccos', 'tr', 'adj', 'rank', 'dim', 'span', 'Span', 'Row', 'Col', 'diag', 'Var'}


def normalize_symbol(value, *, role='', corpus=''):
    """Translate declared symbol aliases, not arbitrary prose or mathematical claims."""
    if not isinstance(value, str):
        raise ValueError('formula_symbol_string_required')
    value = value.strip()
    if value.endswith('_') and value[:-1] in GREEK_NAMES:
        value = value[:-1]  # Python-safe alias lambda_ is not an empty subscript.
    if value in GREEK_NAMES:
        return '\\' + value
    if value in OPERATORS:
        return r'\operatorname{' + value + '}'
    if value in {'Xbar', 'Ybar', 'xbar', 'ybar'}:
        return r'\bar{' + value[0] + '}'
    if re.fullmatch(r'[A-Za-z]+(?:_\d+)?_sq', value):
        return normalize_symbol(value[:-3], role=role, corpus=corpus) + '^2'
    if value.endswith('_hat'):
        return r'\widehat{' + normalize_symbol(value[:-4], role=role, corpus=corpus) + '}'
    if value.endswith('_perp') and ('正交' in role or r'\perp' in corpus or '⊥' in corpus):
        return normalize_symbol(value[:-5], role=role, corpus=corpus) + r'^{\perp}'
    if re.fullmatch(r'[A-Za-z]+_[A-Za-z0-9]+', value):
        base, sub = value.split('_', 1)
        base = '\\' + base if base in GREEK_NAMES else base
        sub = '\\' + sub if sub in GREEK_NAMES else sub
        return base + '_{' + sub + '}'
    # Unseparated aliases become indexed symbols only if that exact indexed
    # symbol is already present in the supplied mathematics.
    if re.fullmatch(r'[A-Za-z][A-Za-z0-9]{1,2}', value):
        base, sub = value[0], value[1:]
        forms = [base + '_{' + sub + '}', base + '_' + sub]
        small = str.maketrans('0123456789aehijklmnoprstuvx', '₀₁₂₃₄₅₆₇₈₉ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ')
        unicode_form = base + sub.translate(small)
        if any(x in corpus for x in forms) or (unicode_form != value and unicode_form in corpus):
            return forms[0]
    return normalize_latex(value)


def _wrap_plain(value):
    """Wrap only visibly supplied TeX spans at Chinese prose boundaries.

    Braced command arguments stay together, including Chinese inside text{}.
    Nothing is guessed for incomplete braces or unmatched dollar delimiters.
    """
    if not TEX_MARKER.search(value):
        return value
    tokens, current, depth = [], [], 0
    for i, char in enumerate(value):
        escaped = i > 0 and value[i - 1] == '\\'
        if char == '{' and not escaped:
            depth += 1
        elif char == '}' and not escaped:
            depth -= 1
        separator = depth == 0 and (bool(CJK.fullmatch(char)) or char == '\n')
        if separator:
            if current:
                tokens.append(''.join(current)); current = []
            tokens.append(char)
        else:
            current.append(char)
    if current:
        tokens.append(''.join(current))
    if depth != 0 or '$' in value:
        return value
    result = []
    for token in tokens:
        if not TEX_MARKER.search(token):
            result.append(token)
            continue
        before = token[:len(token) - len(token.lstrip())]
        after = token[len(token.rstrip()):]
        core = token.strip()
        # A punctuation separator belongs to prose, not to the formula.
        prefix = ''
        while core and core[0] in ':;,':
            prefix += core[0]; core = core[1:].lstrip()
        suffix = ''
        while core and core[-1] in ':;,':
            suffix = core[-1] + suffix; core = core[:-1].rstrip()
        if not core or core.count('{') != core.count('}'):
            result.append(token)
        else:
            result.append(before + prefix + '\\( ' + normalize_latex(core) + ' \\)' + suffix + after)
    return ''.join(result)


def normalize_rich_text(value):
    if not isinstance(value, str):
        raise ValueError('formula_display_text_required')
    parts, cursor = [], 0
    for match in MATH_SPAN.finditer(value):
        parts.append(_wrap_plain(value[cursor:match.start()]))
        raw = match[0]
        expression = normalize_latex(raw)
        if raw.startswith(('$$', '\\[')):
            parts.append('$$\n' + expression + '\n$$')
        else:
            parts.append('\\( ' + expression + ' \\)')
        cursor = match.end()
    parts.append(_wrap_plain(value[cursor:]))
    return ''.join(parts)


def normalize_display_value(value, *, key=''):
    """Normalize presentation copies only; provenance and original text stay intact."""
    if isinstance(value, str):
        return normalize_latex(value) if key in {'formula_latex', 'instantiated_formula_latex'} else normalize_rich_text(value)
    if isinstance(value, list):
        return [normalize_display_value(x, key=key) for x in value]
    if isinstance(value, dict):
        return {k: normalize_display_value(v, key=k) for k, v in value.items()}
    return value
