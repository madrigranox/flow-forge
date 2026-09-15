"""
pdf_export.py — Exportação para PDF sem dependências externas.
Gera o binário PDF manualmente, desenhando shapes via operadores PDF.
Estilo: cópia visual de process map Visio (mesmo visual do canvas).
"""
import io
import math

from core.edges import plan_edges, lane_boundaries

WINE = '#7B2149'
BORDER_DARK = '#3f3f3f'
BORDER_LIGHT = '#a6a6a6'
TITLE_BG = '#f2f2f2'
FOOTER_RED = '#cc0000'
WARN_RED = '#b30000'


# Formatos de papel, em pontos PDF (1 pt = 1/72"). O desenho continua sendo
# feito em coordenadas de modelo; o encaixe na folha é uma transformação
# aplicada na hora de gravar — ver `PDFWriter.encaixar_em`.
PAPEIS = {
    'A4': (595.3, 841.9),
    'A3': (841.9, 1190.6),
    'A2': (1190.6, 1683.8),
    'Carta': (612.0, 792.0),
}
MARGEM_PAPEL = 28.3          # 1 cm de margem ao redor do desenho


def tamanho_papel(nome, orientacao='auto', desenho=None):
    """Dimensões da folha, já na orientação certa.

    `orientacao='auto'` escolhe retrato ou paisagem pelo formato do desenho —
    um fluxo alto pede retrato, um fluxo largo pede paisagem. Escolher errado
    desperdiça metade da folha e encolhe o texto à toa.
    """
    larg, alt = PAPEIS.get(nome, PAPEIS['A4'])
    if orientacao == 'paisagem':
        return max(larg, alt), min(larg, alt)
    if orientacao == 'retrato':
        return min(larg, alt), max(larg, alt)
    if desenho and desenho[0] > desenho[1]:      # desenho mais largo que alto
        return max(larg, alt), min(larg, alt)
    return min(larg, alt), max(larg, alt)


