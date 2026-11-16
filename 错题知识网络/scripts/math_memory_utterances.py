"""Private, rebuildable index of accepted user quotations.

FTS supplies a bounded pool. Only the shared evidence matcher can qualify a
source sentence. No learner state, question, score or original file is written.
The public response contains source handles, never the indexed quote text.
"""
from __future__ import annotations

from contextlib import closing
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unicodedata

SCHEMA = 'math-private-user-utterances-v1'
NATIVE = Path('错题知识网络/个人知识点索引/index.sqlite3')
INDEX = Path('错题知识网络/个人知识点索引/原话索引/index.sqlite3')
RECEIPT = INDEX.with_suffix('.receipt.json')
PROFILES = Path('错题知识网络/个人知识点索引/语义概况')
CORRECTIONS = Path('错题知识网络/个人知识点索引/记忆维护/transactions')
KINDS = {'formal_concept_observation', 'concept_review'}
MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_POOL = 64


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _stamp(path):
    try:
        s = path.stat()
        return [s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino]
    except OSError:
        return None


def _inside(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('utterance_source_outside_repository')
    target = root/rel
    if target.is_symlink() or not target.resolve().is_relative_to(root):
        raise ValueError('utterance_source_outside_repository')
    return target


def _correction_generation(root):
    base = root/CORRECTIONS
    return digest([_stamp(base), [(p.name, _stamp(p)) for p in sorted(base.glob('*.json'))]])


def _native_version(root):
    with closing(sqlite3.connect((root/NATIVE).as_uri()+'?mode=ro', uri=True)) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()
    if not row:
        raise ValueError('native_version_missing')
    return json.loads(row[0])


def _builder_revision():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _normalize(text):
    text = unicodedata.normalize('NFKC', str(text)).casefold().replace('−', '-').replace('–', '-')
    text = re.sub(r'\\(?:operatorname|mathrm|text|left|right)', '', text)
    return re.sub(r'[\s{}，,。；;：“”\"\'？！!?]', '', text)


def _tokens(text):
    """Hashed character ngrams avoid FTS parser syntax and CJK segmentation loss."""
    value = _normalize(text)
    result = set()
    for n in (2, 3, 4):
        for start in range(max(0, len(value)-n+1)):
            gram = value[start:start+n]
            if any(c.isalnum() or '\u3400' <= c <= '\u9fff' for c in gram):
                result.add('g'+hashlib.sha256(gram.encode()).hexdigest()[:20])
    return sorted(result)


def _anchor_expression(text):
    value=_normalize(text)
    if not value:
        return None
    size=min(4,len(value))
    if size<2:
        return None
    tokens=['g'+hashlib.sha256(value[i:i+size].encode()).hexdigest()[:20]
            for i in range(len(value)-size+1)]
    return '('+' AND '.join(dict.fromkeys(tokens))+')'


def _fts_expression(query, quote_request, intent, evidence):
    extractor=getattr(evidence,'evidence_anchors',None)
    anchors=extractor(query) if extractor else {}
    literals=_strings(anchors.get('literals'))
    maths=_strings(anchors.get('math_atoms'))
    terms=sorted(set(_strings(anchors.get('terms'))),key=lambda v:(-len(_normalize(v)),v))[:8]
    primary=[value for term in [*literals,*maths] if (value:=_anchor_expression(term))]
    groups=[]
    for term in terms:
        variants=[term]
        for equivalence in evidence.MATH_WORD_EQUIVALENCES:
            if term in equivalence:variants.extend(equivalence)
        alternatives=list(dict.fromkeys(value for variant in variants if (value:=_anchor_expression(variant))))
        if alternatives:groups.append('('+' OR '.join(alternatives)+')')
    teaching=[]
    for action in anchors.get('teaching_actions',[]):
        alternatives=[value for term in action.get('surfaces',[]) if (value:=_anchor_expression(term))]
        if alternatives:
            teaching.append('('+' OR '.join(alternatives)+')')
        # A requested name is an independent exact anchor even when its
        # grammatical position changed. Variable pairs are checked by the
        # shared matcher because their conjunction can have several surfaces.
        if action.get('action')=='rename':
            teaching.extend(value for term in action.get('objects',[]) if (value:=_anchor_expression(term)))
    teaching_expression=' AND '.join(teaching)
    if primary:
        # The shared matcher accepts a supported literal OR a mathematical
        # expression. An explanatory paraphrase must not suppress an exact atom.
        expression=' OR '.join(primary)
        if len(groups)>=2:
            expression+=' OR ('+' AND '.join(groups)+')'
        elif groups and intent.get('historical_statement'):
            # Recall lexical variants; the shared matcher still verifies
            # the requested utterance, operands, and positive/negative intent.
            expression+=' OR '+groups[0]
    elif groups:
        # The matcher understands mathematical/operation synonyms. FTS must
        # not demand that every source use the query's exact surface wording.
        expression=' OR '.join(groups)
    else:
        spans=intent.get('historical_spans') or []
        text=' '.join(v.get('text','') for v in spans if isinstance(v,dict)) or query
        tokens=_tokens(text)
        expression=' OR '.join(tokens[:384])
    if teaching_expression:
        # Compositional report matching has its own precise candidate path.
        # Never OR it with the whole-query ngram fallback: that would retain
        # all generic historical/reporting words and truncate the useful pool.
        expression=('('+' OR '.join(primary)+') OR ('+teaching_expression+')') if primary else teaching_expression
    return 'quote_terms:('+expression+')' if quote_request and expression else expression


def _strings(value):
    if isinstance(value,str):
        return [value]
    return [v for v in value if isinstance(v,str)] if isinstance(value,(list,tuple)) else []


def _turns(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ('turns', 'messages', 'conversation'):
            if isinstance(value.get(key), list):
                return value[key]
    return []


def _user_matches(value, quote, sequence=None, context='root', package_id=None):
    """Find an actual role=user sentence, not an observation's quoted summary."""
    found = []
    if isinstance(value, dict):
        package_id = value.get('package_id') or package_id
        role=value.get('role')
        if role in {'user','assistant','system','developer','tool'}:
            # Never promote a role-looking object quoted inside another role's
            # content. Cropped preference sources may lack original sequence;
            # keep that unknown rather than inventing a transcript position.
            if role!='user':
                return []
            from math_learning_profiles import _turn_text
            text=_turn_text(value)
            number=value.get('sequence')
            if quote in text and (sequence is None or sequence==number):
                return [{'sequence':number,'context':context,'package_id':package_id,
                         'full_text_sha256':hashlib.sha256(text.encode()).hexdigest()}]
            return []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                found.extend(_user_matches(item, quote, sequence, context+'/'+str(key), package_id))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_user_matches(item, quote, sequence, context+'/'+str(index), package_id))
    return found


class _Sources:
    def __init__(self, root):
        self.root = root
        self.cache = {}
        self.dependencies = {}

    def read(self, ref):
        if not isinstance(ref, dict) or not re.fullmatch('[0-9a-f]{64}', str(ref.get('sha256', ''))):
            raise ValueError('utterance_source_hash_required')
        path = _inside(self.root, ref['path'])
        key = (ref['path'], ref['sha256'])
        if key not in self.cache:
            before = _stamp(path)
            self.dependencies[ref['path']] = {'sha256':ref['sha256'], 'stamp':before}
            if before is None or before[0] > MAX_SOURCE_BYTES:
                raise ValueError('utterance_source_unavailable')
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != ref['sha256'] or _stamp(path) != before:
                raise ValueError('utterance_source_changed')
            self.cache[key] = json.loads(raw)
        return self.cache[key]


def _refs(record):
    return [{'path':v['path'], 'sha256':v['sha256']} for v in record.get('source_refs', [])
            if isinstance(v, dict) and isinstance(v.get('path'), str) and isinstance(v.get('sha256'), str)]


def _formal_quotes(record, sources):
    import math_memory_lifecycle as lifecycle
    summary = record.get('summary', {})
    refs = _refs(record)
    documents = [sources.read(ref) for ref in refs]
    results = []
    for observation in summary.get('observations', []):
        capture_id = observation.get('capture_event_id')
        source_observation = None
        package = None
        for source in documents:
            if source.get('closeout_id') != summary.get('event_id'):
                continue
            for target in source.get('concept_observations', {}).get('targets', []):
                if (target.get('formal_id') != record.get('formal_id')
                        or target.get('study_date') != summary.get('study_date')):
                    continue
                for saved in target.get('observations', []):
                    if lifecycle.observation_hash(saved) == lifecycle.observation_hash(observation):
                        source_observation = saved
                        package = target.get('packages', {}).get(capture_id)
                        break
        if not source_observation or not isinstance(package, dict):
            continue
        turns = _turns(package.get('conversation'))
        hints=source_observation.get('hint_evidence',[])
        if any(type(h.get('sequence')) is not int or not 1<=h['sequence']<=len(turns)
               or turns[h['sequence']-1].get('role')!='assistant'
               or not isinstance(h.get('quote'),str)
               or h['quote'] not in str(turns[h['sequence']-1].get('text',turns[h['sequence']-1].get('content','')))
               for h in hints):
            continue
        for item in source_observation.get('user_evidence', []):
            number, quote = item.get('sequence'), item.get('quote')
            if (type(number) is not int or not 1 <= number <= len(turns) or
                    not isinstance(quote, str) or not quote.strip()):
                continue
            turn = turns[number-1]
            if turn.get('role') != 'user' or quote not in str(turn.get('text', turn.get('content', ''))):
                continue
            full_text=str(turn.get('text',turn.get('content','')))
            results.append((quote, number, package.get('package_id') or capture_id,
                            source_observation, refs,hashlib.sha256(full_text.encode()).hexdigest()))
    return results


def _walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _review_quotes(record, sources):
    summary = record.get('summary', {})
    refs = _refs(record)
    documents = [sources.read(ref) for ref in refs]
    results = []
    for observation in summary.get('observations', []):
        for source in documents:
            for session in _walk(source):
                turns = _turns(session.get('conversation'))
                if not turns or observation not in session.get('observations', []):
                    continue
                for number in observation.get('user_turn_indices', []):
                    if type(number) is not int or not 0 <= number < len(turns):
                        continue
                    turn = turns[number]
                    text = turn.get('text', turn.get('content'))
                    if turn.get('role') == 'user' and isinstance(text, str) and text.strip():
                        origin = session.get('session_id') or summary.get('event_id')
                        results.append((text, number+1, origin, observation, refs,
                                        hashlib.sha256(text.encode()).hexdigest()))
    return results


def _assessment(root, record, observation):
    import math_memory_lifecycle as lifecycle
    summary = record.get('summary', {})
    key = observation.get('concept_key') or record.get('concept_key')
    event = {**summary, 'source_refs':record.get('source_refs', []), 'observations':[observation]}
    effective = lifecycle.apply_observation_corrections(root, [event], concept_key=key)
    rows = effective[0].get('observations', []) if effective else []
    status = rows[0].get('memory_status', 'accepted') if rows else 'retracted'
    return {'assessment_status':status,
            'accepted_outcome':rows[0].get('outcome') if rows else None,
            'effective_annotation':rows[0].get('error_detail','') if rows else '',
            'correction_source_refs':[{'path':ref['path'],'sha256':ref['sha256']}
                for decision in (effective[0].get('memory_corrections',[]) if effective else [])
                for ref in decision.get('source_refs',[])],
            'observation_sha256':lifecycle.observation_hash(observation)}


def _compile(root, conn, sources):
    grouped, excluded = {}, []
    package_origins = {}

    def add(quote, sequence, origin, binding, full_text_sha256):
        quote_sha = hashlib.sha256(quote.encode()).hexdigest()
        identity = digest([origin, sequence, quote_sha])
        row = grouped.setdefault(identity, {'utterance_id':identity, 'quote':quote,
            'quote_sha256':quote_sha, 'sequence':sequence, 'origin_id':origin,
            'source_turn_sha256s':[], 'bindings':[]})
        if full_text_sha256 not in row['source_turn_sha256s']:
            row['source_turn_sha256s'].append(full_text_sha256)
        if digest(binding) not in {digest(v) for v in row['bindings']}:
            row['bindings'].append(binding)

    for rid, body in conn.execute("SELECT id,payload FROM records WHERE json_extract(payload,'$.kind') IN ('formal_concept_observation','concept_review') ORDER BY id"):
        record = json.loads(body)
        try:
            values = _formal_quotes(record, sources) if record['kind']=='formal_concept_observation' else _review_quotes(record,sources)
        except (OSError,ValueError,KeyError,TypeError) as error:
            excluded.append({'record_id':rid, 'reason':type(error).__name__+':'+str(error)[:100]})
            continue
        summary = record.get('summary', {})
        if not values and summary.get('observations'):
            excluded.append({'record_id':rid,'reason':'no_verified_user_quote_with_exact_event_scope'})
        for quote, sequence, origin, observation, refs, full_text_sha256 in values:
            capture = observation.get('capture_event_id')
            key = observation.get('concept_key') or record.get('concept_key')
            if not key:
                continue
            assessment = _assessment(root, record, observation)
            for ref in assessment.get('correction_source_refs',[]):
                sources.read(ref)
            binding = {'record_id':rid, 'kind':record['kind'], 'concept_key':key,
                'formal_id':record.get('formal_id'), 'event_id':summary.get('event_id'),
                'capture_id':capture, 'observation_id':observation.get('observation_id'),
                'study_date':summary.get('study_date'), 'recorded_at':summary.get('recorded_at'),
                'known_at_semantics':'accepted_event_recorded_at', 'source_refs':refs,
                'role':'user', 'evidence_role':'accepted_user_quotation', 'sequence':sequence,
                'sequence_basis':'immutable_conversation_sequence' if record['kind']=='formal_concept_observation' else 'source_conversation_index_plus_one',
                'hint_sequences':[v['sequence'] for v in observation.get('hint_evidence',[]) if type(v.get('sequence')) is int]
                    or [v+1 for v in observation.get('hint_turn_indices',[]) if type(v) is int],
                'annotation':assessment.pop('effective_annotation'),
                'annotation_role':'accepted_observation_annotation_not_user_quote',
                **assessment}
            add(quote,sequence,origin,binding,full_text_sha256)
            if origin:
                package_origins.setdefault(origin,[]).append(binding)

    import math_learning_profiles as profiles
    profile_paths=sorted((root/PROFILES).glob('*.json'))+sorted((root/PROFILES/'历史版本').glob('*/*.json'))
    for path in profile_paths:
        try:
            if path.is_symlink():
                raise ValueError('preference_profile_symlink')
            raw = path.read_bytes(); value=json.loads(raw)
            if value.get('status') not in {'accepted_semantic_update','accepted_semantic_maintenance'}:
                continue
            if profiles.digest({k:v for k,v in value.items() if k!='content_sha256'}) != value.get('content_sha256'):
                raise ValueError('accepted_preference_profile_hash_mismatch')
            # The accepted profile must belong to the exact indexed generation.
            ref={'path':str(path.relative_to(root)),'sha256':hashlib.sha256(raw).hexdigest()}
            historical=path.parent!=root/PROFILES
            if historical:
                if (path.name != value['content_sha256']+'.json'
                        or path.parent.name != value.get('concept_key')):
                    raise ValueError('preference_history_identity_mismatch')
            else:
                expected=conn.execute('SELECT sha256 FROM sources WHERE path=?',(ref['path'],)).fetchone()
                if not expected or expected[0]!=ref['sha256']:
                    raise ValueError('preference_profile_not_indexed')
            sources.dependencies[ref['path']]={'sha256':ref['sha256'],'stamp':_stamp(path)}
            for pref_no,pref in enumerate(value.get('teaching_preferences',[])):
                for source in pref.get('source_refs',[]):
                    if source.get('role')!='user' or not isinstance(source.get('quote'),str):
                        continue
                    source_json=sources.read(source); quote=source['quote']
                    matches=_user_matches(source_json,quote,source.get('sequence'))
                    unique={(m['package_id'],m['context'],m['sequence'],m['full_text_sha256']):m for m in matches}
                    if len(unique)!=1:
                        excluded.append({'profile':path.name,'reason':'preference_quote_role_or_position_not_unique'})
                        continue
                    turn=next(iter(unique.values()))
                    origin=turn['package_id'] or source['sha256']+':'+turn['context']
                    originals=package_origins.get(origin,[])
                    known_fids={v['formal_id'] for v in originals if v.get('formal_id')}
                    dates={v['study_date'] for v in originals if v.get('study_date')}
                    found=re.search(r'20\d{2}-\d{2}-\d{2}',str(source.get('locator','')))
                    date=next(iter(dates)) if len(dates)==1 else found[0] if found else None
                    add(quote,turn['sequence'],origin,{'record_id':'preference:'+value['concept_key']+':'+str(pref_no),
                        'kind':'teaching_preference','concept_key':value['concept_key'],
                        'formal_id':next(iter(known_fids)) if len(known_fids)==1 else None,
                        'event_id':value.get('event_id') or value.get('maintenance_id'), 'capture_id':None,
                        'study_date':date,'recorded_at':value.get('memory_recorded_at'),
                        'known_at_semantics':'profile_acceptance_time_if_recorded',
                        'role':'user','evidence_role':'accepted_preference_user_quotation',
                        'preference_basis':pref.get('basis'),'preference_scope':pref.get('scope'),
                        'preference_version_status':'historical_accepted_profile' if historical else 'current_accepted_profile',
                        'profile_revision':value['content_sha256'],'not_current_preference_proof':True,
                        'sequence':turn['sequence'],'source_refs':[{'path':source['path'],'sha256':source['sha256']}],
                        'sequence_basis':'recorded_source_sequence' if turn['sequence'] is not None else 'source_json_pointer_only',
                        'source_json_pointer':turn['context'],'source_locator':source.get('locator'),
                        'profile_source_ref':ref,'hint_sequences':[], 'annotation':'',
                        'annotation_role':None,'assessment_status':'preference_not_mastery','accepted_outcome':None},turn['full_text_sha256'])
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as error:
            excluded.append({'profile':path.name,'reason':type(error).__name__+':'+str(error)[:100]})
    return list(grouped.values()), excluded


def _open_private(root):
    path=_inside(root,INDEX)
    if not path.is_file():
        raise ValueError('utterance_index_unavailable')
    return sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)


