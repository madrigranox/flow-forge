"""
edges.py — Planejamento e desenho de conexões/setas.

Regra Visio: toda saída é pelo FUNDO do nó e toda entrada pelo TOPO.
Divisões (2+ saídas para baixo) e junções (2+ entradas vindas de cima) usam
conector em T com rótulo "Ou" (decisão) ou "E" (paralelismo), como no padrão.
Retornos (back-edges) contornam pela lateral e entram por cima.

plan_edges() gera primitivas de desenho consumidas tanto pelo Canvas
(draw_edges) quanto pelo PDF (export/pdf_export.py) — roteamento único.
"""
import math

JUNC_DROP = 30      # distância máxima do fundo do nó até a barra do conector E/Ou
BACK_DOWN = 18      # descida inicial de um retorno abaixo do nó de origem
BACK_APPROACH = 26  # altura máxima acima do alvo para a aproximação do retorno
SIDE_GAP = 40       # afastamento lateral mínimo das rotas de retorno
SIDE_STEP = 14      # espaçamento entre rotas de retorno paralelas
CLEARANCE = 16      # folga mínima entre uma rota e qualquer nó
LANE_KEEPOUT = 10   # distância mínima entre um canal e a borda de uma lane
BAND_STEP = 13      # espaçamento entre faixas horizontais de rotas paralelas
BAND_TRIES = 14     # faixas testadas antes de cair no canal lateral
EDGE_MARGIN = 12    # recuo mínimo da faixa em relação ao fundo/topo dos nós

# ── Rótulos como recurso disputado ────────────────────────
LABEL_CHAR_W = 4.3  # largura média de caractere em Arial 7 (rótulo de edge)
LABEL_PAD_X = 5     # respiro lateral da caixinha branca do rótulo
LABEL_H = 12        # altura da caixinha do rótulo
LABEL_GAP = 3       # folga mínima entre dois rótulos
LABEL_SLIDE = 13    # passo do deslizamento do rótulo ao longo da rota
LABEL_TRIES = 7     # deslocamentos testados por eixo

# ── Rótulos de decisão (Sim/Não) ──────────────────────────
# Prática consolidada de fluxograma: o rótulo fica SOBRE A LINHA DE SAÍDA e
# PERTO do losango — nunca dentro dele, nunca solto no meio do desenho. Quem
# olha a decisão precisa ler as duas respostas sem procurar.
LABEL_DEC_DIST = 26    # quanto andar pela rota, a partir da decisão
LABEL_DEC_GAP = 7      # afastamento lateral da linha
LABEL_DEC_PASSOS = (26, 40, 16, 56, 72)   # distâncias tentadas, em ordem


def lane_boundaries(model):
    """Coordenadas x das bordas das lanes — canais de rota devem evitá-las."""
    lane_pos = model.get('_computed', {}).get('lane_positions', {})
    xs = set()
    for lp in lane_pos.values():
        xs.add(lp['x'])
        xs.add(lp['x'] + lp['width'])
    return sorted(xs)


def _bottom(n):
    return (n['x'] + n['size']['w'] / 2, n['y'] + n['size']['h'])


def _top(n):
    return (n['x'] + n['size']['w'] / 2, n['y'])


def dist_point_seg(px, py, x1, y1, x2, y2):
    """Distância de um ponto a um segmento (usado no hit-test de edges)."""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _line_prim(points, edge=None, etype='flow', arrow=False, label=None,
               label_pos=None, label_seg=None, label_decisao=0):
    return {
        'kind': 'line', 'points': points, 'arrow': arrow,
        'edge': edge, 'etype': etype,
        'style': (edge or {}).get('style', {}),
        'label': label, 'label_pos': label_pos, 'label_seg': label_seg,
        # -1 / +1 = ramo de decisão, e de que lado da linha o rótulo fica
        'label_decisao': label_decisao,
    }


def _longest_seg(pts):
    """Segmento mais longo da polilinha: ((mx, my), (x1, y1, x2, y2))."""
    best, best_seg, best_len = None, None, -1
    for i in range(0, len(pts) - 2, 2):
        seg = abs(pts[i + 2] - pts[i]) + abs(pts[i + 3] - pts[i + 1])
        if seg > best_len:
            best_len = seg
            best = ((pts[i] + pts[i + 2]) / 2, (pts[i + 1] + pts[i + 3]) / 2)
            best_seg = (pts[i], pts[i + 1], pts[i + 2], pts[i + 3])
    return best, best_seg


def _longest_seg_mid(pts):
    """Ponto médio do segmento mais longo da polilinha (posição do rótulo)."""
    return _longest_seg(pts)[0]


