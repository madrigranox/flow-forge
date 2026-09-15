"""
parser.py — Validação e normalização do JSON de fluxograma.

JSON MÍNIMO necessário:
{
  "lanes": [ { "id": "L1", "label": "Nome" } ],
  "nodes": [ { "id": "N1", "laneId": "L1", "type": "task", "label": "Texto" } ],
  "edges": [ { "from": "N1", "to": "N2" } ]
}

Tudo o mais é opcional e tem defaults no programa.
"""
import copy
import json


# ── Defaults por tipo de nó (proporções do padrão Visio) ──
DEFAULT_NODE_SIZES = {
    'start':      {'w': 150, 'h': 56},
    'end':        {'w': 170, 'h': 42},
    'task':       {'w': 170, 'h': 64},
    'decision':   {'w': 190, 'h': 90},
    'subprocess': {'w': 170, 'h': 64},
    'parallel':   {'w': 200, 'h': 12},
    'annotation': {'w': 240, 'h': 70},
}

# Tipo assumido quando o JSON omite `type` em um nó
DEFAULT_NODE_TYPE = 'task'

# Lanes brancas como no padrão Visio (documento limpo)
LANE_COLORS = ['#ffffff']


class ParseError(Exception):
    """Erro de parsing/validação do JSON."""
    pass


# Limites de segurança
MAX_JSON_SIZE = 5 * 1024 * 1024   # 5 MB
MAX_NODES = 500


def _sanitize_json_text(text):
    """Remove caracteres problemáticos de copy-paste (smart quotes, etc.)."""
    # Normalizar quebras de linha
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Aspas curvas → aspas retas (o problema mais comum)
    text = text.replace('\u201c', '"').replace('\u201d', '"')  # " "
    text = text.replace('\u2018', "'").replace('\u2019', "'")  # ' '
    text = text.replace('\u00ab', '"').replace('\u00bb', '"')  # « »
    # Traços especiais → traço simples
    text = text.replace('\u2013', '-').replace('\u2014', '-')  # – —
    # Espaços especiais → espaço normal
    text = text.replace('\u00a0', ' ')   # non-breaking space
    text = text.replace('\u200b', '')    # zero-width space
    text = text.replace('\ufeff', '')    # BOM
    return text


