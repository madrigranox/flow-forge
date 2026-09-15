"""
prompt.py — Montagem do prompt de IA com as rédeas do fluxo escolhido.

O prompt genérico deixava a IA inventar os atores: ela lia a descrição do
processo e criava lanes com os nomes que quisesse ("Equipe", "Setor
Responsável", "Gestor"). Nada disso existe no catálogo da empresa, então cada
fluxograma saía com um vocabulário próprio e o resultado precisava ser
reescrito à mão.

Aqui o prompt base ganha um bloco de restrição no topo, com as lanes já
resolvidas — id, cargo e departamento. A IA deixa de escolher os atores e passa
a só distribuir as atividades entre os que foram escolhidos.
"""
import os
import sys

ARQUIVO_BASE = os.path.join('data', 'prompt_ia.txt')


def _raiz():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def carregar_base():
    """Texto do prompt genérico que acompanha o programa."""
    try:
        with open(os.path.join(_raiz(), ARQUIVO_BASE), 'r', encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


def lanes_do_fluxo(selecao):
    """Converte a seleção do assistente em lanes prontas.

    `selecao` é uma lista de pares (departamento, cargo), na ordem em que as
    colunas devem aparecer da esquerda para a direita.
    """
    lanes = []
    for i, (departamento, cargo) in enumerate(selecao, start=1):
        lane = {'id': f'L{i}', 'label': cargo}
        if departamento:
            lane['department'] = departamento
        lanes.append(lane)
    return lanes


def bloco_de_restricao(lanes, titulo='', doc_code=''):
    """O trecho que entra no topo do prompt, prendendo a IA às escolhas."""
    if not lanes:
        return ''

    por_area = {}
    for lane in lanes:
        por_area.setdefault(lane.get('department', '(sem área)'), []).append(lane)

    linhas = [
        '# 🔒 RESTRIÇÕES DESTE FLUXO — LEIA ANTES DE TUDO',
        '',
        'As colunas (lanes) deste fluxograma **já estão definidas**. Use '
        'exatamente estas, com estes `id` e estes `label`, na mesma ordem:',
        '',
        '```json',
        '"lanes": [',
    ]
    for i, lane in enumerate(lanes):
        virgula = ',' if i < len(lanes) - 1 else ''
        dep = lane.get('department', '')
        # Sem comentário `//` aqui: o próprio prompt proíbe comentários dentro
        # do JSON, e um exemplo que os usa convida a IA a repeti-los.
        linhas.append(f'  {{ "id": "{lane["id"]}", "label": "{lane["label"]}"'
                      + (f', "department": "{dep}"' if dep else '')
                      + f' }}{virgula}')
    linhas += [']', '```', '']

    linhas.append('Departamentos envolvidos e seus atores:')
    for area in sorted(por_area):
        nomes = ', '.join(f'"{l["label"]}"' for l in por_area[area])
        linhas.append(f'- **{area}** — {nomes}')
    linhas += [
        '',
        'Regras que não podem ser quebradas:',
        '',
        '1. **Não crie, não renomeie e não remova lanes.** Se uma atividade '
        'parecer pertencer a alguém que não está na lista, atribua-a ao ator '
        'mais próximo que ESTÁ na lista e registre uma anotação '
        '`"Gap: atividade X parece ser de <quem>, fora dos atores deste fluxo"`.',
        '2. Todo `laneId` de nó precisa ser um dos `id` acima. Qualquer outro '
        'valor faz o arquivo ser recusado pelo programa.',
        '3. Os `label` das lanes são nomes oficiais de cargo do catálogo da '
        'empresa — copie-os caractere por caractere, inclusive acentuação e '
        'parênteses.',
        '4. Não repita o nome da ÁREA dentro do texto dos nós — a coluna já a '
        'mostra. Isso vale para o nome do departamento, não para nomes de '
        'cargo: "Comunicar o Supervisor de Produção" é uma atividade legítima '
        'e deve continuar existindo como nó, mesmo havendo uma coluna com esse '
        'cargo.',
    ]
    linhas.append(
        '5. **Não escreva `department` no topo do JSON.** Esse campo é uma '
        'legenda do documento inteiro, e num fluxo com várias áreas não há uma '
        'resposta certa — o programa a monta sozinho a partir das áreas das '
        'lanes. Escolher uma no chute produz um rótulo que contradiz o desenho.')
    if titulo:
        linhas.append(f'6. Use exatamente este título: `"title": "{titulo}"`.')
    if doc_code:
        linhas.append(f'7. Use exatamente este código: `"docCode": "{doc_code}"`.')

    linhas += ['', '---', '']
    return '\n'.join(linhas)


def montar(selecao, titulo='', doc_code='', base=None):
    """Prompt completo: restrições do fluxo + o prompt genérico do programa."""
    base = carregar_base() if base is None else base
    lanes = lanes_do_fluxo(selecao)
    restricao = bloco_de_restricao(lanes, titulo, doc_code)
    return (restricao + base) if restricao else base


def modelo_inicial(selecao, titulo='Novo fluxo', doc_code=''):
    """Documento vazio já com as colunas escolhidas — o ponto de partida.

    Nasce com um único nó de início na primeira coluna: um arquivo sem nó
    nenhum não tem o que renderizar, e a tela em branco não diria ao usuário
    que as colunas dele já estão lá.
    """
    lanes = lanes_do_fluxo(selecao)
    doc = {'title': titulo or 'Novo fluxo'}
    if doc_code:
        doc['docCode'] = doc_code
    # Sem `department` no topo: as áreas envolvidas são desenhadas pelas faixas
    # sobre as colunas. Preencher esse campo com "A · B · C" fazia o mesmo campo
    # significar coisas diferentes conforme a origem do arquivo — legenda
    # derivada aqui, nome de área única nos documentos antigos.
    doc['lanes'] = lanes
    doc['nodes'] = []
    doc['edges'] = []
    if lanes:
        doc['nodes'].append({'id': 'N_START', 'laneId': lanes[0]['id'],
                             'type': 'start', 'label': 'Início do processo'})
    return doc