def _detour_vertical(pts, node_map, exclude_ids, routed=None, owner=None):
    """Desvia segmentos verticais retos que atravessariam outros nós.

    O desvio saía sempre pela ESQUERDA do obstáculo. Quando o caminho livre
    estava do outro lado, a perna desviada atravessava as barras de conector
    vizinhas — um dos cruzamentos que sobravam. Agora os dois lados são
    avaliados e vence o que cruza menos rota já planejada (empate: a esquerda,
    como antes, para não mexer no desenho de quem já estava correto).
    """
    if len(pts) != 4:
        return pts
    x1, y1, x2, y2 = pts
    if abs(x1 - x2) > 2 or y2 <= y1:
        return pts

    blockers = []
    for n in node_map.values():
        if n['id'] in exclude_ids:
            continue
        nx, ny = n.get('x', 0), n.get('y', 0)
        nw, nh = n['size']['w'], n['size']['h']
        if nx <= x1 <= nx + nw and ny < y2 and ny + nh > y1:
            blockers.append(n)

    if not blockers:
        return pts

    livres = _blockers(node_map, exclude_ids)
    opcoes = [min(n['x'] for n in blockers) - 25,
              max(n['x'] + n['size']['w'] for n in blockers) + 25]

    melhor, melhor_custo = None, None
    for i, dx in enumerate(opcoes):
        rota = [x1, y1, x1, y1 + 14, dx, y1 + 14, dx, y2 - 14, x2, y2 - 14, x2, y2]
        if not _vseg_free(livres, dx, y1 + 14, y2 - 14):
            custo = 10000            # o desvio esbarraria em outro nó
        else:
            custo = 0
        if routed is not None:
            custo += routed.crossings(owner, rota) * 100
        custo += i                   # desempate: mantém a esquerda histórica
        if melhor_custo is None or custo < melhor_custo:
            melhor, melhor_custo = rota, custo
    return melhor


def _clear_channel_x(node_map, x, y0, y1, direction, clearance=CLEARANCE,
                     lane_x=()):
    """Ajusta x até obter um canal vertical livre (sem cruzar nós) entre y0 e y1.

    Desloca o canal na direção indicada ('left'/'right') sempre que algum nó
    (inflado pela folga) intercepta o segmento vertical em x. Também afasta o
    canal das bordas de lane, para a rota não se confundir com a divisória.
    """
    step = -1 if direction == 'left' else 1
    for _ in range(24):
        blocker = None
        for n in node_map.values():
            if n.get('type') == 'annotation':
                continue
            nx, ny = n.get('x', 0), n.get('y', 0)
            nw, nh = n['size']['w'], n['size']['h']
            if (nx - clearance) <= x <= (nx + nw + clearance) and \
                    ny - clearance < y1 and ny + nh + clearance > y0:
                blocker = n
                break
        if not blocker:
            break
        if direction == 'left':
            x = blocker['x'] - clearance - 1
        else:
            x = blocker['x'] + blocker['size']['w'] + clearance + 1

    # Afastar da borda de lane mais próxima (sem reentrar em um nó)
    for bx in lane_x:
        if abs(x - bx) < LANE_KEEPOUT:
            x = bx + step * LANE_KEEPOUT
            break
    return x


def _space_above(node_map, tgt, tcx):
    """Espaço vertical livre acima do alvo, na faixa horizontal que ele ocupa.

    Usado para a rota de retorno se aproximar mais perto do alvo do que o
    ponto médio usado pelas conexões normais — assim as duas não se colam.
    """
    tty = tgt['y']
    ceiling = None
    for n in node_map.values():
        if n['id'] == tgt['id'] or n.get('type') == 'annotation':
            continue
        nx, nw = n.get('x', 0), n['size']['w']
        if nx - 30 <= tcx <= nx + nw + 30:
            bottom = n.get('y', 0) + n['size']['h']
            if bottom <= tty:
                ceiling = bottom if ceiling is None else max(ceiling, bottom)
    return tty - ceiling if ceiling is not None else BACK_APPROACH * 2


def _blockers(node_map, exclude_ids):
    """Nós que uma rota deve evitar (anotações vivem na coluna lateral)."""
    return [n for n in node_map.values()
            if n['id'] not in exclude_ids and n.get('type') != 'annotation']


def _hseg_free(blockers, y, x0, x1, clearance=CLEARANCE):
    """O trecho horizontal em `y`, de x0 a x1, passa longe de todos os nós?"""
    lo, hi = min(x0, x1), max(x0, x1)
    for n in blockers:
        nx, ny = n.get('x', 0), n.get('y', 0)
        nw, nh = n['size']['w'], n['size']['h']
        if (ny - clearance) <= y <= (ny + nh + clearance) and \
                nx - clearance < hi and nx + nw + clearance > lo:
            return False
    return True


def _vseg_free(blockers, x, y0, y1, clearance=CLEARANCE):
    """O trecho vertical em `x`, de y0 a y1, passa longe de todos os nós?"""
    lo, hi = min(y0, y1), max(y0, y1)
    for n in blockers:
        nx, ny = n.get('x', 0), n.get('y', 0)
        nw, nh = n['size']['w'], n['size']['h']
        if (nx - clearance) <= x <= (nx + nw + clearance) and \
                ny - clearance < hi and ny + nh + clearance > lo:
            return False
    return True


