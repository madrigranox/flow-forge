# Como publicar uma versão

Roteiro para lançar o Flow Forge e entregar atualizações a quem já instalou.

## A cada versão

**1. Suba o número em `core/versao.py`**

```python
VERSAO = '1.3.0'
```

**2. Suba o mesmo número em `installer.iss`**

```
#define MyAppVersion "1.3.0"
```

Os dois têm de bater. Não é disciplina: `test_versao_do_instalador_bate_com_a_do_codigo`
falha se divergirem — sem isso o programa se anunciaria com uma versão e
checaria atualização contra outra.

**3. Rode as suítes**

```
python tests/test_regressao.py
python tests/test_governanca.py
```

**4. Gere o executável e o instalador**

```
pyinstaller build.spec
ISCC.exe installer.iss
```

Saída: `installer\FlowForge-Setup-1.3.0.exe`.

**5. Publique o instalador**

O GitHub Releases resolve de graça e dá URL permanente. Crie a release `v1.3.0`,
anexe o `.exe` e copie o link direto do arquivo.

**6. Atualize o manifesto**

Edite `versao.json` com o número novo, o link do passo 5 e uma linha sobre o que
mudou. Publique esse arquivo numa URL fixa — que **não muda a cada versão**.
Opções: o próprio repositório (link *raw* do arquivo na branch principal), ou um
GitHub Pages.

```json
{
  "versao": "1.3.0",
  "url": "https://.../FlowForge-Setup-1.3.0.exe",
  "notas": "O que mudou nesta versão"
}
```

**7. Aponte o programa para o manifesto** — uma vez só, na primeira publicação:

```python
# core/versao.py
URL_ATUALIZACAO = 'https://.../versao.json'
```

Enquanto essa constante estiver vazia, a verificação fica desligada e o programa
não faz nenhuma chamada de rede.

---

## O que o usuário vê

Ao abrir, o programa consulta o manifesto uma vez, em segundo plano. Havendo
versão nova, aparece uma faixa verde acima da barra de ferramentas com o número,
as notas e um botão **Baixar**. A faixa é dispensável no ✕ e só reaparece na
próxima abertura.

Não havendo versão nova — ou não havendo internet — nada acontece. Sem diálogo,
sem erro, sem espera: a verificação falha em silêncio de propósito. Um editor de
fluxograma não pode deixar de abrir porque um servidor caiu.

Quem quiser conferir na hora usa **Ajuda › Verificar atualizações**, e aí sim
recebe resposta mesmo quando está em dia.

## O que a atualização preserva

O instalador tem `AppId` fixo, então instala **por cima** da versão anterior em
vez de criar uma segunda cópia. E o catálogo de departamentos e cargos, junto
com as preferências e a lista de recentes, mora em:

```
%APPDATA%\FlowForge\
```

Fora da pasta do programa, de propósito. A lista que a empresa alimentou
sobrevive a todas as atualizações.

## Duas coisas para saber antes da primeira publicação

**SmartScreen.** Instalador não assinado dispara "O Windows protegeu o seu
computador". Não há contorno por código. Ou se compra um certificado de
assinatura de código, ou se orienta a pessoa a clicar em *Mais informações →
Executar assim mesmo*. A reputação melhora com o volume de downloads, mas
devagar.

**Instalação sem administrador.** `PrivilegesRequired=lowest` já está no
`installer.iss`: instala na pasta do usuário, sem UAC. Quem recebe consegue
instalar e atualizar sozinho, sem passar por TI.
