"""
json_panel.py — Painel de texto JSON (ferramenta avançada).

Deixou de ser a porta principal de edição — quem ocupa esse lugar é o painel de
propriedades. Aqui o texto se aplica sozinho, com uma pausa de digitação como
fronteira: sem isso, cada tecla viraria um passo de desfazer e os 50 slots de
histórico se esgotariam em duas frases digitadas.
"""
import tkinter as tk


# ── Paleta "Deep Blue" (light) ─────────────────────────
BG_PANEL = '#e6ebf5'       # fundo do painel (blue-100)
BG_EDITOR = '#ffffff'       # fundo do editor
FG_CODE = '#262626'         # texto do código (ink-800)
FG_CURSOR = '#003399'       # cursor azul
FG_SELECT_BG = '#ccd6eb'    # seleção (blue-200)
FG_SELECT = '#000000'       # texto selecionado
FG_HEADER = '#262626'       # header label
ACCENT = '#003399'          # azul primário
ACCENT_HOVER = '#002a7d'    # hover primário
BTN_DEFAULT = '#4d4d4d'     # botão neutro (ink-700)
BTN_DEFAULT_HOVER = '#262626'
BORDER = '#ccd6eb'          # bordas (blue-200)
DANGER = '#ff0033'          # limpar (vermelho 100%)


class JSONPanel(tk.Frame):
    """Painel com editor de texto para JSON e botões de ação."""

    def __init__(self, parent, on_render=None, on_load=None, **kw):
        super().__init__(parent, **kw)
        self.configure(bg=BG_PANEL)
        self.on_render = on_render
        self.on_load = on_load
        self._pendente = None      # after() agendado da auto-renderização
        self._silencioso = False   # texto trocado por código não se auto-aplica

        # ── Header ──
        header = tk.Frame(self, bg=BG_PANEL)
        header.pack(fill='x', padx=12, pady=(14, 6))

        tk.Label(header, text='📝', font=('Segoe UI', 14),
                 bg=BG_PANEL).pack(side='left')
        tk.Label(header, text='  Editor JSON', font=('Segoe UI', 12, 'bold'),
                 fg=FG_HEADER, bg=BG_PANEL).pack(side='left')

        # ── Text editor ──
        text_frame = tk.Frame(self, bg=BORDER, bd=0)
        text_frame.pack(fill='both', expand=True, padx=12, pady=6)

        # Inner frame para simular borda arredondada
        inner = tk.Frame(text_frame, bg=BG_EDITOR, bd=0)
        inner.pack(fill='both', expand=True, padx=1, pady=1)

        self.text = tk.Text(
            inner, wrap='none', font=('Cascadia Code', 10),
            bg=BG_EDITOR, fg=FG_CODE, insertbackground=FG_CURSOR,
            selectbackground=FG_SELECT_BG, selectforeground=FG_SELECT,
            bd=0, padx=12, pady=10, undo=True,
            relief='flat', highlightthickness=0,
        )
        # Scrollbars com estilo mínimo
        ysb = tk.Scrollbar(inner, orient='vertical', command=self.text.yview)
        xsb = tk.Scrollbar(inner, orient='horizontal', command=self.text.xview)
        self.text.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)

        ysb.pack(side='right', fill='y')
        xsb.pack(side='bottom', fill='x')
        self.text.pack(fill='both', expand=True)

        # Auto-renderização: aplica sozinho após a pausa, e imediatamente ao
        # sair do campo — clicar no canvas não pode engolir o que foi digitado.
        self.text.bind('<<Modified>>', self._on_modified)
        self.text.bind('<FocusOut>', lambda e: self._flush())
        self.bind('<Destroy>', lambda e: self._cancelar_pendente())

        # ── Botões ──
        btn_frame = tk.Frame(self, bg=BG_PANEL)
        btn_frame.pack(fill='x', padx=12, pady=(6, 14))

        self._make_btn(btn_frame, '📂  Carregar', self._on_load,
                       bg=BTN_DEFAULT, hover=BTN_DEFAULT_HOVER).pack(side='left', padx=(0, 6))
        self._make_btn(btn_frame, '🗑  Limpar', self._on_clear,
                       bg='#99add6', hover=DANGER).pack(side='right')
        tk.Label(btn_frame, text='aplica sozinho após a pausa',
                 font=('Segoe UI', 8), fg='#4d4d4d',
                 bg=BG_PANEL).pack(side='left', padx=(4, 0))

    def _make_btn(self, parent, text, command, bg='#495057', hover='#343a40'):
        btn = tk.Button(
            parent, text=text, command=command,
            font=('Segoe UI', 9, 'bold'), fg='#ffffff', bg=bg,
            activebackground=hover, activeforeground='#ffffff',
            bd=0, padx=16, pady=6, cursor='hand2', relief='flat',
        )
        # Hover effects
        btn.bind('<Enter>', lambda e, b=btn, h=hover: b.configure(bg=h))
        btn.bind('<Leave>', lambda e, b=btn, o=bg: b.configure(bg=o))
        return btn

    # ── Auto-renderização ──────────────────────────────────

    ESPERA_MS = 800

    def _on_modified(self, event=None):
        # O Tk só dispara <<Modified>> de novo depois que a flag é zerada
        try:
            self.text.edit_modified(False)
        except tk.TclError:
            return
        if self._silencioso:
            return
        self._cancelar_pendente()
        self._pendente = self.after(self.ESPERA_MS, self._disparar)

    def _cancelar_pendente(self):
        if self._pendente is not None:
            try:
                self.after_cancel(self._pendente)
            except (ValueError, tk.TclError):
                pass
            self._pendente = None

    def _disparar(self):
        self._pendente = None
        # A janela pode ter sido fechada entre o agendamento e o disparo
        if self.on_render and self.winfo_exists():
            self.on_render()

    def _flush(self):
        """Aplica agora o que estiver pendente (ex.: o foco saiu do campo)."""
        if self._pendente is not None:
            self._cancelar_pendente()
            self._disparar()

    def get_json(self):
        return self.text.get('1.0', 'end-1c')

    def set_json(self, text):
        """Troca o texto por código — não deve reagir como se fosse digitação."""
        self._silencioso = True
        self._cancelar_pendente()
        try:
            self.text.delete('1.0', 'end')
            self.text.insert('1.0', text)
            self.text.edit_modified(False)
        finally:
            self._silencioso = False

    def _on_render(self):
        if self.on_render:
            self.on_render()

    def _on_load(self):
        if self.on_load:
            self.on_load()

    def _on_clear(self):
        self.text.delete('1.0', 'end')
