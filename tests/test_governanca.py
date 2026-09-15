"""
test_governanca.py — Portões de release da rodada de governança.

Cobre o roteiro da frente de Verificação, com destaque para os itens que a
consolidação marcou como PORTÃO DE RELEASE, não relatório pós-fato:

    3  — gate bloqueia publicação com pendência
    5  — correção guiada leva ao elemento
    14 — as três portas de entrada escrevem no MESMO histórico
    15 — auto-renderização não estoura o histórico de undo
    16 — painel de propriedades passa pelo ponto único de mutação

Mais os itens de formato (1, 2, 9, 17), o carimbo do PDF (8) e a
compatibilidade de arquivo antigo (12).

Rodar:  python tests/test_governanca.py
"""
import copy
import io
import tkinter as tk
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.parser import (parse_flowchart, serialize_model, validate_model,   # noqa: E402
                         record_event, append_event, build_approval,
                         fingerprint_matches, structural_fingerprint,
                         issue_messages)
from core.layout import compute_layout                                        # noqa: E402
from core import catalogo as cat                                              # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AMOSTRA = os.path.join(RAIZ, 'data', 'sample.json')


def _bruto():
    return json.load(io.open(AMOSTRA, encoding='utf-8'))


def _modelo(dados=None):
    return compute_layout(parse_flowchart(json.dumps(dados or _bruto())))


# ── Formato do arquivo (frente de Dados) ──────────────────

def test_01_round_trip_sem_edicao_nao_injeta_governanca():
    """Abrir e salvar sem editar produz os mesmos bytes (arquivo antigo)."""
    orig = _bruto()
    m = parse_flowchart(json.dumps(orig))
    assert serialize_model(m) == orig, 'round-trip alterou o arquivo'
    assert 'governance' not in serialize_model(m), \
        'bloco novo foi injetado só por abrir o arquivo'
    print('  arquivo antigo atravessa intacto: OK')


def test_02_campo_desconhecido_da_governanca_sobrevive():
    """Campo que esta rodada não conhece não pode ser descartado."""
    dados = _bruto()
    dados['governance'] = {'status': 'draft', 'observacao_legal': 'reter 5 anos',
                           'auditTrail': []}
    m = parse_flowchart(json.dumps(dados))
    m['nodes'][0]['label'] = 'Editado'          # mutação real no meio
    saida = serialize_model(m)
    assert saida['governance'].get('observacao_legal') == 'reter 5 anos'
    print('  campo desconhecido preservado: OK')


def test_09_trilha_e_so_acrescimo():
    """Nenhum caminho do parser encurta, reordena ou reescreve a trilha."""
    m = _modelo()
    for kind in ('editar', 'salvar', 'publicar'):
        record_event(m, kind)
    trilha = m['governance']['auditTrail']
    seqs = [e['seq'] for e in trilha]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs)), \
        f'seq não é estritamente crescente: {seqs}'

    # Round-trip preserva a lista inteira, na ordem
    reaberto = parse_flowchart(json.dumps(serialize_model(m)))
    assert reaberto['governance']['auditTrail'] == trilha

    # A função de acréscimo nunca produz lista mais curta
    antes = list(trilha)
    depois = append_event(antes, 'salvar')
    assert len(depois) == len(antes) + 1 and depois[:len(antes)] == antes
    print(f'  {len(trilha)} eventos, só-acréscimo e estáveis no round-trip: OK')


def test_17_troca_de_tipo_de_no_existente_persiste():
    """Achado 17: `type` de nó já existente nunca era regravado."""
    m = parse_flowchart(json.dumps(_bruto()))
    alvo = next(n for n in m['nodes'] if n['type'] == 'task')
    alvo['type'] = 'decision'
    gravado = next(n for n in serialize_model(m)['nodes'] if n['id'] == alvo['id'])
    assert gravado.get('type') == 'decision', \
        'a troca de tipo aparece na tela mas some ao reabrir'
    print('  troca de tipo sobrevive ao round-trip: OK')


def test_fingerprint_separa_conteudo_de_apresentacao():
    """Posição e estilo não entram no hash; conteúdo entra."""
    m = _modelo()
    base = structural_fingerprint(m)

    m['nodes'][0]['x'] += 137
    m['nodes'][0]['pinned'] = True
    m['nodes'][0]['size'] = {'w': 999, 'h': 999}
    m['edges'][0]['style'] = {'color': '#ff0000'}
    m['edges'][0]['routing'] = 'curvo'
    m['meta']['grid'] = 25
    assert structural_fingerprint(m) == base, 'apresentação vazou para o hash'

    for mutacao in (lambda x: x['nodes'][0].update(label='Outro'),
                    lambda x: x['nodes'][1].update(type='decision'),
                    lambda x: x['nodes'][2].update(laneId=x['lanes'][-1]['id']),
                    lambda x: x['edges'].pop(),
                    lambda x: x['lanes'].pop()):
        alterado = _modelo()
        mutacao(alterado)
        assert structural_fingerprint(alterado) != base, \
            f'mudança estrutural não alterou o hash: {mutacao}'
    print('  hash ignora apresentação e reage a conteúdo: OK')


def test_12_arquivo_antigo_nao_dispara_falso_alarme():
    """"Nunca teve governança" não pode virar "teve e foi violada"."""
    assert fingerprint_matches(_modelo()) is None
    print('  arquivo sem aprovação: sem alarme (None): OK')


def test_04_aprovacao_grava_hash_do_conteudo_atual():
    """Publicar grava a impressão digital recalculada, não uma qualquer."""
    m = _modelo()
    m['governance']['approval'] = build_approval(m)
    assert fingerprint_matches(m) is True
    m['nodes'][0]['label'] = 'Mudou depois de aprovado'
    assert fingerprint_matches(m) is False

    outro = _bruto()
    outro['title'] = 'Processo completamente diferente'
    m2 = _modelo(outro)
    m2['governance']['approval'] = build_approval(m2)
    v1 = m['governance']['approval']['fingerprint']['value']
    v2 = m2['governance']['approval']['fingerprint']['value']
    assert v1 != v2, 'conteúdos diferentes produziram o mesmo hash'
    print('  aprovação amarrada ao conteúdo, e detecta divergência: OK')


# ── Carimbo do PDF (item 8) ───────────────────────────────

def test_08_pdf_so_muda_no_bloco_de_titulo():
    """Rascunho × aprovado: só a região do título pode divergir."""
    from export import pdf_export

    capturado = {}
    original = pdf_export.PDFWriter.save

    def espiar(self, filepath):
        capturado[filepath] = list(self.stream_ops)

    pdf_export.PDFWriter.save = espiar
    try:
        m = _modelo()
        pdf_export.export_pdf(m, 'a.pdf', stamp=pdf_export.STAMP_DRAFT)
        pdf_export.export_pdf(m, 'b.pdf', stamp=pdf_export.STAMP_APPROVED,
                              stamp_ref='fulano · 2026-09-12')
    finally:
        pdf_export.PDFWriter.save = original

    a, b = capturado['a.pdf'], capturado['b.pdf']
    # O carimbo entra logo após o título; tudo depois do bloco precisa bater
    prefixo = os.path.commonprefix([a, b])
    sufixo_a = a[len(prefixo):]
    sufixo_b = b[len(prefixo):]
    comum = 0
    while (comum < min(len(sufixo_a), len(sufixo_b))
           and sufixo_a[-1 - comum] == sufixo_b[-1 - comum]):
        comum += 1
    divergente_a = len(sufixo_a) - comum
    divergente_b = len(sufixo_b) - comum
    assert divergente_a <= 6 and divergente_b <= 10, (
        f'divergência grande demais para ser só o carimbo: '
        f'{divergente_a} vs {divergente_b} operações')
    print(f'  {len(prefixo)} operações idênticas antes e {comum} depois; '
          f'só o bloco de título diverge: OK')


# ── Portões que precisam da janela (Tk oculto) ────────────