def _data_digest(conn):
    h=hashlib.sha256()
    for table,columns,order in [('utterances','id,quote,normalized_quote,payload','id'),
                                ('bindings','utterance_id,concept_key,formal_id,study_date,recorded_at,payload','utterance_id,concept_key,formal_id,payload'),
                                ('utterance_fts','id,quote_terms,annotation_terms','id')]:
        for row in conn.execute('SELECT '+columns+' FROM '+table+' ORDER BY '+order):
            h.update(canonical(list(row)).encode());h.update(b'\n')
    return h.hexdigest()


def _write_receipt(root, version):
    target=_inside(root,RECEIPT)
    data=canonical({'schema':SCHEMA,'version':version,'index_stamp':_stamp(root/INDEX)}).encode()
    temporary=target.with_suffix('.tmp')
    temporary.write_bytes(data);os.chmod(temporary,0o600);os.replace(temporary,target)


def _check_receipt(root, version):
    path=_inside(root,RECEIPT)
    value=json.loads(path.read_bytes())
    if (value.get('schema')!=SCHEMA or value.get('version')!=version
            or value.get('index_stamp')!=_stamp(root/INDEX)):
        raise ValueError('utterance_index_changed')


def _meta(conn):
    return {key:json.loads(value) for key,value in conn.execute('SELECT key,value FROM meta')}


