"""
layout.py — Motor de layout automático.
Calcula posições absolutas (x, y) de todos os nós e subprocessos.
Subprocessos respeitam a mesma estrutura de lanes do fluxo principal.
"""
from collections import defaultdict, deque


DEPT_BAND_HEIGHT = 22   # altura da faixa de departamento sobre as colunas


def _dept_bands(lanes, lane_pos):
    """Agrupa colunas VIZINHAS do mesmo departamento numa faixa só.

    Duas colunas seguidas da mesma área viram uma barra contínua — é o que
    torna a leitura "estes três atores são da Manutenção" imediata, em vez de
    repetir o nome da área sobre cada coluna.
    """
    bands = []
    for lane in lanes:
        area = (lane.get('department') or '').strip()
        lp = lane_pos.get(lane['id'])
        if lp is None:
            continue
        if bands and bands[-1]['department'] == area:
            bands[-1]['width'] = lp['x'] + lp['width'] - bands[-1]['x']
        else:
            bands.append({'department': area, 'x': lp['x'],
                          'width': lp['width']})
    return bands


def _areas_envolvidas(lanes):
    """Áreas presentes nas colunas, sem repetir, na ordem em que aparecem."""
    areas = []
    for lane in lanes:
        area = (lane.get('department') or '').strip()
        if area and area not in areas:
            areas.append(area)
    return areas


def lane_x_positions(lanes, margins, gap):
    """Posição x e largura de cada coluna, na ordem em que elas estão.

    Isolado do resto do layout porque a reordenação de colunas precisa saber
    onde cada uma FICARÁ antes de o layout rodar — é o que permite deslocar
    junto os nós de posição manual, em vez de deixá-los para trás na coluna
    antiga.
    """
    lane_pos = {}
    cx = margins['left']
    for lane in lanes:
        lane_pos[lane['id']] = {'x': cx, 'width': lane['width']}
        cx += lane['width'] + gap
    return lane_pos