def _app(com_documento=True):
    """Instancia a janela sem exibi-la (suficiente para o fluxo de mutação).

    O programa abre na tela inicial, sem documento — estes testes exercitam o
    fluxo de edição, então carregam a amostra para sair dela.
    """
    import tkinter.messagebox as mb
    mb.askyesno = lambda *a, **k: False
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    from ui.app_window import AppWindow
    app = AppWindow()
    app.root.withdraw()
    app.root.update()
    if com_documento:
        app._load_sample()
        app.root.update()
    return app


def test_00_abre_na_tela_inicial_sem_documento():
    """O programa não abre mais com um exemplo já carregado."""
    app = _app(com_documento=False)
    try:
        assert app.model is None, 'abriu já com um documento carregado'
        # `withdraw()` desmapeia tudo, então a checagem olha o gerenciador de
        # layout, não a visibilidade na tela.
        empacotados = app.root.pack_slaves()
        assert app.welcome is not None and app.welcome in empacotados, \
            'tela inicial não apareceu'
        assert app._paned not in empacotados, \
            'a área de trabalho apareceu junto com a tela inicial'
        print('  abre vazio, na tela inicial: OK')
    finally:
        app.root.destroy()


def test_assistente_monta_fluxo_e_prompt_com_redeas():
    """Departamentos → cargos → prompt travado nas colunas escolhidas."""
    from core import prompt as prompt_mod
    from ui.new_flow_wizard import NewFlowWizard

    app = _app(com_documento=False)
    try:
        w = NewFlowWizard(app.root, catalogo=app.catalogo,
                          on_finish=app._criar_fluxo)
        app.root.update()

        areas = ['Operações', 'Manutenção']
        for a in areas:
            assert a in w._vars_dep, f'área {a} não oferecida'
            w._vars_dep[a].set(True)
        w._avancar()
        app.root.update()

        # Passo 2 só pode oferecer cargos DAS ÁREAS ESCOLHIDAS
        oferecidos = {d for d, _ in w._vars_cargo}
        assert oferecidos == set(areas), \
            f'ofereceu cargos de áreas não escolhidas: {oferecidos - set(areas)}'

        escolha = [('Operações', 'Control Operator (CCR)'),
                   ('Manutenção', 'Técnico de Instrumentação')]
        for par in escolha:
            assert par in w._vars_cargo, f'cargo {par} não oferecido na sua área'
            w._vars_cargo[par].set(True)
        w._avancar()
        app.root.update()
        w.ent_titulo.insert(0, 'Processo de teste')
        w._atualizar_prompt()
        app.root.update()

        texto = w.txt_prompt.get('1.0', 'end-1c')
        for cargo in ('Control Operator (CCR)', 'Técnico de Instrumentação'):
            assert f'"label": "{cargo}"' in texto, \
                f'o prompt não travou a lane {cargo}'
        assert 'Não crie, não renomeie e não remova lanes' in texto
        assert '//' not in texto.split('```json')[1].split('```')[0], \
            'exemplo de JSON no prompt traz comentário `//`, que quebra o parse'
        assert '"title": "Processo de teste"' in texto

        w._avancar()          # passo 4: resultado da IA
        app.root.update()
        w._avancar()          # sem colar nada: cria só com as colunas
        app.root.update()
        lanes = app.model['lanes']
        assert len(lanes) == 2, f'esperava 2 colunas, veio {len(lanes)}'
        assert {l['department'] for l in lanes} == set(areas)
        # As áreas envolvidas são DERIVADAS das colunas, não gravadas no campo
        # `department` do documento: ele voltou a significar uma coisa só —
        # a área única de um documento de uma área só.
        assert set(app.model['_computed']['areas_envolvidas']) == set(areas), \
            'as áreas envolvidas não foram derivadas das colunas'
        assert ' · ' not in (app.model.get('department') or ''), \
            'o banner derivado voltou a poluir o campo department'
        print(f"  {len(lanes)} colunas criadas, prompt travado nelas: OK")
    finally:
        app.root.destroy()


def _wizard(app, areas=('Operações', 'Manutenção'),
            escolha=(('Operações', 'Control Operator (CCR)'),
                     ('Manutenção', 'Técnico de Instrumentação'))):
    """Leva o assistente até o passo 4 (colar o resultado da IA)."""
    from ui.new_flow_wizard import NewFlowWizard
    w = NewFlowWizard(app.root, catalogo=app.catalogo, on_finish=app._criar_fluxo)
    app.root.update()
    for a in areas:
        w._vars_dep[a].set(True)
    w._avancar()
    app.root.update()
    for par in escolha:
        w._vars_cargo[par].set(True)
        w._marcar_cargo(par)
    w._avancar()
    app.root.update()
    w.ent_titulo.insert(0, 'Processo de teste')
    w._atualizar_prompt()
    w._avancar()
    app.root.update()
    return w


def test_assistente_aceita_o_json_da_ia_como_primeira_versao():
    """O ciclo fecha: o resultado da IA vira o arquivo, sem redesenhar nada.

    É a razão de o programa existir em vez de um Visio — o assistente parava no
    "copiar prompt" e o usuário ficava sem onde colar a resposta.
    """
    app = _app(com_documento=False)
    try:
        w = _wizard(app)
        ia = {
            'title': 'Vindo da IA',
            'lanes': [{'id': 'L1', 'label': 'Control Operator (CCR)',
                       'department': 'Operações'},
                      {'id': 'L2', 'label': 'Técnico de Instrumentação',
                       'department': 'Manutenção'}],
            'nodes': [{'id': 'N_START', 'laneId': 'L1', 'type': 'start',
                       'label': 'Alarme detectado'},
                      {'id': 'N1', 'laneId': 'L1', 'type': 'task',
                       'label': 'Registrar ocorrência'},
                      {'id': 'N2', 'laneId': 'L2', 'type': 'task',
                       'label': 'Inspecionar instrumento'},
                      {'id': 'N3', 'laneId': 'L1', 'type': 'end',
                       'label': 'Encerrado'}],
            'edges': [{'from': 'N_START', 'to': 'N1'}, {'from': 'N1', 'to': 'N2'},
                      {'from': 'N2', 'to': 'N3'}],
        }
        w.txt_json.insert('1.0', json.dumps(ia, ensure_ascii=False))
        w._validar_json()
        app.root.update()
        assert '✓' in w.lbl_validacao.cget('text'), \
            f'validação recusou um JSON válido: {w.lbl_validacao.cget("text")}'

        w._avancar()
        app.root.update()
        assert len(app.model['nodes']) == 4, 'o JSON da IA não virou o documento'
        assert app.edit_mode, 'caiu fora do modo edição — sem paleta para editar'
        print(f"  {len(app.model['nodes'])} nós vindos da IA, já em modo edição: OK")
    finally:
        app.root.destroy()


def test_assistente_sem_colar_entrega_fluxo_editavel():
    """Quem prefere montar à mão recebe as colunas e a paleta ligada."""
    app = _app(com_documento=False)
    try:
        w = _wizard(app)
        assert 'colunas' in w.lbl_validacao.cget('text').lower(), \
            'campo vazio não explicou o que acontece'
        w._avancar()
        app.root.update()
        assert len(app.model['lanes']) == 2
        assert app.edit_mode, 'sem modo edição, não há como montar nada'
        assert app.palette.winfo_manager() != '', 'paleta não apareceu'
        print('  fluxo vazio, editável, com paleta à mão: OK')
    finally:
        app.root.destroy()


def test_assistente_acusa_ator_inventado_pela_ia():
    """Se a IA furar as rédeas, o aviso aparece antes de criar o arquivo."""
    app = _app(com_documento=False)
    try:
        w = _wizard(app)
        ia = {'title': 'Com intruso',
              'lanes': [{'id': 'L1', 'label': 'Control Operator (CCR)'},
                        {'id': 'L2', 'label': 'Gestor Responsável'}],
              'nodes': [{'id': 'N1', 'laneId': 'L1', 'type': 'task', 'label': 'A'},
                        {'id': 'N2', 'laneId': 'L2', 'type': 'task', 'label': 'B'}],
              'edges': [{'from': 'N1', 'to': 'N2'}]}
        w.txt_json.insert('1.0', json.dumps(ia, ensure_ascii=False))
        w._validar_json()
        app.root.update()
        aviso = w.lbl_validacao.cget('text')
        assert 'Gestor Responsável' in aviso, \
            f'não acusou o ator inventado: {aviso}'
        print('  ator fora dos escolhidos é apontado, não descartado: OK')
    finally:
        app.root.destroy()


