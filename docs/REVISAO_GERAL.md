# Revisão geral do Harmonia — 9 de outubro de 2026

Feita depois das oito fases do [plano do Metrolist](PLANO_METROLIST.md), com
o código em `645f016`. Mede tamanho, complexidade, acoplamento e código morto,
e compara com a beta.3 (`035b76e`), antes das fases.

## Resumo

- **Não criamos monólitos novos.** As fases somaram ~2.500 linhas, quase todas
  em 28 módulos novos com menos de 270 linhas cada. Só três arquivos existentes
  cresceram: `services.py` (+75), `innertube/client.py` (+70) e
  `window_search.py` (+38).
- **Os monólitos antigos continuam.** Treze arquivos passam de 500 linhas; os
  maiores são do frontend KDE (`qt_backend.py`, 1.258) e da janela GTK
  (`window_library.py`, 797). Nenhum cresceu nesta rodada.
- **Código morto é quase nenhum.** A busca encontrou duas sobras, já removidas.
- **O frontend KDE ficou para trás** nas telas das funções novas: a lógica
  chega até ele, mas faltam os controles no QML.

## Corrigido nesta revisão

| O quê | Onde | Commit |
|---|---|---|
| Vídeo de algumas faixas dizia "a sessão expirou": buscas anônimas levavam o `onBehalfOfUser` da sessão e o YouTube recusava com 401 | `innertube/client.py` | `619041d` |
| Restaurar um backup antigo deixava faltar as tabelas novas | `backup.py`, `storage` | `0340f36` |
| Um módulo com texto traduzível podia ficar fora do `po/POTFILES` sem aviso | `tests/test_potfiles.py` | `85bd793` |
| Código sem uso: `crossfade_seconds` e `wallpaper_candidates` | `crossfade_player.py`, `desktop_wallpaper.py` | `645f016` |

## O que está bem

- 62 arquivos de teste e 423 testes passando, incluindo o smoke do GTK numa
  área de trabalho invisível; CI no Windows, nos pacotes do Ubuntu e do Fedora
  e no Flatpak.
- A lógica nova não depende de GTK nem de Qt (`loudness`, `crossfade`,
  `lyrics_words`, `library_sync`, `autoeq`, `accounts`, `player_clients`...),
  é testada sozinha e serve aos dois frontends.
- Cada domínio de dados tem seu repositório em `storage/` (volume,
  mudanças pendentes, perfis do equalizador).
- O plano de modularização anterior está 12/14: faltam só os dois passos do
  Qt (abaixo).

## Problemas e riscos

### 1. Arquivos acima de 500 linhas

| Arquivo | Linhas | Proposta |
|---|---|---|
| `qt_backend.py` | 1.258 | ~120 métodos só repassam chamadas aos controladores. Expor um objeto por página ao QML (passo `f3-backend`). Muda as ligações de 29 arquivos QML: precisa do app KDE rodando no Linux para conferir. |
| `qt_integrations.py` | 795 | 70 métodos de cinco integrações. Separar em `qt_lastfm`, `qt_discord`, `qt_together`, `qt_recognition` e `qt_cast`, com o controlador atual como fachada (o QML não muda). Dá para fazer e testar aqui: o PySide6 6.11 está instalado. |
| `window_library.py` | 797 | Cartões de mídia (`_media_card_*`, 127 linhas) num widget próprio; `_render` (132) em uma função por origem; playlists locais num módulo à parte. |
| `window_playback.py` | 745 | A fila (`_render_queue` e as linhas, ~120 linhas) num `queue_view.py`; o registro no histórico (`_register_*`) num módulo de histórico. |
| `innertube/client.py` | 723 | Separar transporte e sessão (`_api_post`, `_bootstrap`), streams (`player_response`, `resolve_stream`, `register_playback`) e biblioteca/edições, mantendo `InnerTubeClient` como ponto de entrada. |
| `window_detail.py` | 708 | A página do artista (`_show_artist*`, ~260 linhas) num `window_artist.py`; cabeçalho e ações do detalhe num módulo de widgets. |
| `qt_video.py` / `gtk_video.py` | 668 / 605 | O que era comum já foi para `video_sync.py`; o resto é do toolkit. Rever depois dos itens acima. |
| `qt_playback.py`, `app.py`, `qt_catalog.py` | 602, 568, 560 | `app.py`: letras e relacionadas do player expandido para `window_chrome/expanded_player.py`. |
| `window_optional.py` | 508 | `_append_optional_preferences` (125 linhas) para `settings_page/`, como os outros grupos. |
| `window_lyrics.py` | 501 | A montagem da tela de letras (`_lyrics_surface`, `_lyrics_actions`) num módulo de widgets. |

### 2. Acoplamento entre os mixins da janela GTK

Os mixins de `HarmoniaWindow` ainda leem o estado uns dos outros com
`getattr(self, …)`: **59 vezes**, contra 54 na auditoria de 7 de outubro (as
fases somaram 5). Os que mais fazem isso são `gtk_media_variants.py` (14) e
`gtk_video.py` (9). Cada divisão do item 1 deve trocar esses acessos por
parâmetros ou objetos com interface clara, em vez de mover o problema.

### 3. Timer do vídeo sempre ligado

`gtk_video.py` agenda `_sync_gtk_video_transport` a cada 200 ms desde que a
janela abre e nunca o remove, mesmo sem vídeo. Deveria existir só enquanto o
modo vídeo está ativo.

### 4. Lacunas do frontend KDE

A lógica vale nos dois frontends, mas o QML ainda não tem:

- destaque palavra por palavra nas letras;
- selo "E" de conteúdo explícito (o dado já chega em `item_map`);
- botão "Copiar relatório" nos erros de reprodução;
- importar e remover perfis do AutoEQ;
- escolher o canal do YouTube Music;
- nível da normalização, transição entre faixas, "Velocidade muda o tom" e
  posição ao salvar numa playlist (o KDE usa o valor salvo pelo GTK).

### 5. Dívida de lint

Ainda isentos dos limites de tamanho no `pyproject.toml`: `downloads.py` e
`video.py` (complexidade e instruções), `window_detail.py`,
`window_library.py` e `window_optional.py` (instruções) e
`tools/gtk_smoke.py`. Com limites mais estritos, também passam do ponto
`validate` em `player_clients.py` e `theming.py` (15 caminhos) e as funções de
`video.py` que escolhem o vídeo e o formato.

### 6. Falta conferir de verdade

- Mica no Flatpak, com as permissões novas (precisa de um build e de um Linux).
- Escolha de canal com uma conta que tenha canal de marca.
- O frontend KDE inteiro desde a beta.3: só os testes em Python rodaram aqui;
  o QML depende do Kirigami, que não existe no Windows.

## Ordem sugerida

1. Timer do vídeo (pequeno, ganho imediato).
2. `qt_integrations.py` em cinco módulos (testável aqui, QML intacto).
3. `window_playback.py` e `window_library.py`, os maiores do GTK, junto com
   os `getattr(self, …)` que eles usam.
4. `innertube/client.py` em transporte, streams e biblioteca.
5. `window_detail.py`, `window_optional.py`, `window_lyrics.py` e `app.py`.
6. No Linux, com o app KDE aberto: `qt_backend.py` por página e as telas que
   faltam no QML.