def compute_layout(model):
    """Computa posições absolutas para todos os elementos."""
    margins = model['meta']['margins']
    lcfg = model['layout']
    gap = lcfg['swimlanes']['gap']
    label_h = lcfg['swimlanes']['headerHeight']
    v_gap = lcfg['nodes']['vGap']
    lanes = model['lanes']
    nodes = model['nodes']
    edges = model['edges']

    # Faixa de departamento acima do nome do ator. Um fluxo interdepartamental
    # com 15 atores é ilegível sem ela: o cargo sozinho não diz de que área a
    # ação é. A faixa só existe quando alguma coluna declara departamento —
    # arquivos antigos continuam com o cabeçalho de sempre.
    band_h = DEPT_BAND_HEIGHT if any(l.get('department') for l in lanes) else 0
    # `header_h` é a altura TOTAL do cabeçalho: tudo que posiciona nós, mede
    # hit-test ou desenha usa esse número, então a faixa entra nele.
    header_h = band_h + label_h

    # ── 1. Posição X das lanes ──────────────────────────────
    lane_pos = lane_x_positions(lanes, margins, gap)
    lanes_right = (max((lp['x'] + lp['width'] for lp in lane_pos.values()),
                       default=margins['left']))  # borda direita da última lane
    total_lane_width = lanes_right + margins['right']  # largura total com margens

    # ── 2. Classificar nós ──────────────────────────────────
    annotation_ids = {n['id'] for n in nodes if n['type'] == 'annotation'}
    flow_nodes = [n for n in nodes if n['id'] not in annotation_ids]
    ann_nodes = [n for n in nodes if n['id'] in annotation_ids]

    # ── 3. Nivelar nós de fluxo (sem anotações) ─────────────
    flow_edges = [e for e in edges if e['type'] == 'flow']
    levels = _compute_levels(flow_edges, flow_nodes, lcfg)

    # Resolver colisões: dois nós na mesma lane e mesmo nível se sobreporiam —
    # empurrar o posterior para o nível seguinte livre (nós pinned mantêm posição própria).
    # Empurrar um nó também empurra seus sucessores, senão ele pode acabar no mesmo
    # nível do próprio sucessor e a seta seria roteada como retorno.
    base_levels = dict(levels)
    forward = [(e['from'], e['to']) for e in flow_edges
               if base_levels.get(e['to'], 0) > base_levels.get(e['from'], 0)]

    for _ in range(len(flow_nodes) + 1):
        occupied = {}
        moved = False
        for n in sorted(flow_nodes, key=lambda n: levels.get(n['id'], 0)):
            if n.get('pinned'):
                continue
            lvl = levels.get(n['id'], 0)
            while (n['laneId'], lvl) in occupied:
                lvl += 1
            if lvl != levels.get(n['id'], 0):
                levels[n['id']] = lvl
                moved = True
            occupied[(n['laneId'], lvl)] = n['id']

        # Restaurar a ordem topológica quebrada pelos empurrões
        for src_id, tgt_id in forward:
            if levels.get(tgt_id, 0) <= levels.get(src_id, 0):
                levels[tgt_id] = levels[src_id] + 1
                moved = True

        if not moved:
            break

    # ── 4. Posicionar nós de fluxo ──────────────────────────
    max_level = max(levels.values()) if levels else 0

    node_map = {n['id']: n for n in nodes}

    # Altura máxima por nível
    level_heights = {}
    for lvl in range(max_level + 1):
        max_h = 0
        for n in flow_nodes:
            if levels.get(n['id']) == lvl:
                max_h = max(max_h, n['size']['h'])
        level_heights[lvl] = max_h

    # Y de cada nível
    level_y = {}
    cur_y = margins['top'] + header_h + 40
    for lvl in range(max_level + 1):
        if level_heights[lvl] > 0:
            level_y[lvl] = cur_y
            cur_y += level_heights[lvl] + v_gap

    # Atribuir posição a cada nó de fluxo (pinned mantém posição manual)
    for n in flow_nodes:
        if n.get('pinned'):
            continue
        lid = n['laneId']
        if lid not in lane_pos:
            continue
        lp = lane_pos[lid]
        lvl = levels.get(n['id'], 0)
        n['x'] = lp['x'] + (lp['width'] - n['size']['w']) / 2
        n['y'] = level_y.get(lvl, cur_y)

    # ── 5. Coletar anotações como notas laterais ───────────
    notes = []  # lista de {number, text, ref_node_id, ref_node}
    for i, ann in enumerate(ann_nodes):
        ref_node = None
        for e in edges:
            if e['type'] == 'annotation':
                if e['to'] == ann['id'] and e['from'] in node_map:
                    ref_node = node_map[e['from']]
                    break
                if e['from'] == ann['id'] and e['to'] in node_map:
                    ref_node = node_map[e['to']]
                    break
        notes.append({
            'number': i + 1,
            'text': ann['label'],
            'ref_node': ref_node,
            'ann_id': ann['id'],
        })
        # Esconder o nó de anotação do fluxo (posição fora da tela)
        ann['x'] = -9999
        ann['y'] = -9999

    # ── 6. Limites do fluxo principal ──────────────────────
    main_max_y = margins['top'] + header_h
    for n in nodes:
        bottom = n['y'] + n['size']['h']
        if bottom > main_max_y:
            main_max_y = bottom
    main_max_y += v_gap + 20

    # Coluna de comentários lateral (se houver anotações) — adjacente às lanes
    notes_col_width = 300 if notes else 0
    notes_col_x = lanes_right

    # Estender a altura do fluxo se os comentários (alinhados aos nós) descerem além
    if notes:
        est_cy = margins['top'] + header_h + 24
        chars_per_line = max(20, int((notes_col_width - 32) / 4.6))
        for note in notes:
            ref = note.get('ref_node')
            if ref and ref.get('y', 0) > est_cy:
                est_cy = ref['y']
            n_lines = max(1, -(-len(note['text']) // chars_per_line))
            est_cy += n_lines * 13 + 18
        main_max_y = max(main_max_y, est_cy + 20)

    # ── 7. Layout dos subprocessos (dentro das lanes) ──────
    sp_section_y = main_max_y + 30  # Y onde começa a seção de subprocessos

    for sp in model['subprocesses']:
        _layout_subprocess_in_lanes(sp, sp_section_y, lane_pos, v_gap, header_h)
        sp_section_y += sp['height'] + 60

    total_height = sp_section_y + margins['bottom']

    content_right = notes_col_x + notes_col_width if notes else lanes_right

    model['_computed'] = {
        'lane_positions': lane_pos,
        'total_width': max(content_right + margins['right'], 800),
        'total_height': max(total_height, 600),
        'main_max_y': main_max_y,
        'header_height': header_h,
        'dept_band_height': band_h,
        'label_band_height': label_h,
        'dept_bands': _dept_bands(lanes, lane_pos),
        # Áreas envolvidas, na ordem das colunas. É informação DERIVADA das
        # lanes: não mora no documento, para o campo `department` não passar a
        # significar duas coisas conforme quem criou o arquivo.
        'areas_envolvidas': _areas_envolvidas(lanes),
        'sp_section_start': main_max_y + 30 if model['subprocesses'] else main_max_y,
        'notes': notes,
        'notes_col_x': notes_col_x,
        'notes_col_width': notes_col_width,
        'lanes_right': lanes_right,
        'content_right': content_right,
    }
    return model


def _compute_levels(flow_edges, nodes, lcfg):
    """Computa níveis topológicos via caminho mais longo (Kahn's + max level).
    
    Garante que nós com múltiplas entradas fiquem ABAIXO de todos os
    predecessores, evitando back-edges falsos e sobreposição de linhas.
    """
    successors = defaultdict(list)
    predecessors = defaultdict(list)
    for e in flow_edges:
        successors[e['from']].append(e['to'])
        predecessors[e['to']].append(e['from'])

    # Prioridades explícitas
    priorities = {}
    for p in lcfg.get('rules', {}).get('priorities', []):
        priorities[p['nodeId']] = p['level']

    # IDs de nós no fluxo
    flow_ids = set()
    for e in flow_edges:
        flow_ids.add(e['from'])
        flow_ids.add(e['to'])

    # In-degree para cada nó (apenas edges do fluxo, ignorando back-edges)
    in_degree = defaultdict(int)
    for nid in flow_ids:
        in_degree[nid] = 0
    for e in flow_edges:
        in_degree[e['to']] += 1

    # Detectar back-edges via DFS para ignorá-las no cálculo
    back_edges = set()
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in flow_ids}

    def dfs(start):
        stack = [(start, iter(successors[start]), False)]
        color[start] = GRAY
        while stack:
            u, children, _ = stack[-1]
            advanced = False
            for v in children:
                if v not in color:
                    continue
                if color[v] == GRAY:
                    back_edges.add((u, v))
                elif color[v] == WHITE:
                    color[v] = GRAY
                    stack.append((v, iter(successors[v]), False))
                    advanced = True
                    break
            if not advanced:
                color[u] = BLACK
                stack.pop()

    roots = [nid for nid in flow_ids if not predecessors[nid]]
    if not roots and nodes:
        roots = [nodes[0]['id']]

    for r in roots:
        if color.get(r, WHITE) == WHITE:
            dfs(r)

    # Recalcular in-degree sem back-edges
    in_degree_clean = defaultdict(int)
    for nid in flow_ids:
        in_degree_clean[nid] = 0
    for e in flow_edges:
        if (e['from'], e['to']) not in back_edges:
            in_degree_clean[e['to']] += 1

    # Kahn's com longest-path: nível = max(predecessores) + 1
    levels = {}
    for nid, p in priorities.items():
        levels[nid] = p

    queue = deque()
    for nid in flow_ids:
        if in_degree_clean[nid] == 0:
            levels.setdefault(nid, 0)
            queue.append(nid)

    while queue:
        nid = queue.popleft()
        cur = levels.get(nid, 0)
        for s in successors[nid]:
            if (nid, s) in back_edges:
                continue  # ignorar back-edges reais
            new_l = cur + 1
            if s not in levels or levels[s] < new_l:
                levels[s] = new_l
            in_degree_clean[s] -= 1
            if in_degree_clean[s] <= 0:
                queue.append(s)

    for n in nodes:
        levels.setdefault(n['id'], 0)

    return levels


def _layout_subprocess_in_lanes(sp, start_y, lane_pos, v_gap, header_h):
    """Posiciona os nós do subprocesso dentro da lane do nó pai."""
    sp_nodes = sp['nodes']
    sp_edges = sp['edges']
    parent_lane_id = sp.get('parent_lane_id', '')

    lp = lane_pos.get(parent_lane_id)
    if not lp:
        lp = list(lane_pos.values())[0]

    # Guardar posição Y da seção
    sp['section_y'] = start_y
    sp['lanes_y'] = start_y + 40  # depois do título da seção
    sp['header_y'] = sp['lanes_y']
    sp['nodes_start_y'] = sp['lanes_y'] + header_h + 20

    if not sp_nodes:
        sp['height'] = 120
        return

    # Topological sort com ciclos
    sp_succ = defaultdict(list)
    sp_pred = defaultdict(list)
    for e in sp_edges:
        sp_succ[e['from']].append(e['to'])
        sp_pred[e['to']].append(e['from'])

    sp_roots = [n['id'] for n in sp_nodes if not sp_pred[n['id']]]
    if not sp_roots:
        sp_roots = [sp_nodes[0]['id']]

    sp_levels = {}
    for r in sp_roots:
        sp_levels[r] = 0

    sq = deque(sp_roots)
    sv = set()
    while sq:
        nid = sq.popleft()
        if nid in sv:
            continue
        sv.add(nid)
        for s in sp_succ[nid]:
            if s in sv:
                continue
            nl = sp_levels[nid] + 1
            if s not in sp_levels or sp_levels[s] < nl:
                sp_levels[s] = nl
            sq.append(s)

    for n in sp_nodes:
        sp_levels.setdefault(n['id'], 0)

    # Posicionar verticalmente por nível dentro da lane
    max_sp_level = max(sp_levels.values()) if sp_levels else 0
    cur_y = sp['nodes_start_y']

    level_y_map = {}
    for lvl in range(max_sp_level + 1):
        level_nodes = [n for n in sp_nodes if sp_levels[n['id']] == lvl]
        if not level_nodes:
            continue
        max_h = max(n['size']['h'] for n in level_nodes)
        level_y_map[lvl] = cur_y
        cur_y += max_h + v_gap

    for n in sp_nodes:
        lvl = sp_levels[n['id']]
        n['x'] = lp['x'] + (lp['width'] - n['size']['w']) / 2
        n['y'] = level_y_map.get(lvl, sp['nodes_start_y'])

    # Calcular altura total da seção
    all_bottom = max(n['y'] + n['size']['h'] for n in sp_nodes)
    sp['height'] = all_bottom - start_y + 40
    sp['parent_lane_pos'] = lp