def _extract_json_object(text):
    """Isola o objeto JSON quando a resposta da IA vem embrulhada.

    Respostas de IA costumam vir em bloco ```json ... ``` ou precedidas de
    prosa ("Claro! Aqui está..."). Recorta do primeiro '{' até o '}' que o
    fecha, ignorando chaves dentro de strings.
    """
    start = text.find('{')
    if start < 0:
        return None
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif c == '\\':
                escaped = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def parse_flowchart(json_text):
    """Parse e valida JSON de fluxograma, retorna modelo normalizado."""
    # Limite de tamanho para prevenir DoS
    if len(json_text) > MAX_JSON_SIZE:
        raise ParseError(f"JSON excede limite de {MAX_JSON_SIZE // (1024*1024)}MB")

    # Sanitizar caracteres comuns de copy-paste (smart quotes, etc.)
    json_text = _sanitize_json_text(json_text)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        # Segunda tentativa: colagem direta da resposta de uma IA
        snippet = _extract_json_object(json_text)
        if snippet is None:
            raise ParseError(f"JSON inválido: {e}")
        try:
            data = json.loads(snippet)
        except json.JSONDecodeError:
            raise ParseError(f"JSON inválido: {e}")

    if not isinstance(data, dict):
        raise ParseError("O JSON deve ser um objeto com 'lanes', 'nodes' e 'edges'")

    # Apenas lanes, nodes e edges são obrigatórios
    for field in ('lanes', 'nodes', 'edges'):
        if field not in data:
            raise ParseError(f"Campo obrigatório ausente: '{field}'")

    model = {
        'title': data.get('title', 'Fluxograma'),
        'docCode': data.get('docCode', ''),
        'department': data.get('department', ''),
        '_raw': copy.deepcopy(data),  # JSON original para round-trip fiel na serialização
        'meta': _norm_meta(data.get('meta', {})),
        'lanes': [],
        'nodes': [],
        'edges': [],
        'subprocesses': [],
        'layout': _norm_layout(data.get('layout', {})),
        'styles': _norm_styles(data.get('styles', {})),
        'governance': _norm_governance(data.get('governance', {})),
        # O bloco só volta para o disco se já estava lá ou se algo o alterou:
        # abrir e fechar um arquivo antigo não injeta a chave nova nele.
        '_governance_present': 'governance' in data,
        '_governance_dirty': False,
    }

    # --- Lanes (ordem = posição no array se não especificada) ---
    lane_ids = set()
    for i, ld in enumerate(data['lanes']):
        if 'id' not in ld:
            raise ParseError("Lane sem 'id'")
        if ld['id'] in lane_ids:
            raise ParseError(f"Lane ID duplicado: {ld['id']}")
        lane_ids.add(ld['id'])
        model['lanes'].append(_norm_lane(ld, i))
    model['lanes'].sort(key=lambda l: l['order'])

    # --- Nodes (size é automático pelo tipo se não especificado) ---
    node_ids = set()
    if len(data['nodes']) > MAX_NODES:
        raise ParseError(f"Máximo de {MAX_NODES} nós excedido ({len(data['nodes'])} encontrados)")
    for nd in data['nodes']:
        if 'id' not in nd:
            raise ParseError("Node sem 'id'")
        if nd['id'] in node_ids:
            raise ParseError(f"Node ID duplicado: {nd['id']}")
        lid = nd.get('laneId', '')
        if lid and lid not in lane_ids:
            raise ParseError(f"Node '{nd['id']}' referencia lane inexistente: {lid}")
        node_ids.add(nd['id'])
        model['nodes'].append(_norm_node(nd))

        if nd.get('type') == 'subprocess' and 'group' in nd:
            model['subprocesses'].append(
                _norm_subprocess(nd['group'], nd['id'], nd.get('laneId', ''))
            )

    # --- Edges (type default = "flow") ---
    for ed in data['edges']:
        if ed.get('from') not in node_ids:
            raise ParseError(f"Edge 'from' inexistente: {ed.get('from')}")
        if ed.get('to') not in node_ids:
            raise ParseError(f"Edge 'to' inexistente: {ed.get('to')}")
        model['edges'].append(_norm_edge(ed))

    return model


# ── Normalizadores ────────────────────────────────────────

def _norm_meta(m):
    mg = m.get('margins', {})
    # top=100 reserva espaço para o bloco de título + banner do departamento
    return {
        'orientation': m.get('orientation', 'portrait'),
        'margins': {
            'top': mg.get('top', 100), 'right': mg.get('right', 40),
            'bottom': mg.get('bottom', 40), 'left': mg.get('left', 40),
        },
        'grid': m.get('grid', 10),
    }


def _norm_lane(l, index=0):
    return {
        'id': l['id'],
        'label': l.get('label', l['id']),
        # Um fluxo é interdepartamental: cada coluna é um cargo, e o cargo
        # pertence a uma área. Sem isso, "Analista" não diz de onde.
        'department': l.get('department', ''),
        'order': l.get('order', index),
        'width': l.get('width', 320),
        'style': {'fill': l.get('style', {}).get('fill', LANE_COLORS[index % len(LANE_COLORS)])},
    }


def _norm_node(n):
    ntype = n.get('type', DEFAULT_NODE_TYPE)
    defaults = DEFAULT_NODE_SIZES.get(ntype, {'w': 220, 'h': 80})
    sz = n.get('size', {})
    # x/y explícitos no JSON = posição manual (pinned); o auto-layout preserva
    pinned = 'x' in n and 'y' in n
    return {
        'id': n['id'],
        'laneId': n.get('laneId', ''),
        'type': ntype,
        'label': n.get('label', ''),
        'size': {'w': sz.get('w', defaults['w']), 'h': sz.get('h', defaults['h'])},
        'props': n.get('props', {}),
        'x': n.get('x', 0), 'y': n.get('y', 0),
        'pinned': pinned,
    }


