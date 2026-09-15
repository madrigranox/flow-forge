"""
shapes.py — Funções de desenho para cada tipo de nó no tkinter.Canvas.
Estilo: cópia visual de process map Visio (formas da legenda do padrão).
"""
import math

FONT = 'Arial'
TEXT_COLOR = '#000000'
WARN_RED = '#b30000'
GEAR_GRAY = '#595959'


def _rounded_rect_points(x, y, w, h, r=10):
    """Gera pontos para um retângulo arredondado (usado com create_polygon smooth)."""
    return [
        x + r, y,
        x + w - r, y,
        x + w, y,
        x + w, y + r,
        x + w, y + h - r,
        x + w, y + h,
        x + w - r, y + h,
        x + r, y + h,
        x, y + h,
        x, y + h - r,
        x, y + r,
        x, y,
        x + r, y,
    ]


def draw_rounded_rect(canvas, x, y, w, h, radius=10, **kw):
    """Desenha retângulo arredondado."""
    pts = _rounded_rect_points(x, y, w, h, radius)
    return canvas.create_polygon(pts, smooth=True, **kw)


def draw_stadium(canvas, x, y, w, h, **kw):
    """Desenha 'stadium' (retângulo com pontas semicirculares) — produtos no padrão Visio."""
    return draw_rounded_rect(canvas, x, y, w, h, radius=h / 2, **kw)


def draw_hexagon(canvas, x, y, w, h, **kw):
    """Desenha hexágono — Caixa de Decisão no padrão Visio."""
    ind = min(w * 0.18, h * 0.6)
    cy = y + h / 2
    pts = [x + ind, y, x + w - ind, y, x + w, cy,
           x + w - ind, y + h, x + ind, y + h, x, cy]
    return canvas.create_polygon(pts, **kw)


def draw_diamond(canvas, x, y, w, h, **kw):
    """Desenha losango (mantido para compatibilidade)."""
    cx, cy = x + w / 2, y + h / 2
    pts = [cx, y, x + w, cy, cx, y + h, x, cy]
    return canvas.create_polygon(pts, **kw)


def draw_circle(canvas, cx, cy, r, **kw):
    """Desenha círculo."""
    return canvas.create_oval(cx - r, cy - r, cx + r, cy + r, **kw)


def draw_warning_triangle(canvas, cx, cy, size=20, tags=()):
    """Triângulo de alerta com '!' — marca de Instrução de Trabalho no padrão."""
    half = size / 2
    pts = [cx, cy - half, cx + half, cy + half, cx - half, cy + half]
    items = [
        canvas.create_polygon(pts, fill='#ffffff', outline=WARN_RED, width=2, tags=tags),
        canvas.create_text(cx, cy + 3, text='!', font=(FONT, 9, 'bold'),
                           fill=WARN_RED, tags=tags),
    ]
    return items


def draw_gear(canvas, cx, cy, r=8, color=GEAR_GRAY, tags=()):
    """Engrenagem — marca de tarefa automática no padrão."""
    teeth = 8
    pts = []
    for i in range(teeth * 2):
        ang = math.pi * i / teeth - math.pi / 2
        rad = r if i % 2 == 0 else r * 0.68
        pts.extend([cx + rad * math.cos(ang), cy + rad * math.sin(ang)])
    return [
        canvas.create_polygon(pts, fill=color, outline=color, tags=tags),
        canvas.create_oval(cx - r * 0.32, cy - r * 0.32,
                           cx + r * 0.32, cy + r * 0.32,
                           fill='#ffffff', outline='#ffffff', tags=tags),
    ]


def draw_note(canvas, x, y, w, h, fold=14, **kw):
    """Desenha forma de nota/anotação com canto dobrado."""
    outline_c = kw.pop('outline', '#7f7f7f')
    pts = [x, y, x + w - fold, y, x + w, y + fold, x + w, y + h, x, y + h]
    body = canvas.create_polygon(pts, outline=outline_c, **kw)
    fold_line = canvas.create_line(
        x + w - fold, y, x + w - fold, y + fold, x + w, y + fold,
        fill=outline_c, width=1
    )
    return [body, fold_line]


