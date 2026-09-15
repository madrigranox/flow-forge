"""
outline_panel.py — Índice do documento: nós, lacunas e pendências.

Num fluxo de porte real o desenho passa de 4.000px de altura contra uma área
útil de ~770. Sem um índice, achar um nó era rolar às cegas: a única navegação
que existia era a correção guiada, que só entra em cena quando há pendência.

As três listas aqui respondem a três perguntas diferentes que o usuário faz
olhando o mesmo documento:

- **Etapas** — "onde está a atividade X?"
- **Lacunas** — "o que a reunião deixou em aberto?" As anotações `Gap:` que a
  IA escreve ao ler a transcrição são o resultado mais valioso do mapeamento,
  e viviam só como texto cinza na coluna lateral do PDF.
- **Pendências** — "o que falta para eu conseguir publicar?"

Clicar em qualquer linha seleciona o elemento e traz o canvas até ele.
"""
import tkinter as tk

BG_PANEL = '#e6ebf5'
BG_CARD = '#ffffff'
FG_TITULO = '#262626'
TEXT_MUTED = '#4d4d4d'
ACCENT = '#003399'
BORDER = '#ccd6eb'
WARN = '#d13438'
WINE = '#7b2149'

# Marcador por tipo de nó, o mesmo vocabulário da paleta de ferramentas
MARCA = {'start': '⬭', 'end': '▬', 'decision': '⬡', 'task': '▭',
         'subprocess': '⚠', 'parallel': '║', 'annotation': '💬'}


