"""
renderer.py — Orquestrador de renderização no tkinter.Canvas.
Estilo: cópia visual de process map Visio — bloco de título, banner do
departamento, lanes brancas adjacentes e coluna lateral de COMENTÁRIOS.
"""
from core.shapes import draw_node, FONT
from core.edges import plan_edges, draw_edges, lane_boundaries

WINE = '#7B2149'          # banner do departamento (vinho corporativo)
BORDER_DARK = '#3f3f3f'   # bordas de células/título
BORDER_LIGHT = '#a6a6a6'  # bordas das lanes
TITLE_BG = '#f2f2f2'      # fundo da faixa de título
FOOTER_RED = '#cc0000'


def render(canvas, model):
    """Renderiza o fluxograma completo no canvas."""
    canvas.delete('all')
    canvas.update_idletasks()  # Processar eventos pendentes para liberar memória

    comp = model['_computed']
    lane_pos = comp['lane_positions']
    total_w = comp['total_width']
    total_h = comp['total_height']
    header_h = comp['header_height']
    main_max_y = comp['main_max_y']
    lanes_right = comp['lanes_right']
    content_right = comp['content_right']
    margins = model['meta']['margins']
    styles = model['styles']
    lanes = model['lanes']
    notes = comp.get('notes', [])
    top = margins['top']

    canvas.configure(scrollregion=(0, 0, total_w, total_h))

    # ── 1. Fundo branco ────────────────────────────────────
    canvas.create_rectangle(0, 0, total_w, total_h, fill='#ffffff', outline='')

    # ── 2. Moldura externa do documento ────────────────────
    canvas.create_rectangle(margins['left'] - 10, top - 66,
                            content_right + 10, total_h - 14,
                            outline=BORDER_LIGHT, width=1, tags=('frame',))

    # ── 3. Bloco de título (código do documento + nome) ────
    strip_y0, strip_y1 = top - 56, top - 28
    canvas.create_rectangle(margins['left'], strip_y0, content_right, strip_y1,
                            fill=TITLE_BG, outline=BORDER_DARK, width=1, tags=('title',))
    doc = model.get('docCode', '')
    title_txt = (f"{doc} - " if doc else '') + model['title']
    canvas.create_text(margins['left'] + 10, (strip_y0 + strip_y1) / 2,
                       text=title_txt.upper(), font=(FONT, 9, 'bold'),
                       fill='#000000', anchor='w', tags=('title',))

    # ── 4. Banner do departamento (faixa vinho) ────────────
    dep = model.get('department', '')
    if dep and not comp.get('dept_bands'):
        lanes_w = lanes_right - margins['left']
        bw = min(560, lanes_w)
        bx = margins['left'] + lanes_w / 2
        canvas.create_rectangle(bx - bw / 2, top - 28, bx + bw / 2, top,
                                fill=WINE, outline=WINE, tags=('banner',))
        canvas.create_text(bx, top - 14, text=dep.upper(),
                           font=(FONT, 10, 'bold'), fill='#ffffff', tags=('banner',))

    # ── 5. Lanes do fluxo principal ────────────────────────
    _draw_lanes(canvas, lanes, lane_pos, top, main_max_y, header_h,
                bands=comp.get('dept_bands'),
                band_h=comp.get('dept_band_height', 0))

    # ── 6. Edges do fluxo principal (atrás dos nós) ────────
    node_map = {n['id']: n for n in model['nodes']}
    lane_x = lane_boundaries(model)
    prims = plan_edges(model['edges'], node_map, lane_x)
    draw_edges(canvas, prims, styles, tags=['main_edge'])

    # ── 7. Nós do fluxo principal (exceto annotations) ─────
    # Nós referenciados por comentários ganham sufixo "(n)" como no padrão
    suffix = {n['ref_node']['id']: n['number'] for n in notes if n.get('ref_node')}
    for node in model['nodes']:
        if node['type'] == 'annotation':
            continue  # Anotações vão para a coluna COMENTÁRIOS
        ntype = node['type']
        node_style = styles['nodeTypes'].get(ntype, styles['nodeTypes'].get('task', {}))
        if node['id'] in suffix:
            node = {**node, 'label': f"{node['label']} ({suffix[node['id']]})"}
        draw_node(canvas, node, node_style)

    # ── 8. Coluna lateral de COMENTÁRIOS ───────────────────
    if notes:
        _draw_comments_column(canvas, comp, margins, main_max_y)

    # ── 9. Rodapé (aviso de cópia impressa) ────────────────
    canvas.create_text(margins['left'], total_h - 26,
                       text='A PRINTED VERSION OF THIS\nDOCUMENT IS UNCONTROLLED',
                       font=(FONT, 7, 'bold'), fill=FOOTER_RED,
                       anchor='w', justify='left', tags=('footer',))

    # ── 10. Seção de subprocessos ──────────────────────────
    if model['subprocesses']:
        for sp in model['subprocesses']:
            _render_subprocess_section(canvas, sp, lanes, lane_pos, header_h,
                                       margins, styles, content_right,
                                       bands=comp.get('dept_bands'),
                                       band_h=comp.get('dept_band_height', 0))