def refresh(repo_root, expected_native_version):
    """Explicit maintenance; the native writer/postcommit invokes this separately."""
    root=Path(repo_root).resolve();target=_inside(root,INDEX)
    target.parent.mkdir(parents=True,exist_ok=True)
    with (target.parent/'build.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        native_version=_native_version(root)
        if native_version!=expected_native_version:
            raise ValueError('utterance_native_generation_changed')
        correction_generation=_correction_generation(root)
        try:
            with closing(_open_private(root)) as old:
                meta=_meta(old)
                integrity=meta.get('data_digest')==_data_digest(old)
            if (integrity and meta.get('schema')==SCHEMA and meta.get('native_version')==native_version
                    and meta.get('builder_revision')==_builder_revision()
                    and meta.get('correction_generation')==correction_generation
                    and all(_stamp(_inside(root,p))==v['stamp'] for p,v in meta.get('dependencies',{}).items())):
                _write_receipt(root,meta['version'])
                return {'status':'noop','version':meta['version'],'utterance_count':meta['utterance_count'],
                        'excluded_count':meta['excluded_count'],'formal_write_count':0}
        except (OSError,ValueError,KeyError,sqlite3.Error):
            pass
        sources=_Sources(root)
        with closing(sqlite3.connect((root/NATIVE).as_uri()+'?mode=ro',uri=True)) as native:
            native.execute('BEGIN')
            version=json.loads(native.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])
            if version!=native_version:
                raise ValueError('utterance_native_generation_changed')
            rows,excluded=_compile(root,native,sources)
        if (_native_version(root)!=native_version or _correction_generation(root)!=correction_generation
                or any(_stamp(_inside(root,p))!=v['stamp'] for p,v in sources.dependencies.items())):
            raise ValueError('utterance_sources_changed_during_build')
        version=digest([SCHEMA,native_version,correction_generation,rows,sources.dependencies,_builder_revision()])
        meta={'schema':SCHEMA,'version':version,'native_version':native_version,
              'correction_generation':correction_generation,'builder_revision':_builder_revision(),
              'utterance_count':len(rows),'binding_count':sum(len(r['bindings']) for r in rows),
              'excluded_count':len(excluded),'exclusions':excluded,
              'dependencies':sources.dependencies,'coverage':'accepted_user_evidence_and_preferences_only',
              'not_all_raw_conversation_sentences':True}
        fd,name=tempfile.mkstemp(dir=target.parent,prefix='.utterances-',suffix='.sqlite3');os.close(fd)
        temporary=Path(name)
        try:
            with closing(sqlite3.connect(temporary)) as db,db:
                db.executescript('''CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                    CREATE TABLE utterances(id TEXT PRIMARY KEY,quote TEXT NOT NULL,normalized_quote TEXT NOT NULL,payload TEXT NOT NULL);
                    CREATE INDEX utterances_literal ON utterances(normalized_quote);
                    CREATE TABLE bindings(utterance_id TEXT,concept_key TEXT,formal_id TEXT,study_date TEXT,recorded_at TEXT,payload TEXT);
                    CREATE INDEX bindings_scope ON bindings(concept_key,formal_id,study_date);
                    CREATE INDEX bindings_utterance ON bindings(utterance_id);
                    CREATE VIRTUAL TABLE utterance_fts USING fts5(id UNINDEXED,quote_terms,annotation_terms,tokenize='unicode61');''')
                for row in rows:
                    db.execute('INSERT INTO utterances VALUES (?,?,?,?)',(row['utterance_id'],row['quote'],_normalize(row['quote']),canonical({k:v for k,v in row.items() if k not in {'quote','bindings'}})))
                    annotation=' '.join(b['annotation'] for b in row['bindings'] if b.get('annotation') and b.get('assessment_status') not in {'retracted','conflicted'})
                    db.execute('INSERT INTO utterance_fts VALUES (?,?,?)',(row['utterance_id'],' '.join(_tokens(row['quote'])),' '.join(_tokens(annotation))))
                    for binding in row['bindings']:
                        db.execute('INSERT INTO bindings VALUES (?,?,?,?,?,?)',(row['utterance_id'],binding['concept_key'],binding.get('formal_id'),binding.get('study_date'),binding.get('recorded_at'),canonical(binding)))
                meta['data_digest']=_data_digest(db)
                db.executemany('INSERT INTO meta VALUES (?,?)',[(k,canonical(v)) for k,v in meta.items()])
            os.chmod(temporary,0o600);os.replace(temporary,target)
            _write_receipt(root,version)
        finally:
            temporary.unlink(missing_ok=True)
        return {'status':'ready','version':version,'native_version':native_version,
                'utterance_count':len(rows),'binding_count':meta['binding_count'],
                'excluded_count':len(excluded),'formal_write_count':0,'score_write_count':0,
                'index_path':str(INDEX),'coverage':meta['coverage']}


