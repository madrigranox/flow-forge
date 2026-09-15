"""
hittest.py — Resolução de alvo sob o ponteiro, pela GEOMETRIA REAL da forma.

Antes havia duas estratégias concorrentes de hit-test (nós por caixa envolvente
sobre o modelo, comentários por sobreposição de itens do canvas) e nenhuma
delas respeitava a forma desenhada: decisão é hexágono e paralelismo é uma
barra de poucos pixels — ambos respondiam por um retângulo que não é o que o
usuário vê. Aqui há um único resolvedor, que responde "o que está sob este
ponto" na ordem de empilhamento visível, usando a mesma geometria de
`core/shapes.py` e uma folga de toque para alvos finos.

Todas as coordenadas deste módulo estão em espaço de MODELO. Quem chama
converte a entrada com `core.viewport.Viewport.to_model()` antes.
"""
import math

# Alvo mínimo tocável (unidades de modelo). A barra de paralelismo tem 12px de
# altura: sem este piso, acertá-la exige precisão de 6px.
MIN_TOUCH_SIZE = 20
# Extensão acima da barra de paralelismo, onde o rótulo dela é desenhado.
PARALLEL_LABEL_BAND = 16


# ── Primitivas geométricas ────────────────────────────────

def _dist_point_seg(px, py, x1, y1, x2, y2):
    """Distância de um ponto a um segmento."""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _point_in_polygon(px, py, pts):
    """Ray casting sobre polilinha achatada [x1,y1,x2,y2,...]."""
    n = len(pts) // 2
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = pts[2 * i], pts[2 * i + 1]
        xj, yj = pts[2 * j], pts[2 * j + 1]
        if (yi > py) != (yj > py):
            x_cross = (xj - xi) * (py - yi) / (yj - yi) + xi
            if px < x_cross:
                inside = not inside
        j = i
    return inside


def _dist_to_polygon(px, py, pts):
    """Menor distância do ponto ao contorno do polígono."""
    n = len(pts) // 2
    best = float('inf')
    for i in range(n):
        j = (i + 1) % n
        best = min(best, _dist_point_seg(px, py, pts[2 * i], pts[2 * i + 1],
                                         pts[2 * j], pts[2 * j + 1]))
    return best


def _in_polygon(px, py, pts, slop):
    if _point_in_polygon(px, py, pts):
        return True
    return slop > 0 and _dist_to_polygon(px, py, pts) <= slop


def _in_rect(px, py, x, y, w, h, slop):
    return (x - slop) <= px <= (x + w + slop) and (y - slop) <= py <= (y + h + slop)


def _in_ellipse(px, py, x, y, w, h, slop):
    rx, ry = w / 2 + slop, h / 2 + slop
    if rx <= 0 or ry <= 0:
        return False
    cx, cy = x + w / 2, y + h / 2
    return ((px - cx) / rx) ** 2 + ((py - cy) / ry) ** 2 <= 1.0


def _in_capsule(px, py, x, y, w, h, slop):
    """Stadium: retângulo com pontas semicirculares de raio h/2."""
    r = h / 2
    x1, x2 = x + r, x + w - r
    if x2 < x1:  # mais alto que largo — vira círculo
        x1 = x2 = x + w / 2
        r = min(r, w / 2)
    return _dist_point_seg(px, py, x1, y + r, x2, y + r) <= r + slop


# ── Geometria por tipo de nó (espelha core/shapes.py) ─────

def hexagon_points(x, y, w, h):
    """Mesmos pontos de shapes.draw_hexagon (Caixa de Decisão)."""
    ind = min(w * 0.18, h * 0.6)
    cy = y + h / 2
    return [x + ind, y, x + w - ind, y, x + w, cy,
            x + w - ind, y + h, x + ind, y + h, x, cy]


def note_points(x, y, w, h, fold=14):
    """Mesmos pontos de shapes.draw_note (anotação com canto dobrado)."""
    return [x, y, x + w - fold, y, x + w, y + fold, x + w, y + h, x, y + h]


def node_contains(node, px, py, slop=0.0):
    """O ponto (px, py) está sobre a forma VISÍVEL deste nó?

    `slop` é a folga de toque em unidades de modelo (ver Viewport.touch_slop).
    """
    x, y = node.get('x', 0), node.get('y', 0)
    w, h = node['size']['w'], node['size']['h']
    ntype = node.get('type', 'task')

    # Piso de alvo tocável: expande apenas a dimensão fina (barras, tarjas).
    pad = max(0.0, (MIN_TOUCH_SIZE - w) / 2, (MIN_TOUCH_SIZE - h) / 2)
    s = slop + pad

    if ntype == 'start':
        return _in_ellipse(px, py, x, y, w, h, s)
    if ntype == 'end':
        return _in_capsule(px, py, x, y, w, h, s)
    if ntype == 'decision':
        return _in_polygon(px, py, hexagon_points(x, y, w, h), s)
    if ntype == 'annotation':
        return _in_polygon(px, py, note_points(x, y, w, h), s)
    if ntype == 'parallel':
        # A barra carrega o rótulo logo acima dela; a faixa faz parte do alvo.
        top = y - (PARALLEL_LABEL_BAND if node.get('label') else 0)
        return _in_rect(px, py, x, top, w, (y + h) - top, s)
    return _in_rect(px, py, x, y, w, h, s)  # task, subprocess


