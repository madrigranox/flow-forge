"""
editor.py — Modo edição sobre o Canvas.

Recursos:
- Drag-and-drop de nós com reorganização automática dos conectores em tempo real
- Duplo clique para editar textos inline (nós, headers de lane e comentários)
- Clique direito: menu de contexto — adicionar/excluir nós, conectar nós,
  editar/excluir conexões, marcar tarefa automática, adicionar comentário
- Copiar/colar e excluir pelo teclado (Ctrl+C / Ctrl+V / Delete)
- Posições arrastadas ficam "pinned" e persistem no JSON

Dois princípios estruturam este módulo:

1. **O modelo é a única fonte de coordenadas.** Toda entrada de mouse passa por
   `Viewport.event_to_model()` antes de encostar no modelo, e todo desenho
   feito aqui volta para a vista multiplicando pela escala. Sem isso, com zoom
   diferente de 100% o clique era resolvido contra um sistema de coordenadas
   que não é o que está na tela — e arrastar gravava a posição errada no
   arquivo, marcada como posição manual.

2. **Toda mutação passa por `_commit()`.** É lá que o histórico é registrado e
   a consistência reavaliada, para o Ctrl+Z significar a mesma coisa venha a
   edição de onde vier e para o erro de modelagem aparecer quando é cometido.
"""
import copy
import tkinter as tk
from tkinter import ttk

from core.edges import plan_edges, draw_edges, find_edge_at, lane_boundaries
from core.hittest import (resolve_target, find_node_at, find_annotation_at,
                          find_lane_header_at, node_outline,
                          find_subprocess_node_at)
from core.shapes import FONT
from core.parser import DEFAULT_NODE_SIZES
from core import catalogo as cat
from core.layout import lane_x_positions
from core.viewport import Viewport

# Tipos disponíveis no menu "Adicionar" e seus rótulos iniciais
NEW_NODE_TYPES = [
    ('task',       '▭  Tarefa',                 'Nova tarefa'),
    ('decision',   '⬡  Decisão',                'Nova decisão?'),
    ('start',      '⬭  Início',                 'Início'),
    ('end',        '▬  Fim (produto)',          'Fim'),
    ('subprocess', '⚠  Instrução de Trabalho',  'Nova instrução de trabalho'),
    ('parallel',   '▬  Barra de paralelismo',   ''),
]

PASTE_OFFSET = 30  # deslocamento do nó colado em relação ao original