def _history_intent(query):
    import math_memory_evidence as evidence
    parser=getattr(evidence,'request_intent',None)
    intent=parser(query) if parser else {}
    historical=bool(intent.get('historical_statement'))
    historical=historical or bool(re.search(r'原话|说过|讲过|提过|我(?:当时|之前|以前)|那次|上次|过去|历史|记录',query))
    quote_request=bool(intent.get('requires_statement_verification'))
    return historical,quote_request,intent


def _complete_literal_targets(query,intent):
    values=[v.get('text','') for v in intent.get('historical_spans',[]) if isinstance(v,dict)]
    # The outer quotation can contain nested quotation marks. Treating its
    # shorter fragments as rival statements would manufacture ambiguity.
    import math_memory_evidence as evidence
    target_positions={match.start() for match in evidence._target_quotations(query)}
    for left,right in [('“','”'),('「','」'),('"','"'),("'","'")]:
        a,b=query.find(left),query.rfind(right)
        if a>=0 and b>a and a in target_positions:
            values.append(query[a+len(left):b])
    return {_normalize(v) for v in values if len(_normalize(v))>=4}


def _date_sql(dates,parameters):
    on,through=[],[]
    for value in dates or []:
        if not isinstance(value,dict):
            raise ValueError('utterance_date_scope_invalid')
        month,day=int(value['month']),int(value['day']);year=value.get('year')
        dt.date(int(year or 2000),month,day)
        mode=value.get('mode','on')
        if mode=='on':
            if year:
                on.append('b.study_date=?');parameters.append(f'{int(year):04d}-{month:02d}-{day:02d}')
            else:
                on.append('substr(b.study_date,6,5)=?');parameters.append(f'{month:02d}-{day:02d}')
        elif mode=='through':
            if year:
                through.append('b.study_date<=?');parameters.append(f'{int(year):04d}-{month:02d}-{day:02d}')
            else:
                through.append('substr(b.study_date,6,5)<=?');parameters.append(f'{month:02d}-{day:02d}')
        else:
            raise ValueError('utterance_date_scope_invalid')
    return (' AND ('+' OR '.join(on)+')' if on else '')+(' AND '+' AND '.join(through) if through else '')


