"""
prompt_viewer.py — Janela modal para visualizar e copiar o prompt IA.
"""
import tkinter as tk
import os


# ── Paleta "Deep Blue" (light) ─────────────────────────
BG = '#ffffff'
BG_TEXT = '#f2f5fa'
ACCENT = '#003399'
ACCENT_HOVER = '#002a7d'
BORDER = '#ccd6eb'
TEXT_DARK = '#000000'
TEXT_MUTED = '#4d4d4d'
SUCCESS = '#107c10'


def _load_prompt():
    """Carrega o conteúdo do prompt embutido."""
    import sys
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(__file__))
    prompt_path = os.path.join(base, 'data', 'prompt_ia.txt')
    if os.path.exists(prompt_path):
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    # Fallback: tentar o .md na raiz (modo dev)
    md_path = os.path.join(base, 'PROMPT_GERADOR_JSON.md')
    if os.path.exists(md_path):
        with open(md_path, 'r', encoding='utf-8') as f:
            return f.read()
    return '(Prompt não encontrado)'


class PromptViewer(tk.Toplevel):
    """Janela modal para visualizar e copiar o prompt de IA."""

    def __init__(self, parent, texto=None):
        """`texto` permite abrir a versão já travada nas colunas do fluxo.

        Sem ele, mostra o prompt genérico — que é o certo quando ainda não há
        fluxo aberto e, portanto, não há atores para prender a IA.
        """
        super().__init__(parent)
        self._texto = texto
        self.title('📋 Prompt IA — Flow Forge')
        self.geometry('780x650')
        self.minsize(600, 400)
        self.configure(bg=BG)
        self.transient(parent)
        self.grab_set()

        # Ícone (herdar do parent)
        try:
            self.iconbitmap(parent.iconbitmap())
        except Exception:
            pass

        self._build_ui()
        self.focus_force()

    def _build_ui(self):
        # ── Header ──
        header = tk.Frame(self, bg=BG)
        header.pack(fill='x', padx=20, pady=(16, 0))

        tk.Label(header, text='🤖', font=('Segoe UI', 20),
                 bg=BG).pack(side='left')

        title_frame = tk.Frame(header, bg=BG)
        title_frame.pack(side='left', padx=(10, 0))

        tk.Label(title_frame, text='Prompt para Geração de JSON',
                 font=('Segoe UI', 14, 'bold'), fg=TEXT_DARK, bg=BG,
                 anchor='w').pack(anchor='w')
        tk.Label(title_frame,
                 text='Cole este prompt na sua ferramenta de IA + a descrição do seu processo',
                 font=('Segoe UI', 10), fg=TEXT_MUTED, bg=BG,
                 anchor='w').pack(anchor='w')

        # ── Separador ──
        tk.Frame(self, bg=BORDER, height=1).pack(fill='x', padx=20, pady=(12, 0))

        # ── Área de texto ──
        text_frame = tk.Frame(self, bg=BORDER, bd=0)
        text_frame.pack(fill='both', expand=True, padx=20, pady=12)

        inner = tk.Frame(text_frame, bg=BG_TEXT, bd=0)
        inner.pack(fill='both', expand=True, padx=1, pady=1)

        self.text = tk.Text(
            inner, wrap='word', font=('Cascadia Code', 9),
            bg=BG_TEXT, fg=TEXT_DARK, bd=0, padx=14, pady=10,
            relief='flat', highlightthickness=0,
            selectbackground='#ccd6eb', selectforeground=TEXT_DARK,
        )
        ysb = tk.Scrollbar(inner, orient='vertical', command=self.text.yview)
        self.text.configure(yscrollcommand=ysb.set)
        ysb.pack(side='right', fill='y')
        self.text.pack(fill='both', expand=True)

        # Carregar conteúdo
        prompt = self._texto or _load_prompt()
        self.text.insert('1.0', prompt)
        self.text.configure(state='normal')  # permite seleção/cópia

        # ── Footer com botões ──
        footer = tk.Frame(self, bg=BG)
        footer.pack(fill='x', padx=20, pady=(0, 16))

        # Status label (feedback de cópia)
        self._status = tk.Label(footer, text='', font=('Segoe UI', 9),
                                fg=SUCCESS, bg=BG)
        self._status.pack(side='left')

        # Botão Fechar
        close_btn = tk.Button(
            footer, text='Fechar', command=self.destroy,
            font=('Segoe UI', 9), fg=TEXT_MUTED, bg='#f1f3f5',
            activebackground='#e9ecef', activeforeground=TEXT_DARK,
            bd=0, padx=16, pady=6, cursor='hand2', relief='flat',
        )
        close_btn.pack(side='right', padx=(8, 0))
        close_btn.bind('<Enter>', lambda e: close_btn.configure(bg='#e9ecef'))
        close_btn.bind('<Leave>', lambda e: close_btn.configure(bg='#f1f3f5'))

        # Botão Copiar (destaque)
        copy_btn = tk.Button(
            footer, text='📋  Copiar Prompt', command=self._copy,
            font=('Segoe UI', 10, 'bold'), fg='#ffffff', bg=ACCENT,
            activebackground=ACCENT_HOVER, activeforeground='#ffffff',
            bd=0, padx=20, pady=8, cursor='hand2', relief='flat',
        )
        copy_btn.pack(side='right')
        copy_btn.bind('<Enter>', lambda e: copy_btn.configure(bg=ACCENT_HOVER))
        copy_btn.bind('<Leave>', lambda e: copy_btn.configure(bg=ACCENT))

    def _copy(self):
        """Copia o prompt inteiro para o clipboard."""
        content = self.text.get('1.0', 'end-1c')
        self.clipboard_clear()
        self.clipboard_append(content)
        self._status.configure(text='✅ Prompt copiado! Cole na sua ferramenta de IA junto com a descrição do processo.')
        self.after(4000, lambda: self._status.configure(text=''))
