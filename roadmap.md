# Roadmap do Harmonia

Este documento registra o estado do port GTK4/libadwaita inspirado no Metrolist e nos fluxos do YouTube Music. Ele deve ser atualizado junto com cada entrega: um item só recebe `[x]` depois de implementação, testes e validação em runtime.

## Estado atual

O Harmonia já cobre o caminho principal de um cliente desktop: autenticação, sincronização, descoberta, reprodução, biblioteca, playlists, letras e integração com o ambiente Linux.

### Concluído

- [x] Login integrado com WebKitGTK e alternativa por cookie.
- [x] Autenticação `SAPISIDHASH` e bootstrap dinâmico do InnerTube.
- [x] Sincronização de músicas, álbuns, artistas e playlists com paginação.
- [x] Home personalizada e Explorar com cache SQLite.
- [x] Reprodução GStreamer, seek, fila, rádio, autoplay, shuffle e repeat.
- [x] MPRIS e teclas multimídia.
- [x] Player inferior persistente e player expandido.
- [x] Letras nativas com cache.
- [x] Curtir músicas, salvar coleções e inscrever-se em artistas.
- [x] Criar, renomear e excluir playlists; adicionar e remover faixas.
- [x] Interface GTK4/libadwaita responsiva para Home, biblioteca e detalhes.
- [x] Avatar da conta ativa no cabeçalho, com cache e fallback visual.

## Roadmap priorizado

### Marco 1 — Fundação de domínio e arquitetura

- [x] Criar modelos próprios para resultados e grupos de mídia, reduzindo o uso genérico de `LibraryItem`.
- [x] Extrair sincronização, busca e acesso à conta da janela GTK para uma camada de serviços.
- [x] Manter compatibilidade com o banco e a interface existentes.
- [x] Cobrir os novos modelos e serviços com testes.

Critério de conclusão: a janela não instancia diretamente o cliente InnerTube para sincronização ou busca, a UI continua funcional e a suíte completa passa.

### Marco 2 — Resolução e recuperação de streams

- [x] Adicionar perfis de cliente e fallbacks ordenados.
- [x] Implementar retry com backoff para falhas transitórias.
- [x] Armazenar streams resolvidos em cache respeitando expiração.
- [x] Retornar metadados estruturados do stream selecionado.
- [x] Renovar a URL automaticamente após erro do GStreamer.
- [x] Preservar a API de reprodução já utilizada pela interface.

Critério de conclusão: cache, expiração, fallback, retry e renovação possuem testes determinísticos, sem regressão no seek.

### Marco 3 — Busca universal

- [x] Pesquisar músicas, vídeos, álbuns, artistas e playlists.
- [x] Exibir resultados agrupados por categoria.
- [x] Implementar sugestões enquanto o usuário digita.
- [x] Suportar continuation/paginação por categoria.
- [x] Navegar ou reproduzir cada tipo de resultado corretamente.
- [x] Evitar que respostas antigas substituam uma consulta mais recente.

Critério de conclusão: busca e sugestões possuem testes de parser/serviço e a página é validada em runtime GTK.

### Marco 4 — Página completa de artista

- [x] Banner, imagem, descrição e inscrição.
- [x] Músicas populares, álbuns, singles e playlists.
- [x] Artistas relacionados e páginas “Mostrar tudo”.

### Marco 5 — Fila e relacionadas reais

- [x] Separar semanticamente fila e recomendações do endpoint `next`.
- [x] Tocar em seguida, adicionar ao fim, remover e reordenar.
- [x] Persistir fila, faixa, posição, repeat e shuffle.

### Marco 6 — Histórico

- [x] Exibir histórico da conta.
- [x] Registrar reproduções quando aplicável.
- [x] Remover itens e respeitar configurações de privacidade.

### Marco 7 — Downloads e modo offline

- [x] Gerenciador persistente de downloads e retomada.
- [x] Reprodução offline e validação periódica da conta.
- [x] Página de downloads e controle de armazenamento.

### Marco 8 — Biblioteca completa

- [x] Ordenação e filtros por origem.
- [x] Podcasts, uploads, downloads e arquivos locais.
- [x] Playlists locais, importação, exportação e reordenação.

### Marco 9 — Letras avançadas

- [x] Letras sincronizadas e busca ao clicar em uma linha.
- [x] Provedores alternativos, ajuste de tempo, tradução e cópia.

Critério de conclusão: timestamps LRC acompanham a posição real do GStreamer, cada linha realiza seek preciso, o cache preserva provedores e traduções, e o fluxo completo é validado com respostas reais e em runtime GTK.

### Marco 10 — Preferências e distribuição