def _safe_result(row,binding,match,version,known_at=None):
    value={k:v for k,v in binding.items() if k not in {'annotation','profile_source_ref'}}
    value.update(utterance_id=row['utterance_id'],quote_sha256=row['quote_sha256'],
        sequence=row['sequence'],source_origin_id=row['origin_id'],raw_text_returned=False,
        source_turn_sha256s=row.get('source_turn_sha256s',[]),
        not_current_mastery=True,match_kind=match.get('kind'),match_basis=match.get('matched_on','user_quote'),
        normalized_complete_quote_match=bool(match.get('normalized_complete_quote_match')),
        locator={'role':'user','sequence':row['sequence'],'quote_sha256':row['quote_sha256'],
                 'capture_event_id':binding.get('capture_id'),'observation_id':binding.get('observation_id'),
                 'sequence_basis':binding.get('sequence_basis'),
                 'source_json_pointer':binding.get('source_json_pointer'),
                 'source_locator':binding.get('source_locator')},
        source_handles=[{**r,'source_key':'source:'+digest(r['path'])[:24],
            'role':'user','sequence':row['sequence'],'raw_text_returned':False} for r in binding['source_refs']],
        index_version=version)
    value['assessment_time_scope']='current'
    if known_at:
        value.update(assessment_status='historical_assessment_not_reconstructed',accepted_outcome=None,
                     correction_source_refs=[],assessment_time_scope='not_reconstructed_for_known_at')
    return value