def test_assistente_recusa_json_quebrado():
    """JSON inválido não pode virar arquivo — o erro aparece ao digitar."""
    app = _app(com_documento=False)
    try:
        w = _wizard(app)
        w.txt_json.insert('1.0', '{ "lanes": [ISSO NÃO É JSON')
        w._validar_json()
        app.root.update()
        assert w.lbl_validacao.cget('text').startswith('✗'), \
            'JSON quebrado passou pela validação'
        print('  JSON quebrado é recusado na hora: OK')
    finally:
        app.root.destroy()


def test_faixa_de_departamento_agrupa_colunas_vizinhas():
    """A barra de área cobre os atores daquela área, sem repetir o nome."""
    lanes = [
        {'id': 'L1', 'label': 'Control Operator (CCR)', 'department': 'Operações'},
        {'id': 'L2', 'label': 'Supervisor de Produção', 'department': 'Operações'},
        {'id': 'L3', 'label': 'Técnico de Instrumentação', 'department': 'Manutenção'},
    ]
    nodes = [{'id': f'N{i}', 'laneId': f'L{i}', 'type': 'task', 'label': f'E{i}'}
             for i in (1, 2, 3)]
    edges = [{'from': 'N1', 'to': 'N2'}, {'from': 'N2', 'to': 'N3'}]
    m = _modelo({'title': 'Faixas', 'lanes': lanes, 'nodes': nodes, 'edges': edges})
    comp = m['_computed']

    bandas = comp['dept_bands']
    assert [b['department'] for b in bandas] == ['Operações', 'Manutenção'], \
        f'faixas não agruparam colunas vizinhas: {bandas}'
    assert bandas[0]['width'] > bandas[1]['width'], \
        'a faixa de duas colunas devia ser mais larga que a de uma'
    assert comp['header_height'] == comp['dept_band_height'] + \
        comp['label_band_height'], 'a faixa não entrou na altura do cabeçalho'

    # Arquivo antigo (sem área nas colunas) continua sem faixa
    antigo = _modelo()
    assert antigo['_computed']['dept_band_height'] == 0, \
        'arquivo antigo ganhou uma faixa que ninguém pediu'
    print(f'  {len(bandas)} faixas para 3 colunas; arquivo antigo intacto: OK')


def test_banner_derivado_nao_reprova_fluxo_interdepartamental():
    """O banner "A · B · C" não é um nome de área — não pode ser cobrado.

    Quando as colunas declaram a própria área, o `department` do documento
    passa a ser uma legenda derivada delas. Cobrá-la do catálogo reprovava
    TODO fluxo com mais de um departamento, e como a validação é o gate de
    publicação, nenhum deles poderia ser publicado. Nunca.
    """
    catalogo = cat.carregar()
    doc = {
        'title': 'Interdepartamental',
        'department': 'Operações · Manutenção',
        'lanes': [{'id': 'L1', 'label': 'Control Operator (CCR)',
                   'department': 'Operações'},
                  {'id': 'L2', 'label': 'Técnico de Instrumentação',
                   'department': 'Manutenção'}],
        'nodes': [{'id': 'N1', 'laneId': 'L1', 'type': 'start', 'label': 'Início'},
                  {'id': 'N2', 'laneId': 'L2', 'type': 'end', 'label': 'Fim'}],
        'edges': [{'from': 'N1', 'to': 'N2'}],
    }
    avisos = [i for i in validate_model(_modelo(doc), catalogo)
              if 'catalogo' in i['kind']]
    assert not avisos, f'banner derivado reprovou: {[a["msg"] for a in avisos]}'

    # Arquivo antigo (sem área nas colunas) continua sendo cobrado
    antigo = _bruto()
    antigo['department'] = 'Manutencao'
    erro = [i for i in validate_model(_modelo(antigo), catalogo)
            if i['kind'] == 'departamento_fora_do_catalogo']
    assert erro, 'parou de cobrar a grafia do departamento em arquivo antigo'
    print('  banner derivado passa; arquivo antigo ainda é cobrado: OK')


def test_cargo_restrito_a_area_da_coluna():
    """Cargo que existe, mas na área errada, é acusado."""
    catalogo = cat.carregar()
    dados = _bruto()
    dados['lanes'][0]['department'] = 'Tecnologia da Informação'
    avisos = [i for i in validate_model(_modelo(dados), catalogo)
              if i['kind'] == 'cargo_fora_do_catalogo']
    assert avisos, 'não acusou o cargo alocado na área errada'

    dados['lanes'][0]['department'] = cat.departamento_do_cargo(
        dados['lanes'][0]['label'], catalogo)
    ok = [i for i in validate_model(_modelo(dados), catalogo)
          if i['kind'] == 'cargo_fora_do_catalogo']
    assert not ok, f'acusou cargo que está na área certa: {ok}'
    print('  cargo é checado DENTRO da área da coluna: OK')


def test_03_gate_bloqueia_publicacao_com_pendencia():
    """PORTÃO: pendência de `validate_model` impede publicar."""
    app = _app()
    try:
        app._toggle_edit()
        app.root.update()
        app.editor._add_node('task', '', 1200, 300)   # sem texto, sem destino
        app.root.update()
        gov_antes = copy.deepcopy(app.model.get('governance'))
        app._publish()
        app.root.update()
        gov = app.model.get('governance') or {}
        assert gov.get('status') != 'published', 'publicou com pendência'
        assert gov.get('approval') is None, 'gravou aprovação com pendência'
        assert (gov.get('auditTrail') == (gov_antes or {}).get('auditTrail')), \
            'gate bloqueado não pode registrar evento de publicação'
        print('  publicação recusada, sem status/fingerprint/evento: OK')
    finally:
        app.root.destroy()


def test_05_correcao_guiada_leva_ao_elemento():
    """PORTÃO: o nó selecionado é exatamente o do aviso."""
    app = _app()
    try:
        app._toggle_edit()
        app.root.update()
        app.editor._add_node('task', '', 1200, 300)
        app.root.update()
        app._publish()
        app.root.update()

        issues = validate_model(app.model, app.catalogo)
        esperados = {i['node_id'] for i in issues if i.get('node_id')}
        selecionado = (app.editor.selected_node or {}).get('id')
        assert selecionado in esperados, (
            f'correção guiada foi para {selecionado}, fora de {esperados}')
        print(f'  levou ao nó {selecionado}, que é o do aviso: OK')
    finally:
        app.root.destroy()


def test_14_tres_portas_escrevem_no_mesmo_historico():
    """PORTÃO: canvas, painel JSON e painel de propriedades — um histórico."""
    app = _app()
    try:
        app._toggle_edit()
        app.root.update()
        no = next(n for n in app.model['nodes'] if n['type'] == 'task')

        # (a) canvas: arrastar e soltar
        app.editor.select_node(no['id'])
        app.editor.drag_data = {'x': 0, 'y': 0}

        class Ev:
            pass
        ev = Ev()
        ev.x, ev.y = [int(v) for v in app.viewport.to_view(1150, 900)]
        app.editor._on_drag(ev)
        app.editor._on_release(ev)
        app.root.update()
        pos_a = (app.editor.selected_node['x'], app.editor.selected_node['y'])

        # (b) painel JSON
        texto = app.json_panel.get_json().replace(
            app.model['title'], 'Título vindo do painel JSON', 1)
        app.json_panel.set_json(texto)
        app._render()
        app.root.update()
        assert app.model['title'] == 'Título vindo do painel JSON'

        # (c) painel de propriedades
        alvo = next(n for n in app.model['nodes'] if n['id'] == no['id'])
        app.editor.select_node(alvo['id'])
        app.editor.set_node_type(app.editor.selected_node, 'decision')
        app.root.update()
        assert next(n for n in app.model['nodes']
                    if n['id'] == no['id'])['type'] == 'decision'

        # Três Ctrl+Z desfazem na ordem inversa
        app._undo(); app.root.update()
        assert next(n for n in app.model['nodes']
                    if n['id'] == no['id'])['type'] == 'task', '(c) não desfez'
        app._undo(); app.root.update()
        assert app.model['title'] != 'Título vindo do painel JSON', '(b) não desfez'
        app._undo(); app.root.update()
        atual = next(n for n in app.model['nodes'] if n['id'] == no['id'])
        assert (atual['x'], atual['y']) != pos_a, '(a) não desfez'
        print('  três portas, um histórico, ordem inversa: OK')
    finally:
        app.root.destroy()


