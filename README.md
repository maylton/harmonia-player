# Harmonia

Cliente Linux nativo, em GTK 4 e libadwaita, para a biblioteca do YouTube Music. O projeto é inspirado no [Metrolist](https://github.com/MetrolistGroup/Metrolist) e porta sua integração InnerTube para Python. A interface e a reprodução são nativas; WebKitGTK é usado somente durante o login integrado.

> **Beta 0.1:** esta é uma versão de testes. A API InnerTube não é pública e pode mudar sem aviso. Use apenas com sua própria conta. O app nunca solicita nem armazena a senha do Google.

## Estado atual

- interface adaptativa GTK4/libadwaita;
- login automático em navegador WebKitGTK integrado, com captura segura da sessão;
- autenticação manual por cookie como alternativa, usando `SAPISIDHASH`;
- sincronização nativa de playlists, músicas, álbuns e artistas;
- paginação por continuation token;
- cache local para abrir a última biblioteca mesmo offline;
- capas reais com cache local e carregamento em segundo plano;
- navegação para playlists, álbuns e artistas com listagem de faixas;
- reprodução de áudio nativa com GStreamer e resolução de streams pelo InnerTube;
- barra persistente com pausar, continuar e parar;
- busca nativa de músicas com resultados reproduzíveis;
- fila de reprodução com anterior, próxima e avanço automático;
- rádio e reprodução automática via `watch-next`, expandindo a fila com recomendações do YouTube Music;
- integração MPRIS com os controles de mídia do GNOME, KDE e teclas multimídia;
- persistência SQLite transacional com migração automática do cache JSON;
- ações bidirecionais: curtir músicas, inscrição de artistas e gerenciamento de playlists;
- histórico local de alterações enviadas ao YouTube Music;
- home personalizada via `FEmusic_home`, preservando as seções da conta;
- paginação completa da Home, incluindo mixtapes, favoritos antigos, descobertas e prateleiras adicionais;
- barra de progresso buscável, tempos e fila de reprodução navegável;
- layout desktop inspirado no conceito: sidebar responsiva, busca persistente e player em três áreas;
- capas musicais em proporção 1:1, com recorte central e tratamento circular para artistas;
- filtros segmentados da biblioteca, controle de volume, shuffle e repeat;
- letras nativas do YouTube Music com painel no player e cache SQLite para acesso posterior;
- Explorar nativo com lançamentos, paradas, tendências, vídeos, momentos e gêneros navegáveis;
- credencial protegida pelo Secret Service do desktop, com migração segura do arquivo legado;
- preferências de qualidade, idioma, região, proxy, cache e processamento de áudio;
- equalizador, normalização, velocidade, tom, remoção de silêncio e temporizador;
- manifesto Flatpak, ícone próprio, catálogo de traduções e metadados AppStream.

## Executar no código-fonte

Requer Python 3.11+, PyGObject, GTK 4, libadwaita, WebKitGTK 6, GStreamer 1.0 com plugins de áudio e libsecret.

```bash
PYTHONPATH=src python3 -m harmonia
```

Ao abrir, use **Conectar ao YouTube Music** para autenticar no navegador integrado. A entrada manual do cabeçalho `Cookie` permanece disponível como alternativa em ambientes sem WebKitGTK.

## Instalar com Meson

```bash
meson setup build
meson compile -C build
meson install -C build
```

## Testes

```bash
python3 -m pip install -e '.[test]' ruff
ruff check src tests tools
ruff format --check src tests tools
PYTHONPATH=src python3 -m pytest -q
```

Metadados e integração desktop podem ser verificados com:

```bash
desktop-file-validate data/io.github.harmonia.Harmonia.desktop
appstreamcli validate --no-net --strict data/io.github.harmonia.Harmonia.metainfo.xml
```

## Estrutura

- `src/harmonia/innertube.py`: autenticação, requisições, paginação e parser da API;
- `src/harmonia/app.py`: composição da janela e coordenação da interface libadwaita;
- `src/harmonia/services.py`: orquestração dos serviços do YouTube Music;
- `src/harmonia/ui.py`: componentes e estilos de interação compartilhados;
- `src/harmonia/player.py`: reprodução nativa com GStreamer;
- `src/harmonia/storage.py`: sessão e cache local;
- `tests/`: testes do protocolo e parser.

## Licença

GPL-3.0-or-later. Metrolist também é GPL-3.0; este projeto é uma implementação independente baseada no comportamento público do protocolo e na arquitetura do projeto de referência.
