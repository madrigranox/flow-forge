"""
catalogo.py — Catálogo corporativo: DEPARTAMENTOS e, dentro de cada um, CARGOS.

Motivo: o departamento do documento e o nome de cada coluna (lane) eram texto
livre. Dois fluxogramas do mesmo processo saíam com "Manutenção", "Manutencao"
e "Setor de Manutenção" — nomes diferentes para a mesma coisa, o que inutiliza
qualquer busca, indicador ou consolidação por área.

O catálogo é **hierárquico** porque um fluxo é interdepartamental: ele envolve
várias áreas e, dentro de cada área, vários atores. Escolher "Manutenção" e
depois só os cargos que existem em Manutenção é o que impede a combinação
impossível (um "Comandante" dentro de "Tecnologia da Informação").

Onde o arquivo mora:

  %APPDATA%\\FlowForge\\catalogo.json   ← a lista que a empresa mantém

Essa pasta é gravável e sobrevive à reinstalação do programa. O `.exe` gerado
pelo PyInstaller descompacta a si mesmo numa pasta temporária somente-leitura,
então o catálogo NÃO pode morar junto do executável. O arquivo embutido em
`data/catalogo_padrao.json` é só a semente.

O catálogo é dado de configuração, não parte do documento: ele não entra no
`.json` do fluxograma nem na impressão digital de aprovação.
"""
import json
import os
import sys

NOME_ARQUIVO = 'catalogo.json'
PASTA_APP = 'FlowForge'
SEMENTE = os.path.join('data', 'catalogo_padrao.json')
SCHEMA_VERSION = 2

# Destino dos cargos de um catálogo antigo (v1, listas soltas), que não tinha
# como saber a que departamento cada um pertencia.
SEM_DEPARTAMENTO = '(Sem departamento)'


# ── Localização dos arquivos ──────────────────────────────

