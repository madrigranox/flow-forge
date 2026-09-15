"""
properties_panel.py — Painel de propriedades do elemento selecionado.

Substitui o painel JSON como porta principal de edição. Duas seções:

- **Atores do fluxo** — cada coluna com sua ÁREA e seu CARGO, ambos escolhidos
  do catálogo corporativo (`core/catalogo.py`), e o cargo restrito aos que
  existem na área escolhida. Eram texto livre, e daí saíam "Manutenção",
  "Manutencao" e "Setor de Manutenção" no mesmo acervo. É também daqui que se
  acrescenta ou remove um ator do processo — um fluxo é interdepartamental, e
  quem participa dele muda ao longo do mapeamento.
- **Nó selecionado** — tipo, coluna e rótulo, em um passo em vez de três.

Toda alteração daqui passa pelos setters do `Editor`, ou seja, pelo mesmo
ponto único de mutação do canvas: um passo de histórico, revalidação e
sincronização do JSON avançado, sem uma segunda porta de escrita.
"""
import tkinter as tk
from tkinter import ttk

from core.editor import NEW_NODE_TYPES
from core import catalogo as cat

BG_PANEL = '#e6ebf5'
BG_CARD = '#ffffff'
FG_TITULO = '#262626'
TEXT_MUTED = '#4d4d4d'
ACCENT = '#003399'
BORDER = '#ccd6eb'
WARN = '#d13438'

# Rótulo amigável por tipo de nó, na ordem da paleta de ferramentas
TIPOS = [(t, rotulo.split('  ', 1)[-1]) for t, rotulo, _ in NEW_NODE_TYPES]
TIPO_POR_ROTULO = {rotulo: t for t, rotulo in TIPOS}
ROTULO_POR_TIPO = dict(TIPOS)


