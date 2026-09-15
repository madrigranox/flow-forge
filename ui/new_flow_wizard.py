"""
new_flow_wizard.py — Assistente de criação de um fluxo novo.

Quatro passos, nesta ordem, porque cada um depende do anterior:

  1. **Departamentos** — um fluxo é interdepartamental; escolha as áreas.
  2. **Cargos** — dentro de cada área escolhida, quem são os atores. A ordem
     aqui é a ordem das colunas, da esquerda para a direita.
  3. **Prompt de IA** — já montado com as lanes resolvidas. É o passo que
     coloca rédeas na IA: ela deixa de inventar atores e só distribui as
     atividades entre os que foram escolhidos.
  4. **Resultado** — cola o JSON que a IA devolveu, valida ali mesmo e é ele
     que vira a primeira versão do arquivo.

O passo 4 é a razão de o programa existir em vez de um Visio: a ideia é chegar
ao fluxograma com a estrutura quase pronta e editar o mínimo. Quem preferir
montar à mão pula o passo e recebe o documento só com as colunas — a paleta de
ferramentas já vem ligada.
"""
import tkinter as tk
from tkinter import messagebox

from core import catalogo as cat
from core import prompt as prompt_mod
from core.parser import parse_flowchart, ParseError
from ui.catalog_dialog import botao

BG_PANEL = '#f2f5fa'
BG_CARD = '#ffffff'
ACCENT = '#003399'
BTN_FG = '#262626'
BORDER = '#ccd6eb'
TEXT_MUTED = '#4d4d4d'
OK_GREEN = '#107c10'
AVISO = '#b30000'

PASSOS = ('Departamentos', 'Cargos', 'Prompt de IA', 'Resultado')