def test_15_auto_render_nao_estoura_o_historico():
    """PORTÃO: digitar uma frase gera um passo, não um por tecla."""
    app = _app()
    try:
        antes = len(app._history)
        painel = app.json_panel
        for _ in range(20):                    # digitação contínua
            painel.text.edit_modified(True)
            app.root.update()
        assert painel._pendente is not None, 'não agendou a auto-renderização'
        assert len(app._history) == antes, \
            'cada tecla virou um passo de histórico'

        painel._flush()                        # a pausa (ou o foco saindo)
        app.root.update()
        assert len(app._history) - antes <= 1, (
            f'{len(app._history) - antes} passos para uma única digitação')
        print('  20 toques → no máximo 1 passo de histórico: OK')
    finally:
        app.root.destroy()


def test_16_painel_de_propriedades_passa_pelo_commit():
    """PORTÃO: a troca de campo é desfazível e chega ao arquivo salvo."""
    app = _app()
    try:
        app._toggle_edit()
        app.root.update()
        no = next(n for n in app.model['nodes'] if n['type'] == 'task')
        app.editor.select_node(no['id'])
        app.root.update()

        painel = app.properties_panel
        painel.cb_tipo.set('Decisão')
        painel.cb_tipo.event_generate('<<ComboboxSelected>>')
        app.root.update()

        salvo = json.loads(app.json_panel.get_json())
        gravado = next(n for n in salvo['nodes'] if n['id'] == no['id'])
        assert gravado.get('type') == 'decision', \
            'escreveu no dicionário do nó por fora do fluxo (não persistiu)'

        app._undo()
        app.root.update()
        assert next(n for n in app.model['nodes']
                    if n['id'] == no['id'])['type'] == 'task', \
            'não passou por _commit — Ctrl+Z não desfez'
        print('  troca de tipo persiste e é desfazível: OK')
    finally:
        app.root.destroy()


def test_catalogo_padroniza_departamento_e_cargo():
    """Nome fora do catálogo vira aviso — com sugestão do nome correto."""
    catalogo = cat.carregar()
    assert cat.nomes_departamentos(catalogo) and cat.todos_cargos(catalogo), \
        'catálogo semente vazio'
    # Todo cargo pertence a alguma área — é o que a hierarquia garante
    for nome in cat.nomes_departamentos(catalogo):
        for cargo in cat.cargos_de(nome, catalogo):
            assert cat.departamento_do_cargo(cargo, catalogo), \
                f'cargo órfão no catálogo: {cargo}'

    dados = _bruto()
    limpo = validate_model(_modelo(dados), catalogo)
    assert not [i for i in limpo if 'catalogo' in i['kind']], \
        'arquivo real do projeto reprovou no próprio catálogo semente'

    dados['department'] = 'Manutencao'          # sem cedilha/acento
    dados['lanes'][0]['label'] = 'Operador de Painell'
    avisos = [i for i in validate_model(_modelo(dados), catalogo)
              if 'catalogo' in i['kind']]
    assert len(avisos) == 2, f'esperava 2 avisos, veio {len(avisos)}'
    assert 'Manutenção' in avisos[0]['msg'], 'não sugeriu o nome correto'

    # Sem catálogo informado, a validação segue sendo função pura
    assert not [i for i in validate_model(_modelo(dados)) if 'catalogo' in i['kind']]
    print('  fora do catálogo vira aviso com sugestão; sem catálogo, nada: OK')


def test_reordenar_colunas_preserva_posicoes_manuais():
    """A ordem das colunas é a leitura do processo, e precisa sobreviver.

    Prende três coisas: a ordem muda de fato, os nós de posição manual andam
    junto com a coluna deles (senão ficariam para trás, na faixa de quem
    entrou no lugar) e a nova ordem persiste ao reabrir o arquivo.
    """
    app = _app()
    try:
        app._toggle_edit()
        app.root.update()
        lanes = app.model['lanes']
        antes = [l['id'] for l in lanes]
        assert len(antes) >= 3, 'amostra com poucas colunas para o teste'

        alvo = lanes[-1]
        fixado = next(n for n in app.model['nodes']
                      if n.get('laneId') == alvo['id']
                      and n.get('type') != 'annotation')
        fixado['pinned'] = True
        x_antes = fixado['x']

        assert app.editor.move_lane(alvo['id'], -1), 'move_lane recusou'
        app.root.update()

        depois = [l['id'] for l in app.model['lanes']]
        assert depois != antes, 'a ordem não mudou'
        assert depois[-2] == alvo['id'], 'a coluna não foi para a posição certa'
        assert [l['order'] for l in app.model['lanes']] == \
            list(range(len(depois))), 'order não foi renumerado'

        atual = next(n for n in app.model['nodes'] if n['id'] == fixado['id'])
        largura = alvo['width'] + app.model['layout']['swimlanes']['gap']
        assert abs((x_antes - atual['x']) - largura) < 1, (
            f'nó fixado não acompanhou a coluna: andou {x_antes - atual["x"]}, '
            f'esperado {largura}')

        # Persistência: a ordem nova tem de sobreviver à reabertura
        salvo = json.loads(app.json_panel.get_json())
        reaberto = parse_flowchart(json.dumps(salvo))
        assert [l['id'] for l in reaberto['lanes']] == depois, \
            'a ordem voltou ao original ao reabrir o arquivo'

        # E é um único passo de histórico
        app._undo()
        app.root.update()
        assert [l['id'] for l in app.model['lanes']] == antes, \
            'Ctrl+Z não desfez a reordenação'
        print('  ordem muda, nós fixados acompanham, persiste e desfaz: OK')
    finally:
        app.root.destroy()


def test_extremos_nao_saem_da_fila():
    """A primeira coluna não vai para a esquerda; a última, para a direita."""
    app = _app()
    try:
        app._toggle_edit()
        app.root.update()
        lanes = app.model['lanes']
        assert app.editor.move_lane(lanes[0]['id'], -1) is False
        assert app.editor.move_lane(lanes[-1]['id'], 1) is False

        linhas = app.properties_panel._linhas_lane
        assert linhas[0]['esq'].cget('state') == 'disabled'
        assert linhas[-1]['dir'].cget('state') == 'disabled'
        print('  extremos travados no modelo e na interface: OK')
    finally:
        app.root.destroy()


def test_ajustar_a_janela_alcanca_documento_grande():
    """E1: existe um zoom em que o processo inteiro cabe na tela.

    Um fluxo de porte real passa de 4.000px de altura contra ~770 de área útil.
    Com o piso de zoom em 30% não havia estado algum em que o usuário visse o
    documento completo — e, para um mapa de processo, ver o todo é a função.
    """
    from core.viewport import MIN_SCALE

    app = _app()
    try:
        comp = app.model['_computed']
        # Um documento sintético do porte que a IA produz
        necessario = min(1080 / 2620, 770 / 4408)
        assert MIN_SCALE <= necessario, (
            f'piso de zoom {MIN_SCALE:.0%} não alcança os {necessario:.0%} '
            f'necessários para um documento de 2620x4408')
        assert hasattr(app, '_zoom_fit'), 'não existe ajustar à janela'

        app._zoom_fit()
        app.root.update()
        larg, alt = comp['total_width'], comp['total_height']
        s = app.viewport.scale
        assert larg * s <= app.canvas.winfo_width() + 2 or larg * s <= 1200
        print(f'  ajustou para {app.viewport.percent}% '
              f'(piso agora {MIN_SCALE:.0%}): OK')
    finally:
        app.root.destroy()


