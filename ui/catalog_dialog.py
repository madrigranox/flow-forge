"""
catalog_dialog.py — Manutenção do catálogo: departamentos e seus cargos.

Mestre-detalhe: à esquerda os departamentos, à direita os cargos DAQUELE
departamento. É essa hierarquia que permite, na criação de um fluxo, escolher
as áreas envolvidas e depois só os atores que existem em cada uma.

O arquivo editado fica em `%APPDATA%\\FlowForge\\catalogo.json` (ver
`core/catalogo.py`), fora do executável, para sobreviver a atualizações.

A lista costuma chegar do RH como um nome por linha, não como JSON — por isso
"Importar" aceita `.txt`/`.csv` além do `.json` do próprio catálogo.
"""
import os
import tkinter as tk
from tkinter import filedialog, messagebox

from core import catalogo as cat

BG_PANEL = '#f2f5fa'
BG_CARD = '#ffffff'
ACCENT = '#003399'
ACCENT_HOVER = '#002a7d'
BTN_BG = '#e6ebf5'
BTN_HOVER = '#ccd6eb'
BTN_FG = '#262626'
BORDER = '#ccd6eb'
TEXT_MUTED = '#4d4d4d'
DANGER = '#b30000'


def botao(pai, texto, comando, primario=False, compacto=False, perigo=False):
    """Botão no padrão Deep Blue do app (reaproveitado pelas telas novas)."""
    bg = ACCENT if primario else BTN_BG
    hover = ACCENT_HOVER if primario else BTN_HOVER
    fg = '#ffffff' if primario else (DANGER if perigo else BTN_FG)
    btn = tk.Button(pai, text=texto, command=comando,
                    font=('Segoe UI', 9, 'bold' if primario else 'normal'),
                    bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
                    bd=0, relief='flat', cursor='hand2',
                    padx=10 if compacto else 18, pady=4 if compacto else 6)
    btn.bind('<Enter>', lambda e: btn.configure(bg=hover))
    btn.bind('<Leave>', lambda e: btn.configure(bg=bg))
    return btn