- [x] Preferências de conta, qualidade, idioma, região, proxy e cache.
- [x] Equalizador, normalização, velocidade, tom, silêncio e temporizador.
- [x] Secret Service para credenciais.
- [x] Flatpak, ícone próprio, traduções, screenshots e metadados completos.
- [x] Testes de UI, player, login e sincronização assíncrona.

Critério de conclusão: preferências persistem no SQLite e são aplicadas ao InnerTube e ao GStreamer; a sessão migra para o chaveiro do desktop; build Meson, catálogo gettext, manifesto Flatpak e metadados passam nas validações disponíveis; UI e suíte automatizada não apresentam regressões.

### Gate visual antes do Marco 10

Auditoria detalhada: [`visual-audit.md`](visual-audit.md).

- [x] Inventariar botões, controles, cards, listas, estados e shells de página.
- [x] Classificar diferenças intencionais e inconsistências reais.
- [x] Unificar ações primárias, secundárias, selecionadas e destrutivas.
- [x] Unificar shell, largura, espaçamento e cabeçalhos responsivos.
- [x] Unificar cards entre Home, Biblioteca e artista; busca usa a linha de mídia compartilhada.
- [x] Unificar tokens de linhas, ações de hover e foco de teclado.
- [x] Validar matriz visual em 720, 1080, 1440 e 1920 px.

## Recursos opcionais após a paridade principal

- [ ] Estatísticas de reprodução e retrospectiva.
- [ ] Backup e restauração.
- [ ] Last.fm e Discord Rich Presence.
- [ ] Listen Together.
- [ ] Reconhecimento de música.
- [ ] Cast para dispositivos.

## Adaptações específicas para Linux

Recursos Android não devem ser copiados literalmente. Android Auto, Quick Settings, foreground service, widget móvel e alarmes devem ser traduzidos, quando úteis, para MPRIS, notificações com ações, atalhos globais, portais Flatpak e integração GNOME/KDE.

## Registro de validação

### 2026-08-12 — Marcos 1, 2 e 3

- [x] Compilação de `src` e `tests` com `compileall`.
- [x] Suíte automatizada: 28 testes aprovados.
- [x] Serviço testado com sincronização ordenada, falha parcial de categoria e ciclo da credencial.
- [x] Stream testado com seleção por bitrate, metadados, expiração, cache, renovação forçada, retry e fallback de cliente.
- [x] Busca real consultada nas cinco categorias sem erro parcial: 20 músicas, 20 vídeos, 20 álbuns, 13 artistas e 20 playlists.
- [x] Endpoint real de sugestões retornou seis sugestões para a consulta de validação.
- [x] Página GTK renderizada em runtime com cinco grupos e 93 itens reais.
- [x] Proteção contra resposta obsoleta validada: uma consulta anterior não substituiu os resultados atuais.

Observação: a suíte emite apenas um aviso de depreciação do PyGObject sobre `GLib.unix_signal_add_full`, proveniente da integração MPRIS já existente; não houve falha funcional.

### 2026-08-13 — Marcos 4, 5 e 6

- [x] Suíte automatizada ampliada para 33 testes, todos aprovados.
- [x] Página real de artista validada com cabeçalho, descrição, ouvintes, inscrição e oito prateleiras.
- [x] Cinco destinos reais “Mostrar tudo” validados; “Top músicas” expandiu de 5 para 100 faixas.
- [x] Fila e relacionadas mantidas como coleções independentes.
- [x] Tocar em seguida, adicionar ao fim, remover e reordenar validados em runtime GTK.
- [x] Restauração SQLite validada com fila, relacionadas, índice, posição, autoplay, repeat e shuffle.
- [x] Histórico real da conta carregou 199 itens; todos continham token nativo de remoção.
- [x] Histórico local registra após 30 segundos de reprodução e envia o tracking da conta quando disponível.
- [x] Pausar o histórico impede tanto o registro local quanto o tracking remoto iniciado pelo Harmonia.
- [x] Páginas de artista e histórico renderizadas em runtime sem erro de widget ou CSS.

### 2026-08-13 — Marcos 7 e 8

