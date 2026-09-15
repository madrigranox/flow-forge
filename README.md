# Flow Forge

Desenha fluxogramas de processo em raias (swimlanes) — o formato que mostra
**quem faz o quê, e em que ordem** — e exporta em PDF pronto para imprimir.

Você descreve o processo, a IA devolve um JSON, o Flow Forge desenha. Ou você
monta tudo na mão pela paleta, sem IA nenhuma. O arquivo é um `.json` legível:
dá para abrir no bloco de notas, versionar e mandar por e-mail.

![Flow Forge](logo.jpeg)

---

## Instalar

**Windows, sem instalar nada:** baixe o `FlowForge-Setup-x.y.z.exe` na aba
*Releases* e execute. Não pede senha de administrador.

**Rodando o código** (qualquer sistema com Python 3.9 ou superior):

```bash
python main.py
```

Não há o que instalar antes. O programa usa só a biblioteca padrão do
Python — nenhuma dependência externa, nenhum `pip install`.

> No Linux, o Tkinter costuma vir separado: `sudo apt install python3-tk`.

---

## Os três caminhos para criar um fluxo

Ao abrir, a tela inicial oferece:

**1. Com o assistente de IA** (`Ctrl+Shift+N`) — o caminho rápido.
Quatro passos: você dá um nome ao processo, escolhe os departamentos e os
cargos que participam, o programa monta um prompt já com essas informações
dentro, você cola esse prompt no ChatGPT/Claude junto com a descrição do
processo, e cola o JSON da resposta de volta. O desenho aparece pronto.

**2. Em branco** (`Ctrl+N`) — abre um documento vazio; você monta pela paleta
de ferramentas à esquerda: clica na forma, clica no canvas.

**3. Abrindo um arquivo** (`Ctrl+O`) — qualquer `.json` salvo antes.

---

## Editando

Entre no modo edição com `Ctrl+E` (ou o botão ✏ na barra).

- **Arrastar** move o nó; a coluna de destino aceita ou recusa conforme a raia.
- **Clique** num nó ou numa conexão seleciona; o painel da direita mostra tudo
  que dá para mudar naquele elemento.
- **O Sim/Não de uma decisão** fica no painel, com botões de atalho — selecione
  a linha que sai do hexágono.
- **Duplo clique** no cabeçalho da coluna troca o cargo e o departamento dela.
- **`Ctrl+L`** reorganiza o layout sozinho quando o desenho embolar.
- **`Ctrl+0`** ajusta à janela; **`Ctrl+F`** abre o índice do documento.

Tudo tem desfazer (`Ctrl+Z`) e refazer (`Ctrl+Y`).

### Lacunas do processo

Quando o processo tem um buraco — um prazo que ninguém definiu, um responsável
ambíguo — marque o nó como **ponto em aberto** no painel. Ele aparece no
desenho como nota e entra na lista de pendências, em vez de virar um post-it
que se perde.

---

## Departamentos e cargos

Os nomes das raias não são digitados: são escolhidos de um catálogo, para que
"Supervisor de Manutenção" não vire "Sup. Manut." no fluxograma do mês
seguinte.

O catálogo que vem junto é **um exemplo, feito para ser substituído**. Em
*Configurações → Departamentos e cargos* você cadastra os departamentos e os
cargos reais da sua empresa. A lista fica em
`%APPDATA%\FlowForge\catalogo.json` e sobrevive às atualizações do programa —
atualizar o Flow Forge não apaga o que você cadastrou.

Enquanto você estiver usando o catálogo de exemplo, a tela inicial avisa.

---

## Publicar

`Arquivo → Publicar` valida antes de aprovar, e separa duas coisas:

- **Defeitos de estrutura** (uma seta que não chega em lugar nenhum, uma
  decisão sem Sim/Não) — impedem a publicação. São erros de desenho.
- **Desvios de nomenclatura** (um cargo fora do catálogo, uma coluna sem área)
  — não impedem: você confirma num diálogo, e a ressalva fica **registrada na
  trilha de auditoria** do arquivo.

Todo documento carrega um histórico de eventos com data, autor e uma impressão
digital do conteúdo. Se alguém mexer no processo depois da aprovação, a
impressão digital deixa de bater e a aprovação some.

### PDF

`Ctrl+P` exporta. O programa pergunta em que folha o desenho deve caber — A4,
A3, A2 ou Carta — e encaixa tudo numa página só, mostrando de antemão a que
percentual o desenho vai ficar. Sem escolher folha, a página sai do tamanho do
diagrama: bom para ler na tela, ruim para imprimir.

---

## Estrutura do código

```
main.py              ponto de entrada
core/                regras: parser, layout, roteamento, catálogo, editor
  parser.py            dono do schema, validação e trilha de auditoria
  layout.py            posiciona colunas, nós e faixas de departamento
  edges.py             roteamento ortogonal das conexões
  renderer.py          desenha no canvas do Tkinter
  catalogo.py          departamentos e cargos
ui/                  janelas, painéis e diálogos
export/pdf_export.py PDF escrito à mão, sem biblioteca
data/                catálogo semente, exemplo e o prompt de IA
tests/               suíte de regressão
```

Rodar os testes:

```bash
python tests/test_regressao.py
python tests/test_governanca.py
```

---

## Licença

Gratuito para usar, inclusive no trabalho. O código está aqui para leitura e
auditoria, mas **não é código aberto**: os direitos são do autor, e
redistribuir ou modificar precisa de autorização. Detalhes no arquivo
[LICENSE](LICENSE).

Os fluxogramas que você criar são seus — a licença cobre o programa, não o que
você produz com ele.

Desenvolvido por Lucca Madrigrano.
