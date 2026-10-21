# Pulso

Painel no navegador para ver o que está consumindo **CPU**, **memória** e **disco** numa máquina Linux. Foi feito para a WSL: você sobe o Pulso no Linux e abre o endereço no navegador do Windows.

Não instala pacote nenhum além do Python que o sistema já traz.

**English.** Pulso is a local browser dashboard for CPU, memory, and disk on Linux and WSL. It uses only the Python standard library. The guide below is in Portuguese.

A [amostra das telas](docs/GUIA.md) mostra o painel sem instalar.

![Pulso: CPU, memória e disco local](docs/img/pulso-hero.webp)

## Requisitos

| Item | Exigência |
| --- | --- |
| Sistema | Linux com `/proc`. WSL2, Debian, Ubuntu e distribuições parecidas servem. |
| Python | 3.10 ou mais novo. Confira com `python3 --version`. |
| Disco | `du` e `nice`, do pacote coreutils, já presentes na maioria das instalações. |
| Docker | Opcional. Se o comando `docker` funcionar, o painel mostra imagens, volumes e cache. |
| Navegador | Qualquer um na mesma máquina, ou no Windows quando o Pulso roda na WSL2. |

Não há `pip install`. O servidor usa só a biblioteca padrão.

## Instalação

Escolha um dos caminhos. Os dois deixam a pasta `pulso` com `server.py` e `index.html`.

### Caminho A — clonar com Git

1. Instale o Git, se ainda não estiver instalado.

   ```bash
   git --version
   ```

2. Clone o repositório e entre na pasta.

   ```bash
   git clone https://github.com/araguaci/pulso.git
   cd pulso
   ```

3. Confira o Python.

   ```bash
   python3 --version
   ```

   A linha precisa mostrar `Python 3.10` ou uma versão maior.

### Caminho B — baixar o ZIP

1. Abra <https://github.com/araguaci/pulso>.
2. Clique em **Code** e depois em **Download ZIP**.
3. Extraia o arquivo.
4. No terminal, entre na pasta extraída (o nome termina em `-main` ou na etiqueta da versão).

   ```bash
   cd pulso-main
   python3 --version
   ```

## Uso

### 1. Inicie o painel

Na pasta do projeto:

```bash
python3 server.py
```

O terminal mostra os endereços. O padrão é a porta **8787**:

```text
Pulso
http://127.0.0.1:8787
```

Deixe esse terminal aberto. `Ctrl+C` encerra o Pulso.

Para outra porta:

```bash
python3 server.py --port 9090
```

### 2. Abra no navegador

**Linux, na mesma máquina.** Abra <http://127.0.0.1:8787>.

**Windows, com o Pulso na WSL2.** Abra <http://localhost:8787> no navegador do Windows. A WSL2 encaminha essa porta para o Linux quando o servidor escuta em `0.0.0.0`, que é o padrão.

Se `localhost` no Windows não abrir:

1. Na WSL, rode `hostname -I` e anote o primeiro endereço IPv4.
2. No Windows, abra `http://ESSE_ENDERECO:8787`.

### 3. Leia a tela

A página atualiza sozinha a cada 2 segundos.

1. Os três cartões mostram o percentual de CPU, de memória e do disco local, com o uso recente desenhado embaixo.
2. **Quem usa a CPU** lista os processos no topo. `100%` é um núcleo inteiro. Numa máquina de dois núcleos, um processo pode passar de 100%.
3. **Quem usa a memória** lista quem ocupa mais RAM residente.
4. O campo **Filtrar processo** restringe a lista que já está na tela. Digite parte do nome, do usuário ou do pid.
5. **Quem lê e grava agora** mostra a leitura e a gravação reais de cada processo no último intervalo.
6. **O que ocupa o disco** separa o disco local das unidades montadas em `/mnt`. Na WSL, o cartão de disco também mostra o tamanho do arquivo `ext4.vhdx` no Windows.
7. A árvore de pastas mostra os maiores diretórios. A primeira leitura pode levar cerca de um minuto.
8. **Atualizar pastas** mede o disco de novo.
9. Se o Docker estiver acessível, a seção **Docker** mostra imagens, contêineres, volumes e cache de build.

