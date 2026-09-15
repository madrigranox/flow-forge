"""
versao.py — Versão do programa e verificação de atualização.

O número da versão vivia só no `installer.iss`: nenhum código Python o
conhecia, então o programa não tinha como saber se estava desatualizado. Aqui
ele passa a ser **fonte única** — o instalador é conferido contra este arquivo
por teste, para os dois não divergirem em silêncio.

A verificação de atualização é deliberadamente modesta: lê um JSON pequeno numa
URL fixa e compara. Sem servidor, sem telemetria, sem instalação automática —
o programa avisa e abre o link, quem decide é o usuário.

**Nada aqui pode derrubar o app.** Sem internet, atrás de proxy corporativo,
URL fora do ar ou JSON malformado: a verificação falha em silêncio e o programa
segue. Um editor de fluxograma não pode deixar de abrir porque um servidor caiu.
"""
import json
import re
import urllib.error
import urllib.request

VERSAO = '1.2.0'

# URL do manifesto de versão. Vazia = verificação desligada (estado de fábrica).
# Formato esperado do JSON:
#   {"versao": "1.3.0",
#    "url": "https://.../FlowForge-Setup-1.3.0.exe",
#    "notas": "O que mudou nesta versão"}
URL_ATUALIZACAO = ''

TIMEOUT_S = 5
TAMANHO_MAX = 64 * 1024      # manifesto é pequeno; corta resposta absurda


def como_tupla(texto):
    """'1.12.3' → (1, 12, 3). Compara por número, não alfabeticamente.

    Alfabeticamente '1.9.0' > '1.12.0', o que inverteria a ordem justamente
    quando o projeto passa da nona versão menor.
    """
    partes = re.findall(r'\d+', str(texto or ''))
    return tuple(int(p) for p in partes[:4]) or (0,)


def mais_nova(candidata, atual=None):
    """A `candidata` é posterior à versão `atual`?"""
    return como_tupla(candidata) > como_tupla(atual or VERSAO)


def checar(url=None, atual=None, timeout=TIMEOUT_S):
    """Consulta o manifesto. Devolve dict da versão nova, ou None.

    None significa "nada a fazer": ou está atualizado, ou não deu para saber.
    Quem chama não precisa distinguir os dois casos — em ambos não há o que
    mostrar ao usuário.
    """
    # Resolvidos na CHAMADA, não na definição: um valor preso no `def` não
    # acompanha quem ajuste o módulo depois (empacotamento, teste, release).
    alvo = url if url is not None else URL_ATUALIZACAO
    atual = atual or VERSAO
    if not alvo:
        return None
    try:
        req = urllib.request.Request(
            alvo, headers={'User-Agent': f'FlowForge/{atual}'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            bruto = resp.read(TAMANHO_MAX).decode('utf-8', errors='replace')
        dados = json.loads(bruto)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    if not isinstance(dados, dict):
        return None

    nova = str(dados.get('versao', '')).strip()
    if not nova or not mais_nova(nova, atual):
        return None
    return {
        'versao': nova,
        'url': str(dados.get('url', '') or '').strip(),
        'notas': str(dados.get('notas', '') or '').strip(),
    }


def checar_em_segundo_plano(callback, url=None, atual=None):
    """Consulta sem travar a interface; chama `callback(info)` ao terminar.

    O callback roda na thread de rede — quem usa Tk precisa voltar para a
    thread da interface (`widget.after`) antes de tocar em qualquer widget.
    """
    import threading

    def tarefa():
        try:
            callback(checar(url=url, atual=atual))
        except Exception:
            pass          # verificação de versão nunca derruba o programa

    t = threading.Thread(target=tarefa, daemon=True, name='checar-versao')
    t.start()
    return t