class CatalogDialog(tk.Toplevel):
    """Departamentos à esquerda, cargos do selecionado à direita."""

    def __init__(self, parent, on_saved=None):
        super().__init__(parent)
        self.title('Departamentos e cargos')
        self.configure(bg=BG_PANEL)
        self.geometry('820x560')
        self.minsize(700, 460)
        self.transient(parent)
        self.on_saved = on_saved
        self.dados = cat.carregar()
        self._dep_atual = None

        tk.Label(self, text='Catálogo corporativo', font=('Segoe UI', 13, 'bold'),
                 bg=BG_PANEL, fg=BTN_FG).pack(anchor='w', padx=16, pady=(14, 2))
        tk.Label(self, text='Cada departamento tem os seus cargos. Ao criar um '
                            'fluxo você escolhe as áreas envolvidas e, dentro '
                            'delas, os atores — é essa lista que padroniza os nomes.',
                 font=('Segoe UI', 9), bg=BG_PANEL, fg=TEXT_MUTED,
                 justify='left', wraplength=760).pack(anchor='w', padx=16)

        # O programa usa a semente embutida até o primeiro salvamento. Sem este
        # aviso, o usuário padroniza contra uma lista de exemplo achando que é
        # a da empresa — e só descobre quando alguém estranha um nome.
        if not os.path.exists(cat.caminho_catalogo()):
            faixa = tk.Frame(self, bg='#fdf5e6', highlightthickness=1,
                             highlightbackground='#e0b872')
            faixa.pack(fill='x', padx=16, pady=(10, 0))
            tk.Label(faixa, text='⚠  Esta ainda é a lista de exemplo que vem com '
                                 'o programa, não a da sua empresa. Ajuste os '
                                 'nomes e clique em Salvar — a partir daí o '
                                 'arquivo passa a ser seu.',
                     font=('Segoe UI', 9), bg='#fdf5e6', fg='#7a5200',
                     justify='left', wraplength=740).pack(anchor='w', padx=12,
                                                          pady=9)

        corpo = tk.Frame(self, bg=BG_PANEL)
        corpo.pack(fill='both', expand=True, padx=12, pady=10)
        corpo.columnconfigure(0, weight=2, uniform='c')
        corpo.columnconfigure(1, weight=3, uniform='c')
        corpo.rowconfigure(0, weight=1)
        self._montar_departamentos(corpo)
        self._montar_cargos(corpo)

        rodape = tk.Frame(self, bg=BG_PANEL)
        rodape.pack(fill='x', padx=16, pady=(0, 12))
        tk.Label(rodape, text=f'Arquivo: {cat.caminho_catalogo()}',
                 font=('Segoe UI', 8), bg=BG_PANEL, fg=TEXT_MUTED,
                 anchor='w').pack(side='top', fill='x', pady=(0, 8))
        botao(rodape, 'Salvar', self._salvar, primario=True).pack(side='right')
        botao(rodape, 'Cancelar', self.destroy).pack(side='right', padx=(0, 8))
        botao(rodape, 'Restaurar padrão', self._restaurar).pack(side='left')
        botao(rodape, 'Importar catálogo…', self._importar_catalogo,
              ).pack(side='left', padx=8)

        self.bind('<Escape>', lambda e: self.destroy())
        self._recarregar_departamentos()

    # ── Coluna esquerda: departamentos ─────────────────────

    def _montar_departamentos(self, pai):
        card = tk.Frame(pai, bg=BG_CARD, highlightthickness=1,
                        highlightbackground=BORDER)
        card.grid(row=0, column=0, sticky='nsew', padx=(0, 8))

        cab = tk.Frame(card, bg=BG_CARD)
        cab.pack(fill='x', padx=10, pady=(10, 4))
        tk.Label(cab, text='DEPARTAMENTOS', font=('Segoe UI', 9, 'bold'),
                 bg=BG_CARD, fg=BTN_FG).pack(side='left')
        self.cont_dep = tk.Label(cab, text='', font=('Segoe UI', 8),
                                 bg=BG_CARD, fg=TEXT_MUTED)
        self.cont_dep.pack(side='right')

        moldura = tk.Frame(card, bg=BORDER)
        moldura.pack(fill='both', expand=True, padx=10)
        self.lst_dep = tk.Listbox(moldura, font=('Segoe UI', 9), bd=0,
                                  highlightthickness=0, activestyle='none',
                                  selectbackground=ACCENT,
                                  selectforeground='#ffffff', exportselection=False)
        barra = tk.Scrollbar(moldura, orient='vertical', command=self.lst_dep.yview)
        self.lst_dep.configure(yscrollcommand=barra.set)
        barra.pack(side='right', fill='y')
        self.lst_dep.pack(fill='both', expand=True, padx=1, pady=1)
        self.lst_dep.bind('<<ListboxSelect>>', lambda e: self._selecionar_dep())
        self.lst_dep.bind('<Double-Button-1>', lambda e: self._renomear_dep())

        linha = tk.Frame(card, bg=BG_CARD)
        linha.pack(fill='x', padx=10, pady=(6, 4))
        self.ent_dep = tk.Entry(linha, font=('Segoe UI', 9), relief='solid',
                                bd=1, highlightthickness=1, highlightcolor=ACCENT)
        self.ent_dep.pack(side='left', fill='x', expand=True)
        self.ent_dep.bind('<Return>', lambda e: self._adicionar_dep())
        botao(linha, 'Adicionar', self._adicionar_dep,
              compacto=True).pack(side='left', padx=(6, 0))

        acoes = tk.Frame(card, bg=BG_CARD)
        acoes.pack(fill='x', padx=10, pady=(0, 10))
        botao(acoes, 'Renomear', self._renomear_dep, compacto=True).pack(side='left')
        botao(acoes, 'Remover', self._remover_dep, compacto=True,
              perigo=True).pack(side='left', padx=6)

    # ── Coluna direita: cargos do departamento ─────────────

    def _montar_cargos(self, pai):
        card = tk.Frame(pai, bg=BG_CARD, highlightthickness=1,
                        highlightbackground=BORDER)
        card.grid(row=0, column=1, sticky='nsew', padx=(8, 0))

        cab = tk.Frame(card, bg=BG_CARD)
        cab.pack(fill='x', padx=10, pady=(10, 4))
        self.lbl_cargos = tk.Label(cab, text='CARGOS', font=('Segoe UI', 9, 'bold'),
                                   bg=BG_CARD, fg=BTN_FG)
        self.lbl_cargos.pack(side='left')
        self.cont_cargo = tk.Label(cab, text='', font=('Segoe UI', 8),
                                   bg=BG_CARD, fg=TEXT_MUTED)
        self.cont_cargo.pack(side='right')

        moldura = tk.Frame(card, bg=BORDER)
        moldura.pack(fill='both', expand=True, padx=10)
        self.lst_cargo = tk.Listbox(moldura, font=('Segoe UI', 9), bd=0,
                                    highlightthickness=0, activestyle='none',
                                    selectbackground=ACCENT,
                                    selectforeground='#ffffff', exportselection=False)
        barra = tk.Scrollbar(moldura, orient='vertical', command=self.lst_cargo.yview)
        self.lst_cargo.configure(yscrollcommand=barra.set)
        barra.pack(side='right', fill='y')
        self.lst_cargo.pack(fill='both', expand=True, padx=1, pady=1)
        self.lst_cargo.bind('<Double-Button-1>', lambda e: self._renomear_cargo())

        linha = tk.Frame(card, bg=BG_CARD)
        linha.pack(fill='x', padx=10, pady=(6, 4))
        self.ent_cargo = tk.Entry(linha, font=('Segoe UI', 9), relief='solid',
                                  bd=1, highlightthickness=1, highlightcolor=ACCENT)
        self.ent_cargo.pack(side='left', fill='x', expand=True)
        self.ent_cargo.bind('<Return>', lambda e: self._adicionar_cargo())
        botao(linha, 'Adicionar', self._adicionar_cargo,
              compacto=True).pack(side='left', padx=(6, 0))

        acoes = tk.Frame(card, bg=BG_CARD)
        acoes.pack(fill='x', padx=10, pady=(0, 10))
        botao(acoes, 'Renomear', self._renomear_cargo, compacto=True).pack(side='left')
        botao(acoes, 'Remover', self._remover_cargo, compacto=True,
              perigo=True).pack(side='left', padx=6)
        botao(acoes, 'Importar cargos…', self._importar_cargos,
              compacto=True).pack(side='right')

    # ── Estado ─────────────────────────────────────────────

    def _deps(self):
        return self.dados.setdefault('departamentos', [])

    def _dep_obj(self):
        for d in self._deps():
            if d['nome'] == self._dep_atual:
                return d
        return None

    def _recarregar_departamentos(self, manter=None):
        alvo = manter or self._dep_atual
        self.lst_dep.delete(0, 'end')
        for d in self._deps():
            self.lst_dep.insert('end', f"{d['nome']}  ({len(d.get('cargos', []))})")
        self.cont_dep.configure(text=f'{len(self._deps())} áreas')
        nomes = [d['nome'] for d in self._deps()]
        if alvo in nomes:
            i = nomes.index(alvo)
            self.lst_dep.selection_set(i)
            self.lst_dep.see(i)
            self._dep_atual = alvo
        elif nomes:
            self.lst_dep.selection_set(0)
            self._dep_atual = nomes[0]
        else:
            self._dep_atual = None
        self._recarregar_cargos()

    def _selecionar_dep(self):
        sel = self.lst_dep.curselection()
        if sel:
            self._dep_atual = self._deps()[sel[0]]['nome']
            self._recarregar_cargos()

    def _recarregar_cargos(self):
        self.lst_cargo.delete(0, 'end')
        d = self._dep_obj()
        if d is None:
            self.lbl_cargos.configure(text='CARGOS')
            self.cont_cargo.configure(text='selecione um departamento')
            return
        self.lbl_cargos.configure(text=f"CARGOS — {d['nome'].upper()}")
        for c in d.get('cargos', []):
            self.lst_cargo.insert('end', c)
        self.cont_cargo.configure(text=f"{len(d.get('cargos', []))} cargos")

    # ── Ações de departamento ──────────────────────────────

    def _adicionar_dep(self):
        nome = self.ent_dep.get().strip()
        if not nome:
            return
        if any(d['nome'].casefold() == nome.casefold() for d in self._deps()):
            messagebox.showinfo('Catálogo', f"'{nome}' já existe.", parent=self)
            return
        self._deps().append({'nome': nome, 'cargos': []})
        self._deps().sort(key=lambda d: d['nome'].casefold())
        self.ent_dep.delete(0, 'end')
        self._recarregar_departamentos(manter=nome)

    def _renomear_dep(self):
        d = self._dep_obj()
        if d is None:
            messagebox.showinfo('Catálogo', 'Selecione um departamento.', parent=self)
            return
        novo = perguntar_texto(self, 'Renomear departamento', 'Novo nome:', d['nome'])
        if novo and novo.strip() and novo.strip() != d['nome']:
            d['nome'] = novo.strip()
            self._deps().sort(key=lambda x: x['nome'].casefold())
            self._recarregar_departamentos(manter=d['nome'])

    def _remover_dep(self):
        d = self._dep_obj()
        if d is None:
            return
        n = len(d.get('cargos', []))
        extra = f"\n\nOs {n} cargos dentro dele também saem." if n else ''
        if messagebox.askyesno('Remover',
                               f"Remover o departamento '{d['nome']}'?{extra}",
                               parent=self):
            self.dados['departamentos'] = [x for x in self._deps() if x is not d]
            self._dep_atual = None
            self._recarregar_departamentos()

    # ── Ações de cargo ─────────────────────────────────────

    def _cargo_selecionado(self):
        sel = self.lst_cargo.curselection()
        d = self._dep_obj()
        if not sel or d is None:
            return None
        return d['cargos'][sel[0]]

    def _adicionar_cargo(self):
        d = self._dep_obj()
        if d is None:
            messagebox.showinfo('Catálogo',
                                'Selecione um departamento primeiro.', parent=self)
            return
        nome = self.ent_cargo.get().strip()
        if not nome:
            return
        if any(c.casefold() == nome.casefold() for c in d.get('cargos', [])):
            messagebox.showinfo('Catálogo',
                                f"'{nome}' já está neste departamento.", parent=self)
            return
        d.setdefault('cargos', []).append(nome)
        d['cargos'].sort(key=lambda s: s.casefold())
        self.ent_cargo.delete(0, 'end')
        self._recarregar_departamentos(manter=d['nome'])

    def _renomear_cargo(self):
        d, atual = self._dep_obj(), self._cargo_selecionado()
        if atual is None:
            messagebox.showinfo('Catálogo', 'Selecione um cargo.', parent=self)
            return
        novo = perguntar_texto(self, 'Renomear cargo', 'Novo nome:', atual)
        if novo and novo.strip() and novo.strip() != atual:
            d['cargos'] = sorted(
                [novo.strip() if c == atual else c for c in d['cargos']],
                key=lambda s: s.casefold())
            self._recarregar_cargos()

    def _remover_cargo(self):
        d, atual = self._dep_obj(), self._cargo_selecionado()
        if atual is None:
            return
        if messagebox.askyesno('Remover', f"Remover o cargo '{atual}'?", parent=self):
            d['cargos'] = [c for c in d['cargos'] if c != atual]
            self._recarregar_departamentos(manter=d['nome'])

    # ── Importação ─────────────────────────────────────────

    def _importar_cargos(self):
        d = self._dep_obj()
        if d is None:
            messagebox.showinfo('Catálogo',
                                'Selecione o departamento que vai receber os '
                                'cargos.', parent=self)
            return
        caminho = filedialog.askopenfilename(
            parent=self, title=f"Importar cargos para {d['nome']}",
            filetypes=[('Lista de nomes', '*.txt *.csv'), ('Todos', '*.*')])
        if not caminho:
            return
        resultado, msg = cat.importar_de_arquivo(caminho)
        if resultado is None or isinstance(resultado, dict):
            messagebox.showerror(
                'Importar',
                msg if resultado is None
                else 'Este arquivo é um catálogo inteiro — use "Importar '
                     'catálogo" no rodapé.', parent=self)
            return
        d['cargos'] = sorted(set(d.get('cargos', []) + list(resultado)),
                             key=lambda s: s.casefold())
        self._recarregar_departamentos(manter=d['nome'])

    def _importar_catalogo(self):
        caminho = filedialog.askopenfilename(
            parent=self, title='Importar catálogo',
            filetypes=[('Catálogo JSON', '*.json'), ('Todos', '*.*')])
        if not caminho:
            return
        resultado, msg = cat.importar_de_arquivo(caminho)
        if not isinstance(resultado, dict):
            messagebox.showerror('Importar',
                                 msg if resultado is None
                                 else 'Escolha um .json de catálogo.', parent=self)
            return
        if messagebox.askyesno('Importar',
                               'Substituir o catálogo inteiro pelo conteúdo '
                               'do arquivo?', parent=self):
            self.dados = resultado
            self._dep_atual = None
            self._recarregar_departamentos()

    def _restaurar(self):
        if messagebox.askyesno('Restaurar padrão',
                               'Descartar a lista atual e voltar ao catálogo '
                               'que vem com o programa?', parent=self):
            self.dados = cat.restaurar_padrao()
            self._dep_atual = None
            self._recarregar_departamentos()

    def _salvar(self):
        ok, info = cat.salvar(self.dados)
        if not ok:
            messagebox.showerror('Salvar catálogo',
                                 f'Não foi possível gravar:\n{info}', parent=self)
            return
        if self.on_saved:
            self.on_saved(cat.carregar())
        self.destroy()


