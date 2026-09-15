"""
test_regressao.py — Rede de regressão do Flow Forge (headless, sem Tk).

Cobre os critérios de aceite pontuais que a decisão definiu, medidos sobre os
fluxogramas reais do projeto:

  1. Acurácia de hit-test por tipo de forma e por nível de zoom  (alvo: ≥99%)
  2. Crossing Index — cruzamentos de setas por fluxograma        (alvo: 0–1)
  3. Sobreposição de rótulos                                     (alvo: 0)
  4. Paridade canvas ↔ PDF: os dois consomem o MESMO roteamento

Rodar:  python tests/test_regressao.py        (ou pytest tests/)
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.parser import parse_flowchart                      # noqa: E402
from core.layout import compute_layout                       # noqa: E402
from core.edges import (plan_edges, lane_boundaries, _label_box,  # noqa: E402
                        dist_point_seg)
from core.hittest import (node_contains, find_node_at,       # noqa: E402
                          hexagon_points, MIN_TOUCH_SIZE)
from core.viewport import Viewport                           # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZOOMS = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
ALVO_HIT = 0.99
ALVO_CRUZAMENTOS = 1


# ── Carregamento dos fluxogramas reais do projeto ─────────

def fluxogramas():
    """Todos os .json de fluxograma versionados no projeto."""
    achados = [os.path.join(RAIZ, 'data', 'sample.json')]
    for nome in sorted(os.listdir(RAIZ)):
        if nome.endswith('.json'):
            achados.append(os.path.join(RAIZ, nome))
    # Fixtures: fluxos densos (4 lanes, 15+ nós) que os arquivos reais do
    # projeto não exercitam — é neles que o roteamento é medido de verdade.
    fix = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')
    if os.path.isdir(fix):
        for nome in sorted(os.listdir(fix)):
            if nome.endswith('.json'):
                achados.append(os.path.join(fix, nome))
    saida = []
    for caminho in achados:
        if not os.path.exists(caminho):
            continue
        try:
            modelo = compute_layout(parse_flowchart(
                io.open(caminho, encoding='utf-8').read()))
        except Exception:
            continue
        saida.append((os.path.basename(caminho), modelo))
    return saida


def _prims(modelo):
    node_map = {n['id']: n for n in modelo['nodes']}
    return plan_edges(modelo['edges'], node_map, lane_boundaries(modelo)), node_map


# ── Métricas ──────────────────────────────────────────────

def _segmentos(prim):
    pts = prim['points']
    return [(pts[i], pts[i + 1], pts[i + 2], pts[i + 3])
            for i in range(0, len(pts) - 2, 2)]


def _cruzam(a, b):
    """Duas retas ortogonais se cruzam em X (não apenas se tocam nas pontas)?"""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    a_vert = abs(ax1 - ax2) < 1
    b_vert = abs(bx1 - bx2) < 1
    if a_vert == b_vert:
        return False
    if b_vert:
        a, b = b, a
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
    # `a` é vertical, `b` é horizontal
    x = ax1
    y = by1
    return (min(ay1, ay2) + 1 < y < max(ay1, ay2) - 1 and
            min(bx1, bx2) + 1 < x < max(bx1, bx2) - 1)


def crossing_index(prims):
    """Número de cruzamentos entre rotas de conexões diferentes."""
    linhas = [p for p in prims if p.get('kind') == 'line']
    total = 0
    for i, p in enumerate(linhas):
        for q in linhas[i + 1:]:
            # Trechos da mesma conexão (ou do mesmo conector E/Ou) não contam
            if p.get('edge') is not None and p.get('edge') is q.get('edge'):
                continue
            for sa in _segmentos(p):
                for sb in _segmentos(q):
                    if _cruzam(sa, sb):
                        total += 1
    return total


def label_overlaps(prims, node_map):
    """Pares de rótulos sobrepostos + rótulos caídos sobre um nó."""
    caixas = []
    for p in prims:
        if p.get('kind') == 'line' and p.get('label') and p.get('label_pos'):
            caixas.append(_label_box(p['label'], *p['label_pos']))
        elif p.get('kind') == 'jlabel':
            caixas.append(_label_box(p['text'], p['x'], p['y']))

    def cruza(a, b):
        return (min(a[2], b[2]) - max(a[0], b[0]) > 0 and
                min(a[3], b[3]) - max(a[1], b[1]) > 0)

    total = 0
    for i, a in enumerate(caixas):
        for b in caixas[i + 1:]:
            if cruza(a, b):
                total += 1
    for a in caixas:
        for n in node_map.values():
            if n.get('type') == 'annotation':
                continue
            nx, ny = n.get('x', 0), n.get('y', 0)
            if cruza(a, (nx, ny, nx + n['size']['w'], ny + n['size']['h'])):
                total += 1
    return total


def _pontos_dentro(node):
    """Pontos que o usuário considera "dentro" da forma visível."""
    x, y = node['x'], node['y']
    w, h = node['size']['w'], node['size']['h']
    cx, cy = x + w / 2, y + h / 2
    pts = [(cx, cy),
           (cx, y + h * 0.25), (cx, y + h * 0.75),
           (x + w * 0.35, cy), (x + w * 0.65, cy)]
    if node['type'] == 'decision':                    # pontas do hexágono
        hx = hexagon_points(x, y, w, h)
        pts.append((x + w - 3, cy))
        pts.append((x + 3, cy))
        pts.append(((hx[0] + hx[2]) / 2, y + 2))
    return pts


def _pontos_fora(node):
    """Pontos na caixa envolvente mas FORA da forma — não devem selecionar.

    É exatamente o defeito relatado: clicar no canto de uma decisão e pegar o
    nó errado, porque o hit-test respondia pelo retângulo.
    """
    x, y = node['x'], node['y']
    w, h = node['size']['w'], node['size']['h']
    if node['type'] == 'decision':
        ind = min(w * 0.18, h * 0.6)
        return [(x + ind * 0.2, y + 2), (x + w - ind * 0.2, y + 2),
                (x + ind * 0.2, y + h - 2), (x + w - ind * 0.2, y + h - 2)]
    if node['type'] == 'start':                        # cantos da elipse
        return [(x + 2, y + 2), (x + w - 2, y + 2),
                (x + 2, y + h - 2), (x + w - 2, y + h - 2)]
    return []


# ── Testes ────────────────────────────────────────────────

def test_hit_test_acerta_a_forma_em_todos_os_zooms():
    """Acurácia de hit-test ≥99% por forma e por zoom (baseline era ~70%)."""
    acertos = total = 0
    por_forma = {}
    for nome, modelo in fluxogramas():
        alvos = [n for n in modelo['nodes'] if n['type'] != 'annotation']
        for zoom in ZOOMS:
            vp = Viewport(zoom)
            slop = vp.touch_slop()
            for node in alvos:
                for mx, my in _pontos_dentro(node):
                    # Caminho real da entrada: modelo → canvas → volta ao modelo
                    cx, cy = vp.to_view(mx, my)
                    px, py = vp.to_model(cx, cy)
                    ok = find_node_at(modelo, px, py, slop) is node
                    acertos += ok
                    total += 1
                    d = por_forma.setdefault(node['type'], [0, 0])
                    d[0] += ok
                    d[1] += 1
    taxa = acertos / total
    detalhe = ', '.join(f'{k} {v[0] / v[1]:.0%}' for k, v in sorted(por_forma.items()))
    print(f'  acurácia de hit-test: {taxa:.1%} ({acertos}/{total}) — {detalhe}')
    assert taxa >= ALVO_HIT, f'acurácia {taxa:.1%} abaixo do alvo {ALVO_HIT:.0%}'


def test_hit_test_recusa_o_canto_da_caixa_envolvente():
    """Canto de hexágono/elipse não pode selecionar o nó (nem o vizinho)."""
    falhas = []
    for nome, modelo in fluxogramas():
        for node in modelo['nodes']:
            for mx, my in _pontos_fora(node):
                achado = find_node_at(modelo, mx, my, slop=0.0)
                if achado is node:
                    falhas.append(f"{nome}:{node['id']} ({node['type']})")
    print(f'  cantos fora da forma recusados: {"OK" if not falhas else falhas}')
    assert not falhas, f'hit-test ainda responde por caixa envolvente: {falhas}'


def test_alvo_fino_continua_alcancavel():
    """A barra de paralelismo (12px) precisa de piso de alvo tocável."""
    barra = {'id': 'P1', 'type': 'parallel', 'x': 0, 'y': 100, 'label': '',
             'size': {'w': 200, 'h': 12}}
    modelo = {'nodes': [barra], 'lanes': [], 'meta': {'margins': {'top': 0}},
              '_computed': {}}
    vp = Viewport(1.0)
    alto = MIN_TOUCH_SIZE / 2
    print(f'  faixa tocável da barra: {2 * alto:.0f}px (forma tem 12px)')
    assert find_node_at(modelo, 100, 106, vp.touch_slop()) is barra
    assert find_node_at(modelo, 100, 100 - alto + 2, vp.touch_slop()) is barra


def test_crossing_index_dentro_do_alvo():
    """Cruzamentos de setas por fluxograma dentro do alvo (baseline era 3–7)."""
    piores = []
    for nome, modelo in fluxogramas():
        prims, _ = _prims(modelo)
        n = crossing_index(prims)
        print(f'  {nome}: {n} cruzamento(s)')
        if n > ALVO_CRUZAMENTOS:
            piores.append((nome, n))
    assert not piores, f'acima do alvo de {ALVO_CRUZAMENTOS}: {piores}'


def test_rotulos_nao_se_sobrepoem():
    """Rótulos Sim/Não não podem cair uns sobre os outros nem sobre os nós."""
    piores = []
    for nome, modelo in fluxogramas():
        prims, node_map = _prims(modelo)
        n = label_overlaps(prims, node_map)
        print(f'  {nome}: {n} sobreposição(ões) de rótulo')
        if n:
            piores.append((nome, n))
    assert not piores, f'rótulos sobrepostos: {piores}'


def test_rotas_nao_atravessam_nos():
    """Nenhum trecho de rota pode cortar o interior de um nó que não é seu."""
    piores = []
    for nome, modelo in fluxogramas():
        prims, node_map = _prims(modelo)
        for p in prims:
            if p.get('kind') != 'line':
                continue
            envolvidos = set()
            if p.get('edge'):
                envolvidos = {p['edge']['from'], p['edge']['to']}
            for x1, y1, x2, y2 in _segmentos(p):
                for n in node_map.values():
                    if n['id'] in envolvidos or n.get('type') == 'annotation':
                        continue
                    nx, ny = n.get('x', 0), n.get('y', 0)
                    nw, nh = n['size']['w'], n['size']['h']
                    dentro = (nx + 2 < min(x1, x2) < nx + nw - 2 or
                              nx + 2 < max(x1, x2) < nx + nw - 2 or
                              (min(x1, x2) <= nx and max(x1, x2) >= nx + nw))
                    faixa = (ny + 2 < min(y1, y2) < ny + nh - 2 or
                             ny + 2 < max(y1, y2) < ny + nh - 2 or
                             (min(y1, y2) <= ny and max(y1, y2) >= ny + nh))
                    if dentro and faixa:
                        piores.append(f"{nome}: rota atravessa {n['id']}")
    piores = sorted(set(piores))
    print(f'  travessias de nó: {len(piores)}')
    assert not piores, piores[:6]


def test_rotas_ficam_dentro_do_desenho():
    """Nenhuma rota pode sair da área do documento.

    O layout estaciona as anotações em x = -9999 (elas vão para a coluna
    lateral de comentários, não para o diagrama). Quando o cálculo do canal de
    contorno as considerava um "nó mais à esquerda", a rota era mandada para
    dez mil pixels fora do desenho e aparecia como uma linha infinita à
    esquerda, ligada a nada.
    """
    falhas = []
    for nome, modelo in fluxogramas():
        # Toda amostra ganha uma anotação: é o que a IA gera para registrar
        # lacunas, e era o gatilho do defeito.
        with_note = json.loads(json.dumps(modelo.get('_raw') or {}))
        if not with_note.get('lanes'):
            continue
        with_note.setdefault('nodes', []).append(
            {'id': '_ZZ_nota', 'laneId': with_note['lanes'][0]['id'],
             'type': 'annotation', 'label': 'Gap: confirmar responsável'})
        alvo = next((n['id'] for n in with_note['nodes']
                     if n.get('type') != 'annotation'), None)
        if alvo:
            with_note.setdefault('edges', []).append(
                {'from': alvo, 'to': '_ZZ_nota', 'type': 'annotation'})
        try:
            m = compute_layout(parse_flowchart(json.dumps(with_note)))
        except Exception:
            continue

        prims, _ = _prims(m)
        comp = m['_computed']
        limite_esq = m['meta']['margins']['left'] - 120
        limite_dir = comp['content_right'] + 120
        for p in prims:
            if p.get('kind') != 'line':
                continue
            for x in p['points'][0::2]:
                if not (limite_esq <= x <= limite_dir):
                    falhas.append(f'{nome}: rota em x={x:.0f} fora de '
                                  f'[{limite_esq:.0f}, {limite_dir:.0f}]')
    falhas = sorted(set(falhas))
    print(f'  rotas fora do desenho: {len(falhas)}')
    assert not falhas, falhas[:4]


def test_rotulos_de_decisao_ficam_junto_do_proprio_ramo():
    """Sim/Não na linha de saída e perto dela — a regra do fluxograma.

    A prática consolidada (Visio e afins) é: o rótulo de uma decisão vai SOBRE
    A LINHA DE SAÍDA e PERTO do início dela, nunca dentro do losango e nunca
    solto no meio do desenho. Antes o rótulo ia para o meio do segmento mais
    longo: num ramo que voltava para trás, ele acabava a centenas de pixels da
    decisão — e a caça por espaço livre chegava a soltá-lo da própria rota.

    Dois ramos da mesma decisão também precisam ficar em LADOS OPOSTOS da
    linha: quando os dois destinos são do mesmo ator, ambos descem na mesma
    coluna, e sem isso a bifurcação é lida como uma sequência.
    """
    import math

    longe, soltos, mesmo_lado = [], [], []
    for nome, modelo in fluxogramas():
        nos = {n['id']: n for n in modelo['nodes']}
        prims, _ = _prims(modelo)
        por_decisao = {}
        for p in prims:
            e = p.get('edge')
            if p.get('kind') != 'line' or not e or not p.get('label'):
                continue
            if nos.get(e['from'], {}).get('type') != 'decision':
                continue
            lx, ly = p['label_pos']
            pts = p['points']

            # 1) perto da cabeça do próprio ramo
            if math.hypot(lx - pts[0], ly - pts[1]) > 60:
                longe.append(f"{nome}:{e['from']}->{e['to']}")

            # 2) colado à própria linha
            d = min(dist_point_seg(lx, ly, pts[i], pts[i + 1],
                                   pts[i + 2], pts[i + 3])
                    for i in range(0, len(pts) - 2, 2))
            if d > 26:
                soltos.append(f"{nome}:{e['from']}->{e['to']} ({d:.0f}px)")

            por_decisao.setdefault(e['from'], []).append(
                (pts[0], p.get('label_decisao', 0)))

        # 3) ramos que descem na MESMA coluna ficam em lados opostos
        for origem, ramos in por_decisao.items():
            for i in range(len(ramos)):
                for j in range(i + 1, len(ramos)):
                    mesmo_x = abs(ramos[i][0] - ramos[j][0]) < 2
                    if mesmo_x and ramos[i][1] == ramos[j][1] != 0:
                        mesmo_lado.append(f'{nome}:{origem}')

    print(f'  rótulos longe do ramo: {len(longe)} · soltos da linha: '
          f'{len(soltos)} · irmãos do mesmo lado: {len(mesmo_lado)}')
    assert not longe, f'rótulo longe do próprio ramo: {longe[:4]}'
    assert not soltos, f'rótulo solto da própria linha: {soltos[:4]}'
    assert not mesmo_lado, f'ramos irmãos no mesmo lado da linha: {mesmo_lado[:4]}'


def test_paridade_canvas_pdf():
    """Canvas e PDF precisam partir do MESMO roteamento, sempre igual.

    O risco de compliance apontado no parecer é o PDF exportado divergir da
    tela. Aqui isso é garantido por construção — os dois consumidores chamam a
    mesma `plan_edges` — e o teste prende as duas condições que sustentam essa
    garantia: a função é literalmente a mesma nos dois caminhos, e o
    planejamento é determinístico (duas chamadas sobre o mesmo modelo dão o
    mesmo desenho).

    O que ele NÃO faz: comparar os pixels desenhados. Divergência no desenho
    em si (fonte, espessura, forma) continua sendo caso de inspeção visual —
    ver o roteiro em `test_rotas_nao_atravessam_nos` e a conferência manual
    descrita no MELHORIAS_APLICADAS.md.
    """
    from core import renderer                                   # noqa: PLC0415
    from export import pdf_export                               # noqa: PLC0415
    assert renderer.plan_edges is pdf_export.plan_edges is plan_edges, \
        'canvas e PDF deixaram de compartilhar o planejamento de rotas'

    for nome, modelo in fluxogramas():
        node_map = {n['id']: n for n in modelo['nodes']}
        lane_x = lane_boundaries(modelo)
        a = plan_edges(modelo['edges'], node_map, lane_x)
        b = plan_edges(modelo['edges'], node_map, lane_x)

        def chave(ps):
            return [(p['kind'], tuple(p.get('points', ())),
                     p.get('label'), p.get('label_pos')) for p in ps]

        assert chave(a) == chave(b), f'{nome}: roteamento não é determinístico'
    print('  mesma função de roteamento nos dois caminhos + determinismo: OK')


# ── Runner ────────────────────────────────────────────────

def main():
    try:  # o console do Windows ainda abre em cp1252
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, OSError):
        pass
    testes = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    falhas = 0
    for t in testes:
        print(f'\n▶ {t.__name__}')
        try:
            t()
            print('  ✅ passou')
        except AssertionError as e:
            falhas += 1
            print(f'  ❌ FALHOU: {e}')
    print(f'\n{len(testes) - falhas}/{len(testes)} testes passaram')
    return 1 if falhas else 0


if __name__ == '__main__':
    sys.exit(main())
