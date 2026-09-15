"""
welcome_screen.py — Tela inicial do Flow Forge.

O programa abria direto num fluxograma de exemplo já carregado. Isso confundia
duas coisas diferentes: "estou vendo um exemplo" e "estou editando o meu
documento" — e mais de uma vez o exemplo virou a base de um fluxo real por
engano.

Agora a abertura é uma tela vazia com duas saídas: criar um fluxo novo (que
leva ao assistente de departamentos e cargos) ou abrir um que já está em
andamento. Os recentes ficam à mão, porque um fluxograma em desenvolvimento é
reaberto muitas vezes até ser publicado.
"""
import json
import os
import tkinter as tk

BG = '#f2f5fa'
BG_CARD = '#ffffff'
ACCENT = '#003399'
ACCENT_HOVER = '#002a7d'
BTN_BG = '#e6ebf5'
BTN_HOVER = '#ccd6eb'
FG = '#262626'
BORDER = '#ccd6eb'
MUTED = '#4d4d4d'


class WelcomeScreen(tk.Frame):
    """Tela de abertura. Fica sobre a área principal até o usuário escolher."""

    def __init__(self, parent, on_new=None, on_open=None, on_open_recent=None,
                 on_catalog=None, on_sample=None, recentes=None,
                 on_wizard=None, catalogo_e_semente=False, **kw):
        super().__init__(parent, bg=BG, **kw)
        self.on_new = on_new
        self.on_wizard = on_wizard
        self.on_open = on_open
        self.on_open_recent = on_open_recent
        self.on_catalog = on_catalog
        self.on_sample = on_sample

        centro = tk.Frame(self, bg=BG)
        centro.place(relx=0.5, rely=0.46, anchor='center')

        tk.Label(centro, text='⬡', font=('Segoe UI', 40), fg=ACCENT,
                 bg=BG).pack()
        tk.Label(centro, text='Flow Forge', font=('Segoe UI', 24, 'bold'),
                 fg=FG, bg=BG).pack(pady=(2, 0))
        tk.Label(centro, text='Mapeamento de processos em swimlanes',
                 font=('Segoe UI', 10), fg=MUTED, bg=BG).pack(pady=(0, 24))

        cartoes = tk.Frame(centro, bg=BG)
        cartoes.pack()
        self._cartao(cartoes, '✦', 'Documento em branco',
                     'Uma coluna vazia e a paleta de ferramentas. '
                     'Para montar o fluxo à mão, do zero.',
                     self._novo, primario=True).pack(side='left', padx=(0, 10))
        self._cartao(cartoes, '🤖', 'Criar com assistente',
                     'Escolha departamentos e cargos; o prompt de IA sai pronto '
                     'com essas rédeas e você cola o resultado.',
                     self._assistente).pack(side='left', padx=(0, 10))
        self._cartao(cartoes, '📂', 'Abrir existente',
                     'Retome um fluxograma em desenvolvimento ou já publicado.',
                     self._abrir).pack(side='left')

        self.recentes_box = tk.Frame(centro, bg=BG)
        self.recentes_box.pack(fill='x', pady=(24, 0))
        self.set_recentes(recentes or [])

        # O aviso precisa estar ONDE A PESSOA PASSA, não escondido dentro de
        # Configurações: quem não desconfia não vai lá conferir, e desenha
        # dezenas de fluxogramas contra a lista de exemplo antes de descobrir.
        if catalogo_e_semente:
            faixa = tk.Frame(self, bg='#fdf5e6', highlightthickness=1,
                             highlightbackground='#e0b872')
            faixa.pack(side='top', fill='x')
            linha = tk.Frame(faixa, bg='#fdf5e6')
            linha.pack(padx=16, pady=9)
            tk.Label(linha, text='⚠  Os departamentos e cargos ainda são a lista '
                                 'de exemplo que veio com o programa.',
                     font=('Segoe UI', 9), bg='#fdf5e6',
                     fg='#7a5200').pack(side='left')
            alvo = tk.Label(linha, text='  Cadastrar os da empresa',
                            font=('Segoe UI', 9, 'bold'), bg='#fdf5e6',
                            fg=ACCENT, cursor='hand2')
            alvo.pack(side='left')
            if self.on_catalog:
                alvo.bind('<Button-1>', lambda e: self.on_catalog())

        rodape = tk.Frame(self, bg=BG)
        rodape.pack(side='bottom', fill='x', pady=14)
        self._link(rodape, '🏷  Departamentos e cargos',
                   self.on_catalog).pack(side='left', padx=16)
        if self.on_sample:
            self._link(rodape, '👁  Ver um exemplo',
                       self.on_sample).pack(side='right', padx=16)

    # ── Peças ──────────────────────────────────────────────

    def _cartao(self, pai, icone, titulo, descricao, comando, primario=False):
        card = tk.Frame(pai, bg=BG_CARD, highlightthickness=1,
                        highlightbackground=ACCENT if primario else BORDER,
                        cursor='hand2', width=248, height=186)
        card.pack_propagate(False)
        tk.Label(card, text=icone, font=('Segoe UI', 22),
                 fg=ACCENT if primario else MUTED, bg=BG_CARD).pack(pady=(26, 4))
        tk.Label(card, text=titulo, font=('Segoe UI', 12, 'bold'), fg=FG,
                 bg=BG_CARD).pack()
        tk.Label(card, text=descricao, font=('Segoe UI', 9), fg=MUTED,
                 bg=BG_CARD, wraplength=204, justify='center').pack(pady=(6, 0),
                                                                    padx=16)
        # O cartão inteiro é clicável — inclusive os rótulos dentro dele
        for w in [card] + list(card.winfo_children()):
            w.bind('<Button-1>', lambda e, c=comando: c())
            w.bind('<Enter>', lambda e, c=card: c.configure(bg=BTN_BG) or
                   [x.configure(bg=BTN_BG) for x in c.winfo_children()])
            w.bind('<Leave>', lambda e, c=card: c.configure(bg=BG_CARD) or
                   [x.configure(bg=BG_CARD) for x in c.winfo_children()])
        return card

    def _link(self, pai, texto, comando):
        lbl = tk.Label(pai, text=texto, font=('Segoe UI', 9), fg=ACCENT, bg=BG,
                       cursor='hand2')
        if comando:
            lbl.bind('<Button-1>', lambda e: comando())
        return lbl

    def set_recentes(self, caminhos):
        """Lista os últimos arquivos abertos, com o título de dentro do JSON."""
        for w in self.recentes_box.winfo_children():
            w.destroy()
        existentes = [c for c in caminhos if os.path.exists(c)][:5]
        if not existentes:
            return
        tk.Label(self.recentes_box, text='RECENTES', font=('Segoe UI', 8, 'bold'),
                 fg=MUTED, bg=BG).pack(anchor='w', pady=(0, 4))
        for caminho in existentes:
            linha = tk.Frame(self.recentes_box, bg=BG, cursor='hand2')
            linha.pack(fill='x', pady=1)
            titulo = _titulo_do_arquivo(caminho)
            tk.Label(linha, text=f'📄  {titulo}', font=('Segoe UI', 9), fg=FG,
                     bg=BG, anchor='w').pack(side='left')
            tk.Label(linha, text=os.path.basename(caminho),
                     font=('Segoe UI', 8), fg=MUTED, bg=BG).pack(side='right')
            for w in [linha] + list(linha.winfo_children()):
                w.bind('<Button-1>',
                       lambda e, c=caminho: self._abrir_recente(c))

    # ── Ações ──────────────────────────────────────────────

    def _novo(self):
        if self.on_new:
            self.on_new()

    def _assistente(self):
        if self.on_wizard:
            self.on_wizard()

    def _abrir(self):
        if self.on_open:
            self.on_open()

    def _abrir_recente(self, caminho):
        if self.on_open_recent:
            self.on_open_recent(caminho)


def _titulo_do_arquivo(caminho):
    """Título de dentro do JSON — o nome do arquivo raramente é o do processo."""
    try:
        with open(caminho, 'r', encoding='utf-8') as f:
            dados = json.load(f)
        return dados.get('title') or os.path.basename(caminho)
    except (OSError, ValueError):
        return os.path.basename(caminho)