def _band_taken(bands, y, x0, x1):
    """Já existe outra rota ocupando esta faixa na mesma faixa horizontal?"""
    lo, hi = min(x0, x1), max(x0, x1)
    for by, bx0, bx1 in bands:
        if abs(by - y) < BAND_STEP and bx0 < hi and bx1 > lo:
            return True
    return False


def segments(pts):
    """Quebra uma polilinha achatada em segmentos (x1, y1, x2, y2)."""
    return [(pts[i], pts[i + 1], pts[i + 2], pts[i + 3])
            for i in range(0, len(pts) - 2, 2)]


def _crosses(a, b):
    """Dois trechos ortogonais se cruzam em X (não apenas se tocam)?"""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    a_vert, b_vert = abs(ax1 - ax2) < 1, abs(bx1 - bx2) < 1
    if a_vert == b_vert:
        return False
    if b_vert:                       # normaliza: `a` vertical, `b` horizontal
        (ax1, ay1, ax2, ay2), (bx1, by1, bx2, by2) = b, a
        a_vert = True
    return (min(ay1, ay2) + 1 < by1 < max(ay1, ay2) - 1 and
            min(bx1, bx2) + 1 < ax1 < max(bx1, bx2) - 1)


class Routed:
    """Registro dos trechos já planejados, marcados pelo dono.

    Uma rota não pode "cruzar a si mesma": cada trecho guarda a conexão (ou o
    conector E/Ou) que o desenhou, e a contagem de cruzamentos ignora os do
    próprio dono. É isso que permite replanejar em uma segunda passada já
    conhecendo o desenho inteiro, sem a rota fugir da própria posição anterior.
    """

    def __init__(self, segs=None):
        self.segs = list(segs or [])

    def add(self, owner, pts):
        for s in segments(pts):
            self.segs.append((owner, s))

    def crossings(self, owner, pts):
        """Quantos trechos de outros donos esta polilinha cruzaria."""
        return sum(1 for c in segments(pts) for o, r in self.segs
                   if o != owner and _crosses(c, r))

    def snapshot(self):
        return list(self.segs)


def _edge_owner(e):
    return f"e:{e['from']}>{e['to']}"