def test_indice_navega_e_busca():
    """E2/O1: dá para achar um nó sem rolar às cegas."""
    app = _app()
    try:
        app._toggle_outline_panel()
        app.root.update()
        assert app._outline_visivel

        nos = [n for n in app.model['nodes'] if n['type'] != 'annotation']
        alvo = nos[len(nos) // 2]

        # Busca filtra pelo texto da etapa
        painel = app.outline_panel
        painel._limpar_placeholder()
        painel.ent_busca.insert(0, alvo['label'][:8])
        painel._on_busca()
        app.root.update()
        assert alvo['id'] in painel._linhas, \
            f"busca por '{alvo['label'][:8]}' não encontrou o nó"

        # Clicar leva ao nó
        app._toggle_edit()
        app.root.update()
        app._ir_para_no(alvo['id'])
        app.root.update()
        assert (app.editor.selected_node or {}).get('id') == alvo['id'], \
            'clique no índice não selecionou o nó'
        print(f'  busca achou e o clique selecionou {alvo["id"]}: OK')
    finally:
        app.root.destroy()


def test_indice_lista_as_lacunas_do_processo():
    """O1: as anotações Gap deixam de ser texto cinza na lateral."""
    dados = _bruto()
    dados['nodes'].append({'id': 'C_GAP', 'laneId': dados['lanes'][0]['id'],
                           'type': 'annotation',
                           'label': 'Gap: quem aprova a compra urgente?'})
    dados['edges'].append({'from': dados['nodes'][1]['id'], 'to': 'C_GAP',
                           'type': 'annotation'})
    app = _app(com_documento=False)
    try:
        app._esconder_boas_vindas()
        app.json_panel.set_json(json.dumps(dados, ensure_ascii=False))
        app._render()
        app._toggle_outline_panel()
        app.root.update()

        lacunas = app.model['_computed']['notes']
        assert lacunas, 'a anotação não virou lacuna'
        textos = [n['text'] for n in lacunas]
        assert any('compra urgente' in t for t in textos)
        print(f'  {len(lacunas)} lacuna(s) no índice: OK')
    finally:
        app.root.destroy()


def test_cabecalho_da_coluna_so_aceita_o_catalogo():
    """D2: o canvas era uma porta lateral por onde qualquer grafia entrava."""
    app = _app()
    try:
        app._toggle_edit()
        app.root.update()
        lane = app.model['lanes'][0]
        app.editor.set_lane_department(lane['id'], 'Operações')
        app.root.update()

        comp = app.model['_computed']
        top = app.model['meta']['margins']['top']
        band_h = comp['dept_band_height']
        lp = comp['lane_positions'][lane['id']]
        assert band_h > 0, 'sem faixa de área não há o que testar'

        class Ev:
            pass

        def ev(mx, my):
            e = Ev()
            e.x, e.y = [int(v) for v in app.viewport.to_view(mx, my)]
            return e

        # Duplo clique NA FAIXA: escolhe a ÁREA, e é lista, não texto livre
        app.editor._on_double_click(ev(lp['x'] + 60, top + band_h / 2))
        app.root.update()
        w = app.editor._inline_widget
        assert w is not None, 'duplo clique na faixa não abriu nada'
        assert w.winfo_class() == 'TCombobox', \
            f'faixa abriu {w.winfo_class()} — deveria ser lista do catálogo'
        valores = list(w.cget('values'))
        assert 'Operações' in valores and len(valores) > 3, \
            'a lista não veio do catálogo de departamentos'
        app.editor._close_inline(commit=False)
        app.root.update()

        # Duplo clique NO NOME: escolhe o CARGO, restrito à área da coluna
        app.editor._on_double_click(ev(lp['x'] + 60, top + band_h + 12))
        app.root.update()
        w2 = app.editor._inline_widget
        assert w2 is not None and w2.winfo_class() == 'TCombobox', \
            'nome do ator ainda aceita texto livre'
        cargos = set(w2.cget('values'))
        esperado = set(cat.cargos_de('Operações', app.catalogo))
        assert esperado and esperado.issubset(cargos | {lane['label']}), \
            'os cargos oferecidos não são os da área da coluna'
        app.editor._close_inline(commit=False)
        print(f'  faixa → {len(valores)} áreas · nome → cargos de Operações: OK')
    finally:
        app.root.destroy()


def test_subprocesso_responde_ao_clique_e_persiste():
    """D3/O3: clicar numa Instrução de Trabalho deixava de fazer nada."""
    from core.hittest import find_subprocess_node_at

    dados = _bruto()
    alvo = next(n for n in dados['nodes'] if n.get('type') == 'task')
    alvo['type'] = 'subprocess'
    alvo['group'] = {
        'label': 'Emissão de Permissão de Trabalho',
        'nodes': [{'id': 'G_A', 'type': 'task', 'label': 'Analisar risco'},
                  {'id': 'G_B', 'type': 'task', 'label': 'Emitir PT'}],
        'edges': [{'from': 'G_A', 'to': 'G_B'}],
    }
    app = _app(com_documento=False)
    try:
        app._esconder_boas_vindas()
        app.json_panel.set_json(json.dumps(dados, ensure_ascii=False))
        app._render()
        app._toggle_edit()
        app.root.update()

        assert app.model['subprocesses'], 'subprocesso não foi lido'
        sp = app.model['subprocesses'][0]
        interno = sp['nodes'][0]

        # O hit-test agora enxerga o nó de dentro
        achado_sp, achado = find_subprocess_node_at(
            app.model, interno['x'] + 40, interno['y'] + 20, 4)
        assert achado is not None and achado['id'] == interno['id'], \
            'o clique continua atravessando o subprocesso'

        # Editar o texto persiste no arquivo salvo
        app.editor.set_sp_node_label(sp, interno, 'Analisar risco (revisado)')
        app.root.update()
        salvo = json.loads(app.json_panel.get_json())
        pai = next(n for n in salvo['nodes'] if n['id'] == alvo['id'])
        gravado = next(g for g in pai['group']['nodes'] if g['id'] == 'G_A')
        assert gravado['label'] == 'Analisar risco (revisado)', \
            'a edição aparecia na tela e sumia ao salvar'
        print('  subprocesso responde ao clique e a edição persiste: OK')
    finally:
        app.root.destroy()


def test_criar_no_confirma_em_vez_de_repreender():
    """E3: criar algo e receber um aviso de validação como resposta é ruído."""
    app = _app()
    try:
        app._toggle_edit()
        app.root.update()
        app.editor._add_node('task', 'Etapa nova', 1200, 300)
        app.root.update()
        msg = app.status_bar._label.cget('text')
        assert msg.startswith('➕'), \
            f'a confirmação foi engolida pelo aviso: {msg[:70]}'
        assert 'pendência' in msg, \
            'o aviso sumiu por completo — ele deve aparecer, só não no lugar da confirmação'
        print(f'  {msg[:64]}: OK')
    finally:
        app.root.destroy()


def test_prompt_nao_pede_mais_department_no_topo():
    """P4: a IA não deve chutar uma área entre as várias do fluxo."""
    from core import prompt as prompt_mod

    texto = prompt_mod.montar([('Operações', 'Control Operator (CCR)'),
                               ('Manutenção', 'Técnico de Instrumentação')],
                              'Teste', '')
    assert 'Não escreva `department` no topo' in texto, \
        'o prompt ainda deixa a IA escolher o banner no chute'
    doc = prompt_mod.modelo_inicial(
        [('Operações', 'Control Operator (CCR)')], 'Teste')
    assert 'department' not in doc or not doc.get('department'), \
        'o assistente voltou a gravar banner derivado no documento'
    print('  prompt e assistente não poluem mais o campo department: OK')


def test_novo_cria_documento_na_hora():
    """Clicar em Novo entrega um documento, sem atravessar assistente nenhum.

    O assistente de IA é um caminho a mais, não um pedágio: quem vai montar o
    fluxo à mão não deveria precisar de quatro passos para chegar a uma tela
    onde possa desenhar.
    """
    app = _app(com_documento=False)
    try:
        assert app.model is None
        app._novo_documento()
        app.root.update()

        assert app.model is not None, 'Novo não criou documento'
        assert app.model['lanes'], 'documento em branco sem nenhuma coluna'
        assert app.edit_mode, 'caiu fora do modo edição — sem paleta'
        assert app.palette.winfo_manager() != '', 'paleta não apareceu'
        assert app.welcome not in app.root.pack_slaves(), \
            'continuou na tela inicial'
        assert len(app.canvas.find_all()) > 0, 'canvas vazio, sem colunas'
        print(f"  documento com {len(app.model['lanes'])} coluna(s), "
              f"editável de saída: OK")
    finally:
        app.root.destroy()


def test_documento_em_branco_monta_a_mao():
    """Do branco ao fluxo, só com paleta e barra lateral — sem IA."""
    app = _app(com_documento=False)
    try:
        app._novo_documento()
        app.root.update()
        lp = app.model['_computed']['lane_positions'][app.model['lanes'][0]['id']]

        class Ev:
            pass

        def ev(mx, my):
            e = Ev()
            vx, vy = app.viewport.to_view(mx, my)
            e.x = int(vx - app.canvas.canvasx(0))
            e.y = int(vy - app.canvas.canvasy(0))
            return e

        app._arm_tool('start', ('add', 'start', 'Início', False))
        app.editor._on_press(ev(lp['x'] + 160, 220))
        app.root.update()
        app._arm_tool('task', ('add', 'task', 'Executar etapa', False))
        app.editor._on_press(ev(lp['x'] + 160, 380))
        app.root.update()
        app.editor.add_lane('Manutenção', 'Técnico de Instrumentação')
        app.root.update()

        assert len(app.model['nodes']) == 2, 'a paleta não criou os nós'
        assert len(app.model['lanes']) == 2, 'a barra lateral não criou a coluna'
        print('  2 nós e 2 colunas montados à mão, sem assistente: OK')
    finally:
        app.root.destroy()


def test_assistente_passa_do_prompt_para_o_resultado():
    """O botão de avançar não pode ser expulso da janela pelo corpo do passo.

    No passo do prompt o corpo pede mais altura do que a janela tem. Como o
    rodapé era empacotado por último, era ele que o Tk espremia: o botão
    "Avançar" existia, mas fora da tela — não havia como sair do passo.
    """
    app = _app(com_documento=False)
    try:
        # A janela principal fica oculta nos testes, e um filho de janela
        # oculta nunca se declara "mapeado" — a checagem tem de ser sobre a
        # geometria real, com a janela à mostra.
        from ui.new_flow_wizard import NewFlowWizard
        app.root.deiconify()
        app.root.update()

        # Montado passo a passo aqui (e não pelo `_wizard`, que já vai até o
        # passo de colar): o que se mede é justamente a passagem do prompt
        # para o resultado.
        w = NewFlowWizard(app.root, catalogo=app.catalogo,
                          on_finish=app._criar_fluxo)
        app.root.update()
        w._vars_dep['Operações'].set(True)
        w._avancar()
        app.root.update()
        par = ('Operações', 'Control Operator (CCR)')
        w._vars_cargo[par].set(True)
        w._marcar_cargo(par)
        w._avancar()                      # → passo 3: prompt
        app.root.update()
        w.update_idletasks()
        assert hasattr(w, 'txt_prompt'), 'não chegou ao passo do prompt'

        def dentro_da_janela(widget, janela):
            # Quando o corpo expulsa o rodapé, o Tk DESMAPEIA o rodapé inteiro
            # — o widget continua existindo e até guarda a altura antiga, por
            # isso medir só a geometria não acusa nada. `winfo_ismapped` é o
            # que distingue "está na tela" de "existe em algum lugar".
            janela.update_idletasks()
            if not widget.winfo_ismapped():
                return False
            fim = widget.winfo_rooty() + widget.winfo_height()
            return fim <= janela.winfo_rooty() + janela.winfo_height()

        assert dentro_da_janela(w.btn_avancar, w), \
            'o botão de avançar ficou fora da janela no passo do prompt'
        assert dentro_da_janela(w.btn_criar_agora, w), \
            'a saída "Criar agora" ficou fora da janela'

        w._avancar()                      # → passo 4: colar o resultado
        app.root.update()
        w.update_idletasks()
        assert hasattr(w, 'txt_json'), 'não chegou ao passo de colar o JSON'
        assert dentro_da_janela(w.btn_avancar, w), \
            'o botão saiu da janela no passo de colar'
        app.root.withdraw()
        print('  prompt → colar, com o botão dentro da janela nos dois: OK')
    finally:
        app.root.destroy()


def test_assistente_deixa_sair_a_qualquer_momento():
    """"Criar agora" entrega o documento com o que já foi escolhido."""
    app = _app(com_documento=False)
    try:
        w = _wizard(app)                 # passo 3, sem colar nada
        w._concluir()
        app.root.update()
        assert app.model is not None, '"Criar agora" não criou o documento'
        assert len(app.model['lanes']) == 2, 'perdeu as colunas escolhidas'
        assert app.edit_mode
        print('  saiu no passo do prompt e levou as colunas: OK')
    finally:
        app.root.destroy()


def test_versao_do_instalador_bate_com_a_do_codigo():
    """O número da versão tem uma fonte só.

    Ele vivia apenas no `installer.iss`, onde nenhum código Python o enxergava.
    Agora mora em `core/versao.py`, e este teste é o que impede os dois de
    divergirem em silêncio — o que faria o programa instalado se anunciar com
    uma versão e checar atualização contra outra.
    """
    import re

    from core import versao as v

    iss = io.open(os.path.join(RAIZ, 'installer.iss'), encoding='utf-8').read()
    achado = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', iss)
    assert achado, 'não achei MyAppVersion no installer.iss'
    assert achado.group(1) == v.VERSAO, (
        f'installer.iss diz {achado.group(1)}, core/versao.py diz {v.VERSAO}')
    print(f'  instalador e código na mesma versão ({v.VERSAO}): OK')


def test_comparacao_de_versao_e_numerica():
    """'1.12.0' é mais nova que '1.9.0' — comparação alfabética inverteria."""
    from core import versao as v

    assert v.mais_nova('1.3.0', '1.2.0')
    assert v.mais_nova('1.12.0', '1.9.0'), 'comparou como texto, não como número'
    assert v.mais_nova('2.0.0', '1.99.99')
    assert not v.mais_nova('1.2.0', '1.2.0')
    assert not v.mais_nova('1.1.9', '1.2.0')
    print('  ordem numérica, inclusive passando da nona versão menor: OK')


def test_checagem_de_versao_nunca_derruba_o_programa():
    """Sem rede, sem URL ou com lixo na resposta: devolve None, não explode."""
    from core import versao as v

    assert v.checar(url='') is None, 'URL vazia deveria ser silenciosa'
    assert v.checar(url='http://nao-existe-flowforge.invalid/v.json',
                    timeout=2) is None, 'host inexistente deveria ser silencioso'
    print('  falha de rede é silenciosa: OK')


def test_aviso_de_atualizacao_aparece_e_some():
    """A faixa só existe quando há o que dizer, e fica acima da toolbar."""
    import http.server
    import socketserver
    import threading
    import time

    manifesto = json.dumps({'versao': '9.9.9',
                            'url': 'https://exemplo/FlowForge-Setup-9.9.9.exe',
                            'notas': 'versão de teste'}).encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(manifesto)))
            self.end_headers()
            self.wfile.write(manifesto)

        def log_message(self, *a):
            pass

    servidor = socketserver.TCPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{servidor.server_address[1]}/versao.json'

    import ui.app_window as AW
    original = AW.versao_mod.URL_ATUALIZACAO
    AW.versao_mod.URL_ATUALIZACAO = url
    app = _app(com_documento=False)
    try:
        assert app.barra_att.winfo_manager() == '', \
            'a faixa apareceu sem haver atualização'

        app._checar_atualizacao(manual=True)
        for _ in range(80):
            app.root.update()
            time.sleep(0.05)
            if app.barra_att.winfo_manager() != '':
                break
        assert app.barra_att.winfo_manager() != '', \
            'a faixa não apareceu — o resultado não chegou à interface'
        assert '9.9.9' in app.lbl_att.cget('text')

        empacotados = app.root.pack_slaves()
        assert empacotados.index(app.barra_att) < \
            empacotados.index(app._toolbar_wrapper), \
            'a faixa não ficou acima da toolbar'

        app._fechar_barra_atualizacao()
        app.root.update()
        assert app.barra_att.winfo_manager() == '', 'não deu para fechar a faixa'
        print('  faixa aparece, informa a versão e fecha: OK')
    finally:
        AW.versao_mod.URL_ATUALIZACAO = original
        app.root.destroy()
        servidor.shutdown()


