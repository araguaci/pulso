# Segurança

O Pulso não tem login. Quem alcança a porta vê processos, usuários, uso de memória e caminhos de pastas desta máquina.

## Uso previsto

- Na sua WSL ou no seu Linux, consultado por você.
- Escuta em `0.0.0.0` para o navegador do Windows abrir `http://localhost:8787` pela ponte da WSL2.

## O que evitar

- Não publique a porta na internet.
- Numa máquina com IP alcançável por outras pessoas, inicie com `--host 127.0.0.1`.
- Não rode o Pulso como root só para enxergar mais pastas, a menos que você aceite que o painel também mostre esses caminhos.

## Como reportar uma vulnerabilidade

Use um aviso privado: [github.com/araguaci/pulso/security/advisories/new](https://github.com/araguaci/pulso/security/advisories/new).

Inclua a versão (commit ou data), o sistema e os passos para reproduzir. Não abra uma issue pública com o detalhe do problema.

Quem mantém o projeto confirma o recebimento em até 7 dias e combina com você o que pode ser divulgado depois da correção.