class Editor:
    """Gerencia interação de edição (seleção, drag-and-drop, edição de texto)."""

    def __init__(self, canvas, model, on_model_change=None, on_status=None,
                 on_tool_done=None, viewport=None, on_selection_change=None,
                 catalogo=None):
        self.canvas = canvas
        self.model = model
        self.on_model_change = on_model_change
        self.on_status = on_status
        self.on_tool_done = on_tool_done  # avisa a paleta que a ferramenta acabou
        self.on_selection_change = on_selection_change  # avisa o painel lateral
        # Catálogo corporativo: o cabeçalho da coluna passa a ESCOLHER dele, em
        # vez de aceitar texto livre. Sem isso o canvas era uma porta lateral por
        # onde qualquer grafia entrava, furando a padronização que o catálogo
        # existe para garantir.
        self.catalogo = catalogo or {'departamentos': []}
        self.viewport = viewport or Viewport()
        self.active = False
        self.selected_node = None
        self.drag_data = {'x': 0, 'y': 0}
        self._dragged = False
        self._drag_alvo = None
        self._highlight_id = None
        self._inline_widget = None
        self._inline_window = None
        self._inline_commit = None
        self._inline_closing = False
        self._connect_from = None
        self.selected_edge = None   # conexão selecionada (o Sim/Não vive nela)
        self._armed = None  # ferramenta da paleta aguardando clique no canvas
        self._bound_keys = []
        self._clipboard = None

    def enable(self):
        """Ativa modo edição."""
        self.active = True
        self.canvas.bind('<ButtonPress-1>', self._on_press)
        self.canvas.bind('<B1-Motion>', self._on_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_release)
        self.canvas.bind('<Double-Button-1>', self._on_double_click)
        # Clique direito vira menu de contexto (o pan fica no botão do meio)
        self.canvas.bind('<ButtonPress-3>', self._on_context)
        self.canvas.bind('<Motion>', self._on_motion)
        self.canvas.unbind('<B3-Motion>')
        self._bind_keys()
        self.canvas.configure(cursor='hand2')

    def disable(self):
        """Desativa modo edição."""
        self.active = False
        self._close_inline(commit=False)
        self._cancel_connect()
        self.canvas.unbind('<ButtonPress-1>')
        self.canvas.unbind('<B1-Motion>')
        self.canvas.unbind('<ButtonRelease-1>')
        self.canvas.unbind('<Double-Button-1>')
        self.canvas.unbind('<ButtonPress-3>')
        self.canvas.unbind('<Motion>')
        self._unbind_keys()
        self._limpar_previa()
        self._limpar_conexao_previa()
        self.canvas.configure(cursor='')
        self._set_selection(None)

    # ── Atalhos de teclado do modo edição ──────────────────

    def _bind_keys(self):
        """Atalhos que só valem com o modo edição ligado."""
        top = self.canvas.winfo_toplevel()
        atalhos = [
            ('<Escape>', self._cancel_connect),
            ('<Delete>', self._on_delete_key),
            ('<BackSpace>', self._on_delete_key),
            ('<Control-c>', self._on_copy_key),
            ('<Control-v>', self._on_paste_key),
            ('<Control-d>', self._on_duplicate_key),
        ]
        for seq, fn in atalhos:
            self._bound_keys.append((top, seq, top.bind(seq, fn, add='+')))

    def _unbind_keys(self):
        for widget, seq, funcid in self._bound_keys:
            try:
                widget.unbind(seq, funcid)
            except tk.TclError:
                pass
        self._bound_keys = []

    def _digitando(self):
        """O foco está num campo de texto? Então o atalho é do campo, não nosso."""
        if self._inline_widget is not None:
            return True
        try:
            foco = self.canvas.focus_get()
        except (KeyError, tk.TclError):
            return False
        return isinstance(foco, (tk.Entry, tk.Text))

    def _on_delete_key(self, event=None):
        if not self.active or self._digitando() or not self.selected_node:
            return
        self._delete_node(self.selected_node)
        return 'break'

    def _on_copy_key(self, event=None):
        if not self.active or self._digitando() or not self.selected_node:
            return
        self._clipboard = copy.deepcopy(self.selected_node)
        self._status(f"⧉ '{self._clipboard['label'] or self._clipboard['id']}' "
                     f"copiado — Ctrl+V cola", 'info')
        return 'break'

    def _on_paste_key(self, event=None):
        if not self.active or self._digitando() or not self._clipboard:
            return
        self._paste(self._clipboard)
        return 'break'

    def _on_duplicate_key(self, event=None):
        if not self.active or self._digitando() or not self.selected_node:
            return
        self._paste(self.selected_node)
        return 'break'

    def _paste(self, origem):
        """Cola uma cópia do nó, deslocada, e a deixa selecionada."""
        novo = copy.deepcopy(origem)
        novo['id'] = self._new_id('C' if novo['type'] == 'annotation' else 'N')
        novo['x'] = novo.get('x', 0) + PASTE_OFFSET
        novo['y'] = novo.get('y', 0) + PASTE_OFFSET
        novo['pinned'] = True
        self.model['nodes'].append(novo)
        self._set_selection(novo, desenhar=False)
        self._commit(f"⧉ Nó '{novo['id']}' colado — arraste para posicionar",
                     'success')

    # ── Seleção (API usada pelo painel e pela correção guiada) ──

    def _set_selection(self, node, desenhar=True):
        """Ponto único por onde a seleção muda — o painel sempre fica sabendo."""
        self.selected_node = node
        self.selected_edge = None
        if desenhar and node is not None:
            self._draw_highlight(node)
        elif node is None:
            self._clear_highlight()
        if self.on_selection_change:
            self.on_selection_change(node, 'node')

    def _set_selection_edge(self, edge):
        """Seleciona uma conexão e realça a rota dela.

        Rotular um Sim/Não exigia acertar um duplo clique numa linha de 1px, e
        o painel — onde a pessoa olha — só tratava nós. Selecionar a conexão
        leva o rótulo para o mesmo lugar onde o resto se edita.
        """
        self.selected_node = None
        self.selected_edge = edge
        self._clear_highlight()
        if edge is not None:
            self._realcar_edge(edge)
        if self.on_selection_change:
            self.on_selection_change(edge, 'edge')

    def _realcar_edge(self, edge):
        """Desenha a rota da conexão selecionada por cima, em destaque."""
        self.canvas.delete('edge_sel')
        prims = plan_edges(self.model['edges'], self._node_map(),
                           lane_boundaries(self.model))
        for p in prims:
            if p.get('kind') != 'line' or p.get('edge') is not edge:
                continue
            pts = self.viewport.to_view_points(p['points'])
            self._highlight_id = self.canvas.create_line(
                *pts, fill='#003399', width=3, dash=(5, 3),
                tags=('highlight', 'edge_sel'))

    def set_edge_label(self, edge, label):
        """Rótulo da conexão — o Sim/Não de uma decisão."""
        if edge is None or edge.get('label', '') == label:
            return
        edge['label'] = label
        self._commit()

    def select_node(self, node_id):
        """Seleciona um nó pelo id, sem clique. Devolve o nó ou None.

        É o que a correção guiada usa para levar o usuário até o elemento do
        aviso: encapsula o que o clique já fazia, em vez de duplicar.
        """
        for n in self.model['nodes']:
            if n['id'] == node_id:
                self._set_selection(n)
                return n
        return None

    # ── Setters do painel de propriedades ──────────────────
    #
    # Cada um só comita se o valor mudou de fato, e comita pelo mesmo caminho
    # do canvas: uma troca de campo é um passo de histórico, não dois.

    def set_node_type(self, node, ntype):
        if not node or node.get('type') == ntype:
            return
        antigo = node['type']
        node['type'] = ntype
        # O tamanho só acompanha quando ainda era o default do tipo anterior:
        # nó redimensionado à mão fica como está, mas uma tarefa que vira barra
        # de paralelismo não fica com 64px de altura desenhando uma tarja.
        padrao_antigo = DEFAULT_NODE_SIZES.get(antigo)
        padrao_novo = DEFAULT_NODE_SIZES.get(ntype)
        if padrao_novo and padrao_antigo and node.get('size') == padrao_antigo:
            node['size'] = dict(padrao_novo)
        self._commit(f"✏ Tipo de '{node['id']}' alterado", 'success')

    def set_node_lane(self, node, lane_id):
        if not node or not lane_id or node.get('laneId') == lane_id:
            return
        node['laneId'] = lane_id
        # Posição manual deixa de valer: quem escolhe a coluna pelo painel
        # espera o nó ir para lá, não ficar preso à coordenada antiga.
        node['pinned'] = False
        self._commit(f"✏ '{node['id']}' movido de coluna", 'success')

    def set_ponto_em_aberto(self, node, marcado, pergunta=''):
        """Marca o nó como decisão/etapa ainda não resolvida pelo processo.

        Era a necessidade mais pedida no teste aberto: três usuários, três
        processos diferentes, todos precisaram registrar "isto aqui ainda não
        está definido" — e o único caminho era anexar um comentário cujo texto
        começasse com a palavra `Gap:`. Ninguém descobriu.
        """
        props = node.setdefault('props', {})
        antes = (props.get('em_aberto'), props.get('pergunta', ''))
        if marcado:
            props['em_aberto'] = True
            if pergunta:
                props['pergunta'] = pergunta
            else:
                props.pop('pergunta', None)
        else:
            props.pop('em_aberto', None)
            props.pop('pergunta', None)
        if antes == (props.get('em_aberto'), props.get('pergunta', '')):
            return
        msg = (f"❓ '{node['id']}' marcado como ponto em aberto" if marcado
               else f"✔ '{node['id']}' deixou de ser ponto em aberto")
        self._commit(msg, 'info')

    def set_node_label(self, node, label):
        if not node or node.get('label') == label:
            return
        node['label'] = label
        self._commit()

    def set_department(self, nome):
        """Departamento do documento — escolhido do catálogo corporativo."""
        if self.model.get('department') == nome:
            return
        self.model['department'] = nome
        self._commit(f"✏ Departamento: {nome}", 'success')

    def set_lane_label(self, lane_id, label):
        """Cargo de uma coluna — escolhido do catálogo corporativo."""
        for lane in self.model['lanes']:
            if lane['id'] == lane_id:
                if lane.get('label') == label:
                    return
                lane['label'] = label
                self._commit(f"✏ Cargo da coluna {lane_id}: {label}", 'success')
                return

    def set_sp_node_label(self, sp, node, label):
        """Texto de uma etapa dentro de uma Instrução de Trabalho."""
        if not label or node.get('label') == label:
            return
        node['label'] = label
        self._commit(f"✏ Etapa de '{sp['label']}' renomeada", 'success')

    def _edit_sp_node_label(self, sp, node):
        def commit(text):
            self.set_sp_node_label(sp, node, text)
        self._open_inline(node['x'] + node['size']['w'] / 2,
                          node['y'] + node['size']['h'] / 2,
                          max(node['size']['w'] - 10, 120),
                          node.get('label', ''), commit)

    def _realcar_sp_node(self, node):
        """Realce dos nós de subprocesso — mesmo contorno, cor da seção."""
        self._clear_highlight()
        pts = self.viewport.to_view_points(node_outline(node))
        self._highlight_id = self.canvas.create_polygon(
            pts, fill='', outline='#7B2149', width=2, dash=(3, 2),
            tags=('highlight',))

    def set_lane_department(self, lane_id, departamento):
        """Área de uma coluna. Um fluxo atravessa várias — cada uma tem a sua."""
        for lane in self.model['lanes']:
            if lane['id'] == lane_id:
                if lane.get('department') == departamento:
                    return
                lane['department'] = departamento
                self._sincronizar_banner()
                self._commit(f"✏ Área da coluna {lane_id}: {departamento}",
                             'success')
                return

    def add_lane(self, departamento='', cargo=''):
        """Acrescenta uma coluna ao fluxo (novo ator entrando no processo)."""
        existentes = {l['id'] for l in self.model['lanes']}
        i = 1
        while f'L{i}' in existentes:
            i += 1
        lane = {'id': f'L{i}', 'label': cargo or 'Novo ator',
                'department': departamento,
                'order': len(self.model['lanes']),
                'width': 320, 'style': {'fill': '#ffffff'}}
        self.model['lanes'].append(lane)
        for i, l in enumerate(self.model['lanes']):
            l['order'] = i
        self._sincronizar_banner()
        self._commit(f"➕ Coluna '{lane['label']}' adicionada", 'success')
        return lane

    def move_lane(self, lane_id, delta):
        """Move uma coluna para a esquerda (-1) ou para a direita (+1).

        A ordem das colunas é leitura do processo, não enfeite: quem recebe o
        fluxograma lê da esquerda para a direita, e a sequência errada faz o
        processo parecer outro. Antes só dava para mexer nisso editando o
        `order` das lanes no JSON.

        Os nós de posição manual (`pinned`) são deslocados junto com a coluna
        deles — sem isso, mover a coluna deixaria os nós fixados para trás, na
        faixa vertical de quem entrou no lugar.
        """
        lanes = self.model['lanes']
        indice = next((i for i, l in enumerate(lanes) if l['id'] == lane_id), None)
        if indice is None:
            return False
        destino = indice + delta
        if not (0 <= destino < len(lanes)):
            return False

        antes = self._posicoes_das_colunas()
        lanes[indice], lanes[destino] = lanes[destino], lanes[indice]
        for i, lane in enumerate(lanes):
            lane['order'] = i
        depois = self._posicoes_das_colunas()

        for node in self.model['nodes']:
            if not node.get('pinned') or node.get('type') == 'annotation':
                continue
            origem = antes.get(node.get('laneId'))
            alvo = depois.get(node.get('laneId'))
            if origem is not None and alvo is not None:
                node['x'] += alvo['x'] - origem['x']

        lado = 'esquerda' if delta < 0 else 'direita'
        self._commit(f"↔ Coluna '{lanes[destino]['label']}' movida para a {lado}",
                     'success')
        return True

    def _posicoes_das_colunas(self):
        """Onde cada coluna começa, com a ordem atual das lanes."""
        return lane_x_positions(
            self.model['lanes'],
            self.model['meta']['margins'],
            self.model['layout']['swimlanes']['gap'])

    def remove_lane(self, lane_id):
        """Remove uma coluna. Os nós dela iriam para o limbo — vão junto."""
        lanes = self.model['lanes']
        if len(lanes) <= 1:
            self._status('⚠ O fluxo precisa de pelo menos uma coluna', 'warning')
            return False
        alvo = next((l for l in lanes if l['id'] == lane_id), None)
        if alvo is None:
            return False
        orfaos = [n['id'] for n in self.model['nodes']
                  if n.get('laneId') == lane_id]
        self.model['lanes'] = [l for l in lanes if l['id'] != lane_id]
        for i, l in enumerate(self.model['lanes']):
            l['order'] = i
        self.model['nodes'] = [n for n in self.model['nodes']
                               if n['id'] not in orfaos]
        self.model['edges'] = [e for e in self.model['edges']
                               if e['from'] not in orfaos and e['to'] not in orfaos]
        if self.selected_node and self.selected_node['id'] in orfaos:
            self._set_selection(None)
        self._sincronizar_banner()
        extra = f" e {len(orfaos)} nó(s) dela" if orfaos else ''
        self._commit(f"🗑 Coluna '{alvo['label']}'{extra} removida — Ctrl+Z desfaz")
        return True

    def _sincronizar_banner(self):
        """Mantido só para arquivo de UMA área, onde o banner ainda faz sentido.

        Num fluxo interdepartamental o campo `department` do documento não tem
        resposta certa — quem mostra as áreas são as faixas sobre as colunas.
        Escrever "A · B · C" ali fazia o mesmo campo significar coisas
        diferentes conforme a origem do arquivo, e ainda reprovava no catálogo.
        """
        areas = []
        for lane in self.model['lanes']:
            area = (lane.get('department') or '').strip()
            if area and area not in areas:
                areas.append(area)
        if len(areas) == 1:
            self.model['department'] = areas[0]
        elif len(areas) > 1 and ' · ' in (self.model.get('department') or ''):
            # Limpa um banner derivado gravado por uma versão anterior
            self.model['department'] = ''

    def remove_lane(self, lane_id):
        """Remove uma coluna. Os nós dela iriam para o limbo — vão junto."""
        lanes = self.model['lanes']
        if len(lanes) <= 1:
            self._status('⚠ O fluxo precisa de pelo menos uma coluna', 'warning')
            return False
        alvo = next((l for l in lanes if l['id'] == lane_id), None)
        if alvo is None:
            return False
        orfaos = [n['id'] for n in self.model['nodes']
                  if n.get('laneId') == lane_id]
        self.model['lanes'] = [l for l in lanes if l['id'] != lane_id]
        for i, l in enumerate(self.model['lanes']):
            l['order'] = i
        self.model['nodes'] = [n for n in self.model['nodes']
                               if n['id'] not in orfaos]
        self.model['edges'] = [e for e in self.model['edges']
                               if e['from'] not in orfaos and e['to'] not in orfaos]
        if self.selected_node and self.selected_node['id'] in orfaos:
            self._set_selection(None)
        self._sincronizar_banner()
        extra = f" e {len(orfaos)} nó(s) dela" if orfaos else ''
        self._commit(f"🗑 Coluna '{alvo['label']}'{extra} removida — Ctrl+Z desfaz")
        return True

    def _sincronizar_banner(self):
        """O banner mostra as áreas envolvidas, na ordem das colunas.

        Ele era um texto solto que ninguém atualizava ao mexer nas colunas —
        num fluxo interdepartamental isso vira uma legenda que mente sobre
        quem participa do processo.
        """
        areas = []
        for lane in self.model['lanes']:
            area = (lane.get('department') or '').strip()
            if area and area not in areas:
                areas.append(area)
        if areas:
            self.model['department'] = ' · '.join(areas)

    # ── Helpers ────────────────────────────────────────────

    def _status(self, msg, kind='info'):
        if self.on_status:
            self.on_status(msg, kind)

    def _commit(self, msg=None, kind='info'):
        """Ponto ÚNICO de mutação: avisa a janela e reporta o resultado.

        A janela registra o histórico, re-renderiza e revalida — venha a
        alteração do canvas, do menu de contexto ou do teclado. A mensagem vai
        junto para ela poder dar precedência a um aviso de validação.
        """
        if self.on_model_change:
            self.on_model_change(self.model, msg, kind)
        elif msg:
            self._status(msg, kind)

    def _point(self, event):
        """Coordenadas do evento em espaço de MODELO (desfaz scroll e zoom)."""
        return self.viewport.event_to_model(self.canvas, event)

    def _slop(self):
        """Folga de toque em unidades de modelo, constante na tela."""
        return self.viewport.touch_slop()

    def _view(self, x, y):
        return self.viewport.to_view(x, y)

    def _node_map(self):
        return {n['id']: n for n in self.model['nodes']}

    def _new_id(self, prefix='N'):
        existing = {n['id'] for n in self.model['nodes']}
        i = 1
        while f'{prefix}{i}' in existing:
            i += 1
        return f'{prefix}{i}'

    def _lane_at(self, mx):
        comp = self.model.get('_computed', {})
        lane_pos = comp.get('lane_positions', {})
        for lid, lp in lane_pos.items():
            if lp['x'] <= mx <= lp['x'] + lp['width']:
                return lid
        return self.model['lanes'][0]['id'] if self.model['lanes'] else ''

    # ── Resolução de alvo (uma única estratégia) ───────────

    def _edge_finder(self, px, py, slop):
        # Tolerância constante NA TELA: 6px viram mais unidades de modelo
        # quando a vista está reduzida, e menos quando está ampliada.
        return find_edge_at(self.model['edges'], self._node_map(), px, py,
                            tol=max(slop, self.viewport.to_model_len(6)),
                            lane_x=lane_boundaries(self.model))

    def _resolve(self, mx, my, com_edges=True):
        """O que está sob o ponto — nó, comentário, header de lane ou conexão."""
        return resolve_target(
            self.model, mx, my, slop=self._slop(),
            canvas=self.canvas, scale=self.viewport.scale,
            edge_finder=self._edge_finder if com_edges else None)

    def _find_node_at(self, mx, my):
        """Nó do fluxo sob o ponto, pela geometria real da forma."""
        return find_node_at(self.model, mx, my, self._slop())

    def _find_annotation_at(self, mx, my):
        return find_annotation_at(self.model, mx, my, self._slop(),
                                  canvas=self.canvas, scale=self.viewport.scale)

    def _find_lane_header_at(self, mx, my):
        return find_lane_header_at(self.model, mx, my, self._slop())

    # ── Ferramentas da paleta (armar e aguardar clique) ────

    def arm_add(self, ntype, label, automatic=False):
        """Arma a criação de um nó: o próximo clique no canvas o posiciona."""
        self._armed = {'mode': 'add', 'ntype': ntype, 'label': label,
                       'automatic': automatic}
        self._connect_from = None
        self.canvas.configure(cursor='crosshair')
        self._status(f"➕ Clique no fluxograma para posicionar: "
                     f"{label or ntype} — Esc cancela", 'info')

    def arm_connect(self):
        """Arma a criação de conexão: clique na origem, depois no destino."""
        self._armed = {'mode': 'connect'}
        self._connect_from = None
        self.canvas.configure(cursor='crosshair')
        self._status('🔗 Clique no nó de ORIGEM da conexão — Esc cancela', 'info')

    def arm_comment(self):
        """Arma a criação de comentário: clique no nó que o recebe."""
        self._armed = {'mode': 'comment'}
        self.canvas.configure(cursor='crosshair')
        self._status('💬 Clique no nó que recebe o comentário — Esc cancela', 'info')

    def disarm(self, notify=True):
        """Desarma qualquer ferramenta pendente da paleta."""
        self._armed = None
        if self.active:
            self.canvas.configure(cursor='hand2')
        if notify and self.on_tool_done:
            self.on_tool_done()

    # ── Drag-and-drop ──────────────────────────────────────

    def _on_press(self, event):
        self._close_inline(commit=True)
        mx, my = self._point(event)
        self.canvas.focus_set()

        # Ferramenta da paleta armada: este clique executa a ferramenta
        if self._armed:
            armed = self._armed
            mode = armed['mode']
            if mode == 'add':
                self.disarm()
                self._add_node(armed['ntype'], armed['label'], mx, my,
                               automatic=armed.get('automatic', False))
                return
            if mode == 'connect':
                node = self._find_node_at(mx, my)
                if node and node['type'] != 'annotation':
                    self._armed = None  # segue para a fase do destino
                    self._start_connect(node)
                else:
                    self.disarm()
                    self._status('Conexão cancelada', 'info')
                return
            if mode == 'comment':
                node = self._find_node_at(mx, my)
                self.disarm()
                if node and node['type'] != 'annotation':
                    self._add_comment(node)
                else:
                    self._status('Comentário cancelado — clique em um nó', 'info')
                return

        # Modo "conectar a...": este clique escolhe o destino
        if self._connect_from is not None:
            src = self._connect_from
            self._connect_from = None
            self._limpar_conexao_previa()
            self.disarm()
            node = self._find_node_at(mx, my)
            if node and node is not src and node['type'] != 'annotation':
                dup = any(e['from'] == src['id'] and e['to'] == node['id']
                          for e in self.model['edges'])
                if dup:
                    self._status('⚠ Esses nós já estão conectados', 'warning')
                else:
                    self.model['edges'].append({
                        'from': src['id'], 'to': node['id'], 'type': 'flow',
                        'label': '', 'style': {}, 'routing': 'orthogonal',
                    })
                    self._commit()
            else:
                self._status('Conexão cancelada', 'info')
            return

        node = self._find_node_at(mx, my)
        if node is None:
            aresta = self._edge_finder(mx, my, self._slop())
            if aresta is not None:
                self._clear_highlight()
                self._dragged = False
                self._set_selection_edge(aresta)
                self._status(
                    f"🔗 Conexão {aresta['from']} → {aresta['to']} — o rótulo "
                    f"(Sim/Não) está no painel à direita", 'info')
                return
            sp, sp_node = find_subprocess_node_at(self.model, mx, my, self._slop())
            if sp_node is not None:
                self._clear_highlight()
                self._realcar_sp_node(sp_node)
                self._status(
                    f"⚠ '{sp_node['label']}' pertence à Instrução de Trabalho "
                    f"'{sp['label']}' — duplo clique edita o texto; posição e "
                    f"conexões dela são calculadas pelo programa", 'info')
                return
        self._clear_highlight()
        self._dragged = False

        if node:
            self.drag_data['x'] = mx - node['x']
            self.drag_data['y'] = my - node['y']
            self._set_selection(node)
            self.canvas.configure(cursor='fleur')
        else:
            self._set_selection(None)

    def _on_drag(self, event):
        """Move o FANTASMA, não o nó.

        O arraste escrevia a posição candidata direto no nó real e ainda
        trocava a lane a cada quadro — o dado comprometido ia andando durante o
        gesto, por fora do ponto único de mutação. Agora o modelo só é tocado
        ao soltar; durante o gesto o que se vê é uma prévia.
        """
        if not self.selected_node:
            return
        mx, my = self._point(event)
        grid = self.model['meta'].get('grid', 10)
        new_x = round((mx - self.drag_data['x']) / grid) * grid
        new_y = round((my - self.drag_data['y']) / grid) * grid

        if (new_x, new_y) == (self.selected_node['x'], self.selected_node['y'])                 and not self._dragged:
            return

        if not self._dragged:
            # Marcadores de validação ficariam para trás do nó em movimento;
            # eles voltam no redesenho que o commit dispara ao soltar.
            self.canvas.delete('issue')
        self._dragged = True
        self._drag_alvo = (new_x, new_y)
        self._desenhar_fantasma(self.selected_node, new_x, new_y)

    def _desenhar_fantasma(self, node, x, y):
        """Contorno tracejado do nó na posição candidata + prévia das setas."""
        self.canvas.delete('drag_ghost')
        self.canvas.delete('preview_edge')
        cand = {**node, 'x': x, 'y': y}

        pts = self.viewport.to_view_points(node_outline(cand))
        self.canvas.create_polygon(pts, fill='#003399', stipple='gray25',
                                   outline='#003399', width=2, dash=(4, 2),
                                   tags=('drag_ghost',))

        # Só as conexões que tocam este nó, roteadas contra a posição candidata
        tocam = [e for e in self.model['edges']
                 if e['from'] == node['id'] or e['to'] == node['id']]
        if not tocam:
            return
        mapa = self._node_map()
        mapa[node['id']] = cand
        prims = plan_edges(tocam, mapa, lane_boundaries(self.model))
        itens = draw_edges(self.canvas, prims, self.model['styles'],
                           tags=['preview_edge'], scale=self.viewport.scale)
        for item in itens:
            try:
                self.canvas.itemconfigure(item, dash=(2, 2))
            except tk.TclError:
                continue  # textos de rótulo não aceitam dash

    def _limpar_previa(self):
        self.canvas.delete('drag_ghost')
        self.canvas.delete('preview_edge')

    def _on_release(self, event):
        """Aqui, sim, o modelo recebe a posição — uma vez, e com commit."""
        alvo = getattr(self, '_drag_alvo', None)
        self._limpar_previa()
        if self.selected_node and self._dragged and alvo:
            self.selected_node['x'], self.selected_node['y'] = alvo
            self._detect_lane_change(self.selected_node)
            # Posição manual persiste no JSON (pinned)
            self.selected_node['pinned'] = True
            self._commit()
        self._dragged = False
        self._drag_alvo = None
        self.canvas.configure(cursor='hand2')

    # ── Linha de conexão ao vivo (rubber-band) ─────────────

    def _on_motion(self, event):
        """Entre clicar na origem e clicar no destino, mostra para onde vai.

        Antes desses dois cliques não havia resposta visual nenhuma: o usuário
        não sabia se tinha acertado a origem nem para onde estava apontando.
        """
        if self._connect_from is None:
            return
        origem = self._connect_from
        # Mesma âncora de saída que o roteamento usa: centro-x, fundo do nó
        ox = origem['x'] + origem['size']['w'] / 2
        oy = origem['y'] + origem['size']['h']
        vx, vy = self.viewport.to_view(ox, oy)
        self.canvas.delete('connect_preview')
        self.canvas.create_line(vx, vy,
                                self.canvas.canvasx(event.x),
                                self.canvas.canvasy(event.y),
                                fill='#003399', width=2, dash=(4, 2),
                                arrow='last', tags=('connect_preview',))

    def _limpar_conexao_previa(self):
        self.canvas.delete('connect_preview')

    def _redraw_edges(self):
        """Apaga e redesenha os conectores do fluxo principal (roteamento ao vivo)."""
        self.canvas.delete('main_edge')
        prims = plan_edges(self.model['edges'], self._node_map(),
                           lane_boundaries(self.model))
        draw_edges(self.canvas, prims, self.model['styles'], tags=['main_edge'],
                   scale=self.viewport.scale)
        # Manter conectores atrás dos nós
        if self.canvas.find_withtag('node'):
            self.canvas.tag_lower('main_edge', 'node')

    def _detect_lane_change(self, node):
        """Detecta se o nó foi arrastado para outra lane."""
        comp = self.model.get('_computed', {})
        lane_pos = comp.get('lane_positions', {})
        cx = node['x'] + node['size']['w'] / 2

        for lane in self.model['lanes']:
            lp = lane_pos.get(lane['id'])
            if lp and lp['x'] <= cx <= lp['x'] + lp['width']:
                if node['laneId'] != lane['id']:
                    node['laneId'] = lane['id']
                break

    # ── Menu de contexto (clique direito) ──────────────────

    def _on_context(self, event):
        self._close_inline(commit=True)
        mx, my = self._point(event)

        menu = tk.Menu(self.canvas, tearoff=0)
        kind, alvo = self._resolve(mx, my)
        node = alvo if kind == 'node' else None
        ann = alvo if kind == 'annotation' else None
        edge = alvo if kind == 'edge' else None

        if node:
            self._set_selection(node)
            menu.add_command(label='✏  Editar texto',
                             command=lambda n=node: self._edit_node_label(n))
            if node['type'] in ('task', 'subprocess', 'decision'):
                on = node.get('props', {}).get('automatic')
                menu.add_command(label=f"⚙  Tarefa automática {'✔' if on else ''}",
                                 command=lambda n=node: self._toggle_automatic(n))
            menu.add_command(label='🔗  Conectar a…',
                             command=lambda n=node: self._start_connect(n))
            menu.add_command(label='💬  Adicionar comentário',
                             command=lambda n=node: self._add_comment(n))
            menu.add_separator()
            menu.add_command(label='⧉  Copiar', accelerator='Ctrl+C',
                             command=self._on_copy_key)
            menu.add_command(label='⧉  Duplicar', accelerator='Ctrl+D',
                             command=lambda n=node: self._paste(n))
            if self._clipboard:
                menu.add_command(label='📋  Colar', accelerator='Ctrl+V',
                                 command=self._on_paste_key)
            menu.add_separator()
            menu.add_command(label='🗑  Excluir nó', accelerator='Del',
                             command=lambda n=node: self._delete_node(n))
        elif ann:
            menu.add_command(label='✏  Editar comentário',
                             command=lambda a=ann, x=mx, y=my: self._edit_annotation(a, x, y))
            menu.add_separator()
            menu.add_command(label='🗑  Excluir comentário',
                             command=lambda a=ann: self._delete_node(a))
        elif edge:
            menu.add_command(label='✏  Editar rótulo (Sim/Não...)',
                             command=lambda e=edge, x=mx, y=my: self._edit_edge_label(e, x, y))
            menu.add_separator()
            menu.add_command(label='🗑  Excluir conexão',
                             command=lambda e=edge: self._delete_edge(e))
        else:
            add = tk.Menu(menu, tearoff=0)
            for ntype, item_label, init_label in NEW_NODE_TYPES:
                add.add_command(label=item_label,
                                command=lambda t=ntype, l=init_label, x=mx, y=my:
                                self._add_node(t, l, x, y))
            add.add_command(label='⚙  Tarefa automática',
                            command=lambda x=mx, y=my:
                            self._add_node('task', 'Tarefa automática', x, y,
                                           automatic=True))
            menu.add_cascade(label='➕  Adicionar aqui', menu=add)
            if self._clipboard:
                menu.add_command(label='📋  Colar aqui', accelerator='Ctrl+V',
                                 command=lambda x=mx, y=my: self._paste_at(x, y))

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _paste_at(self, mx, my):
        """Cola a área de transferência sob o ponteiro."""
        if not self._clipboard:
            return
        novo = copy.deepcopy(self._clipboard)
        grid = self.model['meta'].get('grid', 10)
        novo['id'] = self._new_id('C' if novo['type'] == 'annotation' else 'N')
        novo['x'] = round((mx - novo['size']['w'] / 2) / grid) * grid
        novo['y'] = round((my - novo['size']['h'] / 2) / grid) * grid
        novo['pinned'] = True
        novo['laneId'] = self._lane_at(mx)
        self.model['nodes'].append(novo)
        self._set_selection(novo, desenhar=False)
        self._commit(f"📋 Nó '{novo['id']}' colado aqui", 'success')

    # ── Criação / exclusão de elementos ────────────────────

    def _add_node(self, ntype, label, mx, my, automatic=False):
        defaults = DEFAULT_NODE_SIZES.get(ntype, {'w': 170, 'h': 64})
        grid = self.model['meta'].get('grid', 10)
        x = round((mx - defaults['w'] / 2) / grid) * grid
        y = round((my - defaults['h'] / 2) / grid) * grid
        node = {
            'id': self._new_id(),
            'laneId': self._lane_at(mx),
            'type': ntype,
            'label': label,
            'size': {'w': defaults['w'], 'h': defaults['h']},
            'props': {'automatic': True} if automatic else {},
            'x': x, 'y': y,
            'pinned': True,
        }
        self.model['nodes'].append(node)
        self._set_selection(node, desenhar=False)
        self._commit(f"➕ Nó '{node['id']}' criado — duplo clique edita o texto",
                     'success')

    def _delete_node(self, node):
        nid = node['id']
        self.model['nodes'] = [n for n in self.model['nodes'] if n['id'] != nid]
        self.model['edges'] = [e for e in self.model['edges']
                               if e['from'] != nid and e['to'] != nid]
        self.model['subprocesses'] = [s for s in self.model['subprocesses']
                                      if s.get('parent_node_id') != nid]
        if self.selected_node is node:
            self._set_selection(None)
        self._commit(f"🗑 Nó '{nid}' excluído (com suas conexões) — Ctrl+Z desfaz")

    def _start_connect(self, node):
        self._connect_from = node
        self.canvas.configure(cursor='crosshair')
        self._status(f"🔗 Clique no nó de destino para conectar a "
                     f"'{node['label'] or node['id']}' — Esc cancela", 'info')

    def _cancel_connect(self, event=None):
        had_tool = self._connect_from is not None or self._armed is not None
        self._connect_from = None
        self._limpar_conexao_previa()
        self.disarm()
        if had_tool:
            self._status('Ferramenta cancelada', 'info')

    def _toggle_automatic(self, node):
        props = node.setdefault('props', {})
        props['automatic'] = not props.get('automatic')
        if not props['automatic']:
            props.pop('automatic', None)
        self._commit()

    def _add_comment(self, node):
        ann = {
            'id': self._new_id('C'),
            'laneId': node['laneId'],
            'type': 'annotation',
            'label': 'Novo comentário',
            'size': {'w': 240, 'h': 70},
            'props': {},
            'x': 0, 'y': 0,
            'pinned': False,
        }
        self.model['nodes'].append(ann)
        self.model['edges'].append({
            'from': node['id'], 'to': ann['id'], 'type': 'annotation',
            'label': '', 'style': {}, 'routing': 'orthogonal',
        })
        self._commit('💬 Comentário criado na coluna lateral — duplo clique edita',
                     'success')

    def _delete_edge(self, edge):
        self.model['edges'] = [e for e in self.model['edges'] if e is not edge]
        self._commit('🗑 Conexão excluída — Ctrl+Z desfaz')

    def _edit_edge_label(self, edge, mx, my):
        def commit(text):
            if text != edge.get('label', ''):
                edge['label'] = text
                self._commit()
        self._open_inline(mx, my, 120, edge.get('label', ''), commit,
                          allow_empty=True)

    # ── Edição de texto inline (duplo clique) ──────────────

    def _on_double_click(self, event):
        mx, my = self._point(event)
        kind, alvo = self._resolve(mx, my)

        if kind == 'node':
            self._edit_node_label(alvo)
        elif kind == 'annotation':
            self._edit_annotation(alvo, mx, my)
        elif kind == 'lane_header':
            self._edit_lane_header(alvo, my)
        elif kind == 'sp_node':
            self._edit_sp_node_label(*alvo)
        elif kind == 'edge':
            self._edit_edge_label(alvo, mx, my)

    def _edit_node_label(self, node):
        def commit(text):
            if text and text != node['label']:
                node['label'] = text
                self._commit()
        self._open_inline(node['x'] + node['size']['w'] / 2,
                          node['y'] + node['size']['h'] / 2,
                          max(node['size']['w'] - 10, 120),
                          node['label'], commit,
                          allow_empty=node['type'] == 'parallel')

    def _edit_lane_header(self, lane, my):
        """Duplo clique no cabeçalho: faixa de cima edita a ÁREA, abaixo o CARGO.

        Antes, os dois pontos abriam o mesmo campo de texto livre do cargo — a
        faixa de departamento editava a coisa errada, e qualquer grafia passava.
        """
        comp = self.model.get('_computed', {})
        top = self.model['meta']['margins']['top']
        band_h = comp.get('dept_band_height', 0)
        if band_h and my <= top + band_h:
            self._edit_lane_department(lane)
        else:
            self._edit_lane_label(lane)

    def _edit_lane_department(self, lane):
        """Escolhe a área da coluna dentro do catálogo corporativo."""
        comp = self.model.get('_computed', {})
        lp = comp.get('lane_positions', {}).get(lane['id'])
        if not lp:
            return
        top = self.model['meta']['margins']['top']
        band_h = comp.get('dept_band_height', 22) or 22
        areas = cat.nomes_departamentos(self.catalogo)
        if not areas:
            self._status('⚠ Catálogo vazio — cadastre as áreas em '
                         'Configurações › Departamentos e cargos', 'warning')
            return

        def commit(valor):
            self.set_lane_department(lane['id'], valor)

        self._open_inline_escolha(lp['x'] + lp['width'] / 2, top + band_h / 2,
                                  lp['width'] - 16, areas,
                                  lane.get('department', ''), commit)

    def _edit_lane_label(self, lane):
        """Escolhe o cargo da coluna — restrito aos que existem na área dela."""
        comp = self.model.get('_computed', {})
        lp = comp.get('lane_positions', {}).get(lane['id'])
        if not lp:
            return
        top = self.model['meta']['margins']['top']
        header_h = comp.get('header_height', 36)
        band_h = comp.get('dept_band_height', 0)
        area = (lane.get('department') or '').strip()
        cargos = (cat.cargos_de(area, self.catalogo) if area
                  else cat.todos_cargos(self.catalogo))
        cy = top + band_h + (header_h - band_h) / 2

        if not cargos:
            # Sem catálogo não há o que oferecer: cair no texto livre é melhor
            # que travar o usuário, mas ele fica sabendo por quê.
            self._status('⚠ Nenhum cargo cadastrado para esta área — texto '
                         'livre; cadastre em Configurações', 'warning')

            def commit_texto(text):
                if text and text != lane['label']:
                    self.set_lane_label(lane['id'], text)

            self._open_inline(lp['x'] + lp['width'] / 2, cy,
                              lp['width'] - 20, lane['label'], commit_texto)
            return

        def commit(valor):
            self.set_lane_label(lane['id'], valor)

        self._open_inline_escolha(lp['x'] + lp['width'] / 2, cy,
                                  lp['width'] - 16, cargos,
                                  lane.get('label', ''), commit)

    def _open_inline_escolha(self, cx, cy, width, valores, atual, on_commit):
        """Lista suspensa sobre o canvas, na posição indicada (espaço de modelo).

        É o equivalente de `_open_inline` para campos que só aceitam valores do
        catálogo: o usuário escolhe, não digita.
        """
        self._close_inline(commit=False)
        scale = self.viewport.scale
        lista = list(valores)
        if atual and atual not in lista:
            # Valor legado fora do catálogo: aparece, para o painel não mentir
            # sobre o que está no arquivo, mas o resto da lista é o caminho.
            lista = [atual] + lista

        combo = ttk.Combobox(self.canvas, values=lista, state='readonly',
                             font=(FONT, max(7, int(round(9 * scale)))))
        combo.set(atual or '')
        self._inline_widget = combo
        self._inline_commit = on_commit
        self._inline_allow_empty = False
        vx, vy = self.viewport.to_view(cx, cy)
        self._inline_window = self.canvas.create_window(
            vx, vy, window=combo,
            width=max(120, width * scale), height=max(24, 26 * scale))

        combo.bind('<<ComboboxSelected>>',
                   lambda e: self._close_inline(commit=True))
        combo.bind('<Escape>', lambda e: self._close_inline(commit=False))
        combo.focus_set()
        try:
            combo.event_generate('<Button-1>')   # já abre a lista
        except tk.TclError:
            pass

    def _edit_annotation(self, ann, mx, my):
        comp = self.model.get('_computed', {})
        nx = comp.get('notes_col_x', mx)
        nw = comp.get('notes_col_width', 280)

        def commit(text):
            if text and text != ann['label']:
                ann['label'] = text
                self._commit()
        self._open_inline(nx + nw / 2, my, nw - 24, ann['label'], commit)

    def _open_inline(self, cx, cy, width, initial, on_commit, allow_empty=False):
        """Abre um campo de edição sobre o canvas na posição indicada.

        `cx/cy/width` vêm em espaço de modelo; a janelinha é posicionada na
        vista, para acompanhar o zoom e cair exatamente sobre a forma.
        """
        self._close_inline(commit=False)
        scale = self.viewport.scale

        entry = tk.Entry(self.canvas, font=(FONT, max(7, int(round(9 * scale)))),
                         justify='center', relief='solid', bd=1,
                         bg='#fffbe6', fg='#000000',
                         insertbackground='#000000',
                         highlightthickness=1, highlightcolor='#003399')
        entry.insert(0, initial)
        entry.select_range(0, 'end')
        entry.icursor('end')

        self._inline_widget = entry
        self._inline_commit = on_commit
        self._inline_allow_empty = allow_empty
        vx, vy = self.viewport.to_view(cx, cy)
        self._inline_window = self.canvas.create_window(
            vx, vy, window=entry,
            width=max(80, width * scale), height=max(22, 26 * scale))

        entry.bind('<Return>', lambda e: self._close_inline(commit=True))
        entry.bind('<Escape>', lambda e: self._close_inline(commit=False))
        entry.bind('<FocusOut>', lambda e: self._close_inline(commit=True))
        entry.focus_set()

    def _close_inline(self, commit=False):
        """Fecha o campo de edição inline, aplicando ou descartando o texto.

        Destruir o Entry dispara outro FocusOut, que reentraria aqui: em
        máquina lenta isso comitava texto pela metade ou o perdia. A trava
        `_inline_closing` garante um único fechamento por edição.
        """
        if not self._inline_widget or self._inline_closing:
            return
        self._inline_closing = True
        try:
            widget = self._inline_widget
            window = self._inline_window
            on_commit = self._inline_commit
            allow_empty = getattr(self, '_inline_allow_empty', False)
            # Limpar referências antes do callback (FocusOut dispara ao destruir)
            self._inline_widget = None
            self._inline_window = None
            self._inline_commit = None
            self._inline_allow_empty = False

            try:
                text = widget.get().strip()
            except tk.TclError:
                text = ''
            try:
                if window:
                    self.canvas.delete(window)
                widget.destroy()
            except tk.TclError:
                pass
            if commit and on_commit and (text or allow_empty):
                on_commit(text)
        finally:
            self._inline_closing = False

    # ── Highlight de seleção ───────────────────────────────

    def _draw_highlight(self, node):
        """Desenha o realce de seleção acompanhando a forma real do nó."""
        self._clear_highlight()
        pts = node_outline(node)
        # Afastar o contorno do centro para o realce não colar na borda
        cx = sum(pts[0::2]) / (len(pts) / 2)
        cy = sum(pts[1::2]) / (len(pts) / 2)
        inflado = []
        for i in range(0, len(pts), 2):
            dx, dy = pts[i] - cx, pts[i + 1] - cy
            norma = max(1.0, (dx * dx + dy * dy) ** 0.5)
            vx, vy = self.viewport.to_view(pts[i] + dx / norma * 5,
                                           pts[i + 1] + dy / norma * 5)
            inflado.extend([vx, vy])
        self._highlight_id = self.canvas.create_polygon(
            inflado, fill='', outline='#003399', width=2, dash=(4, 2),
            tags=('highlight',))

    def _update_highlight(self, node):
        """Atualiza posição do highlight."""
        if self._highlight_id:
            self.canvas.delete(self._highlight_id)
        self._draw_highlight(node)

    def _clear_highlight(self):
        """Remove highlight."""
        self.canvas.delete('edge_sel')
        if self._highlight_id:
            self.canvas.delete(self._highlight_id)
            self._highlight_id = None