def test_gate_separa_defeito_de_estrutura_de_desvio_de_nome():
    """Nome fora do catálogo NÃO pode barrar a publicação como um nó órfão.

    Achado do teste aberto: o aprovador recebeu um fluxo com zero defeitos de
    estrutura e uma divergência de nomenclatura, e ficou sem saída — não podia
    corrigir (não é o autor) nem aprovar (o gate barrava). Defeito de estrutura
    barra; desvio de nome vira ressalva registrada na trilha.
    """
    from core.parser import bloqueios, avisos, severidade

    catalogo = cat.carregar()

    # Fluxo íntegro, mas com cargo fora da lista e raia única
    doc = {'title': 'Um ator só',
           'lanes': [{'id': 'L1', 'label': 'SMS'}],
           'nodes': [{'id': 'N1', 'laneId': 'L1', 'type': 'start', 'label': 'Início'},
                     {'id': 'N2', 'laneId': 'L1', 'type': 'end', 'label': 'Fim'}],
           'edges': [{'from': 'N1', 'to': 'N2'}]}
    iss = validate_model(_modelo(doc), catalogo)
    assert not bloqueios(iss), \
        f'algo de estrutura barrou indevidamente: {issue_messages(bloqueios(iss))}'
    assert avisos(iss), 'a divergência de nome e a raia única sumiram do relatório'
    assert any(i['kind'] == 'raia_unica' for i in iss), \
        'swimlane com uma raia só passou sem comentário'

    # Defeito de estrutura continua barrando
    ruim = json.loads(json.dumps(doc))
    ruim['nodes'].append({'id': 'N3', 'laneId': 'L1', 'type': 'task', 'label': 'Solta'})
    travas = bloqueios(validate_model(_modelo(ruim), catalogo))
    assert travas, 'nó sem destino deixou de barrar'
    assert all(severidade(t) == 'bloqueio' for t in travas)
    print(f'  nomenclatura vira aviso, estrutura barra: OK')


