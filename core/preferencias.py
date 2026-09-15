"""
preferencias.py — Estado da instalação que não pertence a nenhum documento.

Hoje guarda só a lista de arquivos recentes, usada pela tela inicial: um
fluxograma em desenvolvimento é reaberto muitas vezes até ser publicado, e
procurá-lo no explorador de arquivos a cada vez é atrito puro.

Mora na mesma pasta gravável do catálogo (`%APPDATA%\\FlowForge`), pelo mesmo
motivo: o executável do PyInstaller roda a partir de uma pasta temporária
somente-leitura.
"""
import json
import os

from core.catalogo import diretorio_usuario

NOME_ARQUIVO = 'preferencias.json'
MAX_RECENTES = 8


def _caminho():
    return os.path.join(diretorio_usuario(), NOME_ARQUIVO)


def carregar():
    """Nunca levanta exceção: preferência ausente é só ausência de atalho."""
    try:
        with open(_caminho(), 'r', encoding='utf-8') as f:
            dados = json.load(f)
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def salvar(dados):
    try:
        os.makedirs(os.path.dirname(_caminho()), exist_ok=True)
        temporario = _caminho() + '.tmp'
        with open(temporario, 'w', encoding='utf-8') as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        os.replace(temporario, _caminho())
        return True
    except OSError:
        return False


def recentes():
    """Caminhos recentes que ainda existem, do mais novo para o mais antigo."""
    return [c for c in carregar().get('recentes', []) if os.path.exists(c)]


def registrar_recente(caminho):
    """Põe o arquivo no topo da lista, sem repetir."""
    if not caminho:
        return recentes()
    dados = carregar()
    lista = [c for c in dados.get('recentes', [])
             if os.path.normcase(c) != os.path.normcase(caminho)]
    lista.insert(0, caminho)
    dados['recentes'] = lista[:MAX_RECENTES]
    salvar(dados)
    return [c for c in dados['recentes'] if os.path.exists(c)]