class NewFlowWizard(tk.Toplevel):
    """Janela modal dos três passos. Devolve o documento em `self.resultado`."""

    def __init__(self, parent, catalogo=None, on_finish=None,
                 on_edit_catalog=None):
        super().__init__(parent)
        self.title('Novo fluxo')
        self.configure(bg=BG_PANEL)
        self.geometry('860x620')
        self.minsize(760, 560)
        self.transient(parent)
        self.catalogo = catalogo if catalogo is not None else cat.carregar()
        self.on_finish = on_finish
        self.on_edit_catalog = on_edit_catalog

        self.resultado = None
        self._passo = 0
        self._deps_escolhidos = []
        self._cargos_escolhidos = []      # lista de (departamento, cargo)
        self._vars_dep = {}
        self._vars_cargo = {}
        self._json_colado = None
        self._titulo = 'Novo fluxo'
        self._doc_code = ''
        # A ordem em que os cargos são marcados é a ordem das colunas: ela é a
        # leitura do processo, então seguir a ordem alfabética do catálogo
        # produziria um desenho que ninguém pediu.
        self._ordem_selecao = []

        self._montar_cabecalho()
        # O rodapé é empacotado ANTES do corpo, preso embaixo: o corpo tem
        # `expand=True` e, nos passos com área de texto, pede mais altura do que
        # a janela tem — o Tk então espremia justamente o último empacotado, que
        # era o rodapé. O botão "Avançar" existia, mas fora da tela, e não havia
        # como sair do passo do prompt.
        self._montar_rodape()
        self.corpo = tk.Frame(self, bg=BG_PANEL)
        self.corpo.pack(fill='both', expand=True, padx=16, pady=(0, 8))

        self.bind('<Escape>', lambda e: self.destroy())
        self._render_passo()

    # ── Estrutura fixa ─────────────────────────────────────

    def _montar_cabecalho(self):
        topo = tk.Frame(self, bg=BG_PANEL)
        topo.pack(fill='x', padx=16, pady=(14, 8))
        tk.Label(topo, text='Novo fluxo', font=('Segoe UI', 14, 'bold'),
                 bg=BG_PANEL, fg=BTN_FG).pack(anchor='w')
        self.trilha = tk.Frame(topo, bg=BG_PANEL)
        self.trilha.pack(anchor='w', pady=(6, 0))
        self._chips = []
        for i, nome in enumerate(PASSOS):
            chip = tk.Label(self.trilha, text=f'  {i + 1}. {nome}  ',
                            font=('Segoe UI', 9), bg=BG_PANEL, fg=TEXT_MUTED)
            chip.pack(side='left', padx=(0, 6))
            self._chips.append(chip)

    def _montar_rodape(self):
        rod = tk.Frame(self, bg=BG_PANEL)
        rod.pack(side='bottom', fill='x', padx=16, pady=(0, 14))
        self.lbl_resumo = tk.Label(rod, text='', font=('Segoe UI', 9),
                                   bg=BG_PANEL, fg=TEXT_MUTED, anchor='w')
        self.lbl_resumo.pack(side='left')
        self.btn_avancar = botao(rod, 'Avançar  ›', self._avancar, primario=True)
        self.btn_avancar.pack(side='right')
        self.btn_voltar = botao(rod, '‹  Voltar', self._voltar)
        self.btn_voltar.pack(side='right', padx=(0, 8))
        botao(rod, 'Cancelar', self.destroy).pack(side='right', padx=(0, 8))
        # Ninguém é obrigado a chegar ao fim: quem já escolheu os atores pode
        # criar o documento e montar à mão.
        self.btn_criar_agora = botao(rod, 'Criar agora', self._concluir)
        self.btn_criar_agora.pack(side='right', padx=(0, 8))

    def _limpar_corpo(self):
        for w in self.corpo.winfo_children():
            w.destroy()

    def _lista_rolavel(self, pai):
        """Área com rolagem — a lista de cargos passa da altura da janela."""
        casca = tk.Frame(pai, bg=BG_CARD, highlightthickness=1,
                         highlightbackground=BORDER)
        casca.pack(fill='both', expand=True)
        canvas = tk.Canvas(casca, bg=BG_CARD, highlightthickness=0)
        barra = tk.Scrollbar(casca, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=barra.set)
        barra.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        interno = tk.Frame(canvas, bg=BG_CARD)
        janela = canvas.create_window((0, 0), window=interno, anchor='nw')
        interno.bind('<Configure>',
                     lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',
                    lambda e: canvas.itemconfigure(janela, width=e.width))
        canvas.bind('<MouseWheel>',
                    lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units'))
        return interno

    # ── Navegação ──────────────────────────────────────────

    def _render_passo(self):
        for i, chip in enumerate(self._chips):
            ativo = i == self._passo
            feito = i < self._passo
            chip.configure(
                bg=ACCENT if ativo else BG_PANEL,
                fg='#ffffff' if ativo else (OK_GREEN if feito else TEXT_MUTED),
                font=('Segoe UI', 9, 'bold' if ativo else 'normal'),
                text=f"  {'✓' if feito else i + 1}. {PASSOS[i]}  ")
        self._limpar_corpo()
        self.btn_voltar.configure(state='normal' if self._passo else 'disabled')
        self.btn_criar_agora.configure(
            state='normal' if self._passo >= 2 else 'disabled')
        [self._passo_departamentos, self._passo_cargos,
         self._passo_prompt, self._passo_resultado][self._passo]()

    def _avancar(self):
        if self._passo == 0:
            self._deps_escolhidos = [d for d, v in self._vars_dep.items() if v.get()]
            if not self._deps_escolhidos:
                messagebox.showinfo('Novo fluxo',
                                    'Escolha pelo menos um departamento.',
                                    parent=self)
                return
        elif self._passo == 1:
            # Ordem de marcação primeiro; o resto (marcado por outro caminho)
            # entra depois, na ordem do catálogo.
            marcados = [par for par, v in self._vars_cargo.items() if v.get()]
            self._cargos_escolhidos = (
                [p for p in self._ordem_selecao if p in marcados]
                + [p for p in marcados if p not in self._ordem_selecao])
            if not self._cargos_escolhidos:
                messagebox.showinfo('Novo fluxo',
                                    'Escolha pelo menos um cargo — cada um vira '
                                    'uma coluna do fluxograma.', parent=self)
                return
        elif self._passo == 3:
            self._concluir()
            return
        self._passo += 1
        self._render_passo()

    def _voltar(self):
        if self._passo:
            self._passo -= 1
            self._render_passo()

    # ── Passo 1: departamentos ─────────────────────────────

    def _passo_departamentos(self):
        self.btn_avancar.configure(text='Avançar  ›')
        tk.Label(self.corpo,
                 text='Quais áreas participam deste processo? Um fluxo costuma '
                      'atravessar mais de uma.',
                 font=('Segoe UI', 9), bg=BG_PANEL, fg=TEXT_MUTED,
                 anchor='w').pack(fill='x', pady=(0, 8))

        nomes = cat.nomes_departamentos(self.catalogo)
        if not nomes:
            self._catalogo_vazio('Nenhum departamento cadastrado.')
            return

        interno = self._lista_rolavel(self.corpo)
        for nome in nomes:
            var = self._vars_dep.get(nome) or tk.BooleanVar(value=False)
            self._vars_dep[nome] = var
            linha = tk.Frame(interno, bg=BG_CARD)
            linha.pack(fill='x', padx=10, pady=1)
            tk.Checkbutton(linha, text=nome, variable=var, bg=BG_CARD,
                           fg=BTN_FG, font=('Segoe UI', 10), anchor='w',
                           activebackground=BG_CARD, selectcolor='#ffffff',
                           bd=0, highlightthickness=0,
                           command=self._atualizar_resumo).pack(side='left')
            qtd = len(cat.cargos_de(nome, self.catalogo))
            tk.Label(linha, text=f'{qtd} cargos', font=('Segoe UI', 8),
                     bg=BG_CARD, fg=TEXT_MUTED).pack(side='right', padx=8)
        self._atualizar_resumo()

    # ── Passo 2: cargos dentro das áreas ───────────────────

    def _passo_cargos(self):
        self.btn_avancar.configure(text='Avançar  ›')
        tk.Label(self.corpo,
                 text='Quem são os atores? Cada cargo marcado vira uma coluna, '
                      'na ordem em que você marcar — e dá para reordenar '
                      'depois, pela barra lateral.',
                 font=('Segoe UI', 9), bg=BG_PANEL, fg=TEXT_MUTED,
                 anchor='w').pack(fill='x', pady=(0, 8))

        interno = self._lista_rolavel(self.corpo)
        vazios = []
        for dep in self._deps_escolhidos:
            cargos = cat.cargos_de(dep, self.catalogo)
            cabecalho = tk.Frame(interno, bg=BG_CARD)
            cabecalho.pack(fill='x', padx=10, pady=(10, 2))
            tk.Label(cabecalho, text=dep.upper(), font=('Segoe UI', 9, 'bold'),
                     bg=BG_CARD, fg=ACCENT).pack(side='left')
            if not cargos:
                vazios.append(dep)
                tk.Label(cabecalho, text='sem cargos cadastrados',
                         font=('Segoe UI', 8), bg=BG_CARD,
                         fg='#b30000').pack(side='right', padx=8)
                continue
            tk.Button(cabecalho, text='marcar todos', font=('Segoe UI', 8),
                      bg=BG_CARD, fg=ACCENT, bd=0, relief='flat',
                      cursor='hand2', activebackground=BG_CARD,
                      command=lambda d=dep: self._marcar_area(d)).pack(side='right')
            for cargo in cargos:
                par = (dep, cargo)
                var = self._vars_cargo.get(par) or tk.BooleanVar(value=False)
                self._vars_cargo[par] = var
                tk.Checkbutton(interno, text=cargo, variable=var, bg=BG_CARD,
                               fg=BTN_FG, font=('Segoe UI', 10), anchor='w',
                               activebackground=BG_CARD, selectcolor='#ffffff',
                               bd=0, highlightthickness=0,
                               command=lambda p=par: self._marcar_cargo(p)).pack(
                                   fill='x', padx=26, pady=1)
        if vazios:
            tk.Label(self.corpo,
                     text='⚠ Sem cargos cadastrados em: ' + ', '.join(vazios) +
                          '. Cadastre em Configurações › Departamentos e cargos.',
                     font=('Segoe UI', 8), bg=BG_PANEL, fg='#b30000',
                     anchor='w', wraplength=780, justify='left').pack(
                         fill='x', pady=(6, 0))
        self._atualizar_resumo()

    def _marcar_cargo(self, par):
        """Registra a ordem de marcação — é ela que vira a ordem das colunas."""
        if self._vars_cargo[par].get():
            if par not in self._ordem_selecao:
                self._ordem_selecao.append(par)
        elif par in self._ordem_selecao:
            self._ordem_selecao.remove(par)
        self._atualizar_resumo()

    def _marcar_area(self, dep):
        for par, var in self._vars_cargo.items():
            if par[0] == dep and not var.get():
                var.set(True)
                self._marcar_cargo(par)
        self._atualizar_resumo()

    # ── Passo 3: prompt com as rédeas ──────────────────────

    def _passo_prompt(self):
        self.btn_avancar.configure(text='Avançar  ›')

        ident = tk.Frame(self.corpo, bg=BG_PANEL)
        ident.pack(fill='x', pady=(0, 8))
        tk.Label(ident, text='Título do processo', font=('Segoe UI', 8),
                 bg=BG_PANEL, fg=TEXT_MUTED).grid(row=0, column=0, sticky='w')
        tk.Label(ident, text='Código do documento (opcional)',
                 font=('Segoe UI', 8), bg=BG_PANEL,
                 fg=TEXT_MUTED).grid(row=0, column=1, sticky='w', padx=(10, 0))
        self.ent_titulo = tk.Entry(ident, font=('Segoe UI', 10), relief='solid',
                                   bd=1, highlightthickness=1,
                                   highlightcolor=ACCENT)
        self.ent_titulo.grid(row=1, column=0, sticky='ew')
        self.ent_doc = tk.Entry(ident, font=('Segoe UI', 10), relief='solid',
                                bd=1, highlightthickness=1, highlightcolor=ACCENT)
        self.ent_doc.grid(row=1, column=1, sticky='ew', padx=(10, 0))
        ident.columnconfigure(0, weight=3)
        ident.columnconfigure(1, weight=2)
        self.ent_titulo.bind('<KeyRelease>', lambda e: self._atualizar_prompt())
        self.ent_doc.bind('<KeyRelease>', lambda e: self._atualizar_prompt())

        tk.Label(self.corpo,
                 text='Cole este prompt na IA junto com a transcrição da reunião. '
                      'Ele já trava as colunas nos cargos escolhidos — a IA '
                      'distribui as atividades, não inventa atores.',
                 font=('Segoe UI', 9), bg=BG_PANEL, fg=TEXT_MUTED,
                 anchor='w', justify='left', wraplength=800).pack(fill='x',
                                                                  pady=(0, 6))

        moldura = tk.Frame(self.corpo, bg=BORDER)
        moldura.pack(fill='both', expand=True)
        self.txt_prompt = tk.Text(moldura, wrap='word', font=('Cascadia Code', 9),
                                  bg=BG_CARD, fg='#262626', bd=0, padx=10,
                                  pady=8, relief='flat', highlightthickness=0)
        barra = tk.Scrollbar(moldura, orient='vertical',
                             command=self.txt_prompt.yview)
        self.txt_prompt.configure(yscrollcommand=barra.set)
        barra.pack(side='right', fill='y')
        self.txt_prompt.pack(fill='both', expand=True, padx=1, pady=1)

        acoes = tk.Frame(self.corpo, bg=BG_PANEL)
        acoes.pack(fill='x', pady=(6, 0))
        self.btn_copiar = botao(acoes, '📋  Copiar prompt', self._copiar)
        self.btn_copiar.pack(side='left')
        tk.Label(acoes, text='Copie, rode na IA e siga para o próximo passo '
                             'para colar o resultado.',
                 font=('Segoe UI', 8), bg=BG_PANEL,
                 fg=TEXT_MUTED).pack(side='left', padx=10)
        self._atualizar_prompt()

    def _atualizar_prompt(self):
        # Guardados fora dos widgets: o passo 3 é destruído ao avançar.
        self._titulo = self.ent_titulo.get().strip() or 'Novo fluxo'
        self._doc_code = self.ent_doc.get().strip()
        texto = prompt_mod.montar(self._cargos_escolhidos, self._titulo,
                                  self._doc_code)
        self.txt_prompt.delete('1.0', 'end')
        self.txt_prompt.insert('1.0', texto)
        self._atualizar_resumo()

    def _copiar(self):
        self.clipboard_clear()
        self.clipboard_append(self.txt_prompt.get('1.0', 'end-1c'))
        self.btn_copiar.configure(text='✓  Copiado!')
        self.after(1600,
                   lambda: self.btn_copiar.configure(text='📋  Copiar prompt'))

    # ── Passo 4: colar o resultado da IA ───────────────────

    def _passo_resultado(self):
        self.btn_avancar.configure(text='Criar fluxo  ✓')
        tk.Label(self.corpo,
                 text='Cole aqui o JSON que a IA devolveu. Ele vira a primeira '
                      'versão do arquivo — é isso que evita desenhar tudo à mão.',
                 font=('Segoe UI', 9), bg=BG_PANEL, fg=TEXT_MUTED,
                 anchor='w', justify='left', wraplength=800).pack(fill='x',
                                                                  pady=(0, 6))

        moldura = tk.Frame(self.corpo, bg=BORDER)
        moldura.pack(fill='both', expand=True)
        self.txt_json = tk.Text(moldura, wrap='none', font=('Cascadia Code', 9),
                                bg=BG_CARD, fg='#262626', bd=0, padx=10,
                                pady=8, relief='flat', highlightthickness=0)
        barra = tk.Scrollbar(moldura, orient='vertical',
                             command=self.txt_json.yview)
        self.txt_json.configure(yscrollcommand=barra.set)
        barra.pack(side='right', fill='y')
        self.txt_json.pack(fill='both', expand=True, padx=1, pady=1)
        self.txt_json.bind('<KeyRelease>', lambda e: self._validar_json())
        if self._json_colado:
            self.txt_json.insert('1.0', self._json_colado)

        acoes = tk.Frame(self.corpo, bg=BG_PANEL)
        acoes.pack(fill='x', pady=(6, 0))
        botao(acoes, '📥  Colar da área de transferência',
              self._colar_json).pack(side='left')
        self.lbl_validacao = tk.Label(acoes, text='', font=('Segoe UI', 9),
                                      bg=BG_PANEL, fg=TEXT_MUTED, anchor='w',
                                      justify='left', wraplength=520)
        self.lbl_validacao.pack(side='left', padx=10)

        tk.Label(self.corpo,
                 text='Vazio também serve: o fluxo nasce só com as colunas e a '
                      'paleta de ferramentas já ligada, para montar à mão.',
                 font=('Segoe UI', 8), bg=BG_PANEL, fg=TEXT_MUTED,
                 anchor='w').pack(fill='x', pady=(6, 0))
        self._validar_json()

    def _colar_json(self):
        try:
            conteudo = self.clipboard_get()
        except tk.TclError:
            self.lbl_validacao.configure(
                text='Área de transferência vazia.', fg=AVISO)
            return
        self.txt_json.delete('1.0', 'end')
        self.txt_json.insert('1.0', conteudo)
        self._validar_json()

    def _validar_json(self):
        """Valida enquanto se digita: o erro aparece antes de criar o arquivo."""
        texto = self.txt_json.get('1.0', 'end-1c').strip()
        self._json_colado = texto
        if not texto:
            self.lbl_validacao.configure(
                text='Sem JSON: o fluxo nasce só com as colunas.', fg=TEXT_MUTED)
            return None
        try:
            modelo = parse_flowchart(texto)
        except ParseError as e:
            self.lbl_validacao.configure(text=f'✗ {e}', fg=AVISO)
            return None

        esperados = {c for _, c in self._cargos_escolhidos}
        vieram = {l['label'] for l in modelo['lanes']}
        intrusos = vieram - esperados
        resumo = (f"✓ {len(modelo['lanes'])} colunas · "
                  f"{len(modelo['nodes'])} nós · {len(modelo['edges'])} conexões")
        if intrusos:
            # A IA inventou ator apesar das rédeas: melhor avisar do que
            # descartar em silêncio o trabalho dela.
            lista = ', '.join(sorted(intrusos)[:3])
            self.lbl_validacao.configure(
                text=f'{resumo}  ⚠ atores fora dos escolhidos: {lista}',
                fg=AVISO)
        else:
            self.lbl_validacao.configure(text=resumo, fg=OK_GREEN)
        return modelo

    # ── Conclusão ──────────────────────────────────────────

    def _concluir(self):
        """Cria o arquivo: com o JSON da IA, se houver; senão, só as colunas."""
        titulo = self._titulo
        doc = None
        texto = (self._json_colado or '').strip()
        if texto:
            try:
                import json as _json
                doc = _json.loads(texto)
            except ValueError:
                try:                       # resposta de IA embrulhada em prosa
                    modelo = parse_flowchart(texto)
                    doc = modelo.get('_raw')
                except ParseError as e:
                    messagebox.showerror(
                        'Resultado da IA',
                        f'O JSON colado não pôde ser lido:\n\n{e}\n\n'
                        'Corrija o texto ou apague o campo para criar o fluxo '
                        'só com as colunas.', parent=self)
                    return
        if doc is None:
            doc = prompt_mod.modelo_inicial(self._cargos_escolhidos, titulo,
                                            self._doc_code)
        else:
            # Título e código do passo 3 mandam: foram digitados pelo usuário
            doc.setdefault('title', titulo)
            if self._doc_code:
                doc['docCode'] = self._doc_code
        self.resultado = doc
        if self.on_finish:
            self.on_finish(doc, veio_da_ia=bool(texto))
        self.destroy()

    # ── Apoio ──────────────────────────────────────────────

    def _catalogo_vazio(self, msg):
        aviso = tk.Frame(self.corpo, bg=BG_CARD, highlightthickness=1,
                         highlightbackground=BORDER)
        aviso.pack(fill='both', expand=True)
        tk.Label(aviso, text=msg, font=('Segoe UI', 11), bg=BG_CARD,
                 fg=BTN_FG).pack(pady=(40, 6))
        tk.Label(aviso, text='Cadastre as áreas e os cargos da empresa para '
                             'poder montar um fluxo.',
                 font=('Segoe UI', 9), bg=BG_CARD, fg=TEXT_MUTED).pack()
        if self.on_edit_catalog:
            botao(aviso, 'Abrir catálogo', self.on_edit_catalog,
                  primario=True).pack(pady=14)

    def _atualizar_resumo(self):
        deps = [d for d, v in self._vars_dep.items() if v.get()]
        cargos = [p for p, v in self._vars_cargo.items() if v.get()]
        if self._passo == 0:
            texto = f'{len(deps)} departamento(s) selecionado(s)'
        elif self._passo == 3:
            texto = f'{len(cargos)} coluna(s) · cole o JSON ou siga vazio'
        else:
            texto = (f'{len(deps)} área(s) · {len(cargos)} coluna(s) '
                     f'no fluxograma')
        self.lbl_resumo.configure(text=texto)