def test_publicar_com_ressalva_fica_na_trilha():
    """Aprovar apesar de um aviso é decisão — e decisão sem rastro não vale."""
    import shutil
    import tempfile

    import tkinter.messagebox as mb
    original = mb.askyesno

    tmp = tempfile.mkdtemp()
    alvo = os.path.join(tmp, 'um-ator-so.json')
    io.open(alvo, 'w', encoding='utf-8').write(json.dumps(
        {'title': 'Um ator só',
         'lanes': [{'id': 'L1', 'label': 'SMS'}],
         'nodes': [{'id': 'N1', 'laneId': 'L1', 'type': 'start', 'label': 'Início'},
                   {'id': 'N2', 'laneId': 'L1', 'type': 'end', 'label': 'Fim'}],
         'edges': [{'from': 'N1', 'to': 'N2'}]}, ensure_ascii=False))

    app = _app(com_documento=False)
    # DEPOIS de _app(), que remoca os diálogos: aceitar a ressalva, recusar a
    # oferta de exportar o PDF logo em seguida.
    mb.askyesno = lambda t, *a, **k: 'ressalva' in str(t).lower()
    try:
        app._abrir_caminho(alvo)
        app.root.update()
        app._publish()
        app.root.update()

        gov = app.model.get('governance') or {}
        assert gov.get('status') == 'published', \
            'não publicou mesmo sem defeito de estrutura'
        com_detalhe = [e for e in gov.get('auditTrail', []) if e.get('detalhe')]
        assert com_detalhe, 'a ressalva aceita não foi registrada na trilha'
        assert com_detalhe[-1]['type'] == 'publicar_com_ressalva'
        print(f"  publicou com {len(com_detalhe[-1]['detalhe'])} ressalva(s) "
              f"registrada(s): OK")
    finally:
        mb.askyesno = original
        app.root.destroy()
        shutil.rmtree(tmp, ignore_errors=True)


def test_ponto_em_aberto_e_visivel_onde_o_usuario_olha():
    """O pedido de três usuários independentes do teste aberto.

    Registrar "isto ainda não está decidido" só era possível anexando um
    comentário cujo texto começasse com `Gap:`. Nenhum dos três descobriu.
    Agora é uma marca no próprio nó, no painel de propriedades.
    """
    app = _app()
    try:
        app._toggle_edit()
        app._toggle_outline_panel()
        app.root.update()

        dec = next(n for n in app.model['nodes'] if n['type'] == 'decision')
        app.editor.select_node(dec['id'])
        app.root.update()

        painel = app.properties_panel
        assert hasattr(painel, 'chk_aberto'), 'não há caixa de ponto em aberto'
        painel.var_aberto.set(True)
        painel.ent_pergunta.delete(0, 'end')
        painel.ent_pergunta.insert(0, 'quem aprova acima da alçada?')
        painel._commit_aberto()
        app.root.update()

        # 1) foi para o modelo e para o arquivo
        atual = next(n for n in app.model['nodes'] if n['id'] == dec['id'])
        assert (atual.get('props') or {}).get('em_aberto') is True
        salvo = json.loads(app.json_panel.get_json())
        gravado = next(n for n in salvo['nodes'] if n['id'] == dec['id'])
        assert (gravado.get('props') or {}).get('pergunta') == \
            'quem aprova acima da alçada?', 'a pergunta não sobreviveu ao salvar'

        # 2) aparece no canvas em âmbar, com "?" — não em vermelho de erro
        simbolos = [app.canvas.itemcget(i, 'text')
                    for i in app.canvas.find_withtag('issue')
                    if app.canvas.type(i) == 'text']
        assert '?' in simbolos, f'a marca no canvas não é "?": {simbolos}'

        # 3) é listado no índice, navegável
        import tkinter as tk
        textos = []

        def colher(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Label) and c.cget('text'):
                    textos.append(c.cget('text'))
                colher(c)

        colher(app.outline_panel)
        assert any('quem aprova acima da alçada?' in t for t in textos), \
            'o ponto em aberto não apareceu no índice'

        # 4) avisa, mas não impede publicar
        from core.parser import bloqueios
        iss = validate_model(app.model, app.catalogo)
        abertos = [i for i in iss if i['kind'] == 'ponto_em_aberto']
        assert abertos and not any(i in bloqueios(iss) for i in abertos), \
            'ponto em aberto passou a barrar a publicação'

        # 5) desfaz
        app._undo()
        app.root.update()
        depois = next(n for n in app.model['nodes'] if n['id'] == dec['id'])
        assert not (depois.get('props') or {}).get('em_aberto')
        print('  marca no nó, no canvas, no índice e no arquivo; e desfaz: OK')
    finally:
        app.root.destroy()


