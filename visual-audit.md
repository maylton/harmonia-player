# Auditoria visual do Harmonia

Data: 13 de agosto de 2026

## Objetivo e escopo

Esta auditoria compara Home, Biblioteca, busca, artista, histórico, downloads, playlists locais, detalhes de álbuns/playlists, footer e player expandido. Foram considerados os conceitos visuais fornecidos, as capturas de runtime já validadas, a hierarquia GTK e todas as regras de `style.css`.

O objetivo não é tornar todas as telas idênticas. O player expandido pode ser imersivo, detalhes podem ter um hero maior e faixas podem usar linhas em vez de cards. A consistência necessária está nos componentes equivalentes: uma ação primária deve continuar parecendo primária, um botão de ícone deve manter sua geometria e um card de álbum deve responder da mesma maneira onde aparecer.

## Resumo executivo

O app já possui uma identidade reconhecível: fundo escuro, tipografia forte, capas quadradas, artistas circulares, azul como acento e footer persistente. Home, detalhes e player expandido são as superfícies visualmente mais maduras.

O principal problema é que a identidade ainda não foi transformada em um sistema de componentes. O inventário encontrou mais de 200 pontos de criação/configuração de controles. No CSS há 14 valores diferentes de raio, 17 de altura mínima, 46 combinações de padding e 30 fundos. Parte dessa variedade é legítima, mas hoje decisões equivalentes são repetidas localmente e acabam divergindo.

Antes do Marco 10, a recomendação é executar uma rodada curta de consolidação em quatro blocos: ações, shell de página, cards e listas.

## O que já está consistente

- Navegação lateral, cabeçalho global e busca formam um shell reconhecível.
- Capas seguem o padrão quadrado; artistas usam recorte circular.
- O footer é persistente e o player expandido é uma variação imersiva claramente intencional.
- O detalhe de álbuns e playlists possui hierarquia interna coerente entre hero, ações e tracklist.
- As setas das prateleiras agora compartilham o mesmo controle circular de 36 × 36 px.
- Títulos, subtítulos e textos secundários usam uma hierarquia cromática compreensível.

## Inconsistências encontradas

### Prioridade alta — corrigir antes do Marco 10

#### 1. Ações primárias possuem três identidades

- Artista, playlist local e boas-vindas usam pílula azul via `suggested-action`.
- Álbuns e playlists remotas usam um botão branco circular de play.
- Algumas páginas usam pílulas escuras/neutras como principal ação do cabeçalho.

Isso enfraquece a leitura de prioridade. Deve existir um padrão semântico:

- `primary-action`: ação principal da página, branca no contexto de mídia escuro.
- `accent-action`: confirmação, conexão ou ativação persistente, azul.
- `secondary-action`: pílula neutra.
- `destructive-action`: vermelho apenas para remoção irreversível.

O player pode manter o play branco como exceção de transporte, mas páginas de artista, coleção remota e playlist local devem usar a mesma linguagem de ação principal.

#### 2. Shell, largura e espaçamento mudam por página

- Home usa clamp de 1480 px.
- Artista usa 1280 px.
- Histórico e downloads usam 980 px.
- Biblioteca não possui o mesmo clamp estrutural.
- Paddings superiores variam entre 28, 36, 48 e 52 px sem uma escala explícita.

Definir dois shells:

- `content-page`: máximo de 1280 px, margens 32 px e espaçamento vertical de 24/32 px.
- `reading-page`: máximo de 980 px para histórico, downloads, letras e configurações.

Detalhes com backdrop continuam usando superfície própria, mas o conteúdo interno deve alinhar à mesma grade de 32 px.

#### 3. O mesmo card muda de comportamento conforme a página

- Na Home, card escurece apenas a capa e mostra ação central.
- Na Biblioteca, o card inteiro muda de opacidade e não mostra a mesma ação.
- Em busca e seções de artista, há outras combinações de tamanho e ação.
- Home usa card de 168 px; Biblioteca usa 140 px sem um token de densidade declarado.