def _norm_edge(e):
    return {
        'from': e['from'],
        'to': e['to'],
        'type': e.get('type', 'flow'),
        'label': e.get('label', ''),
        'style': e.get('style', {}),
        'routing': e.get('routing', 'orthogonal'),
    }


def _norm_subprocess(g, parent_id, parent_lane_id=''):
    nodes = []
    for n in g.get('nodes', []):
        ntype = n.get('type', 'task')
        defaults = DEFAULT_NODE_SIZES.get(ntype, {'w': 200, 'h': 70})
        sz = n.get('size', {})
        nodes.append({
            'id': n['id'],
            'type': ntype,
            'label': n.get('label', ''),
            'size': {'w': sz.get('w', defaults['w']), 'h': sz.get('h', defaults['h'])},
            'props': n.get('props', {}),
            'x': 0, 'y': 0,
        })
    edges = []
    for e in g.get('edges', []):
        edges.append({
            'from': e['from'], 'to': e['to'],
            'type': e.get('type', 'flow'),
            'label': e.get('label', ''),
            'style': e.get('style', {}),
        })
    return {
        'id': g.get('id', f'G_{parent_id}'),
        'label': g.get('label', 'Subprocesso'),
        'parent_node_id': parent_id,
        'parent_lane_id': parent_lane_id,
        'nodes': nodes,
        'edges': edges,
    }


def _norm_layout(lo):
    sw = lo.get('swimlanes', {})
    nd = lo.get('nodes', {})
    return {
        'swimlanes': {
            'gap': sw.get('gap', 0),  # lanes adjacentes (bordas compartilhadas) como no Visio
            'headerHeight': sw.get('headerHeight', 36),
        },
        'nodes': {
            # 64 dá espaço para junções E/Ou + rótulos Sim/Não sem apertar
            'vGap': nd.get('vGap', 64),
            'minLanePadding': nd.get('minLanePadding', 20),
        },
        'edges': {
            'minDistance': lo.get('edges', {}).get('minDistance', 12),
        },
        'rules': lo.get('rules', {}),
    }


def _norm_styles(s):
    # Estilos do padrão Visio: formas brancas, bordas finas escuras
    nt = {
        'start':      {'shape': 'ellipse',   'stroke': '#3f3f3f', 'fill': '#ffffff'},
        'end':        {'shape': 'stadium',   'stroke': '#000000', 'fill': '#000000'},
        'task':       {'shape': 'rect',      'stroke': '#3f3f3f', 'fill': '#ffffff'},
        'decision':   {'shape': 'hexagon',   'stroke': '#3f3f3f', 'fill': '#ffffff'},
        'subprocess': {'shape': 'rect-dash', 'stroke': '#e60000', 'fill': '#ffffff'},
        'parallel':   {'shape': 'bar',       'stroke': '#374151', 'fill': '#374151'},
        'annotation': {'shape': 'note',      'stroke': '#7f7f7f', 'fill': '#ffffff'},
    }
    et = {
        'flow':       {'stroke': '#595959', 'arrow': 'standard'},
        'annotation': {'stroke': '#7f7f7f', 'dash': True, 'arrow': 'none'},
    }
    for k, v in s.get('nodeTypes', {}).items():
        if k in nt:
            nt[k].update(v)
        else:
            nt[k] = v
    for k, v in s.get('edgeTypes', {}).items():
        if k in et:
            et[k].update(v)
        else:
            et[k] = v
    return {'nodeTypes': nt, 'edgeTypes': et}


# ── Governança: ciclo de vida, trilha e impressão digital ─
#
# `governance` é uma chave de topo NOVA e OPCIONAL. Abrir um arquivo que não a
# tem preenche o bloco default só em memória: abrir e fechar sem salvar não
# injeta nada em disco. O binário 1.2.0 já distribuído não conhece a chave,
# mas como o `serialize_model` dele parte de uma cópia do JSON original e só
# reescreve title/docCode/department/lanes/nodes/edges, o bloco atravessa
# intacto qualquer salvamento feito pela versão antiga.
#
# Quem decide QUANDO o status muda ou um evento é gravado é o orquestrador
# (ui/app_window.py). Aqui mora só o formato do dado e as garantias dele.