def test_pdf_cabe_na_folha_escolhida():
    """O PDF precisa caber em papel de verdade, não no tamanho do desenho.

    Achado do teste aberto: o fluxo real saía numa página de 28 × 55 cm, que
    não corresponde a papel nenhum. A impressora reduzia sozinha ou fatiava —
    e o fluxograma não servia para o uso declarado, que é imprimir e colar na
    parede.
    """
    import re
    import tempfile

    from export import pdf_export

    modelo = _modelo()
    comp = modelo['_computed']
    tmp = tempfile.mkdtemp()

    def media_box(caminho):
        b = io.open(caminho, 'rb').read()
        m = re.search(rb'/MediaBox\s*\[([^\]]+)\]', b)
        p = m.group(1).split()
        paginas = len(re.findall(rb'/Type\s*/Page[^s]', b))
        return float(p[2]), float(p[3]), paginas

    # Sem papel: comportamento antigo preservado (página do tamanho do desenho)
    livre = os.path.join(tmp, 'livre.pdf')
    pdf_export.export_pdf(modelo, livre)
    w, h, pag = media_box(livre)
    assert abs(w - comp['total_width']) < 1 and abs(h - comp['total_height']) < 1, \
        'sem papel, a página deixou de ter o tamanho do desenho'

    # Com papel: a folha manda, e continua sendo UMA página
    for nome, esperado in (('A4', (595.3, 841.9)), ('A3', (841.9, 1190.6))):
        alvo = os.path.join(tmp, f'{nome}.pdf')
        pdf_export.export_pdf(modelo, alvo, papel=nome)
        w, h, pag = media_box(alvo)
        lado_maior, lado_menor = max(w, h), min(w, h)
        assert abs(lado_maior - max(esperado)) < 2 and \
            abs(lado_menor - min(esperado)) < 2, \
            f'{nome} saiu com {w:.0f}x{h:.0f}, esperado {esperado}'
        assert pag == 1, f'{nome} gerou {pag} páginas'

    # Orientação automática acompanha o formato do desenho
    largo = _modelo({'title': 'Largo',
                     'lanes': [{'id': f'L{i}', 'label': f'Ator {i}'}
                               for i in range(1, 7)],
                     'nodes': [{'id': f'N{i}', 'laneId': f'L{i}',
                                'type': 'task', 'label': f'E{i}'}
                               for i in range(1, 7)],
                     'edges': [{'from': f'N{i}', 'to': f'N{i + 1}'}
                               for i in range(1, 6)]})
    alvo = os.path.join(tmp, 'largo.pdf')
    pdf_export.export_pdf(largo, alvo, papel='A4', orientacao='auto')
    w, h, _ = media_box(alvo)
    c = largo['_computed']
    if c['total_width'] > c['total_height']:
        assert w > h, 'desenho largo não virou paisagem'
    print(f"  livre = {comp['total_width']:.0f}x{comp['total_height']:.0f}, "
          f"A4 e A3 no tamanho certo, 1 página: OK")


def test_conexao_e_selecionavel_e_rotulavel_pelo_painel():
    """O Sim/Não deixa de exigir duplo clique preciso numa linha de 1px.

    Achado do teste aberto: um usuário de 20 anos de casa, que já usou Visio,
    não descobriu como rotular uma conexão — e o painel, que é onde a pessoa
    olha, só tratava nós.
    """
    from core.edges import plan_edges, lane_boundaries

    app = _app()
    try:
        app._toggle_edit()
        app.root.update()

        nos = {n['id']: n for n in app.model['nodes']}
        dec = next(n for n in app.model['nodes'] if n['type'] == 'decision')
        aresta = next(e for e in app.model['edges'] if e['from'] == dec['id'])
        chave = (aresta['from'], aresta['to'])

        # Um clique simples sobre a rota seleciona a conexão
        prims = plan_edges(app.model['edges'], nos, lane_boundaries(app.model))
        ponto = None
        for p in prims:
            if p.get('kind') == 'line' and p.get('edge') is aresta:
                pts = p['points']
                ponto = ((pts[0] + pts[2]) / 2, (pts[1] + pts[3]) / 2)
                break
        assert ponto, 'não achei a rota da conexão'

        class Ev:
            pass

        def ev(mx, my):
            e = Ev()
            vx, vy = app.viewport.to_view(mx, my)
            e.x = int(vx - app.canvas.canvasx(0))
            e.y = int(vy - app.canvas.canvasy(0))
            return e

        app.editor._on_press(ev(*ponto))
        app.root.update()
        assert app.editor.selected_edge is aresta, \
            'clique simples na conexão não a selecionou'
        assert app.canvas.find_withtag('edge_sel'), 'a rota não foi realçada'

        painel = app.properties_panel
        # O campo precisa vir PREENCHIDO: um Entry desabilitado ignora insert()
        # em silêncio, e o painel mostrava vazio o que existia no modelo.
        assert painel.ent_edge.get() == (aresta.get('label') or ''), \
            f"painel mostra {painel.ent_edge.get()!r}, modelo tem {aresta.get('label')!r}"

        # Rotular pelo painel muda o modelo, salva e desfaz
        antes = aresta.get('label')
        novo = 'Sim' if antes != 'Sim' else 'Não'
        painel._atalho_edge(novo)
        app.root.update()

        def rotulo():
            return next(e for e in app.model['edges']
                        if (e['from'], e['to']) == chave).get('label')

        assert rotulo() == novo, 'o rótulo não chegou ao modelo'
        salvo = json.loads(app.json_panel.get_json())
        gravado = next(e for e in salvo['edges']
                       if (e['from'], e['to']) == chave).get('label')
        assert gravado == novo, 'o rótulo não foi para o arquivo'
        app._undo()
        app.root.update()
        assert rotulo() == antes, 'Ctrl+Z não desfez o rótulo'
        print(f'  conexão selecionada, rotulada {novo!r}, salva e desfeita: OK')
    finally:
        app.root.destroy()


def test_painel_preenche_campo_mesmo_vindo_de_desabilitado():
    """Bug achado ao implementar: Entry desabilitado ignora insert() calado.

    O preenchimento acontece antes de o estado final ser decidido. Escrever
    direto deixava o campo vazio sempre que a seleção vinha de um estado
    desabilitado — o valor existia no modelo e o painel mostrava nada.
    """
    app = _app()
    try:
        painel = app.properties_panel
        painel.set_editable(False)          # tudo desabilitado
        app.root.update()

        app._toggle_edit()
        app.root.update()
        no = next(n for n in app.model['nodes']
                  if n['type'] == 'task' and n.get('label'))
        app.editor.select_node(no['id'])
        app.root.update()
        assert painel.ent_rotulo.get() == no['label'], \
            f"rótulo do nó veio vazio: {painel.ent_rotulo.get()!r}"
        print('  campo preenche mesmo partindo de desabilitado: OK')
    finally:
        app.root.destroy()


def test_trilha_cabe_no_limite_de_tamanho():
    """Regressão apontada pela Verificação: a trilha mora no próprio arquivo.

    `MAX_JSON_SIZE` rejeita o documento inteiro acima de 5 MB. Como a trilha só
    cresce, um fluxograma muito reeditado poderia passar a ser recusado na
    ABERTURA — não por conteúdo inválido, mas pela própria auditoria. Aqui se
    mede a folga real, em vez de supor que ela existe.
    """
    from core.parser import MAX_JSON_SIZE

    m = _modelo()
    base = len(json.dumps(serialize_model(m), indent=2, ensure_ascii=False))
    for _ in range(100):
        record_event(m, 'editar')
    com_100 = len(json.dumps(serialize_model(m), indent=2, ensure_ascii=False))
    por_evento = (com_100 - base) / 100
    cabem = int((MAX_JSON_SIZE - base) / por_evento)

    print(f'  ~{por_evento:.0f} bytes por evento; documento base de '
          f'{base / 1024:.0f} KB comporta ~{cabem:,} eventos antes dos 5 MB')
    assert cabem > 20000, (
        f'apenas {cabem} eventos cabem — a trilha passa a ameaçar a abertura '
        f'do próprio documento que ela audita')


# ── Runner ────────────────────────────────────────────────

def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, OSError):
        pass
    testes = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    falhas = 0
    for t in testes:
        print(f'\n▶ {t.__name__}')
        try:
            t()
            print('  ✅ passou')
        except AssertionError as e:
            falhas += 1
            print(f'  ❌ FALHOU: {e}')
    print(f'\n{len(testes) - falhas}/{len(testes)} testes passaram')
    return 1 if falhas else 0


if __name__ == '__main__':
    sys.exit(main())
