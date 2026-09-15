"""
app_window.py — Janela principal da aplicação Flow Forge.
Design: light mode corporativo "Deep Blue" (azul #003399 como ação primária).
"""
import tkinter as tk
from tkinter import filedialog, messagebox
import json
import os
import queue
import re
import traceback

from ui.json_panel import JSONPanel
from ui.properties_panel import PropertiesPanel
from ui.outline_panel import OutlinePanel
from ui.catalog_dialog import CatalogDialog
from ui.welcome_screen import WelcomeScreen
from ui.new_flow_wizard import NewFlowWizard
from ui.status_bar import StatusBar
from ui.prompt_viewer import PromptViewer
from core.parser import (parse_flowchart, serialize_model, validate_model,
                         issue_messages, issue_node_ids, ParseError,
                         record_event, build_approval, fingerprint_matches,
                         current_author, mark_governance_dirty,
                         bloqueios, avisos, severidade)
from core.layout import compute_layout
from core.renderer import render
from core.editor import Editor
from core.viewport import Viewport
from core import catalogo as catalogo_mod
from core import preferencias as prefs
from core import prompt as prompt_mod
from core import versao as versao_mod
from export.pdf_export import (export_pdf, STAMP_DRAFT, STAMP_APPROVED,
                               PAPEIS, tamanho_papel)

MAX_HISTORY = 50

# ── Paleta "Deep Blue" (light, corporativa) ────────────
BG_WINDOW = '#f2f5fa'        # fundo geral (blue-50)
BG_TOOLBAR = '#ffffff'       # toolbar branca
BG_CANVAS = '#ffffff'        # canvas branco
ACCENT = '#003399'           # azul primário de ação
ACCENT_HOVER = '#002a7d'     # hover primário (blue-800)
BTN_BG = '#e6ebf5'           # botão neutro (blue-100)
BTN_FG = '#262626'           # texto botão (ink-800)
BTN_HOVER = '#ccd6eb'        # hover neutro (blue-200)
BORDER = '#ccd6eb'           # bordas estruturais (blue-200)
TEXT_DARK = '#000000'        # texto principal
TEXT_MUTED = '#4d4d4d'       # texto secundário (piso 70%)
WARN_MARK = '#d13438'        # defeito de estrutura (barra publicação)
ABERTO_MARK = '#b8860b'      # observação / ponto em aberto (só avisa)
EDIT_ON = '#107c10'          # verde de sucesso para modo edição
EDIT_ON_HOVER = '#0d640d'