GOVERNANCE_SCHEMA_VERSION = 1
GOVERNANCE_STATUS = ('draft', 'published')


def _utc_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def current_author():
    """Autoria autodeclarada. Não há login: é identificação, não autenticação."""
    import getpass
    try:
        user = getpass.getuser()
    except Exception:
        user = ''
    return {'name': '', 'machineUser': user}


def default_governance():
    """Bloco `governance` recém-nascido, usado para arquivo sem a chave."""
    agora = _utc_now()
    return {
        'schemaVersion': GOVERNANCE_SCHEMA_VERSION,
        'status': 'draft',
        'canonical': False,
        'author': current_author(),
        'createdAt': agora,
        'updatedAt': agora,
        'approval': None,
        'auditTrail': [],
    }


def _norm_governance(g):
    """Completa o bloco com os defaults PRESERVANDO campos desconhecidos.

    Mesma regra que já vale para `meta`/`layout`/`styles`: o que a rodada não
    conhece atravessa o round-trip sem ser descartado.
    """
    out = copy.deepcopy(g) if isinstance(g, dict) else {}
    for chave, valor in default_governance().items():
        out.setdefault(chave, valor)
    if out.get('status') not in GOVERNANCE_STATUS:
        out['status'] = 'draft'
    if not isinstance(out.get('auditTrail'), list):
        out['auditTrail'] = []
    if not isinstance(out.get('author'), dict):
        out['author'] = current_author()
    if out.get('approval') is not None and not isinstance(out['approval'], dict):
        out['approval'] = None
    return out


def append_event(trail, kind, by=None, at=None, detalhe=None):
    """Devolve uma NOVA trilha com o evento ao final. Nunca encurta a lista.

    `seq` é estritamente crescente e nunca reaproveitado. Não existe caminho
    neste módulo que reordene, edite ou remova um item já gravado.
    """
    trail = list(trail or [])
    ultimo = 0
    for item in trail:
        try:
            ultimo = max(ultimo, int(item.get('seq', 0)))
        except (TypeError, ValueError):
            continue
    evento = {
        'seq': ultimo + 1,
        'type': kind,
        'at': at or _utc_now(),
        'by': by or current_author(),
    }
    if detalhe:
        # Ressalvas aceitas na publicação ficam registradas: aprovar apesar de
        # um desvio é uma decisão, e decisão sem rastro não vale nada.
        evento['detalhe'] = list(detalhe) if isinstance(detalhe, (list, tuple)) \
            else str(detalhe)
    trail.append(evento)
    return trail


def record_event(model, kind, by=None, detalhe=None):
    """Acrescenta um evento à trilha do modelo e marca o bloco para gravação.

    Falhar ao registrar auditoria nunca pode derrubar a operação que a
    originou — quem chama trata o retorno, não uma exceção.
    """
    try:
        gov = model.setdefault('governance', default_governance())
        gov['auditTrail'] = append_event(gov.get('auditTrail'), kind, by,
                                         detalhe=detalhe)
        gov['updatedAt'] = _utc_now()
        model['_governance_dirty'] = True
        return gov['auditTrail'][-1]
    except Exception:
        return None


def mark_governance_dirty(model):
    """Sinaliza que o bloco mudou e portanto deve ser gravado no próximo save."""
    model['_governance_dirty'] = True


# ── Impressão digital do conteúdo ESTRUTURAL ──────────────