- [x] Suíte automatizada ampliada para 40 testes, todos aprovados.
- [x] Download persistente validado em blocos HTTP de até 1 MiB.
- [x] Retomada validada a partir do byte 345.678, sem reiniciar o arquivo parcial.
- [x] Reprodução local encaminhada diretamente ao GStreamer, sem passar pelo relay HTTP.
- [x] Acesso offline bloqueado para conta diferente ou validação expirada.
- [x] Validação inicial e periódica da conta implementada; validade offline de 30 dias.
- [x] Endpoint real de mídia respondeu HTTP 206 ao intervalo `bytes=0-1023`.
- [x] Página de downloads validada em runtime com progresso, pausa, retomada, reprodução e exclusão.
- [x] Biblioteca real sincronizada com playlists, músicas, álbuns, artistas, uploads e podcasts.
- [x] Cinco origens renderizadas em runtime: YouTube Music, uploads, downloads, local e podcasts.
- [x] Episódios em `musicMultiRowListItemRenderer` tratados como mídia reproduzível.
- [x] Arquivos e playlists locais validados em SQLite, incluindo reordenação persistente.
- [x] Importação M3U/M3U8/JSON e exportação M3U8/JSON implementadas com seletores GTK.
- [x] Layout compacto validado sem estouro horizontal do footer ou da biblioteca.

### 2026-08-13 — Marco 9

- [x] Suíte automatizada ampliada para 46 testes, todos aprovados.
- [x] Parser LRC validado com metadados, offset embutido, múltiplos timestamps e precisão até milissegundos.
- [x] Provedores YouTube Music e LRCLIB integrados com preferência persistente e fallback sequencial.
- [x] Consulta real do LRCLIB para “Instant Crush” retornou 83 linhas sincronizadas.
- [x] Destaque da linha atual conectado à posição real do GStreamer a cada 500 ms.
- [x] Clique em uma linha validado em runtime GTK com seek em microssegundos e compensação do offset configurado.
- [x] Ajuste persistente entre -5.000 e +5.000 ms, em passos de 250 ms, com ação para zerar.
- [x] Tradução para português validada no provedor alternativo, mantendo correspondência linha a linha e cache SQLite.
- [x] Cópia da letra original e traduzida integrada ao clipboard do desktop.
- [x] Player expandido e popover renderizaram simultaneamente 83 linhas, com o mesmo estado ativo e sem erro GTK/CSS.

### 2026-08-13 — Correção da navegação da biblioteca

- [x] Categorias abertas pela barra lateral reutilizam a página principal da Biblioteca.
- [x] Origem, ordenação e seletores de Álbuns, Artistas, Músicas e Playlists permanecem visíveis.
- [x] Troca Artistas → Álbuns validada em runtime GTK, preservando a categoria ativa e sem página intermediária.
- [x] Suíte automatizada ampliada para 48 testes, todos aprovados.

### 2026-08-13 — Padronização dos controles da Home

- [x] Setas de músicas, álbuns e playlists compartilham dimensão, contorno, hover, foco e estado desabilitado.
- [x] Alinhamento vertical impede que os botões circulares sejam deformados pela altura diferente dos títulos.
- [x] Prateleiras de faixas e coleções validadas em runtime com controles idênticos de 36 × 36 px.
- [x] Suíte automatizada mantida com 48 testes aprovados.

### 2026-08-13 — Consolidação do sistema visual

- [x] Primitives compartilhadas criadas para ações, ícones, shells, cabeçalhos e links de seção.
- [x] Quatro papéis de ação e três tamanhos de ícone substituem variantes locais equivalentes.
- [x] Um único construtor de card atende Home, Biblioteca e artista; busca compartilha o padrão de linha.
- [x] Linhas de mídia compartilham altura, raio, hover, foco e ações.
- [x] Cabeçalhos passaram a quebrar naturalmente com `Adw.WrapBox`.
- [x] Configuração visual local da janela reduzida de 214 para 107 ocorrências.
- [x] Matriz de runtime aprovada em 720, 1080, 1440 e 1920 px; maximizado validado em 3440 px.
- [x] Suíte automatizada ampliada para 51 testes, todos aprovados.

### 2026-08-13 — Marco 10

- [x] Página libadwaita de Preferências validada em runtime compacto com conta, streaming, proxy, cache e áudio.
- [x] Idioma, região, proxy e teto de bitrate propagados para cada cliente InnerTube; seleção de qualidade possui teste determinístico.
- [x] Cadeia GStreamer única validada com equalizador de 10 bandas, ReplayGain, velocidade, tom e remoção de silêncio, preservando o `playbin` e o seek.
- [x] Temporizador pausa a reprodução no prazo configurado e permanece ativo durante a navegação.
- [x] Sessão armazenada no Secret Service; migração do arquivo legado e fallback `0600` cobertos por testes isolados do chaveiro real.
- [x] Manifesto Flatpak com permissões mínimas de rede, áudio, Secret Service e MPRIS adicionado e validado sintaticamente.
- [x] Ícone escalável, desktop entry, AppStream, catálogos pt_BR/en e duas screenshots reais adicionados ao pacote.
- [x] Build, compilação e instalação Meson concluídos em `DESTDIR`, incluindo ícone, traduções e metadados.
- [x] `desktop-file-validate` e `appstreamcli validate --no-net` aprovados.
- [x] Suíte automatizada ampliada para 57 testes, todos aprovados; login, sincronização concorrente, player, preferências e credenciais estão cobertos.