def _route_forward(owner, src, tgt, node_map, lane_x, bands, routed):
    """Rota do caminho COMUM (origem acima do alvo), com canal livre e faixas.

    O caminho comum era o único sem verificação de colisão: descia do fundo da
    origem até a metade do vão, atravessava e entrava no topo do alvo — sem
    checar quem estava no meio e sem se afastar de outra rota na mesma altura.
    Era daí que vinham os cruzamentos. Aqui ele recebe o mesmo cuidado que as
    rotas de retorno já tinham: a faixa horizontal é procurada até estar livre
    de nós e de outras rotas, e os dois trechos verticais são validados.
    """
    scx, sby = _bottom(src)
    tcx, tty = _top(tgt)
    exclude = (src['id'], tgt['id'])
    blockers = _blockers(node_map, exclude)

    # Mesma coluna: descida reta, desviando de quem estiver no caminho.
    if abs(scx - tcx) < 2:
        pts = _detour_vertical([scx, sby, tcx, tty], node_map, exclude,
                               routed, owner)
        routed.add(owner, pts)
        return pts

    y_lo = sby + EDGE_MARGIN
    y_hi = tty - EDGE_MARGIN
    mid_y = (sby + tty) / 2

    if y_hi > y_lo:
        melhor, melhor_custo = None, None
        for k in range(BAND_TRIES):
            # Alterna em torno do meio do vão: 0, +1, -1, +2, -2...
            step = ((k + 1) // 2) * BAND_STEP * (1 if k % 2 else -1)
            y = min(max(mid_y + step, y_lo), y_hi)
            if _band_taken(bands, y, scx, tcx):
                continue
            if not _hseg_free(blockers, y, scx, tcx):
                continue
            if not _vseg_free(blockers, scx, sby, y):
                continue
            if not _vseg_free(blockers, tcx, y, tty):
                continue
            pts = [scx, sby, scx, y, tcx, y, tcx, tty]
            # Faixa livre de nós não basta: ela também não pode atravessar
            # outra rota já planejada. É esse custo que derruba o cruzamento.
            cruz = routed.crossings(owner, pts)
            custo = cruz * 1000 + abs(y - mid_y)
            if melhor_custo is None or custo < melhor_custo:
                melhor, melhor_custo = (y, pts), custo
            if cruz == 0:        # sem cruzamento algum: não há o que melhorar
                break
        if melhor is not None:
            y, pts = melhor
            bands.append((y, min(scx, tcx), max(scx, tcx)))
            routed.add(owner, pts)
            return pts

    # Nenhuma faixa livre entre os dois: contorna por um canal vertical livre,
    # o mesmo recurso que as rotas de retorno usam.
    down_y = sby + BACK_DOWN
    appr_y = tty - max(12, min(BACK_APPROACH,
                               _space_above(node_map, tgt, tcx) * 0.3))
    src_l, src_r = src['x'], src['x'] + src['size']['w']
    tgt_l, tgt_r = tgt['x'], tgt['x'] + tgt['size']['w']
    y0, y1 = min(appr_y, down_y), max(appr_y, down_y)

    if tgt_l - src_r >= 2 * CLEARANCE + 8:
        channel_x = _clear_channel_x(node_map, (src_r + tgt_l) / 2, y0, y1,
                                     'right', lane_x=lane_x)
    elif src_l - tgt_r >= 2 * CLEARANCE + 8:
        channel_x = _clear_channel_x(node_map, (tgt_r + src_l) / 2, y0, y1,
                                     'left', lane_x=lane_x)
    else:
        channel_x = _clear_channel_x(node_map, min(src_l, tgt_l) - SIDE_GAP,
                                     y0, y1, 'left', lane_x=lane_x)
    pts = [scx, sby, scx, down_y, channel_x, down_y,
           channel_x, appr_y, tcx, appr_y, tcx, tty]
    routed.add(owner, pts)
    return pts


def _bar_y(owner, y_pref, y_lo, y_hi, x0, x1, drops, blockers, routed):
    """Altura da barra de um conector E/Ou, tratada como faixa disputada.

    As barras eram fixadas a 40% do vão, sem olhar quem passava ali. Como elas
    atravessam toda a largura entre as saídas (ou entradas), eram a maior fonte
    de cruzamento remanescente. Agora escolhem a altura pelo mesmo critério das
    outras rotas: livre de nós e, entre as livres, a que menos cruza.
    """
    if y_hi <= y_lo:
        return min(max(y_pref, y_lo), y_hi) if y_hi >= y_lo else y_pref
    melhor, melhor_custo = None, None
    for k in range(BAND_TRIES):
        step = ((k + 1) // 2) * BAND_STEP * (1 if k % 2 else -1)
        y = min(max(y_pref + step, y_lo), y_hi)
        if not _hseg_free(blockers, y, x0, x1):
            continue
        cruz = routed.crossings(owner, [x0, y, x1, y])
        for dx, dy0, dy1 in drops:          # pernas verticais presas à barra
            cruz += routed.crossings(owner, [dx, dy0 if dy0 is not None else y,
                                             dx, dy1 if dy1 is not None else y])
        custo = cruz * 1000 + abs(y - y_pref)
        if melhor_custo is None or custo < melhor_custo:
            melhor, melhor_custo = y, custo
        if cruz == 0:
            break
    return melhor if melhor is not None else min(max(y_pref, y_lo), y_hi)

# ── Posicionamento de rótulos (recurso disputado) ─────────

def _label_box(text, cx, cy):
    w = len(text or '') * LABEL_CHAR_W + 2 * LABEL_PAD_X
    return (cx - w / 2, cy - LABEL_H / 2, cx + w / 2, cy + LABEL_H / 2)


def _overlap_area(a, b, gap=LABEL_GAP):
    ox = min(a[2], b[2] + gap) - max(a[0], b[0] - gap)
    oy = min(a[3], b[3] + gap) - max(a[1], b[1] - gap)
    return ox * oy if ox > 0 and oy > 0 else 0.0


def _label_candidates(cx, cy, seg, half_w):
    """Posições tentadas para um rótulo, da melhor para a pior.

    Primeiro sobre a própria rota, deslizando ao longo do segmento (o rótulo
    continua colado à linha que ele explica); só depois ao lado dela.
    """
    if seg is None:
        yield cx, cy
        return
    x1, y1, x2, y2 = seg
    vertical = abs(x2 - x1) <= abs(y2 - y1)
    lo, hi = (min(y1, y2), max(y1, y2)) if vertical else (min(x1, x2), max(x1, x2))
    margin = (LABEL_H if vertical else half_w) + 2
    lo, hi = lo + margin, hi - margin

    for side in (0, 1, -1):
        off = side * ((half_w + 7) if vertical else (LABEL_H / 2 + 6))
        for k in range(LABEL_TRIES):
            step = ((k + 1) // 2) * LABEL_SLIDE * (1 if k % 2 else -1)
            if vertical:
                t = cy + step
                if hi >= lo:
                    t = min(max(t, lo), hi)
                yield cx + off, t
            else:
                t = cx + step
                if hi >= lo:
                    t = min(max(t, lo), hi)
                yield t, cy + off


def _ponto_ao_longo(pts, distancia):
    """Ponto a `distancia` do início da polilinha, e o segmento em que caiu.

    As rotas são ortogonais, então o comprimento de cada trecho é |dx|+|dy|.
    """
    restante = float(distancia)
    ultimo = (pts[0], pts[1], pts[2], pts[3])
    for i in range(0, len(pts) - 2, 2):
        x1, y1, x2, y2 = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
        ultimo = (x1, y1, x2, y2)
        comp = abs(x2 - x1) + abs(y2 - y1)
        if comp <= 0:
            continue
        if comp >= restante:
            t = max(0.0, min(1.0, restante / comp))
            return (x1 + (x2 - x1) * t, y1 + (y2 - y1) * t), ultimo
        restante -= comp
    return ((ultimo[2] + ultimo[0]) / 2, (ultimo[3] + ultimo[1]) / 2), ultimo


def _rotulo_de_decisao(pts, texto, lado, distancia=LABEL_DEC_DIST):
    """Onde pôr o "Sim"/"Não": ao lado da linha de saída, junto à decisão.

    `lado` (-1 ou +1) afasta o rótulo para um dos lados da linha. Quando os
    dois ramos de uma decisão descem na MESMA coluna — o que acontece sempre
    que os dois destinos são do mesmo ator — pôr um de cada lado é o que
    impede que a bifurcação seja lida como uma sequência.
    """
    (px, py), seg = _ponto_ao_longo(pts, distancia)
    x1, y1, x2, y2 = seg
    meia = (len(texto or '') * LABEL_CHAR_W + 2 * LABEL_PAD_X) / 2
    if abs(x2 - x1) <= abs(y2 - y1):          # trecho vertical
        return (px + lado * (meia + LABEL_DEC_GAP), py), seg
    return (px, py + lado * (LABEL_H / 2 + LABEL_DEC_GAP)), seg


def _candidatos_decisao(pts, texto, lado):
    """Posições tentadas para um Sim/Não, da melhor para a pior.

    Todas continuam coladas à rota e perto da decisão: um rótulo de decisão
    que se afasta da própria linha deixa de dizer a que ramo pertence.
    """
    for dist in LABEL_DEC_PASSOS:
        for l in (lado, -lado):
            yield _rotulo_de_decisao(pts, texto, l, dist)[0]


def _place_labels(prims, node_map):
    """Resolve a disputa por espaço entre rótulos, nós e conectores E/Ou.

    Os rótulos eram gravados no ponto médio do segmento mais longo, sem olhar
    para os vizinhos: em fluxos com várias saídas os "Sim/Não" caíam uns sobre
    os outros e sobre os nós. Aqui cada rótulo procura a primeira posição livre
    ao longo da própria rota e, não havendo nenhuma, fica na de menor conflito.
    """
    occupied = []
    for n in node_map.values():
        if n.get('type') == 'annotation':
            continue
        nx, ny = n.get('x', 0), n.get('y', 0)
        occupied.append((nx, ny, nx + n['size']['w'], ny + n['size']['h']))
    for p in prims:
        if p.get('kind') == 'jlabel':  # conector E/Ou é âncora fixa
            occupied.append(_label_box(p['text'], p['x'], p['y']))

    # Os Sim/Não vão primeiro: eles têm o lugar certo (junto à decisão) e são
    # os que mais custam se saírem dele. Os demais rótulos se acomodam depois.
    com_rotulo = [p for p in prims
                  if p.get('kind') == 'line' and p.get('label')
                  and p.get('label_pos')]
    com_rotulo.sort(key=lambda p: 0 if p.get('label_decisao') else 1)

    for p in com_rotulo:
        cx, cy = p['label_pos']
        half_w = (len(p['label']) * LABEL_CHAR_W + 2 * LABEL_PAD_X) / 2
        if p.get('label_decisao'):
            candidatos = _candidatos_decisao(p['points'], p['label'],
                                             p['label_decisao'])
        else:
            candidatos = _label_candidates(cx, cy, p.get('label_seg'), half_w)
        best, best_cost = None, None
        for tx, ty in candidatos:
            box = _label_box(p['label'], tx, ty)
            cost = sum(_overlap_area(box, o) for o in occupied)
            if cost == 0:
                best, best_cost = (tx, ty), 0
                break
            if best_cost is None or cost < best_cost:
                best, best_cost = (tx, ty), cost
        if best:
            p['label_pos'] = best
            occupied.append(_label_box(p['label'], *best))
    return prims


def plan_edges(edges, node_map, lane_x=(), _conhecido=None):
    """Planeja o desenho de todas as edges (exceto annotation).

    `lane_x` são as bordas das lanes (ver lane_boundaries), que os canais de
    rota evitam para não se confundirem com as divisórias.

    O planejamento roda em DUAS PASSADAS: a primeira desenha na ordem natural,
    a segunda repete o trabalho já sabendo por onde todas as rotas passam — é
    o que permite a uma conexão planejada cedo desviar de outra planejada
    depois. `_conhecido` carrega os trechos da primeira passada e é uso
    interno; quem chama de fora não o informa.

    Retorna lista de primitivas:
      {'kind': 'line', 'points': [x1,y1,...], 'arrow': bool, 'edge': edge|None,
       'etype': str, 'style': dict, 'label': str|None, 'label_pos': (x,y)|None}
      {'kind': 'jlabel', 'text': 'E'|'Ou', 'x': x, 'y': y}
    """
    flow = []
    for e in edges:
        if e.get('type', 'flow') == 'annotation':
            continue
        src = node_map.get(e['from'])
        tgt = node_map.get(e['to'])
        if not src or not tgt:
            continue
        flow.append((e, src, tgt))

    prims = []
    consumed = set()  # id() das edges já cobertas por conectores E/Ou
    routed = Routed(_conhecido)
    # Quantos ramos já saíram de cada decisão — é o que alterna o lado do
    # rótulo. Compartilhado pelos três caminhos (divisão, junção e individual),
    # senão um mesmo Sim/Não recebia tratamento diferente conforme a rota.
    ramos_decisao = {}

    def _lado_do_ramo(src_id):
        n = ramos_decisao.get(src_id, 0)
        ramos_decisao[src_id] = n + 1
        return 1 if n % 2 == 0 else -1

    def _is_forward(src, tgt):
        return _top(tgt)[1] >= _bottom(src)[1] + 8

    # ── Divisões: 2+ saídas para baixo → conector "E"/"Ou" ─
    by_src = {}
    for item in flow:
        by_src.setdefault(item[0]['from'], []).append(item)

    for _, items in by_src.items():
        fwd = [it for it in items if _is_forward(it[1], it[2])]
        if len(fwd) < 2:
            continue
        src = fwd[0][1]
        scx, sby = _bottom(src)
        min_top = min(_top(t)[1] for _, _, t in fwd)
        owner = f"div:{src['id']}"
        xs = [_top(t)[0] for _, _, t in fwd] + [scx]
        # Preferência histórica: barra a ~40% da altura livre. A busca de
        # faixa mantém essa preferência e só se afasta dela quando ali a barra
        # cruzaria um nó ou outra rota.
        jy = _bar_y(owner, sby + max(14, min(JUNC_DROP, (min_top - sby) * 0.4)),
                    sby + 14, max(sby + 14, min_top - 14), min(xs), max(xs),
                    [(_top(t)[0], None, _top(t)[1]) for _, _, t in fwd],
                    _blockers(node_map, {src['id']} | {t['id'] for _, _, t in fwd}),
                    routed)

        prims.append(_line_prim([scx, sby, scx, jy]))
        routed.add(owner, [scx, sby, scx, jy])
        if max(xs) - min(xs) > 1:
            prims.append(_line_prim([min(xs), jy, max(xs), jy]))
            routed.add(owner, [min(xs), jy, max(xs), jy])
        eh_decisao = src.get('type') == 'decision'
        for e, _, tgt in fwd:
            tcx, tty = _top(tgt)
            pts = _detour_vertical([tcx, jy, tcx, tty], node_map,
                                   (src['id'], tgt['id']),
                                   routed, _edge_owner(e))
            routed.add(_edge_owner(e), pts)
            # Ramos alternam de lado da linha: quando os dois destinos são do
            # mesmo ator, ambos descem na MESMA coluna, e é só isso que impede
            # a bifurcação de ser lida como uma sequência.
            rotulo = e.get('label') or None
            lado = _lado_do_ramo(src['id']) if (eh_decisao and rotulo) else 0
            pos = (tcx, max((jy + tty) / 2, jy + 16))
            if eh_decisao and rotulo:
                pos, _seg = _rotulo_de_decisao(pts, rotulo, lado)
            prims.append(_line_prim(pts, edge=e, etype=e.get('type', 'flow'),
                                    arrow=True, label=rotulo,
                                    label_pos=pos,
                                    label_seg=(tcx, jy, tcx, tty),
                                    label_decisao=lado if rotulo else 0))
            consumed.add(id(e))
        prims.append({'kind': 'jlabel',
                      'text': 'Ou' if src.get('type') == 'decision' else 'E',
                      'x': scx, 'y': jy})

    # ── Junções: 2+ entradas vindas de cima → T invertido ──
    by_tgt = {}
    for item in flow:
        if id(item[0]) in consumed:
            continue
        by_tgt.setdefault(item[0]['to'], []).append(item)

    for _, items in by_tgt.items():
        fwd = [it for it in items if _is_forward(it[1], it[2])]
        if len(fwd) < 2:
            continue
        tgt = fwd[0][2]
        tcx, tty = _top(tgt)
        max_bottom = max(_bottom(s)[1] for _, s, _ in fwd)
        owner = f"jun:{tgt['id']}"
        xs = [_bottom(s)[0] for _, s, _ in fwd] + [tcx]
        # Espelho da divisão: barra a ~40% do vão, medida a partir do alvo.
        jy = _bar_y(owner, tty - max(14, min(JUNC_DROP, (tty - max_bottom) * 0.4)),
                    min(tty - 14, max_bottom + 14), tty - 14, min(xs), max(xs),
                    [(_bottom(s)[0], _bottom(s)[1], None) for _, s, _ in fwd],
                    _blockers(node_map, {tgt['id']} | {s['id'] for _, s, _ in fwd}),
                    routed)

        for e, s, _ in fwd:
            scx, sby = _bottom(s)
            pts = _detour_vertical([scx, sby, scx, jy], node_map,
                                   (s['id'], tgt['id']),
                                   routed, _edge_owner(e))
            routed.add(_edge_owner(e), pts)
            rotulo = e.get('label') or None
            lado = 0
            pos = (scx, (sby + jy) / 2)
            if s.get('type') == 'decision' and rotulo:
                lado = _lado_do_ramo(s['id'])
                pos, _seg = _rotulo_de_decisao(pts, rotulo, lado)
            prims.append(_line_prim(pts, edge=e, etype=e.get('type', 'flow'),
                                    label=rotulo, label_pos=pos,
                                    label_seg=(scx, sby, scx, jy),
                                    label_decisao=lado))
            consumed.add(id(e))
        if max(xs) - min(xs) > 1:
            prims.append(_line_prim([min(xs), jy, max(xs), jy]))
            routed.add(owner, [min(xs), jy, max(xs), jy])
        prims.append(_line_prim([tcx, jy, tcx, tty], arrow=True))
        routed.add(owner, [tcx, jy, tcx, tty])

    # ── Edges individuais ──────────────────────────────────
    side_count = 0
    bands = []   # faixas horizontais já ocupadas: (y, x_ini, x_fim)
    for e, src, tgt in flow:
        if id(e) in consumed:
            continue
        scx, sby = _bottom(src)
        tcx, tty = _top(tgt)

        if _is_forward(src, tgt):
            pts = _route_forward(_edge_owner(e), src, tgt, node_map,
                                 lane_x, bands, routed)
        else:
            # Retorno/lateral: desce, percorre um canal vertical livre e entra
            # por cima. Preferência: o corredor ENTRE as colunas dos dois nós
            # (nunca dar a volta colado no balão); mesma coluna → canal à
            # esquerda. O canal é sempre validado contra todos os nós.
            down_y = sby + BACK_DOWN
            # Aproximar-se mais do alvo do que o ponto médio usado pelas
            # conexões normais (50% do vão), para as duas não se colarem
            appr_y = tty - max(12, min(BACK_APPROACH,
                                       _space_above(node_map, tgt, tcx) * 0.3))
            offset = side_count * SIDE_STEP
            side_count += 1

            src_l, src_r = src['x'], src['x'] + src['size']['w']
            tgt_l, tgt_r = tgt['x'], tgt['x'] + tgt['size']['w']
            y0, y1 = min(appr_y, down_y), max(appr_y, down_y)

            # Preferência: o corredor entre as duas colunas. Se ele obrigar a
            # rota a atravessar uma barra de conector que cruza o desenho
            # inteiro, o contorno por fora do fluxo é a saída mais legível —
            # por isso as duas alternativas são medidas, não presumidas.
            #
            # Os limites do desenho vêm só dos nós do FLUXO: o layout estaciona
            # as anotações em x = -9999 (elas são desenhadas na coluna lateral
            # de comentários, não no diagrama). Incluí-las aqui jogava o canal
            # de contorno para dez mil pixels à esquerda — a rota saía do
            # documento e parecia uma linha infinita ligada a nada.
            reais = [n for n in node_map.values() if n.get('type') != 'annotation']
            if not reais:
                reais = list(node_map.values())
            todos_l = min(n.get('x', 0) for n in reais)
            todos_r = max(n.get('x', 0) + n['size']['w'] for n in reais)
            if tgt_l - src_r >= 2 * CLEARANCE + 8:      # alvo à direita
                pref = ((src_r + tgt_l) / 2 + offset, 'right')
            elif src_l - tgt_r >= 2 * CLEARANCE + 8:    # alvo à esquerda
                pref = ((tgt_r + src_l) / 2 - offset, 'left')
            else:                                        # mesma coluna
                pref = (min(src_l, tgt_l) - SIDE_GAP - offset, 'left')
            opcoes = [pref,
                      (todos_l - SIDE_GAP - offset, 'left'),
                      (todos_r + SIDE_GAP + offset, 'right')]

            melhor, melhor_custo = None, None
            for i, (cx0, direcao) in enumerate(opcoes):
                cx_ok = _clear_channel_x(node_map, cx0, y0, y1, direcao,
                                         lane_x=lane_x)
                rota = [scx, sby, scx, down_y, cx_ok, down_y,
                        cx_ok, appr_y, tcx, appr_y, tcx, tty]
                custo = routed.crossings(_edge_owner(e), rota) * 100 + i
                if melhor_custo is None or custo < melhor_custo:
                    melhor, melhor_custo = rota, custo
                if custo < 100 and i == 0:   # a preferência já não cruza nada
                    break
            pts = melhor
            routed.add(_edge_owner(e), pts)

        mid, seg = _longest_seg(pts)
        rotulo = e.get('label') or None
        lado = 0
        if src.get('type') == 'decision' and rotulo:
            lado = _lado_do_ramo(src['id'])
            mid, seg = _rotulo_de_decisao(pts, rotulo, lado)
        prims.append(_line_prim(pts, edge=e, etype=e.get('type', 'flow'),
                                arrow=True, label=rotulo,
                                label_pos=mid, label_seg=seg,
                                label_decisao=lado))

    if _conhecido is None:
        return plan_edges(edges, node_map, lane_x, _conhecido=routed.snapshot())
    return _place_labels(prims, node_map)


def find_edge_at(edges, node_map, mx, my, tol=6, lane_x=()):
    """Retorna a edge cuja rota passa a até `tol` px do ponto (mx, my)."""
    for p in plan_edges(edges, node_map, lane_x):
        if p.get('kind') != 'line' or not p.get('edge'):
            continue
        pts = p['points']
        for i in range(0, len(pts) - 2, 2):
            if dist_point_seg(mx, my, pts[i], pts[i + 1],
                              pts[i + 2], pts[i + 3]) <= tol:
                return p['edge']
    return None


# ── Desenho no Canvas ─────────────────────────────────────

def _draw_arrowhead(canvas, x1, y1, x2, y2, size=10, **kw):
    """Desenha ponta de seta no ponto (x2, y2)."""
    angle = math.atan2(y2 - y1, x2 - x1)
    a1 = angle + math.pi * 0.85
    a2 = angle - math.pi * 0.85
    ax1 = x2 + size * math.cos(a1)
    ay1 = y2 + size * math.sin(a1)
    ax2 = x2 + size * math.cos(a2)
    ay2 = y2 + size * math.sin(a2)
    return canvas.create_polygon(x2, y2, ax1, ay1, ax2, ay2,
                                 fill=kw.get('fill', '#334155'),
                                 outline=kw.get('fill', '#334155'),
                                 tags=kw.get('tags', ()))


def draw_edges(canvas, prims, styles, tags=None, scale=1.0):
    """Desenha as primitivas planejadas no Canvas. Retorna lista de item IDs.

    `scale` é o zoom da vista: as primitivas vêm em espaço de MODELO e o canvas
    pode estar ampliado (ver core/viewport.py). O redesenho ao vivo das
    conexões durante um arraste precisa disso, senão as setas voltariam a 100%
    enquanto o resto da tela continua ampliado.
    """
    tg = tuple(tags or []) + ('edge',)
    etypes = styles['edgeTypes']
    items = []

    def fs(size):
        return max(5, int(round(size * scale)))

    # 1) Linhas e setas
    for p in prims:
        if p['kind'] != 'line':
            continue
        es = etypes.get(p['etype'], etypes.get('flow', {}))
        stroke = p['style'].get('color', es.get('stroke', '#595959'))
        is_dash = p['style'].get('dash', es.get('dash', False))
        pts = [v * scale for v in p['points']]
        items.append(canvas.create_line(*pts, fill=stroke, width=1,
                                        dash=(6, 4) if is_dash else (), tags=tg))
        if p['arrow'] and es.get('arrow', 'standard') != 'none':
            items.append(_draw_arrowhead(canvas, pts[-4], pts[-3], pts[-2], pts[-1],
                                         size=8 * scale, fill=stroke, tags=tg))

    # 2) Rótulos de junção ("E"/"Ou") — caixinha branca sobre o conector
    for p in prims:
        if p['kind'] != 'jlabel':
            continue
        txt = canvas.create_text(p['x'] * scale, p['y'] * scale, text=p['text'],
                                 font=('Arial', fs(8), 'bold'), fill='#000000', tags=tg)
        bbox = canvas.bbox(txt)
        if bbox:
            bg = canvas.create_rectangle(bbox[0] - 4, bbox[1] - 2,
                                         bbox[2] + 4, bbox[3] + 2,
                                         fill='#ffffff', outline='#595959', tags=tg)
            canvas.tag_lower(bg, txt)
            items.append(bg)
        items.append(txt)

    # 3) Rótulos das edges (Sim/Não...) com fundo branco sobre a linha
    for p in prims:
        if p['kind'] != 'line' or not p.get('label') or not p.get('label_pos'):
            continue
        x, y = p['label_pos']
        txt = canvas.create_text(x * scale, y * scale, text=p['label'],
                                 font=('Arial', fs(7)), fill='#000000', tags=tg)
        bbox = canvas.bbox(txt)
        if bbox:
            bg = canvas.create_rectangle(bbox[0] - 2, bbox[1] - 1,
                                         bbox[2] + 2, bbox[3] + 1,
                                         fill='#ffffff', outline='', tags=tg)
            canvas.tag_lower(bg, txt)
            items.append(bg)
        items.append(txt)

    return items
