#!/usr/bin/env python3
"""
Flow Forge — Software de Fluxogramas em Swimlanes
Ponto de entrada principal. Execute: python main.py
"""
import sys
import os


def get_base_path():
    """Retorna o diretório base, funciona tanto em dev quanto empacotado."""
    if getattr(sys, 'frozen', False):
        # Executando como .exe empacotado (PyInstaller)
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


# Garantir que o diretório raiz está no path
BASE_PATH = get_base_path()
sys.path.insert(0, BASE_PATH)

from ui.app_window import AppWindow


def main():
    app = AppWindow()
    app.run()


if __name__ == '__main__':
    main()