def structural_view(model):
    """Visão canônica do que é conteúdo, sem nada de apresentação.

    Ficam de fora posição (`x`/`y`/`pinned`), `size`, `style`, `routing` e os
    blocos `meta`/`layout`/`styles` — mexer neles não é mudar o processo. O
    próprio `governance` também fica de fora, para não haver circularidade.
    """
    def no(n):
        return {'id': n['id'], 'laneId': n.get('laneId', ''),
                'type': n.get('type', DEFAULT_NODE_TYPE),
                'label': n.get('label', ''), 'props': n.get('props', {})}

    def ed(e):
        return {'from': e['from'], 'to': e['to'],
                'type': e.get('type', 'flow'), 'label': e.get('label', '')}

    def ordem_edge(e):
        return (e['from'], e['to'], e['type'], e['label'])

    subs = []
    for sp in model.get('subprocesses', []):
        subs.append({
            'id': sp.get('id', ''),
            'label': sp.get('label', ''),
            'parent_node_id': sp.get('parent_node_id', ''),
            'nodes': sorted([no(n) for n in sp.get('nodes', [])],
                            key=lambda n: n['id']),
            'edges': sorted([ed(e) for e in sp.get('edges', [])], key=ordem_edge),
        })

    return {
        'title': model.get('title', ''),
        'docCode': model.get('docCode', ''),
        'department': model.get('department', ''),
        'lanes': sorted([{'id': l['id'], 'label': l.get('label', ''),
                          'department': l.get('department', ''),
                          'order': l.get('order', 0)}
                         for l in model.get('lanes', [])], key=lambda l: l['id']),
        'nodes': sorted([no(n) for n in model.get('nodes', [])],
                        key=lambda n: n['id']),
        'edges': sorted([ed(e) for e in model.get('edges', [])], key=ordem_edge),
        'subprocesses': sorted(subs, key=lambda s: s['id']),
    }


def structural_fingerprint(model):
    """sha256 determinístico do conteúdo estrutural (biblioteca padrão)."""
    import hashlib
    canon = json.dumps(structural_view(model), sort_keys=True,
                       separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canon.encode('utf-8')).hexdigest()


def build_approval(model, by=None):
    """Monta o bloco `approval` amarrado ao conteúdo estrutural atual."""
    return {
        'approvedBy': by or current_author(),
        'approvedAt': _utc_now(),
        'fingerprint': {'algorithm': 'sha256', 'scope': 'structural-v1',
                        'value': structural_fingerprint(model)},
    }


def fingerprint_matches(model):
    """A aprovação gravada ainda corresponde ao conteúdo?

    Retorna `True`/`False`, ou `None` quando não há aprovação para conferir —
    "nunca teve governança" não pode ser confundido com "teve e foi violada".
    É operação pura: não escreve nada, não decide nada. O que fazer com a
    divergência é do orquestrador.
    """
    gov = model.get('governance') or {}
    approval = gov.get('approval')
    if not isinstance(approval, dict):
        return None
    gravado = (approval.get('fingerprint') or {}).get('value')
    if not gravado:
        return None
    return structural_fingerprint(model) == gravado


# ── Validação de consistência (avisos, não bloqueiam) ─────

# Defeito de ESTRUTURA barra a publicação: o processo desenhado está errado.
# Desvio de NOMENCLATURA ou lacuna declarada apenas avisa — o processo está
# certo, o nome é que foge do padrão. Tratar os dois com o mesmo peso deixava
# quem aprova num beco sem saída: não pode corrigir (não é o autor) nem
# aprovar (o gate barra), e o documento voltava por causa de uma palavra.
SEVERIDADE = {
    'label_vazio': 'bloqueio',
    'sem_destino': 'bloqueio',
    'sem_origem': 'bloqueio',
    'duplicada': 'bloqueio',
    'decisao_sem_rotulo': 'bloqueio',
    'departamento_fora_do_catalogo': 'aviso',
    'cargo_fora_do_catalogo': 'aviso',
    'raia_unica': 'aviso',
    'lanes_sem_area': 'aviso',
    'ponto_em_aberto': 'aviso',
}


def severidade(issue):
    """'bloqueio' ou 'aviso'. Desconhecido é tratado como bloqueio."""
    if not isinstance(issue, dict):
        return 'bloqueio'
    return issue.get('severidade') or SEVERIDADE.get(issue.get('kind'), 'bloqueio')