def _raiz_empacotada():
    """Raiz de leitura: a pasta temporária do PyInstaller ou a do projeto."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def diretorio_usuario():
    """Pasta gravável onde a empresa mantém o catálogo."""
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, PASTA_APP)


def caminho_catalogo():
    """Caminho completo do catálogo mantido pelo usuário."""
    return os.path.join(diretorio_usuario(), NOME_ARQUIVO)


def caminho_semente():
    return os.path.join(_raiz_empacotada(), SEMENTE)


# ── Normalização e migração ───────────────────────────────

def _limpar_lista(valores):
    """Texto aparado, sem repetição (ignorando caixa), em ordem alfabética."""
    limpos, vistos = [], set()
    for v in (valores or []):
        texto = str(v).strip()
        if texto and texto.casefold() not in vistos:
            vistos.add(texto.casefold())
            limpos.append(texto)
    return sorted(limpos, key=lambda s: s.casefold())


def _normalizar(dados):
    """Garante a forma v2, migrando um catálogo v1 (listas soltas) se preciso."""
    if not isinstance(dados, dict):
        dados = {}

    brutos = dados.get('departamentos') or []
    departamentos = []

    # v1: "departamentos" era lista de strings e "cargos" vinha solto ao lado.
    if brutos and all(not isinstance(d, dict) for d in brutos):
        for nome in _limpar_lista(brutos):
            departamentos.append({'nome': nome, 'cargos': []})
        soltos = _limpar_lista(dados.get('cargos'))
        if soltos:
            # Não há como adivinhar a que área cada cargo pertencia: eles vão
            # para um balde visível, para o usuário distribuir — perder a lista
            # que ele já tinha digitado seria pior.
            departamentos.append({'nome': SEM_DEPARTAMENTO, 'cargos': soltos})
    else:
        for d in brutos:
            if not isinstance(d, dict):
                continue
            nome = str(d.get('nome', '')).strip()
            if nome:
                departamentos.append({'nome': nome,
                                      'cargos': _limpar_lista(d.get('cargos'))})

    # Departamentos repetidos (ignorando caixa) viram um só, com a união
    juntos = {}
    for d in departamentos:
        chave = d['nome'].casefold()
        if chave in juntos:
            juntos[chave]['cargos'] = _limpar_lista(
                juntos[chave]['cargos'] + d['cargos'])
        else:
            juntos[chave] = d
    ordenados = sorted(juntos.values(), key=lambda d: d['nome'].casefold())

    saida = {'schemaVersion': SCHEMA_VERSION, 'departamentos': ordenados}
    if '_comentario' in dados:
        saida['_comentario'] = dados['_comentario']
    return saida


# ── Leitura e escrita ─────────────────────────────────────

def carregar():
    """Catálogo mantido pelo usuário; na falta dele, a semente embutida.

    Nunca levanta exceção: catálogo é conveniência de padronização, e falhar
    em lê-lo não pode impedir ninguém de abrir um fluxograma.
    """
    for caminho in (caminho_catalogo(), caminho_semente()):
        try:
            with open(caminho, 'r', encoding='utf-8') as f:
                return _normalizar(json.load(f))
        except (OSError, ValueError):
            continue
    return _normalizar({})


def salvar(catalogo):
    """Grava o catálogo do usuário de forma atômica. Devolve (ok, mensagem)."""
    destino = caminho_catalogo()
    try:
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        temporario = destino + '.tmp'
        with open(temporario, 'w', encoding='utf-8') as f:
            json.dump(_normalizar(catalogo), f, ensure_ascii=False, indent=2)
        os.replace(temporario, destino)
        return True, destino
    except OSError as e:
        return False, str(e)


def restaurar_padrao():
    """Volta ao catálogo semente embutido no programa (não grava sozinho)."""
    try:
        with open(caminho_semente(), 'r', encoding='utf-8') as f:
            return _normalizar(json.load(f))
    except (OSError, ValueError):
        return _normalizar({})


def importar_de_arquivo(caminho):
    """Lê uma lista de fora do app. Aceita o .json do catálogo ou .txt/.csv.

    O .txt/.csv é um nome por linha — é o formato em que uma lista de RH
    costuma chegar, e exigir JSON para alimentar isso seria atrito à toa.
    Devolve (catalogo_completo | lista_de_nomes | None, mensagem).
    """
    try:
        with open(caminho, 'r', encoding='utf-8-sig') as f:
            bruto = f.read()
    except OSError as e:
        return None, f'Não foi possível ler o arquivo: {e}'

    if caminho.lower().endswith('.json'):
        try:
            return _normalizar(json.loads(bruto)), 'Catálogo importado'
        except ValueError as e:
            return None, f'JSON inválido: {e}'

    linhas = [l.strip().strip('";,') for l in bruto.splitlines()]
    return [l for l in linhas if l], 'Lista importada'


# ── Consulta ──────────────────────────────────────────────

def nomes_departamentos(catalogo=None):
    catalogo = catalogo if catalogo is not None else carregar()
    return [d['nome'] for d in catalogo.get('departamentos', [])]


def cargos_de(departamento, catalogo=None):
    """Cargos que existem dentro de um departamento."""
    catalogo = catalogo if catalogo is not None else carregar()
    alvo = (departamento or '').strip().casefold()
    for d in catalogo.get('departamentos', []):
        if d['nome'].casefold() == alvo:
            return list(d.get('cargos', []))
    return []


def todos_cargos(catalogo=None, departamentos=None):
    """Todos os cargos, ou só os das áreas informadas, sem repetição."""
    catalogo = catalogo if catalogo is not None else carregar()
    if departamentos is None:
        fonte = catalogo.get('departamentos', [])
    else:
        alvos = {d.strip().casefold() for d in departamentos}
        fonte = [d for d in catalogo.get('departamentos', [])
                 if d['nome'].casefold() in alvos]
    juntos = []
    for d in fonte:
        juntos.extend(d.get('cargos', []))
    return _limpar_lista(juntos)


def departamento_do_cargo(cargo, catalogo=None):
    """A que área um cargo pertence (o primeiro, se estiver em mais de uma)."""
    catalogo = catalogo if catalogo is not None else carregar()
    alvo = (cargo or '').strip().casefold()
    for d in catalogo.get('departamentos', []):
        for c in d.get('cargos', []):
            if c.casefold() == alvo:
                return d['nome']
    return ''


# ── Conformidade de um documento com o catálogo ───────────

def fora_do_catalogo(valor, chave, catalogo=None, departamento=None):
    """O valor está fora da lista? Catálogo vazio não reprova ninguém.

    `chave` é 'departamentos' ou 'cargos'. Para cargos, informar
    `departamento` restringe a checagem à área — é o que pega o ator existente,
    mas alocado na coluna errada.
    """
    catalogo = catalogo if catalogo is not None else carregar()
    if chave == 'departamentos':
        lista = nomes_departamentos(catalogo)
    elif departamento:
        lista = cargos_de(departamento, catalogo)
        if not lista:      # área sem cargos cadastrados não reprova ninguém
            return False
    else:
        lista = todos_cargos(catalogo)
    if not lista or not (valor or '').strip():
        return False
    alvo = valor.strip().casefold()
    return all(alvo != item.casefold() for item in lista)


def sugerir(valor, chave, catalogo=None, limite=3, departamento=None):
    """Entradas parecidas, para o aviso dizer o que usar no lugar."""
    import difflib
    catalogo = catalogo if catalogo is not None else carregar()
    if chave == 'departamentos':
        lista = nomes_departamentos(catalogo)
    elif departamento:
        lista = cargos_de(departamento, catalogo) or todos_cargos(catalogo)
    else:
        lista = todos_cargos(catalogo)
    return difflib.get_close_matches(valor or '', lista, n=limite, cutoff=0.5)