def _draw_lanes(canvas, lanes, lane_pos, top_y, bottom_y, header_h,
                bands=None, band_h=0):
    """Colunas das lanes: faixa de departamento, nome do ator e corpo branco.

    A faixa de departamento fica ACIMA do nome do ator e cobre todas as colunas
    vizinhas da mesma área. Num fluxo com 15 atores em 3 áreas, é ela que diz,
    de relance, de quem é cada ação — o nome do cargo sozinho não diz.
    """
    for lane in lanes:
        lp = lane_pos[lane['id']]
        lx = lp['x']
        lw = lp['width']
        fill = lane['style']['fill']

        canvas.create_rectangle(lx, top_y, lx + lw, bottom_y,
                                fill=fill, outline=BORDER_LIGHT, width=1,
                                tags=('lane',))

        canvas.create_rectangle(lx, top_y + band_h, lx + lw, top_y + header_h,
                                fill='#ffffff', outline=BORDER_DARK, width=1,
                                tags=('lane_header',))
        canvas.create_text(lx + lw / 2, top_y + band_h + (header_h - band_h) / 2,
                           text=lane['label'].upper(), font=(FONT, 10, 'bold'),
                           fill='#000000', width=lw - 12, tags=('lane_header',))

    for band in (bands or []):
        area = (band.get('department') or '').strip()
        bx, bw = band['x'], band['width']
        canvas.create_rectangle(bx, top_y, bx + bw, top_y + band_h,
                                fill=WINE if area else '#f2f2f2',
                                outline=WINE if area else BORDER_LIGHT,
                                width=1, tags=('dept_band',))
        if area:
            canvas.create_text(bx + bw / 2, top_y + band_h / 2,
                               text=area.upper(), font=(FONT, 8, 'bold'),
                               fill='#ffffff', width=bw - 10,
                               tags=('dept_band',))


def _draw_comments_column(canvas, comp, margins, main_max_y):
    """Desenha a coluna lateral de COMENTÁRIOS (texto numerado, alinhado aos nós)."""
    notes = comp['notes']
    nx = comp['notes_col_x']
    nw = comp['notes_col_width']
    header_h = comp['header_height']
    top_y = margins['top']

    # Corpo da coluna (branco, mesma tabela das lanes)
    canvas.create_rectangle(nx, top_y, nx + nw, main_max_y,
                            fill='#ffffff', outline=BORDER_LIGHT, width=1,
                            tags=('notes_col',))

    # Header no mesmo estilo das lanes
    canvas.create_rectangle(nx, top_y, nx + nw, top_y + header_h,
                            fill='#ffffff', outline=BORDER_DARK, width=1,
                            tags=('notes_header',))
    canvas.create_text(nx + nw / 2, top_y + header_h / 2,
                       text='COMENTÁRIOS', font=(FONT, 10, 'bold'),
                       fill='#000000', tags=('notes_header',))

    # Cada comentário: "n. texto", alinhado verticalmente ao nó referenciado
    cy = top_y + header_h + 24
    for note in notes:
        ref = note.get('ref_node')
        if ref and ref.get('y', 0) > cy:
            cy = ref['y']

        item = canvas.create_text(nx + 16, cy,
                                  text=f"{note['number']}. {note['text']}",
                                  font=(FONT, 8), fill='#000000',
                                  anchor='nw', width=nw - 32,
                                  tags=('note_item', f"note_ann_{note['ann_id']}"))
        bbox = canvas.bbox(item)
        cy = (bbox[3] if bbox else cy + 20) + 18


def _render_subprocess_section(canvas, sp, lanes, lane_pos, header_h, margins,
                               styles, content_right, bands=None, band_h=0):
    """Renderiza seção de subprocesso com as mesmas lanes."""
    section_y = sp['section_y']
    lanes_y = sp['lanes_y']
    sp_bottom = section_y + sp['height']

    # Separador
    canvas.create_line(margins['left'], section_y - 10, content_right, section_y - 10,
                       fill=BORDER_LIGHT, width=1, dash=(10, 5), tags=('separator',))

    # Título da seção
    canvas.create_text(margins['left'] + 10, section_y + 15,
                       text=f"INSTRUÇÃO DE TRABALHO: {sp['label'].upper()}",
                       font=(FONT, 9, 'bold'), fill=WINE,
                       anchor='w', tags=('sp_title',))

    # Lanes repetidas
    _draw_lanes(canvas, lanes, lane_pos, lanes_y, sp_bottom, header_h,
                bands=bands, band_h=band_h)

    # Edges internos
    sp_node_map = {n['id']: n for n in sp['nodes']}
    sp_lane_x = [v for lp in lane_pos.values() for v in (lp['x'], lp['x'] + lp['width'])]
    sp_prims = plan_edges(sp['edges'], sp_node_map, sorted(set(sp_lane_x)))
    draw_edges(canvas, sp_prims, styles, tags=['sp_edge'])

    # Nós internos
    for node in sp['nodes']:
        ntype = node.get('type', 'task')
        ns = styles['nodeTypes'].get(ntype, styles['nodeTypes'].get('task', {}))
        draw_node(canvas, node, ns, tags=['sp_node'])