def draw_node(canvas, node, style, tags=None):
    """Desenha um nó completo (shape + label). Retorna lista de item IDs."""
    x, y = node['x'], node['y']
    w, h = node['size']['w'], node['size']['h']
    label = node['label']
    ntype = node['type']
    fill = style.get('fill', '#ffffff')
    stroke = style.get('stroke', '#3f3f3f')

    tag_list = list(tags or []) + [f"node_{node['id']}", 'node']
    tg = tuple(tag_list)
    items = []
    cx, cy = x + w / 2, y + h / 2

    if ntype == 'start':
        # Entrada: elipse branca com borda fina
        items.append(canvas.create_oval(x, y, x + w, y + h,
                                        fill=fill, outline=stroke, width=1, tags=tg))
        items.append(canvas.create_text(cx, cy, text=label, font=(FONT, 8),
                                        fill=TEXT_COLOR, width=w - 24, justify='center', tags=tg))

    elif ntype == 'end':
        # Produto Principal: tarja preta com texto branco em negrito
        items.append(draw_stadium(canvas, x, y, w, h,
                                  fill=fill, outline=stroke, width=1, tags=tg))
        items.append(canvas.create_text(cx, cy, text=label, font=(FONT, 8, 'bold'),
                                        fill='#ffffff', width=w - 24, justify='center', tags=tg))

    elif ntype == 'decision':
        # Caixa de Decisão: hexágono
        items.append(draw_hexagon(canvas, x, y, w, h,
                                  fill=fill, outline=stroke, width=1, tags=tg))
        items.append(canvas.create_text(cx, cy, text=label, font=(FONT, 8),
                                        fill=TEXT_COLOR, width=w - 50, justify='center', tags=tg))

    elif ntype == 'annotation':
        note_items = draw_note(canvas, x, y, w, h, fill=fill, outline=stroke,
                               width=1, dash=(4, 2), tags=tg)
        items.extend(note_items)
        items.append(canvas.create_text(x + 10, y + h / 2, text=label, font=(FONT, 8),
                                        fill='#595959', anchor='w', width=w - 30, tags=tg))

    elif ntype == 'parallel':
        # Barra de sincronização (split/join de fluxo paralelo)
        items.append(canvas.create_rectangle(x, y, x + w, y + h,
                                             fill=fill, outline=stroke, width=1, tags=tg))
        if label:
            items.append(canvas.create_text(cx, y - 9, text=label, font=(FONT, 7),
                                            fill='#595959', tags=tg))

    elif ntype == 'subprocess':
        # Tarefa com Instrução de Trabalho: retângulo tracejado vermelho + triângulo de alerta
        items.append(canvas.create_rectangle(x, y, x + w, y + h,
                                             fill=fill, outline=stroke, width=2,
                                             dash=(7, 4), tags=tg))
        items.append(canvas.create_text(cx, cy, text=label, font=(FONT, 8),
                                        fill=TEXT_COLOR, width=w - 20, justify='center', tags=tg))
        items.extend(draw_warning_triangle(canvas, x + w - 14, y + h + 4, size=20, tags=tg))

    else:  # task
        # Tarefa: retângulo de cantos retos, borda fina escura
        items.append(canvas.create_rectangle(x, y, x + w, y + h,
                                             fill=fill, outline=stroke, width=1, tags=tg))
        items.append(canvas.create_text(cx, cy, text=label, font=(FONT, 8),
                                        fill=TEXT_COLOR, width=w - 16, justify='center', tags=tg))

    # Engrenagem em tarefas automáticas (props.automatic = true)
    if node.get('props', {}).get('automatic'):
        items.extend(draw_gear(canvas, x + w - 2, y + 8, r=8, tags=tg))
    return items
