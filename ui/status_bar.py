"""
status_bar.py — Barra de status na parte inferior da janela.
Design: Light mode sutil com feedback colorido.
"""
import tkinter as tk


class StatusBar(tk.Frame):
    """Barra de status com ícone + mensagem."""

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self.configure(bg='#e6ebf5', height=32)
        self.pack_propagate(False)

        # Separador sutil no topo
        sep = tk.Frame(self, bg='#ccd6eb', height=1)
        sep.pack(fill='x', side='top')

        self._label = tk.Label(
            self, text='Pronto', font=('Segoe UI', 9),
            fg='#4d4d4d', bg='#e6ebf5', anchor='w', padx=16
        )
        self._label.pack(side='left', fill='x', expand=True)

        self._right = tk.Label(
            self, text='', font=('Segoe UI', 9),
            fg='#4d4d4d', bg='#e6ebf5', anchor='e', padx=16
        )
        self._right.pack(side='right')

    def set_message(self, msg, kind='info'):
        colors = {
            'info': '#4d4d4d',
            'success': '#107c10',
            'error': '#ff0033',
            'warning': '#b45309',
        }
        self._label.configure(text=msg, fg=colors.get(kind, '#4d4d4d'))

    def set_stats(self, text):
        self._right.configure(text=text)