class AppWindow:
    """Janela principal do Flow Forge."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f'Flow Forge {versao_mod.VERSAO}')
        self.root.geometry('1400x850')
        self.root.minsize(900, 600)
        self.root.configure(bg=BG_WINDOW)

        # Ícone da janela
        import sys
        if getattr(sys, 'frozen', False):
            icon_base = sys._MEIPASS
        else:
            icon_base = os.path.dirname(os.path.dirname(__file__))
        icon_path = os.path.join(icon_base, 'icon.ico')
        if os.path.exists(icon_path):
            self.root.iconbitmap(icon_path)

        # Estado
        self.model = None
        self.editor = None
        self.edit_mode = False
        # Transformação de vista: o modelo guarda as coordenadas, o viewport
        # guarda o zoom. Editor e canvas compartilham esta mesma instância.
        self.viewport = Viewport()
        # Catálogo corporativo de departamentos e cargos (padronização de nomes)
        self.catalogo = catalogo_mod.carregar()
        # Enquanto o arquivo do usuário não existe, a padronização roda contra a
        # lista de exemplo embutida — e isso precisa ser dito, não suposto.
        self._catalogo_e_semente = not os.path.exists(
            catalogo_mod.caminho_catalogo())
        # "Violado" é estado de SESSÃO: nunca vai para o disco. Gravar isso no
        # arquivo seria adulterá-lo só por abri-lo.
        self._aprovacao_violada = False
        self._loaded_mtime = None
        self._fila_correcao = []
        self.welcome = None

        # Arquivo atual e controle de alterações
        self.current_file = None
        self._modified = False

        # Histórico para desfazer/refazer (snapshots de JSON)
        self._history = []
        self._redo_stack = []
        self._last_json = ''

        self._build_menu()
        self._build_barra_atualizacao()
        self._build_toolbar()
        self._build_main_area()
        self._build_status_bar()
        self._bind_shortcuts()
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        self._update_title()
        self._mostrar_boas_vindas()
        # Uma consulta por abertura, em segundo plano. Se falhar, ninguém fica
        # sabendo — e não deve mesmo ficar.
        self.root.after(1200, self._checar_atualizacao)

    def _build_menu(self):
        menubar = tk.Menu(self.root, bg=BG_TOOLBAR, fg=TEXT_DARK,
                          activebackground=ACCENT, activeforeground='#ffffff',
                          relief='flat', bd=0)

        file_menu = tk.Menu(menubar, tearoff=0, bg='#ffffff', fg=TEXT_DARK,
                            activebackground='#e6ebf5', activeforeground=TEXT_DARK)
        file_menu.add_command(label='  ✦  Novo documento em branco', command=self._novo_documento, accelerator='Ctrl+N')
        file_menu.add_command(label='  🤖  Novo com assistente de IA...', command=self._novo_fluxo, accelerator='Ctrl+Shift+N')
        file_menu.add_command(label='  🏠  Tela inicial', command=self._mostrar_boas_vindas)
        file_menu.add_separator()
        file_menu.add_command(label='  📂  Abrir JSON...', command=self._open_file, accelerator='Ctrl+O')
        file_menu.add_command(label='  💾  Salvar', command=self._save_json, accelerator='Ctrl+S')
        file_menu.add_command(label='  💾  Salvar como...', command=self._save_json_as, accelerator='Ctrl+Shift+S')
        file_menu.add_separator()
        file_menu.add_command(label='  📄  Exportar PDF (rascunho)...', command=self._export_pdf, accelerator='Ctrl+P')
        file_menu.add_command(label='  ✅  Publicar (validar e aprovar)...', command=self._publish)
        file_menu.add_separator()
        file_menu.add_command(label='  ❌  Sair', command=self._on_close)
        menubar.add_cascade(label='  Arquivo  ', menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0, bg='#ffffff', fg=TEXT_DARK,
                            activebackground='#e6ebf5', activeforeground=TEXT_DARK)
        edit_menu.add_command(label='  ↶  Desfazer', command=self._undo, accelerator='Ctrl+Z')
        edit_menu.add_command(label='  ↷  Refazer', command=self._redo, accelerator='Ctrl+Y')
        edit_menu.add_separator()
        edit_menu.add_command(label='  ⧉  Copiar nó', command=lambda: self._edit_action('copy'), accelerator='Ctrl+C')
        edit_menu.add_command(label='  📋  Colar nó', command=lambda: self._edit_action('paste'), accelerator='Ctrl+V')
        edit_menu.add_command(label='  ⧉  Duplicar nó', command=lambda: self._edit_action('duplicate'), accelerator='Ctrl+D')
        edit_menu.add_command(label='  🗑  Excluir nó', command=lambda: self._edit_action('delete'), accelerator='Del')
        edit_menu.add_separator()
        edit_menu.add_command(label='  ✏  Alternar modo edição', command=self._toggle_edit, accelerator='Ctrl+E')
        edit_menu.add_command(label='  ⟲  Auto-organizar layout', command=self._auto_layout, accelerator='Ctrl+L')
        menubar.add_cascade(label='  Editar  ', menu=edit_menu)

        cfg_menu = tk.Menu(menubar, tearoff=0, bg='#ffffff', fg=TEXT_DARK,
                           activebackground='#e6ebf5', activeforeground=TEXT_DARK)
        cfg_menu.add_command(label='  🏷  Departamentos e cargos...',
                             command=self._abrir_catalogo)
        menubar.add_cascade(label='  Configurações  ', menu=cfg_menu)

        view_menu = tk.Menu(menubar, tearoff=0, bg='#ffffff', fg=TEXT_DARK,
                            activebackground='#e6ebf5', activeforeground=TEXT_DARK)
        view_menu.add_command(label='  🔍+  Zoom In', command=lambda: self._zoom(1.2), accelerator='Ctrl++')
        view_menu.add_command(label='  🔍−  Zoom Out', command=lambda: self._zoom(0.8), accelerator='Ctrl+-')
        view_menu.add_command(label='  🔄  Zoom 100%', command=lambda: self._zoom_reset())
        view_menu.add_command(label='  ⛶  Ajustar à janela', command=self._zoom_fit, accelerator='Ctrl+0')
        view_menu.add_separator()
        view_menu.add_command(label='  ☰  Índice do documento', command=self._toggle_outline_panel, accelerator='Ctrl+F')
        view_menu.add_command(label='  🧾  JSON avançado', command=self._toggle_json_panel)
        menubar.add_cascade(label='  Visualizar  ', menu=view_menu)

        ajuda_menu = tk.Menu(menubar, tearoff=0, bg='#ffffff', fg=TEXT_DARK,
                             activebackground='#e6ebf5', activeforeground=TEXT_DARK)
        ajuda_menu.add_command(label='  ⭯  Verificar atualizações',
                               command=self._checar_atualizacao_manual)
        ajuda_menu.add_separator()
        ajuda_menu.add_command(label='  ℹ  Sobre o Flow Forge',
                               command=self._mostrar_sobre)
        menubar.add_cascade(label='  Ajuda  ', menu=ajuda_menu)

        self.root.config(menu=menubar)

    def _build_barra_atualizacao(self):
        """Faixa discreta de "há versão nova" — some quando não há o que dizer.

        Fica acima da toolbar e só aparece quando existe atualização: uma faixa
        permanente com "está tudo em dia" seria ruído em 99% das aberturas.
        """
        self.barra_att = tk.Frame(self.root, bg='#e8f2e8',
                                  highlightthickness=1,
                                  highlightbackground='#a9cfa9')
        interno = tk.Frame(self.barra_att, bg='#e8f2e8')
        interno.pack(fill='x', padx=14, pady=7)
        self.lbl_att = tk.Label(interno, text='', font=('Segoe UI', 9),
                                bg='#e8f2e8', fg='#14521f', anchor='w',
                                justify='left')
        self.lbl_att.pack(side='left')

        tk.Button(interno, text='✕', command=self._fechar_barra_atualizacao,
                  font=('Segoe UI', 9), bg='#e8f2e8', fg='#14521f', bd=0,
                  relief='flat', cursor='hand2', padx=6,
                  activebackground='#d5e8d5').pack(side='right')
        self.btn_att = tk.Button(interno, text='Baixar', command=self._abrir_download,
                                 font=('Segoe UI', 9, 'bold'), bg=EDIT_ON,
                                 fg='#ffffff', bd=0, relief='flat',
                                 cursor='hand2', padx=14, pady=3,
                                 activebackground=EDIT_ON_HOVER,
                                 activeforeground='#ffffff')
        self.btn_att.pack(side='right', padx=(0, 10))
        self._att_info = None
        # Ponte entre a thread de rede e a da interface
        self._fila_att = queue.Queue()
        self._att_tentativas = 0

    def _mostrar_barra_atualizacao(self, info):
        """Chamado na thread da interface, com o resultado da verificação."""
        if not info:
            return
        self._att_info = info
        notas = f" — {info['notas']}" if info.get('notas') else ''
        self.lbl_att.configure(
            text=f"⭯  Versão {info['versao']} disponível "
                 f"(você está na {versao_mod.VERSAO}){notas}")
        self.btn_att.configure(state='normal' if info.get('url') else 'disabled')
        self.barra_att.pack(fill='x', side='top', before=self._toolbar_wrapper)

    def _fechar_barra_atualizacao(self):
        self.barra_att.pack_forget()

    def _abrir_download(self):
        import webbrowser
        if self._att_info and self._att_info.get('url'):
            webbrowser.open(self._att_info['url'])

    def _checar_atualizacao(self, manual=False):
        """Dispara a consulta sem travar a interface.

        A thread de rede NÃO toca em widget nenhum: ela só deposita o resultado
        numa fila, e a interface o colhe de dentro da própria thread dela. O Tk
        não é thread-safe — `after()` chamado de fora da thread da interface
        simplesmente não executa, em silêncio.
        """
        if not versao_mod.URL_ATUALIZACAO:
            if manual:
                self.status_bar.set_message(
                    'ℹ Verificação de atualização não configurada nesta versão',
                    'info')
            return
        if manual:
            self.status_bar.set_message('⭯ Verificando atualizações…', 'info')
        versao_mod.checar_em_segundo_plano(
            lambda info: self._fila_att.put((info, manual)))
        self.root.after(250, self._colher_atualizacao)

    def _colher_atualizacao(self):
        """Lê o resultado da consulta, já na thread da interface."""
        try:
            info, manual = self._fila_att.get_nowait()
        except queue.Empty:
            self._att_tentativas = getattr(self, '_att_tentativas', 0) + 1
            if self._att_tentativas < 60:          # ~15s de paciência
                self.root.after(250, self._colher_atualizacao)
            return
        self._att_tentativas = 0
        self._resultado_atualizacao(info, manual)

    def _resultado_atualizacao(self, info, manual):
        if info:
            self._mostrar_barra_atualizacao(info)
        elif manual:
            self.status_bar.set_message(
                f'✅ Você está na versão mais recente ({versao_mod.VERSAO})',
                'success')

    def _checar_atualizacao_manual(self):
        self._checar_atualizacao(manual=True)

    def _mostrar_sobre(self):
        messagebox.showinfo(
            'Sobre o Flow Forge',
            f'Flow Forge {versao_mod.VERSAO}\n\n'
            f'Mapeamento de processos em swimlanes.\n\n'
            f'Catálogo e preferências ficam em:\n'
            f'{catalogo_mod.diretorio_usuario()}\n\n'
            f'Essa pasta não é tocada pelas atualizações — a sua lista de '
            f'departamentos e cargos sobrevive a cada versão nova.')

    def _build_toolbar(self):
        # Toolbar container com borda inferior sutil
        toolbar_wrapper = tk.Frame(self.root, bg=BORDER, height=1)
        toolbar_wrapper.pack(fill='x', side='top')
        self._toolbar_wrapper = toolbar_wrapper

        toolbar = tk.Frame(toolbar_wrapper, bg=BG_TOOLBAR, height=50)
        toolbar.pack(fill='x', side='top')
        toolbar.pack_propagate(False)

        # Borda inferior
        tk.Frame(toolbar_wrapper, bg=BORDER, height=1).pack(fill='x', side='bottom')

        # ── Logo & Título ──
        brand_frame = tk.Frame(toolbar, bg=BG_TOOLBAR)
        brand_frame.pack(side='left', padx=(16, 20), pady=8)

        tk.Label(brand_frame, text='⬡', font=('Segoe UI', 16),
                 fg=ACCENT, bg=BG_TOOLBAR).pack(side='left')
        tk.Label(brand_frame, text=' Flow Forge', font=('Segoe UI', 13, 'bold'),
                 fg=TEXT_DARK, bg=BG_TOOLBAR).pack(side='left')

        # Separador vertical
        tk.Frame(toolbar, bg=BORDER, width=1).pack(side='left', fill='y', pady=10)

        # ── Botões de ação ──
        def tb_btn(parent, text, cmd, bg=BTN_BG, fg=BTN_FG, hover_bg=BTN_HOVER):
            btn = tk.Button(parent, text=text, command=cmd,
                            font=('Segoe UI', 9), fg=fg, bg=bg,
                            activebackground=hover_bg, activeforeground=fg,
                            bd=0, padx=14, pady=5, cursor='hand2', relief='flat')
            btn.pack(side='left', padx=(10, 0), pady=8)
            btn.bind('<Enter>', lambda e, b=btn, h=hover_bg: b.configure(bg=h))
            btn.bind('<Leave>', lambda e, b=btn, o=bg: b.configure(bg=o))
            return btn

        tb_btn(toolbar, '✦  Novo', self._novo_documento)
        tb_btn(toolbar, '🤖  Assistente', self._novo_fluxo)
        tb_btn(toolbar, '📂  Abrir', self._open_file)
        tb_btn(toolbar, '💾  Salvar', self._save_json)
        tb_btn(toolbar, '▶  Renderizar', self._render,
               bg=ACCENT, fg='#ffffff', hover_bg=ACCENT_HOVER)
        self._edit_btn = tb_btn(toolbar, '✏  Editar: OFF', self._toggle_edit)
        tb_btn(toolbar, '⟲  Auto-organizar', self._auto_layout)
        tb_btn(toolbar, '📄  Exportar PDF', self._export_pdf)
        tb_btn(toolbar, '✅  Publicar', self._publish,
               bg='#107c10', fg='#ffffff', hover_bg='#0d640d')

        # Separador vertical
        tk.Frame(toolbar, bg=BORDER, width=1).pack(side='left', fill='y', padx=6, pady=10)

        self._outline_btn = tb_btn(toolbar, '☰  Índice', self._toggle_outline_panel)
        self._json_btn = tb_btn(toolbar, '🧾  JSON avançado', self._toggle_json_panel)
        tb_btn(toolbar, '🤖  Prompt IA', self._show_prompt,
               bg='#e6ebf5', fg=ACCENT, hover_bg='#ccd6eb')

        # ── Zoom controls ──
        zoom_frame = tk.Frame(toolbar, bg=BG_TOOLBAR)
        zoom_frame.pack(side='right', padx=16)

        zoom_out = tk.Button(zoom_frame, text='−', command=lambda: self._zoom(0.8),
                             font=('Segoe UI', 11, 'bold'), fg=TEXT_MUTED, bg=BTN_BG,
                             bd=0, width=3, cursor='hand2', relief='flat',
                             activebackground=BTN_HOVER)
        zoom_out.pack(side='left', padx=2)
        zoom_out.bind('<Enter>', lambda e: zoom_out.configure(bg=BTN_HOVER))
        zoom_out.bind('<Leave>', lambda e: zoom_out.configure(bg=BTN_BG))

        self._zoom_label = tk.Label(zoom_frame, text='100%', font=('Segoe UI', 9),
                                    fg=TEXT_MUTED, bg=BG_TOOLBAR, width=6)
        self._zoom_label.pack(side='left')

        fit = tk.Button(zoom_frame, text='⛶', command=self._zoom_fit,
                        font=('Segoe UI', 10), fg=TEXT_MUTED, bg=BTN_BG,
                        bd=0, width=3, cursor='hand2', relief='flat',
                        activebackground=BTN_HOVER)
        fit.pack(side='left', padx=(6, 0))
        fit.bind('<Enter>', lambda e: fit.configure(bg=BTN_HOVER))
        fit.bind('<Leave>', lambda e: fit.configure(bg=BTN_BG))

        zoom_in = tk.Button(zoom_frame, text='+', command=lambda: self._zoom(1.2),
                            font=('Segoe UI', 11, 'bold'), fg=TEXT_MUTED, bg=BTN_BG,
                            bd=0, width=3, cursor='hand2', relief='flat',
                            activebackground=BTN_HOVER)
        zoom_in.pack(side='left', padx=2)
        zoom_in.bind('<Enter>', lambda e: zoom_in.configure(bg=BTN_HOVER))
        zoom_in.bind('<Leave>', lambda e: zoom_in.configure(bg=BTN_BG))

    def _build_main_area(self):
        # PanedWindow horizontal
        paned = tk.PanedWindow(self.root, orient='horizontal', bg=BORDER,
                               sashwidth=4, sashrelief='flat')
        paned.pack(fill='both', expand=True)

        self._paned = paned

        # Painel de propriedades (esquerda) — porta principal de edição
        self.properties_panel = PropertiesPanel(
            paned,
            on_node_type=lambda v: self._prop_set('set_node_type', v),
            on_node_lane=lambda v: self._prop_set('set_node_lane', v),
            on_node_label=lambda v: self._prop_set('set_node_label', v),
            on_department=self._prop_set_department,
            on_lane_label=self._prop_set_lane_label,
            on_lane_department=self._prop_set_lane_department,
            on_add_lane=self._prop_add_lane,
            on_remove_lane=self._prop_remove_lane,
            on_move_lane=self._prop_move_lane,
            on_ponto_aberto=self._prop_ponto_aberto,
            on_edge_label=self._prop_edge_label,
            on_edit_catalog=self._abrir_catalogo)
        self.properties_panel.set_catalogo(self.catalogo)
        paned.add(self.properties_panel, width=280, minsize=220)

        # Índice do documento: navegação em fluxo longo. Entra sob demanda,
        # como o painel JSON.
        self.outline_panel = OutlinePanel(paned,
                                          on_goto_node=self._ir_para_no,
                                          on_goto_issue=self._ir_para_issue)
        self._outline_visivel = False

        # Painel JSON: ferramenta avançada, entra sob demanda pela toolbar
        self.json_panel = JSONPanel(paned, on_render=self._render,
                                    on_load=self._open_file)
        self._json_visivel = False

        # Canvas (direita)
        canvas_frame = tk.Frame(paned, bg=BG_WINDOW)
        paned.add(canvas_frame, minsize=400)

        self.canvas = tk.Canvas(canvas_frame, bg=BG_CANVAS, highlightthickness=0)
        h_scroll = tk.Scrollbar(canvas_frame, orient='horizontal', command=self.canvas.xview)
        v_scroll = tk.Scrollbar(canvas_frame, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)

        h_scroll.pack(side='bottom', fill='x')
        v_scroll.pack(side='right', fill='y')

        # Paleta de ferramentas — só aparece no modo edição
        self.palette = self._build_palette(canvas_frame)
        self.canvas.pack(fill='both', expand=True)

        # Scroll vertical com mouse wheel
        self.canvas.bind('<MouseWheel>', self._on_scroll_vertical)
        # Scroll horizontal com Shift + mouse wheel
        self.canvas.bind('<Shift-MouseWheel>', self._on_scroll_horizontal)
        # Zoom com Ctrl + mouse wheel
        self.canvas.bind('<Control-MouseWheel>', self._on_scroll_zoom)
        # Pan com middle mouse ou click direito
        self.canvas.bind('<ButtonPress-2>', self._pan_start)
        self.canvas.bind('<B2-Motion>', self._pan_move)
        self._bind_right_pan()

    def _bind_right_pan(self):
        """Pan com botão direito (no modo edição ele vira menu de contexto)."""
        self.canvas.bind('<ButtonPress-3>', self._pan_start)
        self.canvas.bind('<B3-Motion>', self._pan_move)

    def _make_editor(self):
        """Cria o editor ligado ao modelo atual."""
        return Editor(self.canvas, self.model, self._on_editor_change,
                      on_status=self.status_bar.set_message,
                      on_tool_done=self._clear_tool_highlight,
                      viewport=self.viewport,
                      on_selection_change=self._on_selection_change,
                      catalogo=self.catalogo)

    # ── Paleta de ferramentas (modo edição) ────────────────

    def _build_palette(self, parent):
        """Paleta lateral para criar balões e conexões no modo edição."""
        pal = tk.Frame(parent, bg=BG_TOOLBAR, bd=0,
                       highlightthickness=1, highlightbackground=BORDER)
        tk.Label(pal, text='FERRAMENTAS', font=('Segoe UI', 8, 'bold'),
                 fg=TEXT_MUTED, bg=BG_TOOLBAR).pack(fill='x', padx=12, pady=(12, 6))

        self._tool_btns = {}
        self._active_tool = None

        # (chave, rótulo do botão, ação: ('add', tipo, label, automática) | outras)
        tools = [
            ('task',       '▭   Tarefa',              ('add', 'task', 'Nova tarefa', False)),
            ('auto',       '⚙   Tarefa automática',   ('add', 'task', 'Tarefa automática', True)),
            ('decision',   '⬡   Decisão',             ('add', 'decision', 'Nova decisão?', False)),
            ('start',      '⬭   Início',              ('add', 'start', 'Início', False)),
            ('end',        '▬   Fim (produto)',       ('add', 'end', 'Fim', False)),
            ('subprocess', '⚠   Instr. de Trabalho',  ('add', 'subprocess', 'Nova instrução de trabalho', False)),
            ('parallel',   '║   Paralelismo (barra)', ('add', 'parallel', '', False)),
            ('comment',    '💬  Comentário',          ('comment',)),
            None,  # separador
            ('connect',    '🔗  Conectar nós',        ('connect',)),
        ]
        for tool in tools:
            if tool is None:
                tk.Frame(pal, bg=BORDER, height=1).pack(fill='x', padx=10, pady=6)
                continue
            key, text, spec = tool
            btn = tk.Button(pal, text=text, font=('Segoe UI', 9),
                            fg=BTN_FG, bg=BG_TOOLBAR,
                            activebackground=BTN_BG, activeforeground=BTN_FG,
                            bd=0, padx=12, pady=5, cursor='hand2',
                            relief='flat', anchor='w',
                            command=lambda k=key, s=spec: self._arm_tool(k, s))
            btn.pack(fill='x', padx=6, pady=1)
            btn.bind('<Enter>', lambda e, k=key, b=btn:
                     b.configure(bg=BTN_BG) if self._active_tool != k else None)
            btn.bind('<Leave>', lambda e, k=key, b=btn:
                     b.configure(bg=BG_TOOLBAR) if self._active_tool != k else None)
            self._tool_btns[key] = btn

        tk.Label(pal, text='Esc cancela a ferramenta', font=('Segoe UI', 8),
                 fg=TEXT_MUTED, bg=BG_TOOLBAR).pack(fill='x', padx=12, pady=(8, 12))
        return pal

    def _arm_tool(self, key, spec):
        """Ativa uma ferramenta da paleta (o próximo clique no canvas executa)."""
        if not (self.edit_mode and self.editor):
            self.status_bar.set_message('⚠ Renderize um fluxograma primeiro', 'warning')
            return
        self._set_active_tool(key)
        if spec[0] == 'add':
            _, ntype, label, automatic = spec
            self.editor.arm_add(ntype, label, automatic=automatic)
        elif spec[0] == 'comment':
            self.editor.arm_comment()
        else:
            self.editor.arm_connect()

    def _set_active_tool(self, key):
        self._active_tool = key
        for k, b in self._tool_btns.items():
            if k == key:
                b.configure(bg=ACCENT, fg='#ffffff')
            else:
                b.configure(bg=BG_TOOLBAR, fg=BTN_FG)

    def _clear_tool_highlight(self):
        self._active_tool = None
        for b in self._tool_btns.values():
            b.configure(bg=BG_TOOLBAR, fg=BTN_FG)

    def _show_palette(self):
        self.palette.pack(side='left', fill='y', before=self.canvas)

    def _hide_palette(self):
        self._clear_tool_highlight()
        self.palette.pack_forget()

    def _build_status_bar(self):
        self.status_bar = StatusBar(self.root)
        self.status_bar.pack(fill='x', side='bottom')

    def _bind_shortcuts(self):
        self.root.bind('<Control-n>', lambda e: self._novo_documento())
        self.root.bind('<Control-N>', lambda e: self._novo_fluxo())  # Ctrl+Shift+N
        self.root.bind('<Control-o>', lambda e: self._open_file())
        self.root.bind('<Control-r>', lambda e: self._render())
        self.root.bind('<Control-e>', lambda e: self._toggle_edit())
        self.root.bind('<Control-s>', lambda e: self._save_json())
        self.root.bind('<Control-S>', lambda e: self._save_json_as())  # Ctrl+Shift+S
        self.root.bind('<Control-p>', lambda e: self._export_pdf())
        self.root.bind('<Control-l>', lambda e: self._auto_layout())
        self.root.bind('<Control-0>', lambda e: self._zoom_fit())
        self.root.bind('<Control-f>', lambda e: self._abrir_indice_e_buscar())
        self.root.bind('<Control-z>', self._undo)
        self.root.bind('<Control-y>', self._redo)

    def _load_sample(self):
        """Carrega o JSON de exemplo."""
        import sys
        if getattr(sys, 'frozen', False):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(os.path.dirname(__file__))
        sample_path = os.path.join(base, 'data', 'sample.json')
        if os.path.exists(sample_path):
            self._esconder_boas_vindas()
            with open(sample_path, 'r', encoding='utf-8') as f:
                self.json_panel.set_json(f.read())
            self.current_file = None
            self._render()
            self.status_bar.set_message(
                '👁 Exemplo carregado — "Salvar como..." para partir dele',
                'info')

    # ── Ações ──────────────────────────────────────────────

    def _render(self):
        """Parsea JSON, calcula layout e renderiza.

        O painel de texto é a segunda porta de entrada do documento. Ela passa
        pelo mesmo histórico da edição no canvas: sem isso, o Ctrl+Z
        significava uma coisa depois de arrastar um nó e outra depois de mexer
        no JSON — e o estado anterior ao "Renderizar" se perdia.
        """
        json_text = self.json_panel.get_json()
        if not json_text.strip():
            self.status_bar.set_message('JSON vazio', 'warning')
            return

        # Reset zoom ao renderizar novo JSON
        self.viewport.reset()
        self._zoom_label.configure(text='100%')

        alterado_no_painel = bool(self._last_json) and json_text != self._last_json

        try:
            self.model = parse_flowchart(json_text)
            self.model = compute_layout(self.model)
            if alterado_no_painel:
                self._push_history()
            self._paint()

            n_nodes = len(self.model['nodes'])
            n_lanes = len(self.model['lanes'])
            n_edges = len(self.model['edges'])
            n_sp = len(self.model['subprocesses'])

            self._report_issues(self._show_issues())
            self.properties_panel.set_document(self.model)
            self.properties_panel.set_editable(bool(self.edit_mode and self.editor))
            self._atualizar_indice()
            stats = f'{n_lanes} lanes • {n_nodes} nós • {n_edges} edges'
            if n_sp:
                stats += f' • {n_sp} subprocessos'
            self.status_bar.set_stats(stats)
            self._last_json = json_text
            if alterado_no_painel:
                self._set_modified(True)

            # Recriar editor se ativo
            if self.edit_mode and self.model:
                self.editor = self._make_editor()
                self.editor.enable()

        except ParseError as e:
            self.status_bar.set_message(f'❌ Erro: {e}', 'error')
        except Exception as e:
            traceback.print_exc()
            self.status_bar.set_message(f'❌ Erro inesperado: {e}', 'error')

    def _open_file(self):
        """Abre diálogo para carregar arquivo JSON."""
        path = filedialog.askopenfilename(
            title='Abrir JSON',
            filetypes=[('JSON files', '*.json'), ('All files', '*.*')]
        )
        if path:
            try:
                self._esconder_boas_vindas()
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.json_panel.set_json(content)
                self.current_file = path
                self._history.clear()
                self._redo_stack.clear()
                self._render()
                try:
                    self._loaded_mtime = os.path.getmtime(path)
                except OSError:
                    self._loaded_mtime = None
                self._set_modified(False)
                self.status_bar.set_message(f'📂 Arquivo carregado: {os.path.basename(path)}', 'info')
                self._registrar_recente(path)
                # Abrir não gera evento — só confere se a aprovação ainda vale
                self._checar_aprovacao()
            except Exception as e:
                traceback.print_exc()
                self.status_bar.set_message(f'❌ Erro ao abrir: {e}', 'error')

    def _save_json(self):
        """Salva no arquivo atual (Ctrl+S). Sem arquivo aberto, pergunta o destino."""
        if not self.current_file:
            self._save_json_as()
            return
        try:
            with open(self.current_file, 'w', encoding='utf-8') as f:
                f.write(self._texto_para_gravar('salvar'))
            try:
                self._loaded_mtime = os.path.getmtime(self.current_file)
            except OSError:
                self._loaded_mtime = None
            self._set_modified(False)
            self.status_bar.set_message(f'💾 Salvo: {os.path.basename(self.current_file)}', 'success')
        except Exception as e:
            traceback.print_exc()
            self.status_bar.set_message(f'❌ Erro ao salvar: {e}', 'error')

    def _save_json_as(self):
        """Salva o JSON atual em um novo arquivo (Salvar como...)."""
        initial = os.path.basename(self.current_file) if self.current_file else \
            (f"{self.model['title']}.json" if self.model else 'fluxograma.json')
        path = filedialog.asksaveasfilename(
            title='Salvar JSON como',
            defaultextension='.json',
            initialfile=initial,
            filetypes=[('JSON files', '*.json')]
        )
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(self._texto_para_gravar('salvar'))
                self.current_file = path
                try:
                    self._loaded_mtime = os.path.getmtime(path)
                except OSError:
                    self._loaded_mtime = None
                self._set_modified(False)
                self._registrar_recente(path)
                self.status_bar.set_message(f'💾 Salvo: {os.path.basename(path)}', 'success')
            except Exception as e:
                traceback.print_exc()
                self.status_bar.set_message(f'❌ Erro ao salvar: {e}', 'error')

    def _texto_para_gravar(self, kind):
        """Texto a gravar em disco, já com o evento de auditoria dentro dele.

        A trilha mora no arquivo que ela audita: registrar o evento e só então
        serializar é o que garante que o salvamento e o seu registro sejam a
        mesma escrita, não duas.
        """
        if not self.model:
            return self.json_panel.get_json()
        self._append_audit(kind)
        try:
            texto = json.dumps(serialize_model(self.model), indent=2,
                               ensure_ascii=False)
        except (TypeError, ValueError):
            return self.json_panel.get_json()   # trilha nunca impede salvar
        self.json_panel.set_json(texto)
        self._last_json = texto
        return texto

    def _escolher_papel(self):
        """Pergunta em que folha o PDF deve caber. Devolve (papel, orientação).

        A página saía do tamanho do diagrama — 28 × 55 cm num fluxo real, que
        não é papel nenhum. A impressora reduzia sozinha ou fatiava, e o
        fluxograma não servia para imprimir e colar na parede, que é o uso.
        """
        comp = (self.model or {}).get('_computed', {})
        dw = comp.get('total_width', 0)
        dh = comp.get('total_height', 0)

        escolha = {'papel': prefs.carregar().get('papel_pdf', 'A4'),
                   'orientacao': 'auto', 'ok': False}

        janela = tk.Toplevel(self.root)
        janela.title('Exportar PDF')
        janela.configure(bg=BG_WINDOW)
        janela.transient(self.root)
        janela.resizable(False, False)

        tk.Label(janela, text='Em que folha o desenho deve caber?',
                 font=('Segoe UI', 11, 'bold'), bg=BG_WINDOW,
                 fg=TEXT_DARK).pack(anchor='w', padx=18, pady=(16, 2))
        tk.Label(janela, text=f'O diagrama tem {dw / 72 * 2.54:.0f} × '
                              f'{dh / 72 * 2.54:.0f} cm.',
                 font=('Segoe UI', 9), bg=BG_WINDOW,
                 fg=TEXT_MUTED).pack(anchor='w', padx=18)

        var_papel = tk.StringVar(value=escolha['papel'])
        var_orient = tk.StringVar(value='auto')

        corpo = tk.Frame(janela, bg=BG_WINDOW)
        corpo.pack(fill='x', padx=18, pady=(12, 4))
        opcoes = [(nome, nome) for nome in PAPEIS] + \
                 [('Tamanho do desenho (não imprime bem)', '')]
        for rotulo, valor in opcoes:
            linha = tk.Frame(corpo, bg=BG_WINDOW)
            linha.pack(fill='x', pady=1)
            tk.Radiobutton(linha, text=rotulo, variable=var_papel, value=valor,
                           font=('Segoe UI', 10), bg=BG_WINDOW, fg=TEXT_DARK,
                           activebackground=BG_WINDOW, selectcolor='#ffffff',
                           bd=0, highlightthickness=0,
                           anchor='w').pack(side='left')
            if valor:
                pw, ph = tamanho_papel(valor, 'auto', desenho=(dw, dh))
                reduz = min((pw - 57) / dw, (ph - 57) / dh, 1.0) if dw and dh else 1
                tk.Label(linha, text=f'{reduz:.0%} do tamanho',
                         font=('Segoe UI', 8), bg=BG_WINDOW,
                         fg=TEXT_MUTED).pack(side='right')

        ori = tk.Frame(janela, bg=BG_WINDOW)
        ori.pack(fill='x', padx=18, pady=(10, 0))
        tk.Label(ori, text='Orientação:', font=('Segoe UI', 9), bg=BG_WINDOW,
                 fg=TEXT_MUTED).pack(side='left', padx=(0, 8))
        for rotulo, valor in (('Automática', 'auto'), ('Retrato', 'retrato'),
                              ('Paisagem', 'paisagem')):
            tk.Radiobutton(ori, text=rotulo, variable=var_orient, value=valor,
                           font=('Segoe UI', 9), bg=BG_WINDOW, fg=TEXT_DARK,
                           activebackground=BG_WINDOW, selectcolor='#ffffff',
                           bd=0, highlightthickness=0).pack(side='left')

        barra = tk.Frame(janela, bg=BG_WINDOW)
        barra.pack(fill='x', padx=18, pady=16)

        def confirmar():
            escolha['papel'] = var_papel.get()
            escolha['orientacao'] = var_orient.get()
            escolha['ok'] = True
            dados = prefs.carregar()
            dados['papel_pdf'] = var_papel.get()
            prefs.salvar(dados)
            janela.destroy()

        tk.Button(barra, text='Exportar', command=confirmar, bg=ACCENT,
                  fg='#ffffff', font=('Segoe UI', 9, 'bold'), bd=0,
                  relief='flat', padx=20, pady=6,
                  cursor='hand2').pack(side='right')
        tk.Button(barra, text='Cancelar', command=janela.destroy, bg=BTN_BG,
                  fg=BTN_FG, font=('Segoe UI', 9), bd=0, relief='flat',
                  padx=14, pady=6, cursor='hand2').pack(side='right', padx=(0, 8))

        janela.bind('<Return>', lambda e: confirmar())
        janela.bind('<Escape>', lambda e: janela.destroy())
        janela.grab_set()
        self.root.wait_window(janela)
        if not escolha['ok']:
            return None
        return escolha['papel'] or None, escolha['orientacao']

    def _show_prompt(self):
        """Prompt de IA — já travado nas colunas, quando há um fluxo aberto.

        Com um fluxo na tela, o prompt genérico é o errado: ele deixaria a IA
        inventar atores que não estão no documento. Aqui ele sai com as mesmas
        rédeas que o assistente de criação monta.
        """
        texto = None
        if self.model and self.model.get('lanes'):
            selecao = [(l.get('department', ''), l.get('label', ''))
                       for l in self.model['lanes']]
            texto = prompt_mod.montar(selecao, self.model.get('title', ''),
                                      self.model.get('docCode', ''))
        PromptViewer(self.root, texto=texto)

    def _export_pdf(self):
        """Exporta o fluxograma para PDF — sempre a partir do estado atual do JSON."""
        json_text = self.json_panel.get_json()
        if not json_text.strip():
            self.status_bar.set_message('⚠ JSON vazio — nada para exportar', 'warning')
            return

        # Reconstruir o modelo do JSON atual: garante que o PDF é idêntico
        # ao que está na tela, mesmo sem clicar em Renderizar antes
        try:
            model = compute_layout(parse_flowchart(json_text))
        except ParseError as e:
            messagebox.showerror('Exportar PDF', f'JSON inválido:\n{e}')
            return

        # Nome de arquivo seguro a partir do título
        safe_title = re.sub(r'[<>:"/\\|?*]', '-', model['title']).strip() or 'fluxograma'
        initialdir = os.path.dirname(self.current_file) if self.current_file else None

        formato = self._escolher_papel()
        if formato is None:
            return
        papel, orientacao = formato

        path = filedialog.asksaveasfilename(
            title='Exportar PDF',
            defaultextension='.pdf',
            initialfile=f'{safe_title}.pdf',
            initialdir=initialdir,
            filetypes=[('PDF files', '*.pdf')]
        )
        if not path:
            return

        try:
            carimbo, referencia = self._estado_publicacao()
            export_pdf(model, path, stamp=carimbo, stamp_ref=referencia,
                       papel=papel, orientacao=orientacao)
        except PermissionError:
            messagebox.showerror(
                'Exportar PDF',
                f'Não foi possível gravar em:\n{path}\n\n'
                'O arquivo provavelmente está aberto em outro programa '
                '(ex.: leitor de PDF). Feche-o e exporte novamente.')
            self.status_bar.set_message('❌ Exportação falhou: arquivo em uso', 'error')
            return
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror('Exportar PDF', f'Erro ao exportar:\n{e}')
            self.status_bar.set_message(f'❌ Erro ao exportar: {e}', 'error')
            return

        # Sincronizar canvas com o modelo exportado (WYSIWYG)
        self.model = model
        self._paint()
        if self.edit_mode:
            self.editor = self._make_editor()
            self.editor.enable()

        onde = f' em {papel}' if papel else ' no tamanho do desenho'
        self.status_bar.set_message(f'📄 PDF exportado{onde}: {path}', 'success')
        if messagebox.askyesno('PDF exportado',
                               f'PDF salvo em:\n{path}\n\nAbrir agora?'):
            try:
                os.startfile(path)
            except OSError as e:
                self.status_bar.set_message(f'⚠ Não foi possível abrir o PDF: {e}', 'warning')

    def _toggle_edit(self):
        """Alterna modo edição."""
        self.edit_mode = not self.edit_mode
        if self.edit_mode:
            if self.model:
                self.editor = self._make_editor()
                self.editor.enable()
            self._show_palette()
            self._edit_btn.configure(text='✏  Editar: ON', bg=EDIT_ON, fg='#ffffff')
            self._edit_btn.unbind('<Enter>')
            self._edit_btn.unbind('<Leave>')
            self._edit_btn.bind('<Enter>', lambda e: self._edit_btn.configure(bg=EDIT_ON_HOVER))
            self._edit_btn.bind('<Leave>', lambda e: self._edit_btn.configure(bg=EDIT_ON))
            self.properties_panel.set_editable(True)
            self.status_bar.set_message(
                '✏ Modo edição: arraste os nós • duplo clique edita textos • '
                'clique direito abre o menu • Ctrl+C/Ctrl+V copia e cola • '
                'Del exclui • Ctrl+Z desfaz', 'info')
        else:
            if self.editor:
                self.editor.disable()
            self._hide_palette()
            self._bind_right_pan()  # devolver o pan ao botão direito
            self._edit_btn.configure(text='✏  Editar: OFF', bg=BTN_BG, fg=BTN_FG)
            self._edit_btn.unbind('<Enter>')
            self._edit_btn.unbind('<Leave>')
            self._edit_btn.bind('<Enter>', lambda e: self._edit_btn.configure(bg=BTN_HOVER))
            self._edit_btn.bind('<Leave>', lambda e: self._edit_btn.configure(bg=BTN_BG))
            self.properties_panel.set_editable(False)
            self.status_bar.set_message('Modo visualização', 'info')

    # ── Tela inicial e criação de fluxo ────────────────────

    def _mostrar_boas_vindas(self):
        """Volta para a tela de abertura, escondendo a área de trabalho.

        O programa abria já com um fluxograma de exemplo carregado, o que
        misturava "estou vendo um exemplo" com "estou editando o meu
        documento". A tela inicial separa as duas coisas.
        """
        if self._modified and not self._confirmar_descartar():
            return
        if self.edit_mode:
            self._toggle_edit()
        self._paned.pack_forget()
        self.status_bar.pack_forget()
        if getattr(self, 'welcome', None) is None:
            self.welcome = WelcomeScreen(
                self.root,
                on_new=self._novo_documento,
                on_wizard=self._novo_fluxo,
                on_open=self._open_file,
                on_open_recent=self._abrir_caminho,
                on_catalog=self._abrir_catalogo,
                on_sample=self._load_sample,
                recentes=prefs.recentes(),
                catalogo_e_semente=self._catalogo_e_semente)
        else:
            self.welcome.set_recentes(prefs.recentes())
        self.welcome.pack(fill='both', expand=True)

    def _esconder_boas_vindas(self):
        """Mostra a área de trabalho — chamado ao abrir ou criar um fluxo."""
        if getattr(self, 'welcome', None) is not None:
            self.welcome.pack_forget()
        if not self._paned.winfo_ismapped():
            self._paned.pack(fill='both', expand=True)
            self.status_bar.pack(fill='x', side='bottom')

    def _confirmar_descartar(self):
        resp = messagebox.askyesnocancel(
            'Alterações não salvas',
            'Há alterações não salvas neste fluxograma. Salvar antes?')
        if resp is None:
            return False
        if resp:
            self._save_json()
            return not self._modified
        return True

    def _novo_documento(self):
        """Novo documento, na hora — sem assistente, sem perguntas.

        É o "documento em branco" de qualquer editor: clicou em Novo, tem um
        arquivo. O assistente de IA é um caminho a mais, não um pedágio: quem
        quer montar tudo à mão não deveria precisar atravessar quatro passos
        para chegar a uma tela onde possa desenhar.
        """
        if self.model and self._modified and not self._confirmar_descartar():
            return
        self._criar_fluxo({
            'title': 'Novo fluxograma',
            'lanes': [{'id': 'L1', 'label': 'Ator 1'}],
            'nodes': [],
            'edges': [],
        }, em_branco=True)

    def _novo_fluxo(self):
        """Assistente: departamentos → cargos → prompt → resultado da IA."""
        if self.model and self._modified and not self._confirmar_descartar():
            return
        NewFlowWizard(self.root, catalogo=self.catalogo,
                      on_finish=self._criar_fluxo,
                      on_edit_catalog=self._abrir_catalogo)

    def _criar_fluxo(self, documento, veio_da_ia=False, em_branco=False):
        """Recebe do assistente o documento pronto — da IA ou só com as colunas.

        Em qualquer dos dois casos o modo edição entra ligado: criar um fluxo e
        cair numa tela onde nada pode ser feito até achar o Ctrl+E era o ponto
        em que o fluxo de criação morria.
        """
        self._esconder_boas_vindas()
        self.current_file = None
        self._loaded_mtime = None
        self._history.clear()
        self._redo_stack.clear()
        self._last_json = ''
        self.json_panel.set_json(
            json.dumps(documento, indent=2, ensure_ascii=False))
        self._render()
        self._set_modified(True)
        if not self.edit_mode:
            self._toggle_edit()     # paleta de ferramentas disponível de saída
        colunas = len(documento.get('lanes', []))
        nos = len(documento.get('nodes', []))
        if em_branco:
            self.status_bar.set_message(
                '✦ Documento em branco — defina a área e o cargo da coluna no '
                'painel à direita, e use a paleta à esquerda para desenhar',
                'success')
        elif veio_da_ia:
            self.status_bar.set_message(
                f'✦ Fluxo criado da IA: {colunas} coluna(s) e {nos} nó(s) — '
                f'revise pelo canvas e publique quando estiver certo', 'success')
        else:
            self.status_bar.set_message(
                f'✦ Fluxo criado com {colunas} coluna(s) — use a paleta à '
                f'esquerda para montar, ou cole o JSON no painel avançado',
                'success')

    def _abrir_caminho(self, caminho):
        """Abre um arquivo já conhecido (recentes da tela inicial)."""
        try:
            with open(caminho, 'r', encoding='utf-8') as f:
                conteudo = f.read()
        except OSError as e:
            messagebox.showerror('Abrir', f'Não foi possível abrir:\n{e}')
            return
        self._esconder_boas_vindas()
        self.json_panel.set_json(conteudo)
        self.current_file = caminho
        self._history.clear()
        self._redo_stack.clear()
        self._render()
        try:
            self._loaded_mtime = os.path.getmtime(caminho)
        except OSError:
            self._loaded_mtime = None
        self._set_modified(False)
        self.status_bar.set_message(
            f'📂 Arquivo carregado: {os.path.basename(caminho)}', 'info')
        self._registrar_recente(caminho)
        self._checar_aprovacao()

    def _registrar_recente(self, caminho):
        recentes = prefs.registrar_recente(caminho)
        if getattr(self, 'welcome', None) is not None:
            self.welcome.set_recentes(recentes)

    # ── Governança: gate, correção guiada, auditoria ───────

    def _append_audit(self, kind):
        """Registra um evento na trilha do documento.

        Não existe evento de "abrir": abrir não muda o documento, e registrar
        isso incharia o arquivo — a trilha mora dentro do que ela audita.
        Falhar aqui nunca derruba a operação que originou o evento.
        """
        if not self.model:
            return None
        return record_event(self.model, kind)

    def _estado_publicacao(self):
        """Carimbo que o PDF deve levar e a referência de aprovação.

        Aprovado só vale se o bloco disser publicado E a impressão digital
        ainda conferir com o conteúdo. Divergência detectada na abertura
        rebaixa o documento até uma nova publicação.
        """
        gov = (self.model or {}).get('governance') or {}
        aprovado = (gov.get('status') == 'published'
                    and not self._aprovacao_violada
                    and fingerprint_matches(self.model) is True)
        if not aprovado:
            return STAMP_DRAFT, ''
        ap = gov.get('approval') or {}
        quem = (ap.get('approvedBy') or {}).get('machineUser', '')
        quando = (ap.get('approvedAt') or '')[:10]
        return STAMP_APPROVED, ' · '.join(x for x in (quem, quando) if x)

    def _checar_aprovacao(self):
        """Na abertura, confere se a aprovação gravada ainda vale.

        É detecção, não prevenção: o arquivo abre normalmente. O que deixa de
        valer é ele circular como aprovado — e isso o usuário precisa saber
        antes de qualquer outra interação.
        """
        self._aprovacao_violada = False
        if not self.model:
            return
        confere = fingerprint_matches(self.model)
        if confere is not False:
            return  # None = nunca teve aprovação; True = confere
        self._aprovacao_violada = True
        self._append_audit('discrepancia_detectada')
        messagebox.showwarning(
            'Aprovação não confere',
            'O conteúdo deste fluxograma mudou depois de aprovado — a '
            'impressão digital registrada não corresponde ao que está no '
            'arquivo.\n\nEle abre normalmente, mas passa a valer como '
            'RASCUNHO: exportações sairão sem o carimbo de aprovado até que '
            'ele seja publicado de novo.')
        self.status_bar.set_message(
            '⚠ Aprovação não confere — documento rebaixado a rascunho nesta '
            'sessão', 'warning')

    def _publish(self):
        """Único caminho que produz artefato aprovado. Pendência é parada dura."""
        if not self.model:
            self.status_bar.set_message('⚠ Renderize um fluxograma primeiro',
                                        'warning')
            return

        issues = validate_model(self.model, self.catalogo)
        travas = bloqueios(issues)
        if travas:
            # Só defeito de ESTRUTURA barra. Antes, um nome fora do catálogo
            # tinha o mesmo peso de um nó sem destino — e quem aprova, que não
            # é o autor, ficava sem poder corrigir nem aprovar.
            self._start_guided_correction(travas)
            return

        ressalvas = avisos(issues)
        if ressalvas and not self._confirmar_ressalvas(ressalvas):
            return

        if not self._checar_arquivo_intacto():
            return

        gov = self.model.setdefault('governance', {})
        gov['status'] = 'published'
        gov['canonical'] = True
        gov['approval'] = build_approval(self.model)
        mark_governance_dirty(self.model)
        self._aprovacao_violada = False
        if ressalvas:
            record_event(self.model, 'publicar_com_ressalva',
                         detalhe=issue_messages(ressalvas))
            self.model['_governance_dirty'] = True
        else:
            self._append_audit('publicar')

        if not self._gravar_publicacao():
            return

        quem = current_author().get('machineUser', '')
        self.status_bar.set_message(
            f'✅ Publicado e aprovado por {quem} — impressão digital gravada',
            'success')
        if messagebox.askyesno('Publicado',
                               'Documento aprovado e gravado.\n\n'
                               'Exportar o PDF aprovado agora?'):
            self._export_pdf()

    def _confirmar_ressalvas(self, ressalvas):
        """Publicar apesar de avisos é decisão de quem aprova — e fica no papel.

        O desvio não impede que o processo esteja certo, mas quem assina precisa
        saber o que está assinando junto. O aceite vai para a trilha.
        """
        lista = '\n'.join(f'  •  {m}' for m in issue_messages(ressalvas)[:8])
        extra = ('\n  …e mais %d' % (len(ressalvas) - 8)) if len(ressalvas) > 8 else ''
        return messagebox.askyesno(
            'Publicar com ressalva?',
            f'O processo não tem defeito de estrutura, mas há '
            f'{len(ressalvas)} observação(ões):\n\n{lista}{extra}\n\n'
            f'Publicar assim mesmo? O aceite fica registrado na trilha de '
            f'auditoria do documento.')

    def _checar_arquivo_intacto(self):
        """O arquivo mudou em disco desde que esta instância o leu?

        Publicar grava conteúdo E carimbo de aprovação no mesmo arquivo: uma
        sobrescrita silenciosa aqui não é "perdi o rascunho", é "um arquivo se
        diz aprovado sem nunca ter sido". Checagem otimista por mtime — não há
        servidor de coordenação nesta rodada.
        """
        if not self.current_file or self._loaded_mtime is None:
            return True
        try:
            atual = os.path.getmtime(self.current_file)
        except OSError:
            return True
        if abs(atual - self._loaded_mtime) < 1e-6:
            return True
        messagebox.showwarning(
            'Publicar',
            'O arquivo mudou em disco desde que foi aberto nesta janela.\n\n'
            'Reabra o arquivo antes de publicar, para não sobrescrever o '
            'trabalho de outra sessão.')
        self.status_bar.set_message(
            '⚠ Publicação abortada — o arquivo mudou em disco', 'warning')
        return False

    def _gravar_publicacao(self):
        """Grava o JSON publicado de forma atômica (temporário + os.replace).

        Uma queda no meio da gravação nunca pode deixar um JSON pela metade se
        fazendo passar por aprovado: no pior caso sobra um `.tmp` órfão e o
        arquivo anterior segue íntegro. Só o caminho de publicação faz isso —
        salvar rascunho continua como estava.
        """
        if not self.current_file:
            self._save_json_as()
            if not self.current_file:
                return False
        texto = json.dumps(serialize_model(self.model), indent=2,
                           ensure_ascii=False)
        temporario = self.current_file + '.tmp'
        try:
            with open(temporario, 'w', encoding='utf-8') as f:
                f.write(texto)
            os.replace(temporario, self.current_file)
        except OSError as e:
            try:
                os.remove(temporario)
            except OSError:
                pass
            messagebox.showerror('Publicar', f'Não foi possível gravar:\n{e}')
            self.status_bar.set_message(f'❌ Falha ao publicar: {e}', 'error')
            return False
        try:
            self._loaded_mtime = os.path.getmtime(self.current_file)
        except OSError:
            self._loaded_mtime = None
        self.json_panel.set_json(texto)
        self._last_json = texto
        self._set_modified(False)
        return True

    def _start_guided_correction(self, issues):
        """Leva o usuário ao primeiro elemento com pendência, um a um.

        Marcar todos os nós ao mesmo tempo e escrever três frases na barra de
        status deixava o usuário caçando retângulo tracejado pela tela.
        """
        self._fila_correcao = [i for i in issues if i.get('node_id')]
        if not self.edit_mode:
            self._toggle_edit()
        self._ir_para_pendencia(0, len(issues))
        if not self._fila_correcao:
            return

    def _ir_para_pendencia(self, indice, total):
        if not self._fila_correcao:
            # Pendência sem elemento associado (ex.: departamento fora do
            # catálogo): não há para onde navegar, só o que informar.
            pend = issue_messages(
                bloqueios(validate_model(self.model, self.catalogo)))
            self.status_bar.set_message(
                f'🔧 Publicação bloqueada — {len(pend)} defeito(s) de '
                f'estrutura: {pend[0] if pend else ""}', 'warning')
            return
        msgs = issue_messages(self._fila_correcao)
        indice = max(0, min(indice, len(self._fila_correcao) - 1))
        alvo = self._fila_correcao[indice]
        if self.editor:
            no = self.editor.select_node(alvo['node_id'])
            if no is not None:
                self._trazer_a_vista(no)
        self.status_bar.set_message(
            f'🔧 Corrija {indice + 1} de {total}: {msgs[indice]}', 'warning')

    def _trazer_a_vista(self, node):
        """Rola o canvas até o nó — usa só a transformação de vista existente."""
        try:
            caixa = self.canvas.bbox('all')
            if not caixa:
                return
            x0, y0, x1, y1 = caixa
            largura = max(1.0, x1 - x0)
            altura = max(1.0, y1 - y0)
            vx, vy = self.viewport.to_view(node['x'], node['y'])
            vw, vh = self.viewport.to_view(node['size']['w'], node['size']['h'])
            self.canvas.xview_moveto(
                max(0.0, min(1.0, (vx + vw / 2 - x0) / largura - 0.25)))
            self.canvas.yview_moveto(
                max(0.0, min(1.0, (vy + vh / 2 - y0) / altura - 0.25)))
        except (tk.TclError, ZeroDivisionError, TypeError):
            pass

    # ── Painel de propriedades e catálogo ──────────────────

    def _on_selection_change(self, alvo, kind='node'):
        """O editor mudou a seleção — os painéis passam a mostrar esse elemento."""
        if kind == 'edge':
            self.properties_panel.show_edge(alvo)
            self.properties_panel.set_editable(
                bool(self.edit_mode and self.editor))
            if self._outline_visivel:
                self.outline_panel.marcar_selecionado(None)
            return
        self.properties_panel.show(alvo, self.model)
        self.properties_panel.show_edge(None)
        self.properties_panel.set_editable(bool(self.edit_mode and self.editor))
        if self._outline_visivel:
            self.outline_panel.marcar_selecionado(alvo['id'] if alvo else None)

    def _prop_set(self, metodo, valor):
        """Encaminha uma edição do painel para o setter correspondente."""
        if not (self.edit_mode and self.editor and self.editor.selected_node):
            return
        getattr(self.editor, metodo)(self.editor.selected_node, valor)

    def _prop_set_department(self, nome):
        if self.edit_mode and self.editor:
            self.editor.set_department(nome)

    def _prop_set_lane_label(self, lane_id, label):
        if self.edit_mode and self.editor:
            self.editor.set_lane_label(lane_id, label)

    def _prop_set_lane_department(self, lane_id, departamento):
        if self.edit_mode and self.editor:
            self.editor.set_lane_department(lane_id, departamento)

    def _prop_add_lane(self):
        """Acrescenta um ator ao fluxo, pela barra lateral."""
        if not (self.edit_mode and self.editor):
            self.status_bar.set_message(
                '⚠ Ligue o modo edição (Ctrl+E) para mexer nas colunas',
                'warning')
            return
        self.editor.add_lane()

    def _prop_edge_label(self, texto):
        """Rótulo da conexão selecionada (o Sim/Não), vindo do painel."""
        if self.edit_mode and self.editor and self.editor.selected_edge:
            self.editor.set_edge_label(self.editor.selected_edge, texto)

    def _prop_ponto_aberto(self, marcado, pergunta):
        """Marca o nó selecionado como ponto em aberto do processo."""
        if self.edit_mode and self.editor and self.editor.selected_node:
            self.editor.set_ponto_em_aberto(self.editor.selected_node,
                                            marcado, pergunta)

    def _prop_move_lane(self, lane_id, delta):
        """Reordena as colunas — a ordem é a leitura do processo."""
        if not (self.edit_mode and self.editor):
            self.status_bar.set_message(
                '⚠ Ligue o modo edição (Ctrl+E) para reordenar as colunas',
                'warning')
            return
        self.editor.move_lane(lane_id, delta)

    def _prop_remove_lane(self, lane_id):
        """Tira um ator do fluxo. Os nós dele iriam para o limbo — vão junto."""
        if not (self.edit_mode and self.editor):
            return
        lane = next((l for l in self.model['lanes'] if l['id'] == lane_id), None)
        if lane is None:
            return
        nos = sum(1 for n in self.model['nodes'] if n.get('laneId') == lane_id)
        aviso = (f"\n\nOs {nos} nó(s) dessa coluna também saem."
                 if nos else '')
        if messagebox.askyesno(
                'Remover coluna',
                f"Remover a coluna '{lane.get('label', lane_id)}'?{aviso}"):
            self.editor.remove_lane(lane_id)

    def _abrir_catalogo(self):
        """Abre a tela onde a empresa mantém departamentos e cargos."""
        CatalogDialog(self.root, on_saved=self._catalogo_atualizado)

    def _catalogo_atualizado(self, novo):
        """Catálogo salvo: painel e validação passam a usar a lista nova."""
        self.catalogo = novo
        self._catalogo_e_semente = not os.path.exists(
            catalogo_mod.caminho_catalogo())
        if self.editor:
            self.editor.catalogo = novo
        self.properties_panel.set_catalogo(novo)
        if self.model:
            self.properties_panel.set_document(self.model)
            self._report_issues(self._paint())
        self.status_bar.set_message(
            f"🏷 Catálogo atualizado — {len(novo.get('departamentos', []))} "
            f"departamentos, {len(novo.get('cargos', []))} cargos", 'success')

    def _toggle_outline_panel(self):
        """Mostra/esconde o índice — a navegação de documento longo."""
        if self._outline_visivel:
            self._paned.forget(self.outline_panel)
            self._outline_visivel = False
            self._outline_btn.configure(bg=BTN_BG, fg=BTN_FG)
        else:
            self._paned.add(self.outline_panel, before=self.properties_panel,
                            width=250, minsize=200)
            self._outline_visivel = True
            self._outline_btn.configure(bg=ACCENT, fg='#ffffff')
            self._atualizar_indice()

    def _abrir_indice_e_buscar(self):
        """Ctrl+F: abre o índice (se preciso) e põe o cursor na busca."""
        if not self._outline_visivel:
            self._toggle_outline_panel()
        self.outline_panel.focar_busca()
        return 'break'

    def _atualizar_indice(self, issues=None):
        """Mantém o índice em dia com o documento e com as pendências."""
        if not self._outline_visivel:
            return
        if issues is None:
            issues = validate_model(self.model, self.catalogo) if self.model else []
        self.outline_panel.set_document(self.model, issues)
        if self.editor and self.editor.selected_node:
            self.outline_panel.marcar_selecionado(self.editor.selected_node['id'])

    def _ir_para_no(self, node_id):
        """Clique no índice: seleciona o nó e traz o canvas até ele."""
        if not self.model:
            return
        node = next((n for n in self.model['nodes'] if n['id'] == node_id), None)
        if node is None:
            return
        if self.edit_mode and self.editor:
            self.editor.select_node(node_id)
        self._trazer_a_vista(node)
        self.outline_panel.marcar_selecionado(node_id)
        self.status_bar.set_message(
            f"☰ {node.get('label') or node_id}", 'info')

    def _ir_para_issue(self, issue):
        """Clique numa pendência: leva ao elemento, quando ela tem um."""
        if issue.get('node_id'):
            self._ir_para_no(issue['node_id'])
        else:
            self.status_bar.set_message(f"⚠ {issue.get('msg', '')}", 'warning')

    def _toggle_json_panel(self):
        """O painel JSON vira ferramenta avançada: entra e sai sob demanda."""
        if self._json_visivel:
            self._paned.forget(self.json_panel)
            self._json_visivel = False
            self._json_btn.configure(bg=BTN_BG, fg=BTN_FG)
        else:
            self._paned.add(self.json_panel, before=self.properties_panel,
                            width=380, minsize=250)
            self._json_visivel = True
            self._json_btn.configure(bg=ACCENT, fg='#ffffff')

    def _edit_action(self, acao):
        """Dispara pelo menu as operações de edição que também têm atalho."""
        if not (self.edit_mode and self.editor):
            self.status_bar.set_message(
                '⚠ Ligue o modo edição (Ctrl+E) para usar esta ação', 'warning')
            return
        fn = {'copy': self.editor._on_copy_key,
              'paste': self.editor._on_paste_key,
              'duplicate': self.editor._on_duplicate_key,
              'delete': self.editor._on_delete_key}[acao]
        if fn() != 'break' and acao != 'paste':
            self.status_bar.set_message(
                '⚠ Selecione um nó no fluxograma primeiro', 'warning')

    # Operações em que a confirmação vale mais que o aviso: o nó acabou de
    # nascer e ainda não pode ter destino — repreender aqui é ruído.
    _MSG_TEM_PRECEDENCIA = ('➕', '⧉', '📋')

    def _on_editor_change(self, model, msg=None, kind='info'):
        """Ponto de entrada ÚNICO das alterações vindas do canvas.

        Toda mutação do editor desemboca aqui: histórico, sincronização do
        painel JSON, redesenho e revalidação acontecem juntos e na mesma ordem,
        não importa se a origem foi um arraste, o menu de contexto ou um
        atalho de teclado. Pendência encontrada tem precedência sobre a
        mensagem de sucesso da operação — é o aviso no momento do erro.
        """
        try:
            js = json.dumps(serialize_model(model), indent=2, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            self.status_bar.set_message(f'⚠ Erro ao atualizar JSON: {e}', 'warning')
            return

        self._push_history()
        self._append_audit('editar')
        self.json_panel.set_json(js)
        self._last_json = js

        # Re-renderizar preservando posições manuais (pinned)
        try:
            self.model = compute_layout(model)
            issues = self._paint()
        except Exception as e:
            traceback.print_exc()
            self.status_bar.set_message(f'❌ Erro ao re-renderizar: {e}', 'error')
            return

        self._restaurar_selecao()
        self._atualizar_indice(issues)
        self._set_modified(True)
        criou = bool(msg) and msg[0] in self._MSG_TEM_PRECEDENCIA
        if issues and not criou:
            self._report_issues(issues)
        elif criou:
            pend = f'  ({len(issues)} pendência(s) no fluxo)' if issues else ''
            self.status_bar.set_message(msg + pend, kind)
        else:
            self.status_bar.set_message(
                msg or '✏ Alteração aplicada — Ctrl+Z desfaz, Ctrl+S salva', kind)

    def _restaurar_selecao(self):
        """Redesenha o realce do nó selecionado depois de um redesenho total.

        `render()` começa com `canvas.delete('all')`: o polígono de seleção ia
        embora junto a cada edição comprometida, e o usuário tinha de clicar no
        nó de novo. O `selected_node` continuava certo — só o desenho sumia.
        `compute_layout` pode ter recriado o dict do nó, então a busca é por id.
        """
        if not (self.editor and self.editor.selected_node):
            return
        alvo = self.editor.selected_node['id']
        atual = next((n for n in self.model['nodes'] if n['id'] == alvo), None)
        if atual is None:
            self.editor.selected_node = None
            self.properties_panel.show(None, self.model)
            return
        self.editor.selected_node = atual
        self.editor._draw_highlight(atual)
        self.properties_panel.show(atual, self.model)
        self.properties_panel.set_editable(bool(self.edit_mode and self.editor))

    # ── Desfazer / Refazer ─────────────────────────────────

    def _push_history(self):
        """Guarda o estado atual antes de uma alteração."""
        if self._last_json:
            self._history.append(self._last_json)
            if len(self._history) > MAX_HISTORY:
                self._history.pop(0)
        self._redo_stack.clear()

    def _undo(self, event=None):
        """Desfaz a última alteração do editor (Ctrl+Z)."""
        # Não interferir no undo nativo do painel de texto JSON
        if self.root.focus_get() is self.json_panel.text:
            return
        if not self._history:
            self.status_bar.set_message('Nada a desfazer', 'info')
            return
        self._redo_stack.append(self.json_panel.get_json())
        js = self._history.pop()
        self._apply_json_state(js)
        self.status_bar.set_message('↶ Alteração desfeita', 'info')

    def _redo(self, event=None):
        """Refaz a alteração desfeita (Ctrl+Y)."""
        if self.root.focus_get() is self.json_panel.text:
            return
        if not self._redo_stack:
            self.status_bar.set_message('Nada a refazer', 'info')
            return
        self._history.append(self.json_panel.get_json())
        js = self._redo_stack.pop()
        self._apply_json_state(js)
        self.status_bar.set_message('↷ Alteração refeita', 'info')

    def _apply_json_state(self, js):
        """Aplica um snapshot de JSON (usado por desfazer/refazer)."""
        self.json_panel.set_json(js)
        self._last_json = js
        try:
            self.model = compute_layout(parse_flowchart(js))
            self._paint()
            if self.edit_mode and self.model:
                self.editor = self._make_editor()
                self.editor.enable()
            self._set_modified(True)
        except Exception as e:
            traceback.print_exc()
            self.status_bar.set_message(f'❌ Erro ao aplicar estado: {e}', 'error')

    # ── Auto-organizar layout ──────────────────────────────

    def _auto_layout(self):
        """Remove posições manuais e reorganiza tudo automaticamente (Ctrl+L)."""
        if not self.model:
            self.status_bar.set_message('⚠ Renderize um fluxograma primeiro', 'warning')
            return
        self._push_history()
        for n in self.model['nodes']:
            n['pinned'] = False
        try:
            self.model = compute_layout(self.model)
            self._paint()
            js = json.dumps(serialize_model(self.model), indent=2, ensure_ascii=False)
            self.json_panel.set_json(js)
            self._last_json = js
            if self.edit_mode:
                self.editor = self._make_editor()
                self.editor.enable()
            self._set_modified(True)
            self.status_bar.set_message('⟲ Layout reorganizado automaticamente', 'success')
        except Exception as e:
            traceback.print_exc()
            self.status_bar.set_message(f'❌ Erro ao reorganizar: {e}', 'error')

    # ── Título da janela / estado do arquivo ───────────────

    def _set_modified(self, flag):
        self._modified = flag
        self._update_title()

    def _update_title(self):
        name = os.path.basename(self.current_file) if self.current_file else 'Sem título'
        mark = ' •' if self._modified else ''
        self.root.title(f'Flow Forge {versao_mod.VERSAO} — {name}{mark}')

    # ── Desenho: um único caminho, do modelo à tela ────────

    def _paint(self):
        """Desenha o modelo e aplica a transformação de vista por cima.

        O renderizador desenha SEMPRE em espaço de modelo (1:1); o zoom é
        aplicado depois, a partir do desenho recém-feito. Antes, cada zoom
        escalava os itens já escalados e arredondava as fontes de novo a cada
        passo — a tela derivava do modelo. Agora a escala é sempre recalculada
        da base, e `self.viewport` descreve exatamente a relação entre as duas.
        """
        if not self.model:
            return []
        render(self.canvas, self.model)
        self._apply_view_transform()
        return self._show_issues()

    def _apply_view_transform(self):
        """Aplica o zoom atual sobre o desenho em escala 1:1."""
        s = self.viewport.scale
        if s != 1.0:
            self.canvas.scale('all', 0, 0, s, s)
            for item_id in self.canvas.find_all():
                if self.canvas.type(item_id) != 'text':
                    continue
                try:
                    parts = self.root.tk.splitlist(
                        self.canvas.itemcget(item_id, 'font'))
                    family = parts[0]
                    base = float(parts[1])
                    style = parts[2] if len(parts) > 2 else ''
                    size = max(5, int(round(base * s)))
                    self.canvas.itemconfigure(
                        item_id, font=(family, size, style) if style
                        else (family, size))
                    w = self.canvas.itemcget(item_id, 'width')
                    if w and float(w) > 0:
                        self.canvas.itemconfigure(item_id, width=float(w) * s)
                except (ValueError, IndexError, tk.TclError):
                    continue  # itens sem fonte válida

        bbox = self.canvas.bbox('all')
        if bbox:
            pad = 20
            self.canvas.configure(scrollregion=(bbox[0] - pad, bbox[1] - pad,
                                                bbox[2] + pad, bbox[3] + pad))
        self._zoom_label.configure(text=f'{self.viewport.percent}%')

    def _show_issues(self):
        """Marca no canvas os nós com pendência, distinguindo o que é o quê.

        Vermelho = defeito de estrutura, barra a publicação.
        Âmbar    = observação: nome fora do catálogo, ou ponto que o processo
                   deliberadamente deixou em aberto. Pintar os dois de vermelho
                   dizia ao usuário que ele errou, quando às vezes ele só
                   registrou uma pergunta que a empresa ainda não respondeu.
        """
        self.canvas.delete('issue')
        if not self.model:
            return []
        issues = validate_model(self.model, self.catalogo)

        por_no = {}
        for i in issues:
            nid = i.get('node_id')
            if not nid:
                continue
            atual = por_no.get(nid)
            # Bloqueio tem precedência na cor; "em aberto" define o símbolo
            sev = severidade(i)
            if atual is None:
                por_no[nid] = {'sev': sev, 'aberto': i['kind'] == 'ponto_em_aberto'}
            else:
                if sev == 'bloqueio':
                    atual['sev'] = 'bloqueio'
                atual['aberto'] = atual['aberto'] or i['kind'] == 'ponto_em_aberto'

        for node in self.model['nodes']:
            marca = por_no.get(node['id'])
            if not marca or node['type'] == 'annotation':
                continue
            cor = WARN_MARK if marca['sev'] == 'bloqueio' else ABERTO_MARK
            simbolo = '?' if marca['aberto'] else '!'
            x, y = self.viewport.to_view(node['x'], node['y'])
            w, h = self.viewport.to_view(node['size']['w'], node['size']['h'])
            pad = self.viewport.to_view_len(3)
            self.canvas.create_rectangle(x - pad, y - pad, x + w + pad, y + h + pad,
                                         outline=cor, width=2, dash=(3, 3),
                                         tags=('issue',))
            self.canvas.create_text(
                x + w + pad + 2, y - pad, text=simbolo,
                font=('Segoe UI', max(8, int(11 * self.viewport.scale)), 'bold'),
                fill=cor, anchor='sw', tags=('issue',))
        return issues

    def _report_issues(self, issues, ok_msg='✅ Renderizado com sucesso'):
        """Resume na barra de status, sem confundir defeito com observação."""
        travas = bloqueios(issues)
        obs = avisos(issues)
        if travas:
            msgs = issue_messages(travas)
            shown = ' • '.join(msgs[:2])
            resto = len(travas) - 2
            if resto > 0:
                shown += f' (+{resto})'
            extra = f' · {len(obs)} observação(ões)' if obs else ''
            self.status_bar.set_message(f'⚠ {shown}{extra}', 'warning')
        elif obs:
            msgs = issue_messages(obs)
            shown = ' • '.join(msgs[:2])
            resto = len(obs) - 2
            if resto > 0:
                shown += f' (+{resto})'
            self.status_bar.set_message(
                f'ℹ {shown} — não impede publicar', 'info')
        else:
            self.status_bar.set_message(ok_msg, 'success')

    # ── Zoom ───────────────────────────────────────────────

    def _zoom(self, factor):
        """Amplia/reduz re-renderizando sob a transformação de vista."""
        if not self.model:
            self.viewport.apply_factor(factor)
            self._zoom_label.configure(text=f'{self.viewport.percent}%')
            return
        antes = self.viewport.scale
        if self.viewport.apply_factor(factor) == antes:
            return  # já no limite
        self._paint()
        if self.edit_mode and self.editor:
            self.editor = self._make_editor()
            self.editor.enable()

    def _zoom_fit(self):
        """Ajusta o zoom para o documento inteiro caber na área visível.

        Sem isto não havia estado algum em que o usuário visse o processo
        completo: um fluxo de porte real passa de 4000px de altura contra ~770
        de área útil, e nem o zoom mínimo alcançava.
        """
        if not self.model:
            self.status_bar.set_message('⚠ Nenhum fluxograma aberto', 'warning')
            return
        comp = self.model.get('_computed', {})
        larg = comp.get('total_width', 0)
        alt = comp.get('total_height', 0)
        self.canvas.update_idletasks()
        disp_w = max(80, self.canvas.winfo_width() - 24)
        disp_h = max(80, self.canvas.winfo_height() - 24)
        if larg <= 0 or alt <= 0:
            return
        alvo = min(disp_w / larg, disp_h / alt)
        aplicado = self.viewport.set_scale(alvo)
        self._paint()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        if self.edit_mode and self.editor:
            self.editor = self._make_editor()
            self.editor.enable()
        if aplicado < alvo - 1e-6:
            self.status_bar.set_message(
                f'🔎 {self.viewport.percent}% — é o menor zoom possível; o '
                f'documento ainda não cabe inteiro', 'warning')
        else:
            self.status_bar.set_message(
                f'🔎 Ajustado à janela: {self.viewport.percent}%', 'info')

    def _zoom_reset(self):
        self.viewport.reset()
        if self.model:
            self._paint()
            if self.edit_mode and self.editor:
                self.editor = self._make_editor()
                self.editor.enable()
        else:
            self._zoom_label.configure(text='100%')

    def _on_scroll_vertical(self, event):
        """Scroll vertical com roda do mouse."""
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')

    def _on_scroll_horizontal(self, event):
        """Scroll horizontal com Shift + roda do mouse."""
        self.canvas.xview_scroll(int(-1 * (event.delta / 120)), 'units')

    def _on_scroll_zoom(self, event):
        """Zoom com Ctrl + roda do mouse."""
        factor = 1.1 if event.delta > 0 else 0.9
        self._zoom(factor)

    def _pan_start(self, event):
        self.canvas.scan_mark(event.x, event.y)

    def _pan_move(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _on_close(self):
        """Fecha o app, avisando sobre alterações não salvas."""
        if self._modified:
            resp = messagebox.askyesnocancel(
                'Sair do Flow Forge',
                'Há alterações não salvas. Deseja salvar antes de sair?')
            if resp is None:
                return  # cancelou
            if resp:
                self._save_json()
                if self._modified:
                    return  # salvamento cancelado ou falhou
        self.root.destroy()

    def run(self):
        self.root.mainloop()