def bloqueios(issues):
    """Só o que impede publicar."""
    return [i for i in issues if severidade(i) == 'bloqueio']


def avisos(issues):
    """O que merece ser dito, mas não impede publicar."""
    return [i for i in issues if severidade(i) == 'aviso']


def validate_model(model, catalogo=None):
    """Avisos de consistência do fluxo, já apontando O ELEMENTO afetado.

    `catalogo` (opcional) é o catálogo corporativo de departamentos e cargos:
    quando informado, nomes fora da lista viram aviso de padronização. O
    parser não lê esse arquivo por conta própria — quem orquestra é que sabe
    onde ele mora, e sem ele a validação continua sendo função pura.

    Antes a validação só rodava ao renderizar e devolvia frases soltas: o
    usuário editava cinco nós achando que estava tudo certo, salvava e só
    descobria o erro ao carregar de novo. Cada aviso agora carrega o `node_id`
    ou a conexão de origem, para o erro ser mostrado onde ele foi cometido, no
    momento em que é cometido.

    Retorna lista de dicts:
      {'kind': str, 'msg': str, 'node_id': str|None, 'edge': dict|None}
    """
    nodes = {n['id']: n for n in model['nodes']}
    flow = [e for e in model['edges'] if e.get('type', 'flow') == 'flow']
    has_out = {e['from'] for e in flow}
    has_in = {e['to'] for e in flow}
    issues = []

    def nome(n):
        return n['label'] or n['id']

    for n in model['nodes']:
        if n['type'] == 'annotation':
            continue

        # Rótulo vazio: a barra de paralelismo é a única forma muda no padrão
        if n['type'] != 'parallel' and not (n.get('label') or '').strip():
            issues.append({'kind': 'label_vazio', 'node_id': n['id'], 'edge': None,
                           'msg': f"nó '{n['id']}' está sem texto"})

        if n['type'] != 'end' and n['id'] not in has_out:
            issues.append({'kind': 'sem_destino', 'node_id': n['id'], 'edge': None,
                           'msg': f"atividade sem destino: '{nome(n)}'"})

        if n['type'] != 'start' and n['id'] not in has_in:
            issues.append({'kind': 'sem_origem', 'node_id': n['id'], 'edge': None,
                           'msg': f"nó sem entrada: '{nome(n)}'"})

    # Conexões duplicadas — silenciosas até aqui
    vistas = {}
    for e in flow:
        chave = (e['from'], e['to'])
        vistas[chave] = vistas.get(chave, 0) + 1
        if vistas[chave] == 2:
            origem = nodes.get(e['from'])
            destino = nodes.get(e['to'])
            issues.append({
                'kind': 'duplicada', 'node_id': e['from'], 'edge': e,
                'msg': f"conexão duplicada: '{nome(origem) if origem else e['from']}'"
                       f" → '{nome(destino) if destino else e['to']}'"})

    # Padronização: departamento e cargos (labels de lane) fora do catálogo
    if catalogo:
        from core.catalogo import fora_do_catalogo, sugerir

        def _aviso_catalogo(valor, chave, kind, onde, lane_id=None, area=None):
            if not fora_do_catalogo(valor, chave, catalogo, departamento=area):
                return
            perto = sugerir(valor, chave, catalogo, limite=1, departamento=area)
            dica = f" — talvez '{perto[0]}'" if perto else ''
            issues.append({'kind': kind, 'node_id': None, 'edge': None,
                           'lane_id': lane_id,
                           'msg': f"{onde} fora do catálogo: '{valor}'{dica}"})

        # O `department` do documento só é um nome de área quando as colunas
        # não declaram a sua. Em fluxo interdepartamental ele é uma legenda
        # derivada ("Operações · Manutenção · SMS") — cobrá-la do catálogo
        # reprovaria todo fluxo com mais de uma área, para sempre.
        if not any(l.get('department') for l in model.get('lanes', [])):
            _aviso_catalogo(model.get('department', ''), 'departamentos',
                            'departamento_fora_do_catalogo', 'departamento')
        for lane in model.get('lanes', []):
            area = lane.get('department', '')
            if area:
                _aviso_catalogo(area, 'departamentos',
                                'departamento_fora_do_catalogo',
                                f"área da coluna '{lane['id']}'", lane['id'])
            # Com a área conhecida, a checagem do cargo é feita DENTRO dela:
            # é o que pega o ator que existe, mas na coluna da área errada.
            _aviso_catalogo(lane.get('label', ''), 'cargos',
                            'cargo_fora_do_catalogo',
                            f"cargo da coluna '{lane['id']}'", lane['id'],
                            area=area)

    # Decisão com várias saídas exige rótulo em cada uma (Sim/Não no padrão)
    por_origem = {}
    for e in flow:
        por_origem.setdefault(e['from'], []).append(e)
    for nid, saidas in por_origem.items():
        n = nodes.get(nid)
        if not n or n['type'] != 'decision' or len(saidas) < 2:
            continue
        if any(not (e.get('label') or '').strip() for e in saidas):
            issues.append({'kind': 'decisao_sem_rotulo', 'node_id': nid, 'edge': None,
                           'msg': f"decisão sem rótulo nas saídas: '{nome(n)}'"})

    # Um swimlane existe para mostrar QUEM faz o quê. Com uma raia só — ou com
    # raias sem área — ele não responde a isso, e o programa deixava passar sem
    # dizer nada. É o erro de modelagem mais básico do formato.
    lanes = model.get('lanes', [])
    if len(lanes) == 1:
        issues.append({
            'kind': 'raia_unica', 'node_id': None, 'edge': None,
            'msg': f"fluxo com uma única raia ('{lanes[0].get('label') or lanes[0]['id']}') "
                   f"— um swimlane existe para mostrar quem faz o quê"})
    elif lanes and not any(l.get('department') for l in lanes):
        issues.append({
            'kind': 'lanes_sem_area', 'node_id': None, 'edge': None,
            'msg': f'nenhuma das {len(lanes)} colunas tem área definida'})

    # Pontos deliberadamente deixados em aberto pelo autor
    for n in model.get('nodes', []):
        aberto = (n.get('props') or {}).get('em_aberto')
        if not aberto:
            continue
        pergunta = (n.get('props') or {}).get('pergunta') or ''
        detalhe = f': {pergunta}' if pergunta else ''
        issues.append({
            'kind': 'ponto_em_aberto', 'node_id': n['id'], 'edge': None,
            'msg': f"ponto em aberto em '{n.get('label') or n['id']}'{detalhe}"})

    for i in issues:
        i.setdefault('severidade', SEVERIDADE.get(i['kind'], 'bloqueio'))
    return issues