### 4. Encerre

No terminal onde o Pulso está rodando, pressione `Ctrl+C`.

## O que os números significam

- **CPU** do cartão é a fração ocupada da máquina inteira, de 0% a 100%.
- **CPU** de um processo segue o mesmo critério do `top`: 100% enche um núcleo.
- **Memória em uso** é o total menos o que ainda está disponível para programas, no mesmo espírito da coluna disponível do `free`.
- **Disco local** é o sistema de arquivos de `/`, no mesmo espírito do `df`.
- **Arquivo no Windows** é o tamanho do `ext4.vhdx` da distribuição, o que o disco do Windows realmente ocupa. Ele pode ser maior do que o uso interno e não encolhe sozinho.
- **Swap em arquivo** é o `swap-wsl.vhdx`, quando a WSL usa um arquivo de swap ao lado da distribuição.
- **Entrada e saída de swap** são a taxa de páginas entrando e saindo da troca, lida de `/proc/vmstat`.
- **Leitura e gravação** são os bytes que o processo enviou ao disco naquele intervalo (`read_bytes` e `write_bytes` em `/proc`).
- **Unidades em /mnt** aparecem só com o total. O Pulso não percorre os arquivos do Windows.
- Pastas que o seu usuário não pode ler ficam de fora da árvore. O espaço delas entra em “espaço não atribuído”. No caso do Docker, a seção própria cobre imagens e volumes.

## Deixar rodando

O comando da seção de uso ocupa o terminal. Para soltar o processo e fechar a janela:

```bash
cd pulso
setsid nohup python3 server.py >> pulso.log 2>&1 < /dev/null &
```

A saída fica em `pulso.log`. Para parar mais tarde:

```bash
pkill -f "python3 server.py"
```

Esse `pkill` encerra todo processo cujo comando contém esse texto. Use-o só se não houver outro `server.py` com o mesmo comando.

### Serviço systemd de usuário

Quando `systemctl --user` funciona, dá para subir o Pulso no login.

1. Confirme o caminho da pasta. O arquivo `contrib/pulso.service` espera `~/pulso`.
2. Copie a unidade:

   ```bash
   mkdir -p ~/.config/systemd/user
   cp contrib/pulso.service ~/.config/systemd/user/pulso.service
   ```

3. Ative:

   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now pulso.service
   systemctl --user status pulso.service
   ```

Na WSL, o systemd de usuário às vezes não tem barramento (`Failed to connect to bus`). Nesse caso use o `setsid` acima, ou o systemd do sistema se você administra a máquina.

## Configuração

| Opção | Padrão | Efeito |
| --- | --- | --- |
| `--host` | `0.0.0.0` | Interface de escuta. Use `127.0.0.1` se outras pessoas alcançam o IP desta máquina. |
| `--port` | `8787` | Porta HTTP. |

```bash
python3 server.py --help
```

Não há arquivo de configuração. Porta e endereço ficam na linha de comando.

## Segurança

O painel não pede senha. Quem abre o endereço vê nomes de processo, usuários, memória e caminhos de pasta.

- Na WSL, `http://localhost:8787` no Windows é o uso previsto.
- Não encaminhe essa porta para a internet.
- Se a máquina tem um IP visível na rede, prefira `python3 server.py --host 127.0.0.1`.

Detalhes e o caminho para reportar vulnerabilidade: [SECURITY.md](SECURITY.md).

## Contribuir

Issues, pull requests e o código de conduta estão em [CONTRIBUTING.md](CONTRIBUTING.md) e [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Licença

[MIT](LICENSE). Copyright (c) 2026 araguaci.