class PDFWriter:
    """Gerador de PDF minimalista (sem dependências)."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.stream_ops = []  # operações de desenho da página
        # Folha de saída. Nulo = a página tem o tamanho do desenho (como era).
        self._pagina = None
        self._encaixe = None

    def set_fill(self, hex_color):
        r, g, b = self._hex_to_rgb(hex_color)
        self.stream_ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg")

    def set_stroke(self, hex_color):
        r, g, b = self._hex_to_rgb(hex_color)
        self.stream_ops.append(f"{r:.3f} {g:.3f} {b:.3f} RG")

    def set_line_width(self, w):
        self.stream_ops.append(f"{w:.1f} w")

    def set_dash(self, on=6, off=4):
        self.stream_ops.append(f"[{on} {off}] 0 d")

    def clear_dash(self):
        self.stream_ops.append("[] 0 d")

    def rect(self, x, y, w, h, fill=True, stroke=True):
        """Desenha retângulo. Coordenadas em sistema PDF (Y invertido)."""
        py = self.height - y - h
        op = 'B' if fill and stroke else ('f' if fill else 'S')
        self.stream_ops.append(f"{x:.1f} {py:.1f} {w:.1f} {h:.1f} re {op}")

    def line(self, x1, y1, x2, y2):
        py1 = self.height - y1
        py2 = self.height - y2
        self.stream_ops.append(f"{x1:.1f} {py1:.1f} m {x2:.1f} {py2:.1f} l S")

    def polyline(self, points):
        """points = [(x1,y1), (x2,y2), ...]"""
        if len(points) < 2:
            return
        ops = []
        x0, y0 = points[0]
        ops.append(f"{x0:.1f} {self.height - y0:.1f} m")
        for x, y in points[1:]:
            ops.append(f"{x:.1f} {self.height - y:.1f} l")
        ops.append("S")
        self.stream_ops.append(" ".join(ops))

    def polygon(self, points, fill=True, stroke=True):
        if len(points) < 3:
            return
        ops = []
        x0, y0 = points[0]
        ops.append(f"{x0:.1f} {self.height - y0:.1f} m")
        for x, y in points[1:]:
            ops.append(f"{x:.1f} {self.height - y:.1f} l")
        ops.append("h")
        op = 'B' if fill and stroke else ('f' if fill else 'S')
        ops.append(op)
        self.stream_ops.append(" ".join(ops))

    def ellipse(self, cx, cy, rx, ry, fill=True, stroke=True):
        """Elipse com 4 curvas de Bézier."""
        k = 0.5522847498
        pcy = self.height - cy
        ops = []
        ops.append(f"{cx:.1f} {pcy + ry:.1f} m")
        ops.append(f"{cx + rx * k:.1f} {pcy + ry:.1f} {cx + rx:.1f} {pcy + ry * k:.1f} {cx + rx:.1f} {pcy:.1f} c")
        ops.append(f"{cx + rx:.1f} {pcy - ry * k:.1f} {cx + rx * k:.1f} {pcy - ry:.1f} {cx:.1f} {pcy - ry:.1f} c")
        ops.append(f"{cx - rx * k:.1f} {pcy - ry:.1f} {cx - rx:.1f} {pcy - ry * k:.1f} {cx - rx:.1f} {pcy:.1f} c")
        ops.append(f"{cx - rx:.1f} {pcy + ry * k:.1f} {cx - rx * k:.1f} {pcy + ry:.1f} {cx:.1f} {pcy + ry:.1f} c")
        op = 'B' if fill and stroke else ('f' if fill else 'S')
        ops.append(op)
        self.stream_ops.append(" ".join(ops))

    def circle(self, cx, cy, r, fill=True, stroke=True):
        self.ellipse(cx, cy, r, r, fill=fill, stroke=stroke)

    def rounded_rect(self, x, y, w, h, r, fill=True, stroke=True):
        """Retângulo arredondado (r = h/2 produz um 'stadium')."""
        r = min(r, w / 2, h / 2)
        k = 0.5522847498 * r
        x0, x1 = x, x + w
        y0 = self.height - y - h  # bottom (PDF space)
        y1 = self.height - y      # top (PDF space)
        ops = [
            f"{x0 + r:.1f} {y0:.1f} m",
            f"{x1 - r:.1f} {y0:.1f} l",
            f"{x1 - r + k:.1f} {y0:.1f} {x1:.1f} {y0 + r - k:.1f} {x1:.1f} {y0 + r:.1f} c",
            f"{x1:.1f} {y1 - r:.1f} l",
            f"{x1:.1f} {y1 - r + k:.1f} {x1 - r + k:.1f} {y1:.1f} {x1 - r:.1f} {y1:.1f} c",
            f"{x0 + r:.1f} {y1:.1f} l",
            f"{x0 + r - k:.1f} {y1:.1f} {x0:.1f} {y1 - r + k:.1f} {x0:.1f} {y1 - r:.1f} c",
            f"{x0:.1f} {y0 + r:.1f} l",
            f"{x0:.1f} {y0 + r - k:.1f} {x0 + r - k:.1f} {y0:.1f} {x0 + r:.1f} {y0:.1f} c",
            "h",
            'B' if fill and stroke else ('f' if fill else 'S'),
        ]
        self.stream_ops.append(" ".join(ops))

    def text(self, x, y, txt, size=10, bold=False):
        py = self.height - y
        # Escapar parênteses no texto
        safe = txt.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        font = '/F2' if bold else '/F1'
        self.stream_ops.append(f"BT {font} {size} Tf {x:.1f} {py:.1f} Td ({safe}) Tj ET")

    def _hex_to_rgb(self, h):
        h = h.lstrip('#')
        if len(h) == 3:
            h = h[0]*2 + h[1]*2 + h[2]*2
        if len(h) != 6 or not all(c in '0123456789abcdefABCDEF' for c in h):
            return 0.2, 0.2, 0.2  # fallback: cinza escuro
        r = int(h[0:2], 16) / 255
        g = int(h[2:4], 16) / 255
        b = int(h[4:6], 16) / 255
        return r, g, b

    def encaixar_em(self, pagina_w, pagina_h, margem=MARGEM_PAPEL):
        """Coloca o desenho inteiro numa folha de tamanho fixo.

        O desenho continua desenhado em coordenadas de modelo — o que muda é
        uma transformação aplicada no fim, que escala e centraliza tudo dentro
        da folha. Sem isso a página do PDF saía com o tamanho do diagrama
        (28 × 55 cm num fluxo real), que não corresponde a papel nenhum: a
        impressora reduzia sozinha ou fatiava em várias folhas.
        """
        util_w = max(1.0, pagina_w - 2 * margem)
        util_h = max(1.0, pagina_h - 2 * margem)
        escala = min(util_w / self.width, util_h / self.height, 1.0)
        tx = (pagina_w - self.width * escala) / 2
        ty = (pagina_h - self.height * escala) / 2
        self._pagina = (pagina_w, pagina_h)
        self._encaixe = (escala, tx, ty)
        return escala

    def save(self, filepath):
        """Gera e salva o arquivo PDF."""
        if self._encaixe:
            escala, tx, ty = self._encaixe
            # `cm` concatena a matriz; q/Q isolam para não vazar estado.
            self.stream_ops.insert(
                0, f"q {escala:.5f} 0 0 {escala:.5f} {tx:.2f} {ty:.2f} cm")
            self.stream_ops.append("Q")
        stream_content = "\n".join(self.stream_ops)
        # cp1252 = WinAnsiEncoding declarado nas fontes (cobre —, ", etc.)
        stream_bytes = stream_content.encode('cp1252', errors='replace')
        self.stream_ops.clear()  # Liberar memória imediatamente

        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (f"<< /Type /Page /Parent 2 0 R "
             f"/MediaBox [0 0 {(self._pagina or (self.width, self.height))[0]:.1f} "
             f"{(self._pagina or (self.width, self.height))[1]:.1f}] "
             f"/Contents 6 0 R "
             f"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> >>").encode(),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
            None,  # obj 6: stream (tratado abaixo)
        ]

        buf = io.BytesIO()
        try:
            buf.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
            offsets = []
            for i, obj in enumerate(objects, start=1):
                offsets.append(buf.tell())
                if obj is None:
                    buf.write(f"{i} 0 obj\n<< /Length {len(stream_bytes)} >>\nstream\n".encode())
                    buf.write(stream_bytes)
                    buf.write(b"\nendstream\nendobj\n")
                else:
                    buf.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")

            xref_offset = buf.tell()
            num_objs = len(objects) + 1
            buf.write(f"xref\n0 {num_objs}\n".encode())
            buf.write(b"0000000000 65535 f \n")
            for off in offsets:
                buf.write(f"{off:010d} 00000 n \n".encode())
            buf.write(f"trailer\n<< /Size {num_objs} /Root 1 0 R >>\n".encode())
            buf.write(f"startxref\n{xref_offset}\n%%EOF\n".encode())

            with open(filepath, 'wb') as f:
                f.write(buf.getvalue())
        finally:
            buf.close()


# ── Helpers de texto ──────────────────────────────────────

def _wrap(txt, max_chars):
    """Quebra texto em linhas de no máximo max_chars caracteres (por palavras)."""
    words = txt.split()
    lines, cur = [], ''
    for w in words:
        cand = (cur + ' ' + w).strip()
        if len(cand) <= max_chars:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or ['']


def _text_center(pdf, cx, cy, txt, size, max_w, color='#000000', bold=False):
    """Texto centralizado (multi-linha) em (cx, cy) — coords do canvas."""
    max_chars = max(4, int(max_w / (size * 0.52)))
    lines = _wrap(txt, max_chars)
    lh = size * 1.3
    y0 = cy - (len(lines) - 1) * lh / 2 + size * 0.35
    pdf.set_fill(color)
    for i, ln in enumerate(lines):
        x = cx - len(ln) * size * 0.26
        pdf.text(x, y0 + i * lh, ln, size=size, bold=bold)


# ── Exportação ────────────────────────────────────────────

# Carimbos de ciclo de vida no bloco de título
STAMP_DRAFT = 'RASCUNHO'
STAMP_APPROVED = 'APROVADO'
STAMP_COLORS = {STAMP_DRAFT: '#b30000', STAMP_APPROVED: '#107c10'}


def export_pdf(model, filepath, stamp=STAMP_DRAFT, stamp_ref='',
               papel=None, orientacao='auto', margem=MARGEM_PAPEL):
    """Exporta o fluxograma para PDF.

    `stamp` carimba o estado do ciclo de vida no bloco de título — o PDF é o
    veículo em que o documento circula, e sem essa marca não há como quem
    recebe distinguir um rascunho de uma versão aprovada. O default é
    RASCUNHO: exportar nunca produz um artefato que se diz aprovado; só o
    caminho de publicação, depois do gate, pede APROVADO.

    `stamp_ref` é a referência de aprovação (quem/quando), exibida ao lado.

    `papel` ('A4', 'A3', 'A2', 'Carta') encaixa o desenho inteiro numa folha
    desse tamanho, reduzindo o necessário. Sem ele, a página sai do tamanho do
    diagrama — o que serve para ler na tela, mas não para imprimir.

    Nenhuma outra região da página muda — moldura, banner, lanes, notas,
    rodapé e subprocessos ficam onde estavam.
    """
    if '_computed' not in model:
        raise ValueError("Modelo sem layout computado. Execute compute_layout() primeiro.")
    comp = model['_computed']
    tw = comp['total_width']
    th = comp['total_height']
    styles = model['styles']

    pdf = PDFWriter(tw, th)
    margins = model['meta']['margins']
    lane_pos = comp['lane_positions']
    header_h = comp['header_height']
    main_max_y = comp['main_max_y']
    lanes_right = comp['lanes_right']
    content_right = comp['content_right']
    notes = comp.get('notes', [])
    top = margins['top']

    # ── Moldura externa ────────────────────────────────────
    pdf.set_stroke(BORDER_LIGHT)
    pdf.set_line_width(0.8)
    pdf.rect(margins['left'] - 10, top - 66,
             content_right - margins['left'] + 20, th - 14 - (top - 66),
             fill=False)

    # ── Bloco de título ────────────────────────────────────
    pdf.set_fill(TITLE_BG)
    pdf.set_stroke(BORDER_DARK)
    pdf.set_line_width(0.8)
    pdf.rect(margins['left'], top - 56, content_right - margins['left'], 28)
    doc = model.get('docCode', '')
    title_txt = ((f"{doc} - " if doc else '') + model['title']).upper()
    pdf.set_fill('#000000')
    pdf.text(margins['left'] + 10, top - 56 + 18, title_txt, size=9, bold=True)

    # Carimbo de estado, encostado à direita dentro do mesmo retângulo
    if stamp:
        marca = str(stamp).upper()
        cor = STAMP_COLORS.get(marca, '#b30000')
        largura_marca = len(marca) * 9 * 0.62
        x_marca = content_right - 10 - largura_marca
        pdf.set_fill(cor)
        pdf.text(x_marca, top - 56 + 18, marca, size=9, bold=True)
        if stamp_ref:
            ref = str(stamp_ref)
            pdf.set_fill('#4d4d4d')
            pdf.text(x_marca - len(ref) * 6 * 0.55 - 10, top - 56 + 18,
                     ref, size=6)

    # ── Banner do departamento ─────────────────────────────
    dep = model.get('department', '')
    if dep and not comp.get('dept_bands'):
        lanes_w = lanes_right - margins['left']
        bw = min(560, lanes_w)
        bx = margins['left'] + lanes_w / 2
        pdf.set_fill(WINE)
        pdf.set_stroke(WINE)
        pdf.rect(bx - bw / 2, top - 28, bw, 28)
        _text_center(pdf, bx, top - 13, dep.upper(), 10, bw - 20,
                     color='#ffffff', bold=True)

    # ── Lanes do fluxo principal ───────────────────────────
    _pdf_draw_lanes(pdf, model['lanes'], lane_pos, top, main_max_y, header_h,
                    bands=comp.get('dept_bands'),
                    band_h=comp.get('dept_band_height', 0))

    # ── Edges primeiro (ficam atrás dos nós) ───────────────
    node_map = {n['id']: n for n in model['nodes']}
    lane_x = lane_boundaries(model)
    _pdf_draw_edges(pdf, plan_edges(model['edges'], node_map, lane_x), styles)

    # ── Nós por cima (exceto annotations), com sufixo (n) ──
    suffix = {n['ref_node']['id']: n['number'] for n in notes if n.get('ref_node')}
    for node in model['nodes']:
        if node['type'] == 'annotation':
            continue
        if node['id'] in suffix:
            node = {**node, 'label': f"{node['label']} ({suffix[node['id']]})"}
        _pdf_draw_node(pdf, node, styles)

    # ── Coluna de COMENTÁRIOS ──────────────────────────────
    if notes:
        nx = comp['notes_col_x']
        nw = comp['notes_col_width']

        pdf.set_fill('#ffffff')
        pdf.set_stroke(BORDER_LIGHT)
        pdf.set_line_width(0.8)
        pdf.rect(nx, top, nw, main_max_y - top)

        pdf.set_stroke(BORDER_DARK)
        pdf.rect(nx, top, nw, header_h)
        _text_center(pdf, nx + nw / 2, top + header_h / 2, 'COMENTÁRIOS',
                     10, nw - 20, color='#000000', bold=True)

        cy = top + header_h + 24
        max_chars = max(20, int((nw - 32) / (8 * 0.52)))
        pdf.set_fill('#000000')
        for note in notes:
            ref = note.get('ref_node')
            if ref and ref.get('y', 0) > cy:
                cy = ref['y']
            lines = _wrap(f"{note['number']}. {note['text']}", max_chars)
            for i, ln in enumerate(lines):
                pdf.text(nx + 16, cy + 8 + i * 11, ln, size=8)
            cy += len(lines) * 11 + 18

    # ── Rodapé ─────────────────────────────────────────────
    pdf.set_fill(FOOTER_RED)
    pdf.text(margins['left'], th - 30, 'A PRINTED VERSION OF THIS', size=7, bold=True)
    pdf.text(margins['left'], th - 20, 'DOCUMENT IS UNCONTROLLED', size=7, bold=True)

    # ── Subprocessos ───────────────────────────────────────
    for sp in model['subprocesses']:
        section_y = sp.get('section_y', main_max_y)
        lanes_y = sp.get('lanes_y', section_y + 40)
        sp_bottom = section_y + sp.get('height', 200)

        # Separador
        pdf.set_stroke(BORDER_LIGHT)
        pdf.set_line_width(0.8)
        pdf.set_dash(8, 4)
        pdf.line(margins['left'], section_y - 10, content_right, section_y - 10)
        pdf.clear_dash()

        # Título da seção
        pdf.set_fill(WINE)
        pdf.text(margins['left'] + 10, section_y + 18,
                 f"INSTRUÇÃO DE TRABALHO: {sp['label'].upper()}", size=9, bold=True)

        # Lanes repetidas
        _pdf_draw_lanes(pdf, model['lanes'], lane_pos, lanes_y, sp_bottom,
                        header_h, bands=comp.get('dept_bands'),
                        band_h=comp.get('dept_band_height', 0))

        # Edges primeiro, nós por cima
        sp_node_map = {n['id']: n for n in sp['nodes']}
        _pdf_draw_edges(pdf, plan_edges(sp['edges'], sp_node_map, lane_x), styles)
        for node in sp['nodes']:
            _pdf_draw_node(pdf, node, styles)

    if papel:
        pw, ph = tamanho_papel(papel, orientacao, desenho=(tw, th))
        pdf.encaixar_em(pw, ph, margem)
    pdf.save(filepath)


def _pdf_draw_lanes(pdf, lanes, lane_pos, top_y, bottom_y, header_h,
                    bands=None, band_h=0):
    """Mesma composição do canvas: faixa de área por cima, ator embaixo.

    O PDF é o documento que circula — se ele não disser de que área é cada
    coluna, quem recebe não tem como saber.
    """
    for lane in lanes:
        lp = lane_pos[lane['id']]
        lx, lw = lp['x'], lp['width']

        pdf.set_fill(lane['style']['fill'])
        pdf.set_stroke(BORDER_LIGHT)
        pdf.set_line_width(0.8)
        pdf.rect(lx, top_y, lw, bottom_y - top_y)

        pdf.set_fill('#ffffff')
        pdf.set_stroke(BORDER_DARK)
        pdf.rect(lx, top_y + band_h, lw, header_h - band_h)
        _text_center(pdf, lx + lw / 2,
                     top_y + band_h + (header_h - band_h) / 2,
                     lane['label'].upper(), 10, lw - 20,
                     color='#000000', bold=True)

    for band in (bands or []):
        area = (band.get('department') or '').strip()
        bx, bw = band['x'], band['width']
        pdf.set_fill(WINE if area else '#f2f2f2')
        pdf.set_stroke(WINE if area else BORDER_LIGHT)
        pdf.set_line_width(0.8)
        pdf.rect(bx, top_y, bw, band_h)
        if area:
            _text_center(pdf, bx + bw / 2, top_y + band_h / 2,
                         area.upper(), 8, bw - 10, color='#ffffff', bold=True)


def _pdf_draw_node(pdf, node, styles):
    """Desenha um nó no PDF com as formas do padrão Visio."""
    x, y = node['x'], node['y']
    w, h = node['size']['w'], node['size']['h']
    ntype = node['type']
    ns = styles['nodeTypes'].get(ntype, styles['nodeTypes']['task'])
    cx, cy = x + w / 2, y + h / 2

    pdf.set_fill(ns['fill'])
    pdf.set_stroke(ns['stroke'])
    pdf.set_line_width(1)

    if ntype == 'start':
        # Entrada: elipse branca
        pdf.ellipse(cx, cy, w / 2, h / 2)
        _text_center(pdf, cx, cy, node['label'], 8, w - 24)

    elif ntype == 'end':
        # Produto Principal: tarja preta, texto branco em negrito
        pdf.rounded_rect(x, y, w, h, h / 2)
        _text_center(pdf, cx, cy, node['label'], 8, w - 24,
                     color='#ffffff', bold=True)

    elif ntype == 'decision':
        # Caixa de Decisão: hexágono
        ind = min(w * 0.18, h * 0.6)
        pdf.polygon([(x + ind, y), (x + w - ind, y), (x + w, cy),
                     (x + w - ind, y + h), (x + ind, y + h), (x, cy)])
        _text_center(pdf, cx, cy, node['label'], 8, w - 50)

    elif ntype == 'parallel':
        # Barra de sincronização (split/join de fluxo paralelo)
        pdf.rect(x, y, w, h)
        if node['label']:
            _text_center(pdf, cx, y - 8, node['label'], 7, w * 2, color='#595959')

    elif ntype == 'subprocess':
        # Tarefa com Instrução de Trabalho: tracejado vermelho + triângulo de alerta
        pdf.set_line_width(1.5)
        pdf.set_dash(7, 4)
        pdf.rect(x, y, w, h)
        pdf.clear_dash()
        _text_center(pdf, cx, cy, node['label'], 8, w - 20)

        tx, ty = x + w - 14, y + h + 4  # centro do triângulo
        half = 10
        pdf.set_fill('#ffffff')
        pdf.set_stroke(WARN_RED)
        pdf.set_line_width(1.5)
        pdf.polygon([(tx, ty - half), (tx + half, ty + half), (tx - half, ty + half)])
        pdf.set_fill(WARN_RED)
        pdf.text(tx - 1.5, ty + 7, '!', size=9, bold=True)

    else:  # task
        pdf.rect(x, y, w, h)
        _text_center(pdf, cx, cy, node['label'], 8, w - 16)

    # Engrenagem em tarefas automáticas (props.automatic = true)
    if node.get('props', {}).get('automatic'):
        _pdf_draw_gear(pdf, x + w - 2, y + 8)


def _pdf_draw_gear(pdf, cx, cy, r=8, color='#595959'):
    """Engrenagem — marca de tarefa automática (mesma forma do canvas)."""
    teeth = 8
    pts = []
    for i in range(teeth * 2):
        ang = math.pi * i / teeth - math.pi / 2
        rad = r if i % 2 == 0 else r * 0.68
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    pdf.set_fill(color)
    pdf.set_stroke(color)
    pdf.set_line_width(1)
    pdf.polygon(pts)
    pdf.set_fill('#ffffff')
    pdf.circle(cx, cy, r * 0.32, fill=True, stroke=False)


def _pdf_draw_edges(pdf, prims, styles):
    """Desenha as primitivas planejadas (mesmo roteamento do canvas)."""
    etypes = styles['edgeTypes']

    # 1) Linhas e setas
    for p in prims:
        if p['kind'] != 'line':
            continue
        es = etypes.get(p['etype'], etypes.get('flow', {}))
        stroke = p['style'].get('color', es.get('stroke', '#595959'))
        is_dash = p['style'].get('dash', es.get('dash', False))

        pdf.set_stroke(stroke)
        pdf.set_line_width(1)
        if is_dash:
            pdf.set_dash(6, 4)
        pts = p['points']
        points = [(pts[i], pts[i + 1]) for i in range(0, len(pts), 2)]
        pdf.polyline(points)
        if is_dash:
            pdf.clear_dash()

        if p['arrow'] and es.get('arrow', 'standard') != 'none' and len(points) >= 2:
            x2, y2 = points[-1]
            x1, y1 = points[-2]
            angle = math.atan2(y2 - y1, x2 - x1)
            size = 7
            a1 = angle + math.pi * 0.85
            a2 = angle - math.pi * 0.85
            pdf.set_fill(stroke)
            pdf.polygon([(x2, y2),
                         (x2 + size * math.cos(a1), y2 + size * math.sin(a1)),
                         (x2 + size * math.cos(a2), y2 + size * math.sin(a2))])

    # 2) Rótulos de junção ("E"/"Ou") — caixinha branca sobre o conector
    for p in prims:
        if p['kind'] != 'jlabel':
            continue
        bw = len(p['text']) * 8 * 0.6 + 10
        bh = 13
        pdf.set_fill('#ffffff')
        pdf.set_stroke('#595959')
        pdf.set_line_width(0.8)
        pdf.rect(p['x'] - bw / 2, p['y'] - bh / 2, bw, bh)
        _text_center(pdf, p['x'], p['y'], p['text'], 8, bw, bold=True)

    # 3) Rótulos das edges (Sim/Não...) com fundo branco sobre a linha
    for p in prims:
        if p['kind'] != 'line' or not p.get('label') or not p.get('label_pos'):
            continue
        lx, ly = p['label_pos']
        bw = len(p['label']) * 7 * 0.55 + 6
        bh = 11
        pdf.set_fill('#ffffff')
        pdf.rect(lx - bw / 2, ly - bh / 2, bw, bh, fill=True, stroke=False)
        _text_center(pdf, lx, ly, p['label'], 7, bw)
