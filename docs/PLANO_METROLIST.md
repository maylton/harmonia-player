# Plano: funcionalidades inspiradas no Metrolist

O [Metrolist](https://github.com/MetrolistGroup/Metrolist) é um cliente de
YouTube Music para Android (Kotlin, GPL-3.0). Este plano lista o que dele faz
sentido no Harmonia, por prioridade. Nada é copiado: as ideias são
reimplementadas em Python sobre a arquitetura do Harmonia.

Legenda: `[x]` feito · `[ ]` a fazer · `[-]` descartado (com o motivo).

## Regras para todas as fases

- **Windows e Linux.** Toda funcionalidade funciona nos dois sistemas, com o
  mesmo código. O que depende do sistema fica atrás de `host.py`.
- **Um módulo por funcionalidade.** A lógica fica em um módulo próprio,
  independente de GTK e Qt e testável sem interface. As janelas só ligam a
  funcionalidade à interface. Módulos novos devem ficar abaixo de ~300 linhas.
  Se um arquivo existente passar de ~500 linhas, a parte nova vai para um
  módulo novo, nunca para ele.
- **Persistência por domínio.** Dados novos ganham um repositório próprio em
  `storage/`, com a sua tabela, como os que já existem.
- **GTK e KDE (Qt).** A lógica compartilhada serve aos dois frontends. Quando
  só um ganha interface, o plano diz qual.
- **Interface em português**, com `_()` e as traduções em `po/` (pt_BR e en).
- **Testes** para cada módulo novo. Antes de cada commit rodam `ruff check`,
  `ruff format --check` e o `pytest`.
- **Traduções**: todo módulo com `_()` entra em `po/POTFILES`
  (`tests/test_potfiles.py` confere).

## Visão geral

| Fase | Funcionalidade | Prioridade | Estado |
|---|---|---|---|
| 1 | Normalização de volume por faixa | Alta | Feita |
| 2 | Crossfade entre faixas | Alta | Feita |
| 3 | Letras palavra por palavra e novos provedores | Alta | Feita (falta o KDE) |
| 4 | Sincronização segura da biblioteca | Alta | Feita |
| 5 | Pequenas melhorias de uso | Média | Feita (falta o visual no KDE) |
| 6 | Equalizador com perfis do AutoEQ | Média | Feita (falta importar no KDE) |
| 7 | Backup antes de atualizar e escolha de conta | Média | Feita (falta conferir canal de marca) |
| 8 | Confiabilidade do streaming e ajustes finos | Baixa | A fazer |

---

## Fase 1 — Normalização de volume por faixa (alta)

**Problema.** A opção "Normalização de volume" usava o `rgvolume` do
GStreamer, que depende de etiquetas ReplayGain. Os streams do YouTube não têm
essas etiquetas, então a opção só baixava todas as faixas 6 dB por igual.

**Solução.** O YouTube informa na resposta do player quanto cada faixa está
acima da sua referência (`playerConfig.audioConfig.loudnessDb`). O Harmonia
transforma esse valor em ganho para o `rgvolume`, guarda o valor para tocar
downloads offline e oferece um nível de volume.

- [x] `loudness.py`: lê o `loudnessDb` da resposta do player e calcula o ganho
  (só atenua, como o YouTube; o nível desloca tudo). Os clientes iOS e
  visionOS só informam o valor por formato ou como volume absoluto menos o
  alvo; os três formatos são lidos (conferido com respostas reais). Também alinha arquivos
  locais com etiquetas ReplayGain (referência −18 LUFS) aos streams (−14 LUFS).
- [x] `StreamInfo.loudness_db`, preenchido por `innertube/client.py`.
- [x] `storage/loudness.py`: repositório `LoudnessRecords`, tabela
  `track_loudness`, para os downloads offline.
- [x] `player.py`: `rglimiter` após o `rgvolume`, para nada saturar quando o
  nível aumenta o volume; `set_track_loudness()` por faixa.
- [x] GTK e KDE: o ganho da faixa é aplicado ao iniciar cada stream (online,
  offline e local).
- [x] Preferência `normalization_level` (Suave, Padrão, Alto), com seletor no
  GTK. O frontend KDE ainda não tem página de áudio; ele usa o valor salvo.
- [x] Testes: cálculo do ganho, leitura da resposta, repositório e regra das
  preferências.

## Fase 2 — Crossfade entre faixas (alta)

Uma faixa termina enquanto a próxima começa, com volumes cruzados.

- [x] `crossfade.py`: quando começar e a curva dos volumes (potência
  constante, sem queda no meio), sem GStreamer.
- [x] `crossfade_player.py`: `CrossfadingPlayer`, com a interface do
  `NativePlayer` e dois players por trás. Ele avisa o fim da faixa alguns
  segundos antes; a janela toca a próxima como sempre, que entra no segundo
  player enquanto a primeira some. Os dois tocam em saídas separadas, que o
  sistema mistura (WASAPI no Windows, PipeWire/PulseAudio no Linux). O
  segundo player só é criado no primeiro crossfade.
- [x] Só o player ativo fala com a janela: posição, duração, MPRIS e SMTC
  seguem a faixa nova; erros e fim da faixa que sai são ignorados.
- [x] Não cruzar quando: vídeo ativo, transmissão (Cast/UPnP ou a do KDE),
  faixa com menos de três vezes a duração do crossfade, ou a próxima só ficou
  pronta depois do fim. Trocar de faixa, pausar, buscar ou parar corta a
  faixa que sai.
- [x] Preferência "Transição entre faixas": desligada, 3, 5, 8 ou 12 s.
  Seletor no GTK; o KDE usa o valor salvo.
- [x] Velocidade, tom, equalizador e normalização valem nos dois players; a
  normalização da faixa nova não altera a que sai.
- [x] Testes da agenda, da troca de papéis e dos cortes, e um teste real com
  GStreamer (saída muda) conferindo o fim antecipado e a rampa dos volumes.

## Fase 3 — Letras palavra por palavra e novos provedores (alta)

- [x] `models.LyricWord` e `LyricLine.words`: tempo de cada palavra.
- [x] `lrc.py` (parser de LRC, saído de `lyrics.py`) entende as marcas de
  palavra do LRC estendido (`<mm:ss.xx>`), que antes apareciam no texto.
  `lyrics_words.py` tem o que é comum: palavras cantadas e o markup.
- [x] `lyrics_providers/`, um módulo por provedor: `lrclib.py` (movido),
  `lyricsplus.py` (novo) e `common.py`.
  - LyricsPlus: o espelho `binimum` traz as letras do Apple Music com tempo por
    palavra (inclusive músicas brasileiras); o `prjktla` traz as do Musixmatch
    por linha. Conferido com respostas reais.
  - [-] Better Lyrics: a API passou a exigir chave para o que não está em cache.
  - [-] KuGou: só por linha e pouco útil para músicas ocidentais e brasileiras.
- [x] Ordem automática: LyricsPlus por palavra, LRCLIB, LyricsPlus por linha,
  YouTube Music. A fonte "LyricsPlus" pode ser escolhida na tela de letras.
- [x] Destaque da palavra atual no GTK (`gtk_lyric_words.py`): a linha ativa
  acende palavra por palavra, com um timer próprio de 60 ms que só repinta
  quando outra palavra começa e a letra está visível.
- [ ] Destaque por palavra no KDE (QML): as palavras já chegam no documento;
  falta a tela, a testar no Linux.
- [x] Cache: as palavras ficam no JSON de `lyrics_documents`, e a escolha
  automática do cache prefere letras com tempo por palavra. A tradução
  preserva as palavras.
- [x] Testes do parser, do LyricsPlus (espelhos, falhas, vocais de fundo), do
  resolvedor, do cache e da tradução.

## Fase 4 — Sincronização segura da biblioteca (alta)

Antes, cada categoria vinda do YouTube substituía o cache inteiro: uma lista
vazia por erro apagava a biblioteca local, uma lista cortada no limite de
páginas perdia o resto, e uma curtida recém-feita sumia na sincronização que
vinha logo depois, porque o YouTube demora a listá-la.

- [x] `library_sync.py` (sem rede nem interface): junta a lista do YouTube
  com o cache.
- [x] Remoções feitas no YouTube são aplicadas quando a lista está completa
  (`InnerTubeClient.library_listing` informa se leu todas as páginas; a
  sincronização lê até 40).
- [x] Lista incompleta só acrescenta; lista vazia sobre um cache com itens é
  tratada como resposta com erro.
- [x] Mudanças feitas no Harmonia (curtir, inscrever-se, salvar álbum ou
  playlist, excluir playlist) ficam em `storage/library_changes.py` e valem
  por cima da lista até o YouTube mostrá-las, por até 15 minutos. Os dois
  frontends as registram pelo serviço (`set_song_liked` e afins).
- [x] Testes com listas completas, incompletas e vazias, mudanças pendentes,
  a sincronização do serviço e o repositório.

## Fase 5 — Pequenas melhorias de uso (média)

Cada item é independente e pode virar um commit separado.

- [x] **Colar link na busca** (`youtube_links.py`): links de música, vídeo,
  Shorts, youtu.be, playlist, álbum e canal de artista. Música e vídeo tocam
  direto (`InnerTubeClient.watch_item`, que funciona até sem login); os
  outros abrem a página. GTK e KDE.
- [x] **Posição ao adicionar à playlist** (`playlist_position.py`):
  Preferências > Biblioteca > "Ao salvar numa playlist", no fim ou no início.
  No YouTube, a faixa é adicionada e depois movida para antes da primeira
  (`ACTION_MOVE_VIDEO_BEFORE`, com o `setVideoId` que a edição devolve); nas
  playlists locais, entra na frente. GTK e KDE (no KDE, pelo valor salvo).
- [x] **Velocidade e tom juntos** (`playback_speed.py`): "Velocidade muda o
  tom" usa o `rate` do elemento `pitch`, como um disco mais rápido; o seletor
  de tom fica desativado. Posição e duração seguem iguais às do modo
  separado (conferido com GStreamer).
- [x] **Selo de conteúdo explícito**: `LibraryItem.explicit`, lido do
  `badges` da InnerTube (listas, buscas e fila), guardado em todas as tabelas
  de itens (coluna nova, com migração) e mostrado como "E" nas faixas do GTK.
  O KDE já recebe o dado (`explicit` no `item_map`); falta o selo no QML.
- [x] **Relatório de erro de reprodução** (`playback_report.py`): texto com
  as versões do Harmonia, do sistema, do Python e do GStreamer, a faixa e o
  erro (que já lista a falha de cada cliente da InnerTube). Links de stream
  perdem os parâmetros, que levam o IP do usuário. No GTK, a mensagem de
  erro ganha o botão "Copiar relatório"; no KDE, falta o botão no QML.

## Fase 6 — Equalizador com perfis do AutoEQ (média)

- [x] `autoeq.py`: lê ParametricEQ, FixedBandEQ e GraphicEQ do AutoEQ e
  converte para as 10 bandas do `equalizer-10bands` (30 Hz a 15 kHz,
  conferidas no GStreamer): a resposta dos filtros (biquads do RBJ Audio EQ
  Cookbook, a 48 kHz) ou da curva gráfica é calculada como média dentro de
  cada banda e somada ao pré-amplificador, para não saturar.
- [x] `equalizer.py`: predefinições e perfis; a preferência guarda
  `autoeq:<nome>`, e os dois frontends passam ao player os ganhos das bandas.
- [x] Perfis salvos em `storage/eq_profiles.py` e listados junto às
  predefinições.
- [x] GTK: Preferências > Áudio > "Perfis do AutoEQ", com Importar (seletor de
  arquivos) e Remover (`settings_page/equalizer.py`). No KDE o perfil
  escolhido vale, mas falta o botão de importar no QML.
- [x] Testes com os filtros do cookbook e com o HD 600; conferido com os
  arquivos reais do AutoEQ: ParametricEQ e GraphicEQ do mesmo fone dão bandas
  com até ~1 dB de diferença.

## Fase 7 — Backup antes de atualizar e escolha de conta (média)

- [x] Backup automático do banco quando a versão do app muda
  (`auto_backup.py`): o arquivo é copiado antes de o `Storage` abri-lo, ainda
  como a versão anterior o deixou, só se houver biblioteca, histórico ou
  playlists locais; os 3 últimos ficam em `backups/`, junto ao banco, e se
  restauram por Preferências > Dados e backup. Uma falha no backup não impede
  o app de abrir. Restaurar um backup antigo agora recria as tabelas novas
  (`Storage.initialize_tables`).
- [x] Escolha do canal (pessoal ou de marca) em Preferências > Conta, quando
  o login tem mais de um (`accounts.py`, `settings_page/identity.py`). A lista
  vem de `account/accounts_list` (o seletor de canais, como no Metrolist), só
  com os canais do mesmo login Google; o escolhido vai como
  `onBehalfOfUser` em todas as requisições. Trocar de canal apaga a
  biblioteca em cache e as mudanças pendentes do canal anterior e sincroniza;
  um novo login ou sair volta ao canal do próprio login. No KDE, o canal
  escolhido vale, mas falta o seletor no QML.
  - [ ] Conferir com uma conta real que tenha canal de marca.

## Fase 8 — Confiabilidade do streaming e ajustes finos (baixa)

- [ ] Configuração dos clientes do player atualizável por um arquivo publicado
  no repositório, para corrigir mudanças do YouTube sem nova versão.
- [ ] Plano B de streaming: decodificação da assinatura e PoToken, se os
  clientes atuais deixarem de entregar URLs diretas.
- [ ] Opção para ocultar as playlists automáticas de "mais tocadas".

## Descartado

- [-] Android Auto, widget da tela inicial, escala para tablet e ícone
  dinâmico: são do Android e não se aplicam ao desktop.