class OutlinePanel(tk.Frame):
    """Painel lateral de navegação. Só lê o modelo; navegar é do AppWindow."""

    def __init__(self, parent, on_goto_node=None, on_goto_issue=None, **kw):
        super().__init__(parent, **kw)
        self.configure(bg=BG_PANEL)
        self.on_goto_node = on_goto_node
        self.on_goto_issue = on_goto_issue

        self._model = None
        self._issues = []
        self._filtro = ''
        self._selecionado = None
        self._linhas = {}      # node_id -> widget da linha, para realçar

        cab = tk.Frame(self, bg=BG_PANEL)
        cab.pack(fill='x', padx=12, pady=(14, 6))
        tk.Label(cab, text='☰', font=('Segoe UI', 12), bg=BG_PANEL).pack(side='left')
        tk.Label(cab, text='  Índice', font=('Segoe UI', 12, 'bold'),
                 fg=FG_TITULO, bg=BG_PANEL).pack(side='left')
        self.lbl_contagem = tk.Label(cab, text='', font=('Segoe UI', 8),
                                     fg=TEXT_MUTED, bg=BG_PANEL)
        self.lbl_contagem.pack(side='right')

        busca = tk.Frame(self, bg=BG_PANEL)
        busca.pack(fill='x', padx=12, pady=(0, 8))
        self.ent_busca = tk.Entry(busca, font=('Segoe UI', 9), relief='solid',
                                  bd=1, highlightthickness=1,
                                  highlightcolor=ACCENT)
        self.ent_busca.pack(fill='x')
        self.ent_busca.bind('<KeyRelease>', self._on_busca)
        self.ent_busca.bind('<Escape>', lambda e: self._limpar_busca())
        self._placeholder()

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

    # ── Busca ──────────────────────────────────────────────

    def _placeholder(self):
        self.ent_busca.delete(0, 'end')
        self.ent_busca.insert(0, 'Buscar etapa…')
        self.ent_busca.configure(fg=TEXT_MUTED)
        self.ent_busca.bind('<FocusIn>', self._limpar_placeholder)

    def _limpar_placeholder(self, event=None):
        if self.ent_busca.cget('fg') == TEXT_MUTED:
            self.ent_busca.delete(0, 'end')
            self.ent_busca.configure(fg=FG_TITULO)

    def _on_busca(self, event=None):
        if self.ent_busca.cget('fg') == TEXT_MUTED:
            return
        self._filtro = self.ent_busca.get().strip().casefold()
        self.refresh()

    def _limpar_busca(self):
        self._filtro = ''
        self.ent_busca.delete(0, 'end')
        self.ent_busca.configure(fg=FG_TITULO)
        self.refresh()

    def focar_busca(self):
        """Ctrl+F: leva o cursor para o campo de busca."""
        self._limpar_placeholder()
        self.ent_busca.focus_set()

    # ── Conteúdo ───────────────────────────────────────────

    def set_document(self, model, issues=None):
        self._model = model
        self._issues = list(issues or [])
        self.refresh()

    def marcar_selecionado(self, node_id):
        """Realça no índice o nó que está selecionado no canvas."""
        self._selecionado = node_id
        for nid, linha in self._linhas.items():
            cor = '#dce5f7' if nid == node_id else BG_CARD
            linha.configure(bg=cor)
            for w in linha.winfo_children():
                try:
                    w.configure(bg=cor)
                except tk.TclError:
                    pass

    def refresh(self):
        for w in self._corpo.winfo_children():
            w.destroy()
        self._linhas = {}
        if not self._model:
            self.lbl_contagem.configure(text='')
            tk.Label(self._corpo, text='Nenhum fluxograma aberto.',
                     font=('Segoe UI', 9), fg=TEXT_MUTED, bg=BG_PANEL).pack(
                         anchor='w', padx=6, pady=8)
            return

        nos = [n for n in self._model['nodes'] if n.get('type') != 'annotation']
        lacunas = (self._model.get('_computed', {}) or {}).get('notes', [])
        self.lbl_contagem.configure(
            text=f'{len(nos)} etapas · {len(lacunas)} lacunas')

        self._secao_pendencias()
        self._secao_lacunas(lacunas)
        self._secao_etapas(nos)

    # ── Seções ─────────────────────────────────────────────

    def _titulo_secao(self, texto, cor=TEXT_MUTED):
        tk.Label(self._corpo, text=texto.upper(), font=('Segoe UI', 8, 'bold'),
                 fg=cor, bg=BG_PANEL).pack(anchor='w', padx=6, pady=(10, 4))

    def _linha(self, marca, texto, cor_marca, comando, node_id=None,
               sub=None):
        linha = tk.Frame(self._corpo, bg=BG_CARD, cursor='hand2')
        linha.pack(fill='x', padx=4, pady=1)
        m = tk.Label(linha, text=marca, font=('Segoe UI', 9), fg=cor_marca,
                     bg=BG_CARD, width=2)
        m.pack(side='left', padx=(8, 4), pady=5)
        caixa = tk.Frame(linha, bg=BG_CARD)
        caixa.pack(side='left', fill='x', expand=True, pady=4)
        tk.Label(caixa, text=texto, font=('Segoe UI', 9), fg=FG_TITULO,
                 bg=BG_CARD, anchor='w', justify='left',
                 wraplength=196).pack(fill='x')
        if sub:
            tk.Label(caixa, text=sub, font=('Segoe UI', 8), fg=TEXT_MUTED,
                     bg=BG_CARD, anchor='w').pack(fill='x')
        for w in [linha, m, caixa] + list(caixa.winfo_children()):
            w.bind('<Button-1>', lambda e, c=comando: c())
        if node_id:
            self._linhas[node_id] = linha
        return linha

    def _secao_pendencias(self):
        if not self._issues:
            return
        self._titulo_secao(f'Pendências ({len(self._issues)})', WARN)
        for issue in self._issues[:12]:
            nid = issue.get('node_id')
            self._linha('!', issue.get('msg', ''), WARN,
                        lambda i=issue: self._ir_issue(i), sub=None)

    def _secao_lacunas(self, lacunas):
        # Pontos marcados "em aberto" nos nós entram na MESMA lista das
        # anotações: para quem lê, as duas coisas são a mesma pergunta — "o que
        # este processo ainda não resolveu?".
        abertos = []
        for i in self._issues:
            if i.get('kind') == 'ponto_em_aberto' and i.get('node_id'):
                abertos.append(i)
        if not lacunas and not abertos:
            return
        visiveis = [n for n in lacunas
                    if not self._filtro or self._filtro in n['text'].casefold()]
        abertos_vis = [i for i in abertos
                       if not self._filtro or self._filtro in i['msg'].casefold()]
        if not visiveis and not abertos_vis:
            return
        total = len(lacunas) + len(abertos)
        self._titulo_secao(f'Lacunas do processo ({total})', WINE)

        nos = {n['id']: n for n in self._model['nodes']}
        for i in abertos_vis:
            no = nos.get(i['node_id'], {})
            props = no.get('props') or {}
            texto = props.get('pergunta') or 'ponto em aberto'
            self._linha('?', texto, '#b8860b',
                        lambda a=i['node_id']: self._ir_no(a),
                        sub=f"em: {(no.get('label') or i['node_id'])[:34]}")
        for nota in visiveis:
            ref = nota.get('ref_node')
            alvo = ref['id'] if ref else None
            sub = f"em: {ref['label'][:34]}" if ref else 'sem etapa associada'
            self._linha(str(nota['number']), nota['text'], WINE,
                        lambda a=alvo: self._ir_no(a) if a else None, sub=sub)

    def _secao_etapas(self, nos):
        lanes = {l['id']: l for l in self._model['lanes']}
        visiveis = [n for n in nos
                    if not self._filtro
                    or self._filtro in (n.get('label') or '').casefold()
                    or self._filtro in n['id'].casefold()]
        titulo = 'Etapas'
        if self._filtro:
            titulo = f'Etapas ({len(visiveis)} de {len(nos)})'
        self._titulo_secao(titulo)
        if not visiveis:
            tk.Label(self._corpo, text='Nada encontrado.', font=('Segoe UI', 9),
                     fg=TEXT_MUTED, bg=BG_PANEL).pack(anchor='w', padx=10, pady=6)
            return
        for n in visiveis:
            lane = lanes.get(n.get('laneId'))
            sub = lane['label'] if lane else ''
            self._linha(MARCA.get(n.get('type'), '▭'),
                        n.get('label') or n['id'], ACCENT,
                        lambda i=n['id']: self._ir_no(i),
                        node_id=n['id'], sub=sub)

    # ── Navegação ──────────────────────────────────────────

    def _ir_no(self, node_id):
        if node_id and self.on_goto_node:
            self.on_goto_node(node_id)

    def _ir_issue(self, issue):
        if self.on_goto_issue:
            self.on_goto_issue(issue)
        elif issue.get('node_id'):
            self._ir_no(issue['node_id'])