Criar um único `MediaCard` com variantes de densidade (`compact` 140 e `regular` 168), mantendo os mesmos raio, hover, foco, título, subtítulo e overlay. O tipo do item pode mudar o ícone — play para mídia reproduzível e seta para navegação — sem mudar o componente.

#### 4. Listas equivalentes usam três linguagens

- Home e detalhe usam linhas customizadas com hover e ações reveladas.
- Biblioteca usa `Adw.ActionRow` dentro de `boxed-list`.
- Histórico e downloads usam `Adw.PreferencesGroup` e ações sempre visíveis.

Não é necessário usar um único widget, mas devem compartilhar tokens: altura de 64/72 px, capa de 48 px, raio de 8 px, área de ação de 36 px, hover, seleção, foco e cor de faixa ativa. Ações secundárias devem surgir no hover quando não forem essenciais.

### Prioridade média

#### 5. Geometria dos botões de ícone não segue uma escala

Há botões de 34, 36, 38, 44, 48, 50 e 54 px fora dos controles principais de transporte. Adotar apenas:

- `icon-button-sm`: 34/36 px para linhas e toolbars.
- `icon-button-md`: 44 px para ações comuns.
- `icon-button-lg`: 50 px para heros e detalhes.
- Transporte do player permanece uma família separada.

`Gtk.MenuButton` deve usar o mesmo helper/CSS do `Gtk.Button`, evitando novamente contorno duplo e hover quadrado.

#### 6. Estados selecionados usam o acento com significados diferentes

Azul aparece para item salvo, inscrição já ativa, autoplay, shuffle/repeat e ações sugeridas. Definir:

- azul preenchido para ação primária ou ativação persistente;
- ícone azul sem fundo para favorito/salvo;
- fundo azul sutil para linha/faixa selecionada;
- controles de transporte ativos com ícone azul, sem parecer botão de confirmação.

#### 7. Ações de seção não têm nomenclatura nem forma única

Existem “Ver tudo” como botão flat, “Mostrar tudo” como flat + pill e “Mais …” como pill. Padronizar em `section-link`: texto “Mostrar tudo”, flat, altura de 36 px e seta opcional.

#### 8. Ações destrutivas nem sempre parecem destrutivas

Excluir playlist no menu remoto usa `destructive-action`, mas excluir playlist local e alguns lixos de cabeçalho permanecem circulares neutros. Em listas, lixo neutro pode ser aceitável; em ações de página ou confirmação deve usar semântica destrutiva consistente e diálogo de confirmação.

#### 9. Cabeçalhos ainda não respondem igualmente em modo compacto

Biblioteca possui breakpoint próprio. Artista, histórico, downloads, playlist local e barra de ferramentas de letras usam caixas horizontais que podem comprimir ou transbordar. Todos os cabeçalhos de página devem migrar para `Adw.WrapBox` ou um breakpoint compartilhado.

### Prioridade baixa

#### 10. Tokens de cor e tipografia estão codificados localmente

Há repetição de `#242424`, `#1e1e1e`, `#3a3a3a`, `#4a4a4a`, branco e cinzas em muitos seletores. Consolidar em variáveis nomeadas do app e, quando possível, tokens do Libadwaita. Isso também prepara contraste elevado e uma eventual preferência de tema.

#### 11. Loading, vazio e erro não seguem sempre a mesma composição

Algumas páginas usam `Adw.StatusPage`, outras spinner isolado e outras substituem toda a página. Criar três estados reutilizáveis: carregando, vazio e erro recuperável, sempre com ícone, título, descrição e ação opcional.

#### 12. Foco de teclado é explícito em poucos controles customizados

As novas setas de prateleira possuem foco visível, mas cards, linhas customizadas, ações reveladas no hover e alguns overlays dependem do estilo padrão ou de gestos sem equivalente claro de teclado. A consolidação deve incluir foco, `can-target`, tooltip e área mínima de clique.

## Padrão proposto