def node_outline(node):
    """Contorno da forma para o realce de seleção — polilinha fechada."""
    x, y = node.get('x', 0), node.get('y', 0)
    w, h = node['size']['w'], node['size']['h']
    ntype = node.get('type', 'task')
    if ntype == 'decision':
        return hexagon_points(x, y, w, h)
    if ntype == 'annotation':
        return note_points(x, y, w, h)
    return [x, y, x + w, y, x + w, y + h, x, y + h]


# ── Resolvedor único ──────────────────────────────────────

def find_node_at(model, px, py, slop=0.0, skip_annotations=True):
    """Nó do fluxo sob o ponto, na ordem de empilhamento (topo primeiro).

    O renderizador desenha os nós na ordem da lista, então o último desenhado
    é o que aparece por cima: a busca percorre ao contrário.
    """
    for node in reversed(model['nodes']):
        if skip_annotations and node.get('type') == 'annotation':
            continue
        if node_contains(node, px, py, slop):
            return node
    return None


def find_lane_header_at(model, px, py, slop=0.0):
    """Header de lane sob o ponto (a faixa de título no topo de cada coluna)."""
    comp = model.get('_computed', {})
    lane_pos = comp.get('lane_positions', {})
    top = model['meta']['margins']['top']
    header_h = comp.get('header_height', 36)
    if not (top - slop <= py <= top + header_h + slop):
        return None
    for lane in model['lanes']:
        lp = lane_pos.get(lane['id'])
        if lp and lp['x'] - slop <= px <= lp['x'] + lp['width'] + slop:
            return lane
    return None


def find_annotation_at(model, px, py, slop=0.0, canvas=None, scale=1.0):
    """Comentário sob o ponto.

    Os comentários são posicionados pelo renderizador na coluna lateral (a
    altura de cada um depende do texto quebrado pelo Tk), então a fonte de
    verdade é o próprio canvas. Sem canvas — em teste headless — cai para a
    caixa do modelo, que o layout já preenche.
    """
    if canvas is not None:
        vx, vy = px * scale, py * scale
        vs = max(2.0, slop * scale)
        for item in canvas.find_overlapping(vx - vs, vy - vs, vx + vs, vy + vs):
            for t in canvas.gettags(item):
                if t.startswith('note_ann_'):
                    ann_id = t[len('note_ann_'):]
                    for n in model['nodes']:
                        if n['id'] == ann_id:
                            return n
        return None
    for n in reversed(model['nodes']):
        if n.get('type') == 'annotation' and node_contains(n, px, py, slop):
            return n
    return None


def find_subprocess_node_at(model, px, py, slop=0.0):
    """Nó de dentro de uma Instrução de Trabalho sob o ponto.

    Os subprocessos são desenhados numa seção própria abaixo do fluxo, com
    posição calculada pelo layout — mas a busca de alvo só percorria
    `model['nodes']`, então clicar neles não fazia nada e nada explicava por
    quê. Devolve `(subprocesso, nó)` ou `(None, None)`.
    """
    for sp in reversed(model.get('subprocesses', [])):
        for node in reversed(sp.get('nodes', [])):
            if node_contains(node, px, py, slop):
                return sp, node
    return None, None


def resolve_target(model, px, py, slop=0.0, canvas=None, scale=1.0,
                   edge_finder=None):
    """Resolvedor único: o que está sob este ponto?

    Retorna `(kind, obj)` com kind em 'node' | 'annotation' | 'lane_header' |
    'edge' | None, na ordem de empilhamento visível.
    """
    node = find_node_at(model, px, py, slop)
    if node is not None:
        return 'node', node

    ann = find_annotation_at(model, px, py, slop, canvas=canvas, scale=scale)
    if ann is not None:
        return 'annotation', ann

    lane = find_lane_header_at(model, px, py, slop)
    if lane is not None:
        return 'lane_header', lane

    if edge_finder is not None:
        edge = edge_finder(px, py, slop)
        if edge is not None:
            return 'edge', edge

    # Por último: os nós dentro das Instruções de Trabalho, que vivem na seção
    # de baixo e não competem com o fluxo principal por espaço.
    sp, sp_node = find_subprocess_node_at(model, px, py, slop)
    if sp_node is not None:
        return 'sp_node', (sp, sp_node)

    return None, None