### 2026-08-13 — Avatar da conta

- [x] Perfil da conta lido pelo endpoint autenticado `account/account_menu`.
- [x] Maior miniatura de `activeAccountHeaderRenderer.accountPhoto` utilizada no cabeçalho.
- [x] Avatar circular armazenado no cache de imagens e restaurado sem bloquear a abertura.
- [x] Glifo padrão preservado durante carregamento, falhas de rede e estado desconectado.
- [x] Troca e desconexão de conta removem imediatamente o avatar anterior.
- [x] Parser, serviço e estados GTK de avatar/fallback validados; suíte ampliada para 59 testes aprovados.

### 2026-08-13 — Refinamento das letras

- [x] Acompanhamento automático deixou de roubar o foco do teclado e de saltar instantaneamente.
- [x] Rolagem interpolada em 420 ms com desaceleração suave no popover do footer e player expandido.
- [x] Linha ativa posicionada a 42% da altura no popover e centralizada no player expandido.
- [x] Espaço de respiro permite centralizar também as primeiras e últimas linhas no modo expandido.
- [x] Destaque, opacidade e fundo transitam suavemente entre a linha anterior e a atual.
- [x] Posicionamento real validado em runtime GTK; suíte ampliada para 60 testes aprovados.
- [x] Linha sincronizada ativa usa somente a cor de acento, sem bloco de fundo ou mudança de geometria.
- [x] Reabrir o atalho do footer preserva seu scroller em vez de reconstruí-lo no início da letra.
- [x] Pedidos de rolagem obsoletos são invalidados antes da transição para a linha seguinte.
- [x] Regressão de callbacks atrasados coberta; suíte ampliada para 62 testes aprovados.
- [x] Leituras transitórias regressivas do GStreamer não podem mais levar o atalho de letras de volta ao topo.
- [x] Seek explícito continua permitindo navegar corretamente para linhas anteriores.
- [x] Falhas momentâneas de `query_position` preservam a última posição válida do player.
- [x] Coordenadas de linhas convertidas do viewport para o conteúdo impedem a oscilação do scroll a cada redesenho.

### 2026-08-13 — Capas em alta resolução

- [x] Variantes do CDN Google/YouTube redimensionadas conforme o contexto visual.
- [x] Player expandido e backdrop solicitam capas de até 1024 × 1024 px.
- [x] Cards e linhas mantêm variantes menores para equilibrar nitidez, rede e memória.
- [x] Cache diferencia cada resolução e evita reutilizar miniaturas de 120 px no player grande.
- [x] Requisições assíncronas antigas não podem mais sobrescrever a capa da faixa atual.
- [x] CDN e runtime GTK validados: amostra real subiu de 120 × 120 para 800 × 800 no player; suíte ampliada para 61 testes aprovados.

### 2026-08-13 — Opções de aparência

- [x] Grupo Aparência integrado às Preferências e persistido no SQLite.
- [x] Fundo ambiente opcional usa a capa atual em alta resolução com desfoque e camadas translúcidas.
- [x] Estilo GTK preserva integralmente o tema de ícones configurado no sistema.
- [x] Material Expressive fornece símbolos próprios para navegação e transporte.
- [x] Formas, contornos e feedback dos controles acompanham o pack selecionado.
- [x] Troca entre blur, GTK e Material validada em runtime sem reiniciar o aplicativo.
- [x] Fallback preserva símbolos sem variante própria; suíte completa mantida com 61 testes aprovados.
- [x] Material cobre todos os 48 nomes de ícones usados atualmente pelo aplicativo.
- [x] Tema selecionado é aplicado ao processo GTK inteiro, incluindo páginas, diálogos e popovers criados depois da troca.
- [x] SVGs provisórios substituídos por Material Symbols Rounded (Apache 2.0).
- [x] Material Symbols utiliza nomes simbólicos GTK e acompanha automaticamente as cores do tema e dos estados.
- [x] Opção iOS removida; preferências antigas migram com segurança para o tema GTK.
- [x] Play/pause Material usa fundo de acento e glifo `accent_fg_color` em ambos os players.
- [x] Migração do estilo removido coberta; suíte ampliada para 70 testes aprovados.
- [x] Avatar tratado como mídia circular e isolado da geometria de botões Material Expressive.
- [x] Estados hover, active, checked, focus e disabled auditados para botões comuns e `Gtk.MenuButton` no Material Expressive.
- [x] Menus de três pontos usam ações padronizadas com ícone e rótulo textual simultâneos.
- [x] Hover do `Gtk.MenuButton` isolado no botão interno para preservar o formato circular no tema GTK.
- [x] Ações sobre capas usam um contêiner central fixo, mantendo play e abertura de álbuns alinhados no centro da arte.
- [x] Assets são vendorizados para uso offline com manifesto reproduzível, proveniência e licenças instaladas no pacote.
- [x] Teste de cobertura impede novos ícones sem variante Material correspondente.
- [x] Build e instalação Meson validados com 48 SVGs e licenças.