def search(repo_root, query, *, view, explicit_history_request, concept_keys=(), formal_ids=(),
           dates=(), known_at=None, limit=1, excluded_formal_ids=(), excluded_dates=()):
    """Return at most one source sentence, or explicit ambiguity; never raw text."""
    if view not in {'protected','after_attempt','direct'}:
        raise ValueError('utterance_view_invalid')
    if view=='protected':
        return {'status':'protected','selection_status':'not_requested','records':[]}
    if not explicit_history_request:
        return {'status':'not_requested','selection_status':'not_requested','records':[]}
    if not isinstance(query,str) or not query.strip() or len(query)>2000 or not 1<=limit<=8:
        raise ValueError('utterance_query_invalid')
    history,quote_request,intent=_history_intent(query)
    if not history:
        return {'status':'not_requested','selection_status':'not_requested','records':[],
                'reason':'explicit_historical_content_required'}
    root=Path(repo_root).resolve()
    result={'status':'unavailable','selection_status':'no_match','records':[],
            'coverage':'accepted_user_evidence_and_preferences_only','does_not_prove_absence':True,
            'formal_write_count':0,'score_write_count':0,'raw_text_returned':False}
    try:
        import math_memory_evidence as evidence
        matcher=getattr(evidence,'user_evidence_match',None)
        if matcher is None:
            raise ValueError('utterance_matcher_unavailable')
        native_version=_native_version(root)
        with closing(_open_private(root)) as db:
            db.execute('BEGIN');meta=_meta(db)
            _check_receipt(root,meta.get('version'))
            if (meta.get('schema')!=SCHEMA or meta.get('native_version')!=native_version
                    or meta.get('builder_revision')!=_builder_revision()
                    or meta.get('correction_generation')!=_correction_generation(root)):
                raise ValueError('utterance_index_stale')
            parameters=[];scope='1=1'
            from math_memory_retrieval import analyze_query
            current=intent.get('current_constraint_text',query)
            excluded=set(excluded_formal_ids)
            rejected_dates=list(excluded_dates)
            for item in analyze_query(current).get('excluded',[]):
                for match in evidence.FORMAL.finditer(item.get('text','')):
                    excluded.add(f'{match.group(1).upper()}-{int(match.group(2)):03d}')
                rejected_dates.extend(evidence._dates(item.get('text','')))
            for field,values in [('concept_key',concept_keys),('formal_id',formal_ids)]:
                values=list(dict.fromkeys(values))
                if values:
                    scope+=' AND b.'+field+' IN ('+','.join('?' for _ in values)+')';parameters.extend(values)
            if excluded:
                scope+=' AND b.formal_id NOT IN ('+','.join('?' for _ in excluded)+')'
                parameters.extend(sorted(excluded))
            scope+=_date_sql(dates,parameters)
            if rejected_dates:
                excluded_date_parameters=[]
                condition=_date_sql(rejected_dates,excluded_date_parameters)
                if condition:
                    scope+=' AND NOT ('+condition.removeprefix(' AND ')+')'
                    parameters.extend(excluded_date_parameters)
            if known_at:
                from math_memory_lifecycle import _moment
                cutoff=_moment(known_at,end=True).astimezone(dt.timezone.utc).isoformat()
                scope+=' AND b.recorded_at IS NOT NULL AND julianday(b.recorded_at)<=julianday(?)';parameters.append(cutoff)
            complete_literals=_complete_literal_targets(query,intent)
            pool=[]
            if complete_literals:
                pool=db.execute('SELECT u.id,u.quote,u.payload FROM utterances u WHERE u.normalized_quote IN ('+
                    ','.join('?' for _ in complete_literals)+') AND EXISTS(SELECT 1 FROM bindings b WHERE b.utterance_id=u.id AND '+scope+') '
                    'ORDER BY u.id LIMIT ?', [*sorted(complete_literals),*parameters,MAX_POOL+1]).fetchall()
            retrieval_mode='exact_normalized_user_quote' if pool else 'fts_candidates_then_evidence_match'
            expression=_fts_expression(query,quote_request or bool(known_at),intent,evidence)
            if not expression:
                return {**result,'status':'available','reason':'no_discriminating_query_terms'}
            if not pool:
                pool=db.execute('SELECT u.id,u.quote,u.payload FROM utterance_fts JOIN utterances u ON u.id=utterance_fts.id '
                    'WHERE utterance_fts MATCH ? AND EXISTS(SELECT 1 FROM bindings b WHERE b.utterance_id=u.id AND '+scope+') '
                    'ORDER BY bm25(utterance_fts),u.id LIMIT ?', [expression,*parameters,MAX_POOL+1]).fetchall()
            truncated=len(pool)>MAX_POOL;supported=[];source_changed=[]
            for uid,quote,payload in pool[:MAX_POOL]:
                public=json.loads(payload)
                if (public.get('utterance_id')!=uid or hashlib.sha256(quote.encode()).hexdigest()!=public.get('quote_sha256')
                        or digest([public.get('origin_id'),public.get('sequence'),public.get('quote_sha256')])!=uid):
                    raise ValueError('utterance_cache_quote_corrupt')
                bindings=[json.loads(v[0]) for v in db.execute('SELECT b.payload FROM bindings b WHERE b.utterance_id=? AND '+scope,[uid,*parameters])]
                match=matcher(query,quote)
                for binding in bindings:
                    chosen={**match,'matched_on':'user_quote'}
                    chosen['normalized_complete_quote_match']=_normalize(quote) in complete_literals
                    annotation=(matcher(query,binding['annotation']) if not known_at and binding.get('annotation')
                                and binding.get('assessment_status') not in {'retracted','conflicted'} else {})
                    chosen['point_annotation_supported']=bool(annotation.get('supported'))
                    if not chosen.get('supported') and not quote_request and not known_at and binding.get('annotation') and binding.get('assessment_status') not in {'retracted','conflicted'}:
                        chosen={**annotation,'matched_on':'formal_observation_annotation_not_user_quote',
                                'point_annotation_supported':bool(annotation.get('supported'))}
                    if not chosen.get('supported'):
                        continue
                    # Action-only fuzzy overlap is insufficient for an unscoped
                    # historical search even if it was useful within one card.
                    if (chosen.get('kind')=='scoped_action' and not concept_keys and not formal_ids
                            and len(set(chosen.get('matched_anchors',[])))<2):
                        continue
                    if (chosen.get('kind')=='literal' and not concept_keys and not formal_ids
                            and not any(len(_normalize(v))>=4 for v in chosen.get('matched_anchors',[]))):
                        continue
                    valid=True
                    checks=list(binding['source_refs'])+(binding.get('correction_source_refs',[]) if not known_at else [])
                    if binding.get('profile_source_ref'):checks.append(binding['profile_source_ref'])
                    for ref in checks:
                        source=_inside(root,ref['path']);expected=meta['dependencies'].get(ref['path'])
                        if not expected:
                            valid=False;break
                        if _stamp(source)!=expected['stamp']:
                            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=ref['sha256']:
                                valid=False;break
                    if not valid:
                        source_changed.append(uid);continue
                    supported.append((public,binding,chosen))
        if _native_version(root)!=native_version:
            raise ValueError('utterance_native_generation_changed')
        complete=[row for row in supported if row[2].get('normalized_complete_quote_match')]
        if complete:
            supported=complete
        def original_statement(row):
            hashes=row.get('source_turn_sha256s',[])
            if len(hashes)==1:
                return digest([row['origin_id'],row['sequence'],hashes[0]])
            # Differing full turns at one purported position are not verified
            # copies, even when their selected quotation happens to be equal.
            return row['utterance_id']
        groups={original_statement(r[0]) for r in supported}
        source_identity_conflict=any(len(row[0].get('source_turn_sha256s',[]))>1 for row in supported)
        version=digest([meta['version'],query,view,list(concept_keys),list(formal_ids),sorted(excluded),dates,rejected_dates,known_at,
                        hashlib.sha256(Path(evidence.__file__).read_bytes()).hexdigest()])
        result.update(status='available',version=version,native_version=native_version,
            retrieval_mode=retrieval_mode,
            indexed_utterance_count=meta['utterance_count'],excluded_source_count=meta['excluded_count'],
            candidate_pool_truncated=truncated,source_changed_count=len(set(source_changed)),
            source_identity_conflict=source_identity_conflict,
            maintenance_required=bool(source_changed),
            current_negation_is_not_historical_quote_negation=True)
        if len(groups)==1 and not truncated and not source_identity_conflict:
            original_count=len(supported)
            annotation_bound=[row for row in supported if row[2].get('point_annotation_supported')]
            # A source message can be cited for more than one mathematical
            # step. Its accepted step annotation can distinguish those honest
            # bindings, but is never relabelled as the user's own utterance.
            if len({row[1]['concept_key'] for row in supported})>1 and annotation_bound:
                supported=annotation_bound
                point_basis='accepted_annotation_supports_requested_action'
            else:
                point_basis='original_user_quote_scope'
            rows=[_safe_result(*row,version,known_at) for row in supported]
            # One original sentence may have multiple honest point bindings.
            keys=sorted({r['concept_key'] for r in rows})
            primary=dict(rows[0])
            if len(keys)>1:
                primary.update(record_id='utterance:'+primary['utterance_id'],concept_key=None,kind='user_utterance',
                               accepted_outcome=None,evidence_role='user_quotation_with_multiple_point_bindings')
            result.update(selection_status='matched',records=[primary],
                matched_utterance_count=1,concept_keys=keys,
                matched_quote_fragment_count=len({row[0]['utterance_id'] for row in supported}),
                statement_grouping_basis='same_verified_origin_sequence_and_full_user_turn_hash',
                point_selection_status='matched' if len(keys)==1 else 'ambiguous',
                point_disambiguation_basis=point_basis,
                original_bindings=rows[:8], original_binding_count=original_count,
                query_binding_count=len(rows),bindings_omitted=max(0,len(rows)-8),
                unselected_bindings_omitted=original_count-len(rows),
                all_original_bindings_retained_in_index=True)
        elif groups:
            result.update(selection_status='ambiguous',reason='multiple_original_utterances_or_incomplete_pool',
                matched_utterance_count=len(groups),records=[])
        else:
            result.update(selection_status='no_match',reason='no_verified_unique_user_evidence')
        return result
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as error:
        return {**result,'reason':str(error)[:160], 'maintenance_required':True}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('action',choices=['refresh'])
    args=parser.parse_args()
    print(json.dumps(refresh(args.repo,_native_version(args.repo)),ensure_ascii=False))