class PropertiesPanel(tk.Frame):
    """Painel lateral de propriedades — leitura sempre, edição no modo edição."""

    def __init__(self, parent, on_node_type=None, on_node_lane=None,
                 on_node_label=None, on_department=None, on_lane_label=None,
                 on_edit_catalog=None, on_lane_department=None,
                 on_add_lane=None, on_remove_lane=None, on_move_lane=None,
                 on_ponto_aberto=None, on_edge_label=None, **kw):
        super().__init__(parent, **kw)
        self.configure(bg=BG_PANEL)
        self.on_node_type = on_node_type
        self.on_node_lane = on_node_lane
        self.on_node_label = on_node_label
        self.on_department = on_department
        self.on_lane_label = on_lane_label
        self.on_edit_catalog = on_edit_catalog
        self.on_lane_department = on_lane_department
        self.on_add_lane = on_add_lane
        self.on_remove_lane = on_remove_lane
        self.on_move_lane = on_move_lane
        self.on_ponto_aberto = on_ponto_aberto
        self.on_edge_label = on_edge_label

        self._node = None
        self._edge = None
        self._lanes = []
        self._catalogo = {'departamentos': []}
        self._editavel = False
        self._silencioso = False   # evita eco ao preencher os campos por código
        self._linhas_lane = []
        self._areas = []
        self._model_nodes = []

        cabecalho = tk.Frame(self, bg=BG_PANEL)
        cabecalho.pack(fill='x', padx=12, pady=(14, 6))
        tk.Label(cabecalho, text='⚙', font=('Segoe UI', 13),
                 bg=BG_PANEL).pack(side='left')
        tk.Label(cabecalho, text='  Propriedades', font=('Segoe UI', 12, 'bold'),
                 fg=FG_TITULO, bg=BG_PANEL).pack(side='left')

        # Rolagem: com muitas lanes a seção do documento passa da altura útil
        casca = tk.Frame(self, bg=BG_PANEL)
        casca.pack(fill='both', expand=True, padx=8, pady=(0, 10))
        self._canvas = tk.Canvas(casca, bg=BG_PANEL, highlightthickness=0)
        barra = tk.Scrollbar(casca, orient='vertical', command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=barra.set)
        barra.pack(side='right', fill='y')
        self._canvas.pack(side='left', fill='both', expand=True)
        self._corpo = tk.Frame(self._canvas, bg=BG_PANEL)
        self._janela = self._canvas.create_window((0, 0), window=self._corpo,
                                                  anchor='nw')
        self._corpo.bind('<Configure>', lambda e: self._canvas.configure(
            scrollregion=self._canvas.bbox('all')))
        self._canvas.bind('<Configure>', lambda e: self._canvas.itemconfigure(
            self._janela, width=e.width))
        self._canvas.bind('<MouseWheel>', lambda e: self._canvas.yview_scroll(
            int(-1 * (e.delta / 120)), 'units'))

        self._montar_documento()
        self._montar_no()
        self._montar_conexao()
        self.clear()

    # ── Montagem ───────────────────────────────────────────

    def _cartao(self, titulo, dica=None):
        card = tk.Frame(self._corpo, bg=BG_CARD, highlightthickness=1,
                        highlightbackground=BORDER)
        card.pack(fill='x', padx=4, pady=(0, 10))
        tk.Label(card, text=titulo.upper(), font=('Segoe UI', 8, 'bold'),
                 fg=TEXT_MUTED, bg=BG_CARD).pack(anchor='w', padx=12,
                                                 pady=(10, 2))
        if dica:
            tk.Label(card, text=dica, font=('Segoe UI', 8), fg=TEXT_MUTED,
                     bg=BG_CARD, justify='left', wraplength=230).pack(
                         anchor='w', padx=12, pady=(0, 4))
        return card

    def _campo(self, pai, rotulo):
        linha = tk.Frame(pai, bg=BG_CARD)
        linha.pack(fill='x', padx=12, pady=(4, 2))
        tk.Label(linha, text=rotulo, font=('Segoe UI', 8), fg=TEXT_MUTED,
                 bg=BG_CARD).pack(anchor='w')
        return linha

    def _montar_documento(self):
        card = self._cartao(
            'Atores do fluxo',
            'Um fluxo atravessa várias áreas. Cada coluna é um ator: escolha a '
            'área e, dentro dela, o cargo.')

        self.lanes_box = tk.Frame(card, bg=BG_CARD)
        self.lanes_box.pack(fill='x')

        self.lbl_banner = tk.Label(card, text='', font=('Segoe UI', 8),
                                   fg=TEXT_MUTED, bg=BG_CARD, justify='left',
                                   wraplength=230, anchor='w')
        self.lbl_banner.pack(fill='x', padx=12, pady=(6, 0))

        rodape = tk.Frame(card, bg=BG_CARD)
        rodape.pack(fill='x', padx=12, pady=(6, 10))
        self.btn_add_lane = tk.Button(
            rodape, text='＋  Adicionar coluna', font=('Segoe UI', 8, 'bold'),
            bg=BG_CARD, fg=ACCENT, activebackground=BG_CARD,
            activeforeground=ACCENT, bd=0, relief='flat', cursor='hand2',
            anchor='w', padx=0,
            command=lambda: self._disparar_direto(self.on_add_lane))
        self.btn_add_lane.pack(anchor='w')
        self.btn_catalogo = tk.Button(
            rodape, text='✎  Editar catálogo…', font=('Segoe UI', 8),
            bg=BG_CARD, fg=ACCENT, activebackground=BG_CARD,
            activeforeground=ACCENT, bd=0, relief='flat', cursor='hand2',
            anchor='w', padx=0, command=lambda: self._disparar_direto(
                self.on_edit_catalog))
        self.btn_catalogo.pack(anchor='w')
        self.aviso_catalogo = tk.Label(card, text='', font=('Segoe UI', 8),
                                       fg=WARN, bg=BG_CARD, justify='left',
                                       wraplength=230)

    def _montar_no(self):
        card = self._cartao('Nó selecionado')
        self.card_no = card

        linha = self._campo(card, 'Tipo')
        self.cb_tipo = ttk.Combobox(linha, state='readonly',
                                    font=('Segoe UI', 9),
                                    values=[r for _, r in TIPOS])
        self.cb_tipo.pack(fill='x')
        self.cb_tipo.bind('<<ComboboxSelected>>', lambda e: self._disparar(
            self.on_node_type, TIPO_POR_ROTULO.get(self.cb_tipo.get())))

        linha = self._campo(card, 'Coluna (lane)')
        self.cb_lane = ttk.Combobox(linha, state='readonly',
                                    font=('Segoe UI', 9))
        self.cb_lane.pack(fill='x')
        self.cb_lane.bind('<<ComboboxSelected>>', lambda e: self._disparar(
            self.on_node_lane, self._lane_id_do_rotulo(self.cb_lane.get())))

        linha = self._campo(card, 'Rótulo')
        self.ent_rotulo = tk.Entry(linha, font=('Segoe UI', 9), relief='solid',
                                   bd=1, highlightthickness=1,
                                   highlightcolor=ACCENT)
        self.ent_rotulo.pack(fill='x')
        self.ent_rotulo.bind('<Return>', lambda e: self._commit_rotulo())
        self.ent_rotulo.bind('<FocusOut>', lambda e: self._commit_rotulo())

        # Ponto em aberto: o que o processo ainda não decidiu. Fica aqui, no
        # painel onde a pessoa já está olhando — não atrás de um gesto.
        sep = tk.Frame(card, bg=BORDER, height=1)
        sep.pack(fill='x', padx=12, pady=(8, 6))
        self.var_aberto = tk.BooleanVar(value=False)
        self.chk_aberto = tk.Checkbutton(
            card, text=' Ponto em aberto', variable=self.var_aberto,
            font=('Segoe UI', 9), bg=BG_CARD, fg='#8a5a00', anchor='w',
            activebackground=BG_CARD, selectcolor='#ffffff', bd=0,
            highlightthickness=0, command=self._commit_aberto)
        self.chk_aberto.pack(fill='x', padx=10)
        self.ent_pergunta = tk.Entry(card, font=('Segoe UI', 9), relief='solid',
                                     bd=1, highlightthickness=1,
                                     highlightcolor=ACCENT, fg=TEXT_MUTED)
        self.ent_pergunta.pack(fill='x', padx=12, pady=(2, 0))
        self.ent_pergunta.bind('<Return>', lambda e: self._commit_aberto())
        self.ent_pergunta.bind('<FocusOut>', lambda e: self._commit_aberto())
        tk.Label(card, text='O que falta decidir (aparece no índice e no PDF)',
                 font=('Segoe UI', 8), fg=TEXT_MUTED, bg=BG_CARD,
                 anchor='w').pack(fill='x', padx=12, pady=(1, 4))

        self.lbl_vazio = tk.Label(card, text='Selecione um nó no fluxograma.',
                                  font=('Segoe UI', 8), fg=TEXT_MUTED,
                                  bg=BG_CARD, justify='left', wraplength=230)
        self.lbl_vazio.pack(anchor='w', padx=12, pady=(4, 10))

    def _montar_conexao(self):
        """Cartão da conexão selecionada — é aqui que mora o Sim/Não."""
        card = self._cartao('Conexão selecionada')
        self.card_conexao = card

        self.lbl_conexao = tk.Label(card, text='', font=('Segoe UI', 9),
                                    fg=TEXT_MUTED, bg=BG_CARD, anchor='w',
                                    justify='left', wraplength=230)
        self.lbl_conexao.pack(fill='x', padx=12, pady=(0, 2))

        linha = self._campo(card, 'Rótulo (Sim / Não / condição)')
        self.ent_edge = tk.Entry(linha, font=('Segoe UI', 9), relief='solid',
                                 bd=1, highlightthickness=1,
                                 highlightcolor=ACCENT)
        self.ent_edge.pack(fill='x')
        self.ent_edge.bind('<Return>', lambda e: self._commit_edge())
        self.ent_edge.bind('<FocusOut>', lambda e: self._commit_edge())

        atalhos = tk.Frame(card, bg=BG_CARD)
        atalhos.pack(fill='x', padx=12, pady=(4, 10))
        for texto in ('Sim', 'Não'):
            tk.Button(atalhos, text=texto, font=('Segoe UI', 8),
                      bg=BG_PANEL, fg=FG_TITULO, bd=0, relief='flat',
                      cursor='hand2', padx=10, pady=2,
                      command=lambda t=texto: self._atalho_edge(t)).pack(
                          side='left', padx=(0, 6))

    def _atalho_edge(self, texto):
        if not self._editavel or self._edge is None:
            return
        self.ent_edge.delete(0, 'end')
        self.ent_edge.insert(0, texto)
        self._commit_edge()

    def _commit_edge(self):
        if self._silencioso or not self._editavel or self._edge is None:
            return
        if self.on_edge_label:
            self.on_edge_label(self.ent_edge.get().strip())

    def show_edge(self, edge):
        """Mostra a conexão selecionada e esconde o cartão de nó."""
        self._edge = edge
        if edge is not None:
            # Só uma coisa fica selecionada por vez. Mas limpar o nó também
            # quando `edge` é None apagava a seleção recém-feita: quem escolhe
            # um nó chama show(no) e, logo depois, show_edge(None) para
            # esconder o cartão de conexão.
            self._node = None
        self._silencioso = True
        try:
            if edge is None:
                self._preencher(self.ent_edge, '')
                self.lbl_conexao.configure(text='Selecione uma conexão.')
            else:
                nos = {n['id']: n for n in (self._model_nodes or [])}
                origem = (nos.get(edge['from'], {}).get('label')
                          or edge['from'])
                destino = (nos.get(edge['to'], {}).get('label') or edge['to'])
                self.lbl_conexao.configure(text=f'{origem}  →  {destino}')
                self._preencher(self.ent_edge, edge.get('label', '') or '')
        finally:
            self._silencioso = False
        self._aplicar_estado()

    # ── Disparo dos callbacks ──────────────────────────────

    def _disparar(self, callback, valor):
        if self._silencioso or not self._editavel or callback is None:
            return
        if valor is not None:
            callback(valor)

    def _disparar_direto(self, callback):
        if callback:
            callback()

    def _preencher(self, entry, texto):
        """Escreve num Entry mesmo que ele esteja desabilitado no momento.

        Um `tk.Entry` em `state='disabled'` ignora `insert()` **em silêncio**.
        Como o preenchimento acontece antes de `_aplicar_estado()` decidir o
        estado final, escrever direto deixava o campo vazio toda vez que a
        seleção vinha de um estado desabilitado — o valor existia no modelo e
        o painel mostrava nada.
        """
        estado = entry.cget('state')
        if estado != 'normal':
            entry.configure(state='normal')
        entry.delete(0, 'end')
        if texto:
            entry.insert(0, texto)
        if estado != 'normal':
            entry.configure(state=estado)

    def _commit_aberto(self):
        if self._silencioso or not self._editavel or not self._node:
            return
        if self.on_ponto_aberto:
            self.on_ponto_aberto(self.var_aberto.get(),
                                 self.ent_pergunta.get().strip())

    def _commit_rotulo(self):
        if self._silencioso or not self._editavel or not self._node:
            return
        texto = self.ent_rotulo.get().strip()
        if texto != (self._node.get('label') or ''):
            self._disparar(self.on_node_label, texto)

    def _lane_id_do_rotulo(self, rotulo):
        for lane in self._lanes:
            if self._rotulo_lane(lane) == rotulo:
                return lane['id']
        return None

    # ── Estado ─────────────────────────────────────────────

    def set_catalogo(self, catalogo):
        self._catalogo = catalogo or {'departamentos': []}
        self._areas = cat.nomes_departamentos(self._catalogo)
        for linha in self._linhas_lane:
            linha['area'].configure(values=self._areas)
            self._atualizar_cargos_da_linha(linha)
        self._checar_catalogo()

    def set_document(self, model):
        """Preenche a lista de atores (uma linha por coluna do fluxograma)."""
        self._silencioso = True
        try:
            self._lanes = list(model['lanes']) if model else []
            self._model_nodes = list(model['nodes']) if model else []
            self._montar_linhas_lane()
            self.cb_lane.configure(values=[self._rotulo_lane(l)
                                           for l in self._lanes])
            banner = (model or {}).get('department', '')
            self.lbl_banner.configure(
                text=f'Banner do documento: {banner}' if banner else '')
        finally:
            self._silencioso = False
        self._checar_catalogo()

    def _rotulo_lane(self, lane):
        """Como a coluna aparece no seletor do nó: cargo (área)."""
        area = lane.get('department', '')
        return f"{lane.get('label', '')} ({area})" if area else lane.get('label', '')

    def _montar_linhas_lane(self):
        for w in self.lanes_box.winfo_children():
            w.destroy()
        self._linhas_lane = []
        if not self._lanes:
            tk.Label(self.lanes_box, text='Nenhuma coluna ainda.',
                     font=('Segoe UI', 8), fg=TEXT_MUTED, bg=BG_CARD).pack(
                         anchor='w', padx=12, pady=(6, 2))
            return

        for i, lane in enumerate(self._lanes, start=1):
            bloco = tk.Frame(self.lanes_box, bg=BG_CARD)
            bloco.pack(fill='x', padx=12, pady=(8, 2))

            topo = tk.Frame(bloco, bg=BG_CARD)
            topo.pack(fill='x')
            tk.Label(topo, text=f'Coluna {i}', font=('Segoe UI', 8, 'bold'),
                     fg=TEXT_MUTED, bg=BG_CARD).pack(side='left')
            btn_x = tk.Button(topo, text='✕', font=('Segoe UI', 8),
                              bg=BG_CARD, fg=WARN, activebackground=BG_CARD,
                              activeforeground=WARN, bd=0, relief='flat',
                              cursor='hand2', padx=2, pady=0,
                              command=lambda lid=lane['id']:
                              self._remover_lane(lid))
            btn_x.pack(side='right')

            # A ordem das colunas é a ordem de leitura do processo: as setas
            # movem a coluna na horizontal, que é como ela aparece no desenho.
            btn_dir = tk.Button(topo, text='▶', font=('Segoe UI', 7),
                                bg=BG_CARD, fg=ACCENT, activebackground=BG_CARD,
                                activeforeground=ACCENT, bd=0, relief='flat',
                                cursor='hand2', padx=2, pady=0,
                                command=lambda lid=lane['id']:
                                self._mover_lane(lid, 1))
            btn_dir.pack(side='right', padx=(0, 6))
            btn_esq = tk.Button(topo, text='◀', font=('Segoe UI', 7),
                                bg=BG_CARD, fg=ACCENT, activebackground=BG_CARD,
                                activeforeground=ACCENT, bd=0, relief='flat',
                                cursor='hand2', padx=2, pady=0,
                                command=lambda lid=lane['id']:
                                self._mover_lane(lid, -1))
            btn_esq.pack(side='right')

            cb_area = ttk.Combobox(bloco, state='readonly',
                                   font=('Segoe UI', 9),
                                   values=getattr(self, '_areas', []))
            cb_area.pack(fill='x', pady=(2, 1))
            cb_cargo = ttk.Combobox(bloco, state='readonly',
                                    font=('Segoe UI', 9))
            cb_cargo.pack(fill='x')

            linha = {'lane_id': lane['id'], 'area': cb_area, 'combo': cb_cargo,
                     'remover': btn_x, 'esq': btn_esq, 'dir': btn_dir,
                     'primeira': i == 1, 'ultima': i == len(self._lanes)}
            self._set_combo(cb_area, lane.get('department', ''))
            self._atualizar_cargos_da_linha(linha, lane.get('label', ''))

            cb_area.bind('<<ComboboxSelected>>',
                         lambda e, l=linha: self._disparar_area(l))
            cb_cargo.bind('<<ComboboxSelected>>',
                          lambda e, l=linha: self._disparar_lane(l))
            self._linhas_lane.append(linha)
        self._aplicar_estado()

    def _atualizar_cargos_da_linha(self, linha, valor=None):
        """Os cargos oferecidos são os que existem na área escolhida.

        É isso que impede a combinação impossível — um "Comandante" dentro de
        "Tecnologia da Informação".
        """
        area = linha['area'].get()
        cargos = (cat.cargos_de(area, self._catalogo) if area
                  else cat.todos_cargos(self._catalogo))
        atual = valor if valor is not None else linha['combo'].get()
        linha['combo'].configure(values=cargos)
        self._set_combo(linha['combo'], atual)

    def _disparar_area(self, linha):
        if self._silencioso or not self._editavel:
            return
        self._atualizar_cargos_da_linha(linha, valor='')
        if self.on_lane_department:
            self.on_lane_department(linha['lane_id'], linha['area'].get())

    def _disparar_lane(self, linha):
        if self._silencioso or not self._editavel or not self.on_lane_label:
            return
        self.on_lane_label(linha['lane_id'], linha['combo'].get())

    def _remover_lane(self, lane_id):
        if self._editavel and self.on_remove_lane:
            self.on_remove_lane(lane_id)

    def _mover_lane(self, lane_id, delta):
        if self._editavel and self.on_move_lane:
            self.on_move_lane(lane_id, delta)

    def _set_combo(self, combo, valor):
        """Mostra o valor atual mesmo quando ele não está no catálogo.

        Um documento antigo pode trazer um nome fora da lista; escondê-lo faria
        o painel mentir sobre o que está no arquivo. Ele aparece, e o aviso de
        padronização diz que está fora — a correção é escolha do usuário.
        """
        valores = list(combo.cget('values'))
        if valor and valor not in valores:
            combo.configure(values=[valor] + valores)
        combo.set(valor or '')

    def show(self, node, model=None):
        """Mostra as propriedades do nó selecionado."""
        self._node = node
        if node is not None:
            self._edge = None
        if model is not None:
            self.set_document(model)
        self._silencioso = True
        try:
            if node is None:
                self.cb_tipo.set('')
                self.cb_lane.set('')
                self._preencher(self.ent_rotulo, '')
                self.var_aberto.set(False)
                self._preencher(self.ent_pergunta, '')
                self.lbl_vazio.configure(
                    text='Selecione um nó no fluxograma.')
            else:
                self.cb_tipo.set(ROTULO_POR_TIPO.get(node.get('type', ''),
                                                     node.get('type', '')))
                lane = next((l for l in self._lanes
                             if l['id'] == node.get('laneId')), None)
                self.cb_lane.set(self._rotulo_lane(lane) if lane else '')
                self._preencher(self.ent_rotulo, node.get('label') or '')
                props = node.get('props') or {}
                self.var_aberto.set(bool(props.get('em_aberto')))
                self._preencher(self.ent_pergunta, props.get('pergunta', '') or '')
                self.lbl_vazio.configure(text=f"id: {node['id']}")
        finally:
            self._silencioso = False
        self._aplicar_estado()

    def clear(self):
        self.show(None)

    def set_editable(self, editavel):
        """Fora do modo edição os campos mostram, mas não deixam mexer."""
        self._editavel = bool(editavel)
        self._aplicar_estado()

    def _aplicar_estado(self):
        tem_no = self._node is not None
        estado_combo = 'readonly' if self._editavel else 'disabled'
        for linha in self._linhas_lane:
            linha['area'].configure(state=estado_combo)
            linha['combo'].configure(state=estado_combo)
            linha['remover'].configure(
                state='normal' if self._editavel else 'disabled')
            linha['esq'].configure(
                state='normal' if (self._editavel and not linha['primeira'])
                else 'disabled')
            linha['dir'].configure(
                state='normal' if (self._editavel and not linha['ultima'])
                else 'disabled')
        self.btn_add_lane.configure(
            state='normal' if self._editavel else 'disabled')
        self.cb_tipo.configure(state=estado_combo if tem_no else 'disabled')
        self.cb_lane.configure(state=estado_combo if tem_no else 'disabled')
        self.ent_rotulo.configure(
            state='normal' if (self._editavel and tem_no) else 'disabled')
        tem_edge = self._edge is not None
        self.ent_edge.configure(
            state='normal' if (self._editavel and tem_edge) else 'disabled')
        self.chk_aberto.configure(
            state='normal' if (self._editavel and tem_no) else 'disabled')
        self.ent_pergunta.configure(
            state='normal' if (self._editavel and tem_no) else 'disabled')

    def _checar_catalogo(self):
        """Avisa, no próprio painel, o que está fora da lista corporativa."""
        fora = []
        for linha in self._linhas_lane:
            area = linha['area'].get()
            cargo = linha['combo'].get()
            if cat.fora_do_catalogo(area, 'departamentos', self._catalogo):
                fora.append(f'área "{area}"')
            if cat.fora_do_catalogo(cargo, 'cargos', self._catalogo,
                                    departamento=area):
                fora.append(f'cargo "{cargo}"')
        if fora:
            self.aviso_catalogo.configure(
                text='⚠ Fora do catálogo: ' + ', '.join(fora[:3]) +
                     ('…' if len(fora) > 3 else ''))
            self.aviso_catalogo.pack(anchor='w', padx=12, pady=(0, 10))
        else:
            self.aviso_catalogo.pack_forget()
