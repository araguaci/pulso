# Como contribuir

Obrigado por melhorar o Pulso. Mudanças pequenas e fáceis de revisar entram mais rápido.

## Antes de abrir um pull request

1. Procure uma issue parecida. Se não existir, abra uma quando a mudança alterar comportamento.
2. Correção de texto, de um bug óbvio ou de um detalhe visual pode ir direto ao pull request.
3. Leia o [código de conduta](CODE_OF_CONDUCT.md).

## Ambiente

Requisitos iguais aos de quem usa o projeto: Linux com `/proc`, Python 3.10 ou mais novo, `du` e `nice` (coreutils). Não há dependência para instalar.

```bash
git clone https://github.com/araguaci/pulso.git
cd pulso
python3 -m py_compile server.py
python3 server.py --help
python3 server.py
```

Abra `http://127.0.0.1:8787` e percorra a tela que você alterou: cartões, tabelas de processo, filtro e a seção de disco.

## O que manter

- Python só com a biblioteca padrão.
- A interface e a documentação em português.
- Nomes de processo e caminhos inseridos na página via `textContent`, nunca via HTML montado com esses textos.
- A varredura de disco fora de `/mnt`. O total de cada unidade montada ali pode aparecer; a lista de arquivos, não.
- A escuta padrão em `0.0.0.0` e na porta `8787`, para a WSL continuar acessível pelo navegador do Windows.

## Estilo

- Funções curtas e nomes diretos.
- Sem framework de frontend. O `index.html` permanece num único arquivo.
- Comentário só onde o código sozinho não explica a restrição.

## Mensagem do commit

Uma frase no imperativo, dizendo por que a mudança existe.

```text
Mostra o nome do script quando o processo é Python.
```

## Pull request

Descreva o problema, como testou e qualquer limite que ficou. O modelo do repositório traz a lista mínima.

Quem mantém o projeto pode pedir ajuste, recusar com um motivo, ou juntar o commit. Silêncio por algumas semanas não é aceite: se precisar de um retorno, comente de novo na issue.