def issue_messages(issues):
    """Só as frases dos avisos — para status bar e logs."""
    return [i['msg'] if isinstance(i, dict) else str(i) for i in issues]


def issue_node_ids(issues):
    """Ids dos nós com pendência, para o realce visual no canvas."""
    return {i['node_id'] for i in issues
            if isinstance(i, dict) and i.get('node_id')}


# ── Serialização (modelo → JSON limpo) ────────────────────

def _sync_group(group, subprocesses, parent_id):
    """Devolve ao `group` do nó pai o que foi editado no subprocesso."""
    sp = next((g for g in subprocesses
               if g.get('parent_node_id') == parent_id), None)
    if sp is None:
        return
    if sp.get('label'):
        group['label'] = sp['label']
    editados = {n['id']: n for n in sp.get('nodes', [])}
    for gn in group.get('nodes', []):
        atual = editados.get(gn.get('id'))
        if atual is None:
            continue
        gn['label'] = atual.get('label', gn.get('label', ''))
        if 'type' in gn or atual.get('type') != DEFAULT_NODE_TYPE:
            gn['type'] = atual.get('type', DEFAULT_NODE_TYPE)


def serialize_model(model):
    """Serializa o modelo de volta para o JSON do usuário (round-trip fiel).

    Parte do JSON original (_raw) e sincroniza o que o editor pode alterar:
    labels, laneId, posições manuais (x/y de nós pinned), props, criação e
    exclusão de nós e conexões. Campos extras do usuário (meta, layout,
    styles, group...) são preservados.
    """
    raw = copy.deepcopy(model.get('_raw') or {})
    raw['title'] = model['title']
    if model.get('docCode'):
        raw['docCode'] = model['docCode']
    if model.get('department'):
        raw['department'] = model['department']

    # Lanes: sincronizar labels, preservando campos extras
    raw_lanes = {l.get('id'): l for l in raw.get('lanes', [])}
    raw['lanes'] = []
    for lane in model['lanes']:
        rl = raw_lanes.get(lane['id'], {'id': lane['id']})
        rl['label'] = lane['label']
        if lane.get('department'):
            rl['department'] = lane['department']
        else:
            rl.pop('department', None)
        # A ordem das colunas já viaja na ordem deste array (o parser usa o
        # índice como default). Só regravamos `order` quando o arquivo original
        # o declarava — senão um `order` antigo sobreviveria à reordenação e
        # desfaria, na próxima abertura, o que o usuário acabou de fazer.
        if 'order' in rl:
            rl['order'] = lane.get('order', 0)
        raw['lanes'].append(rl)

    # Nodes: sincronizar label/laneId/posição manual/props (inclui criar/excluir)
    raw_nodes = {n.get('id'): n for n in raw.get('nodes', [])}
    raw['nodes'] = []
    for node in model['nodes']:
        rn = raw_nodes.get(node['id'], {'id': node['id'], 'type': node['type'],
                                        'laneId': node['laneId']})
        # `type` de nó JÁ EXISTENTE nunca era regravado: só nós novos ganhavam
        # a chave. Enquanto nenhuma porta de edição trocava o tipo isso não
        # aparecia; com o painel de propriedades a troca ia sumir ao reabrir.
        # A chave só é injetada em arquivo que a omitia quando o tipo deixa de
        # ser o default implícito do parser — abrir e salvar sem editar
        # continua produzindo os mesmos bytes.
        if 'type' in rn or node['type'] != DEFAULT_NODE_TYPE:
            rn['type'] = node['type']
        rn['label'] = node['label']
        rn['laneId'] = node['laneId']
        if node.get('pinned'):
            rn['x'] = round(node['x'])
            rn['y'] = round(node['y'])
        else:
            rn.pop('x', None)
            rn.pop('y', None)
        if node.get('props'):
            rn['props'] = node['props']
        else:
            rn.pop('props', None)
        # Conteúdo da Instrução de Trabalho: `model['subprocesses']` é uma
        # cópia normalizada e vivia desligada do `group` do nó pai — editar uma
        # etapa lá dentro aparecia na tela e sumia ao salvar.
        if isinstance(rn.get('group'), dict):
            _sync_group(rn['group'], model.get('subprocesses', []), node['id'])
        raw['nodes'].append(rn)

    # Edges: sincronizar com o modelo (o editor pode criar/excluir conexões),
    # preservando campos extras das edges originais (style, routing...)
    pending = {}
    for re_ in raw.get('edges', []):
        pending.setdefault((re_.get('from'), re_.get('to')), []).append(re_)
    raw['edges'] = []
    for e in model['edges']:
        matches = pending.get((e['from'], e['to']))
        re_ = matches.pop(0) if matches else {'from': e['from'], 'to': e['to']}
        if e['type'] != 'flow':
            re_['type'] = e['type']
        if e.get('label'):
            re_['label'] = e['label']
        else:
            re_.pop('label', None)
        raw['edges'].append(re_)

    # Governança: escrita CONDICIONAL. Sem isso, um evento acrescentado em
    # memória ficaria congelado no valor lido na abertura e o "só-acréscimo"
    # da trilha se perderia; com escrita incondicional, abrir e salvar um
    # arquivo antigo passaria a injetar a chave nele.
    if model.get('_governance_present') or model.get('_governance_dirty'):
        gov = copy.deepcopy(model.get('governance') or default_governance())
        gov.pop('_dirty', None)
        raw['governance'] = gov
    return raw