### 2026-08-13 — Backdrop imersivo do player expandido

- [x] Capa atual preenche toda a superfície do player expandido com `ContentFit.COVER`.
- [x] Composição em duas camadas preserva as cores da arte mesmo com blur amplo de 72 px.
- [x] Véu em gradiente mantém títulos, controles e letras legíveis sem esconder os tons da capa.
- [x] Backdrop solicita a variante de alta resolução e acompanha cada troca de faixa.
- [x] Blur tonal ampliado oculta a composição original e preserva somente as massas de cor da capa.

## Riscos conhecidos

- InnerTube não é uma API pública e pode mudar sem aviso.
- Cipher, PoToken e URLs assinadas exigem uma estratégia de atualização independente da UI.
- Downloads precisam respeitar disponibilidade regional, expiração e benefícios da conta.
- O cache nunca deve ser apagado por uma sincronização parcial ou malsucedida.
- Sem um serviço Secret Service disponível, a credencial usa o fallback local com permissão `0600`.

## 2026-08-13 — Auditoria de release 0.1.0-beta.1

- [x] Ruff configurado como lint e formatter reproduzível; código, testes e ferramentas aprovados.
- [x] Imports mortos, método de UI obsoleto, estilos órfãos, chamada duplicada e arquivo PostScript acidental removidos.
- [x] Exceções opcionais silenciosas passaram a produzir diagnóstico de log sem interromper a interface.
- [x] MPRIS agora reporta e altera volume, shuffle e repetição reais e limpa metadados ao parar.
- [x] Instalação Meson exclui caches locais e inclui GPL integral e licenças de terceiros.
- [x] Desktop entry, AppStream offline, catálogos gettext, SVGs e manifesto YAML validados.
- [x] Suíte ampliada para 79 testes aprovados, incluindo integridade dos catálogos e assets do lançador.
- [x] Launcher instalado iniciado com diretórios XDG limpos e warnings GLib fatais, sem erros do aplicativo.
- [x] Workflow de CI adicionado para repetir lint, testes, metadados, traduções e build no GitHub Actions.
- [x] Repositório Git publicado em `maylton/harmonia-player`, com branch `main`, CI e tag `v0.1.0-beta.1`.
- [x] Executar o build Flatpak completo em ambiente com `flatpak-builder`.
- [ ] Decompor `HarmoniaWindow` por domínio após o beta; a classe concentra 210 métodos e uma refatoração ampla agora elevaria o risco de regressão.
- [x] Interface completa internacionalizada em português do Brasil e inglês, incluindo plurais, erros, diálogos, tooltips e metadados AppStream.
- [x] Catálogos `pt_BR` e `en` com 316 mensagens, cobertura integral e smoketest do pacote instalado nos dois idiomas.
- [x] Ícone final do lançador integrado ao tema `hicolor` em oito tamanhos, de 16 a 1024 px, e validado na instalação Meson.
- [x] Desktop Entry usa o caminho absoluto do prefixo instalado e anuncia App ID, nome, ícone e `StartupWMClass` consistentes ao GNOME Shell.
- [x] Build completo executado com `org.flatpak.Builder`, GNOME Platform/SDK 50 e exportação para repositório OSTree local.
- [x] Pacote instalado e iniciado na sessão GNOME real sem traceback ou erros GTK/GLib; imports GTK, libadwaita e GStreamer validados dentro do sandbox.
- [x] Bundle único `Harmonia-0.1.0-beta.1-x86_64.flatpak` gerado com catálogos `pt_BR` e `en` incorporados e reinstalado com sucesso.
- [x] Limite Flatpak de 512 px aplicado aos ícones exportados; a fonte de 1024 px permanece disponível no repositório.
- [x] O linter do repositório confirma a estrutura do pacote e registra somente os bloqueios já conhecidos para Flathub: App ID sem correspondência ao repositório e screenshots sem espelhamento pela infraestrutura Flathub.
