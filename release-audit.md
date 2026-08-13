# Auditoria de release — 0.1.0-beta.1

Data: 2026-08-13

## Resultado

O código-fonte e o pacote Meson estão aptos para o primeiro beta. A inicialização foi testada em português do Brasil e inglês a partir de uma instalação limpa em `DESTDIR`, com diretórios XDG vazios e warnings GLib fatais. Os processos permaneceram estáveis durante os smoke tests.

## Validações aprovadas

- Ruff lint e formatter em `src`, `tests` e `tools`;
- compilação de todos os módulos Python;
- 79 testes automatizados, incluindo traduções em runtime e assets do lançador;
- build e instalação Meson em modo release;
- inicialização pelo launcher instalado com `/usr/bin/python3`;
- MPRIS consultado ao vivo por D-Bus, incluindo alteração de volume;
- desktop entry com `desktop-file-validate`;
- AppStream offline em modo estrito;
- catálogos gettext completos em português do Brasil e inglês, com plurais e placeholders validados;
- 316 mensagens traduzidas em cada idioma e carregamento confirmado pelo pacote instalado;
- XML de todos os SVGs e metadados;
- consistência da versão `0.1.0-beta.1` entre Python, Meson, PyProject e AppStream;
- manifesto Flatpak analisado como YAML e consistente com o ID do aplicativo.

## Correções realizadas

- removido arquivo PostScript acidental de 5,6 MB da raiz;
- removidos imports, método de UI, seletores CSS e chamada duplicada sem uso;
- padronizada a formatação e adicionada configuração Ruff reproduzível;
- substituídas falhas silenciosas por logs de diagnóstico onde apropriado;
- corrigidas propriedades MPRIS que reportavam valores fixos ou ignoravam escrita;
- eliminados metadados MPRIS obsoletos após parar a reprodução;
- removido bytecode local do plano de cópia do Meson;
- incluídas GPL integral, licença de terceiros e cabeçalhos gettext completos;
- substituído o ícone provisório pelo asset final em oito tamanhos padrão do tema `hicolor`;
- corrigida a descoberta de instalações por usuário no GNOME Shell sem depender do `PATH` da sessão gráfica;
- ajustada a altura inicial para respeitar o tamanho natural da interface;
- adicionado workflow de CI para GitHub Actions.

## Pendências externas ou pós-beta

- esta cópia ainda não é um repositório Git; criar o repositório e publicar a tag `v0.1.0-beta.1` continua sendo uma ação externa;
- os URLs e screenshots remotos do AppStream só poderão ser validados após o primeiro push ao GitHub;
- `flatpak-builder` não está instalado neste ambiente, portanto o build Flatpak completo permanece pendente;
- `HarmoniaWindow` ainda é um monólito com mais de 200 métodos. A separação por páginas/controladores deve ocorrer depois do beta, com testes de integração, para não introduzir uma refatoração de alto risco na release.