def perguntar_texto(parent, titulo, rotulo, inicial=''):
    """simpledialog com o visual do app (e sem trazer outra dependência)."""
    janela = tk.Toplevel(parent)
    janela.title(titulo)
    janela.configure(bg=BG_PANEL)
    janela.transient(parent)
    janela.resizable(False, False)
    tk.Label(janela, text=rotulo, font=('Segoe UI', 9), bg=BG_PANEL,
             fg=BTN_FG).pack(anchor='w', padx=16, pady=(14, 4))
    entrada = tk.Entry(janela, font=('Segoe UI', 10), width=42, relief='solid',
                       bd=1, highlightthickness=1, highlightcolor=ACCENT)
    entrada.insert(0, inicial)
    entrada.select_range(0, 'end')
    entrada.pack(padx=16)
    resposta = {'valor': None}

    def confirmar():
        resposta['valor'] = entrada.get()
        janela.destroy()

    barra = tk.Frame(janela, bg=BG_PANEL)
    barra.pack(fill='x', padx=16, pady=12)
    botao(barra, 'OK', confirmar, primario=True).pack(side='right')
    botao(barra, 'Cancelar', janela.destroy).pack(side='right', padx=(0, 8))
    entrada.bind('<Return>', lambda e: confirmar())
    janela.bind('<Escape>', lambda e: janela.destroy())
    entrada.focus_set()
    janela.grab_set()
    parent.wait_window(janela)
    return resposta['valor']