| Família | Variantes | Regra |
|---|---|---|
| Ação com texto | primary, accent, secondary, destructive | Mesma altura de 44 px e raio de pílula |
| Botão de ícone | sm 36, md 44, lg 50 | Sempre circular; `MenuButton` e `Button` idênticos |
| Link de seção | section-link | Flat, 36 px, “Mostrar tudo” |
| Card de mídia | compact 140, regular 168 | Mesmo hover, overlay, foco e tipografia |
| Linha de mídia | compact 64, detailed 72 | Capa 48, ações 36, raio 8 |
| Shell de página | content 1280, reading 980 | Margens 32 e breakpoints compartilhados |
| Estado | loading, empty, error | `Adw.StatusPage` com ação opcional |

## Ordem recomendada de implementação

1. Criar classes/helpers compartilhados de ações e botões de ícone; migrar cabeçalhos, detalhes, artista e playlist local.
2. Criar shell de página e cabeçalho responsivo; migrar Biblioteca, Histórico, Downloads e Artista.
3. Unificar `MediaCard` em Home, Biblioteca, busca e artista.
4. Unificar tokens das linhas de mídia e ações de hover.
5. Padronizar links de seção, estados vazios/loading/erro e semântica destrutiva.
6. Executar matriz visual em 720, 1080, 1440 e 1920 px, com navegação por teclado.

## Critério de aceite visual

- Componentes equivalentes possuem a mesma geometria, cor, hover, foco, estado ativo e estado desabilitado.
- Nenhum cabeçalho ou grupo de ações transborda a 720 px.
- A mesma mídia mantém card e comportamento equivalentes entre Home, Biblioteca, busca e artista.
- Ações primária, secundária, selecionada e destrutiva são reconhecíveis sem depender do texto.
- Player expandido continua sendo uma variação imersiva da mesma identidade, não um sistema paralelo.
- A matriz de páginas é revisada nas quatro larguras e a suíte automatizada permanece aprovada.

## Implementação concluída

A padronização foi aplicada em 13 de agosto de 2026:

- `src/harmonia/ui.py` centraliza quatro papéis de ação, três tamanhos de botão de ícone, dois shells, cabeçalhos responsivos e links de seção.
- Home, Biblioteca e seções de artista usam o mesmo construtor de `MediaCard`, com densidades de 140 e 168 px; a busca mantém a apresentação em linhas e reutiliza o padrão `media-row`.
- Home, Explorar e Biblioteca usam o shell de conteúdo; Histórico, Downloads, busca e playlists locais usam o shell de leitura.
- Cabeçalhos usam `Adw.WrapBox`, eliminando breakpoints locais e mantendo as ações acessíveis em modo compacto.
- Artista, detalhes remotos e playlists locais usam a mesma semântica: play branco, ação de confirmação azul, secundárias neutras e destrutivas vermelhas.
- Botões comuns usam escalas de 36, 44 e 50 px; transporte expandido permanece uma família intencionalmente separada.
- `Gtk.Button` e `Gtk.MenuButton` compartilham geometria e hover, sem contorno duplicado.
- Linhas da Home, Biblioteca, busca, histórico, downloads, detalhes e playlists locais compartilham altura, raio, hover e ações de 36 px.
- “Ver tudo”, “Mostrar tudo” e “Mais…” convergiram para o link de seção “Mostrar tudo” ou para a ação explícita “Carregar mais”.
- Exclusão de playlist local ganhou semântica destrutiva e confirmação antes da remoção.
- A configuração visual local em `app.py` caiu de 214 para 107 ocorrências; as exceções restantes são widgets ou controles especializados.

Validação:

- 51 testes automatizados aprovados.
- Home, Biblioteca, playlist local e detalhes validados em 720, 1080, 1440 e 1920 px.
- Modo maximizado validado em 3440 × 1408 px.
- Nenhum `Gtk-CRITICAL`, warning do Libadwaita ou overflow nos cabeçalhos compartilhados.
