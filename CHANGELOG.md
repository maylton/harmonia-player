# Changelog

Todas as mudanças relevantes do projeto serão documentadas neste arquivo.

## Não lançado

- modo tela cheia no player expandido, como no YouTube Music: botão no canto do cabeçalho, ou as teclas F e F11; a capa e o vídeo crescem com a tela, a coluna "A seguir" sai, e o cabeçalho, os controles e o cursor somem com o mouse parado e voltam quando ele se mexe. Esc sai da tela cheia;
- corrigido: com "Pular silêncio" ligado, o fim das músicas tocava de novo por um ou dois segundos antes de avançar: o silêncio removido atrasava a posição, a faixa parecia terminar antes da hora e era retomada ali;
- corrigido: o volume não era guardado entre as sessões; no GTK, ele também começava em 100% com a barra mostrando 80%;
- corrigido: com o desfoque do compositor no Hyprland, o Harmonia gastava até um núcleo inteiro da CPU enquanto tocava, porque o GTK redesenhava a janela inteira a cada quadro das animações; agora o pedido de desfoque fica numa camada vazia atrás do conteúdo, e o consumo caiu para cerca de um quarto;

## 0.1.0-beta.6 — 2026-10-22

- tema Harmonia: o antigo tema Windows 11 virou o tema padrão do Harmonia, com o Mica automático atrás da janela; o Acrílico e o menu "Efeito de fundo" saíram, e no Linux fica só a opção "Desfoque do compositor" (KWin ou Blur my Shell; desligada ou sem eles, o Mica usa o papel de parede). O tema escuro antigo deu lugar a ele;
- novo tema Material Design 3, inspirado no player do dashboard do Caelestia Shell: barra de progresso ondulada, capa em forma de biscoito que gira enquanto a música toca, botões que mudam de forma e empurram os vizinhos ao serem pressionados, e a janela emoldurada como a borda do Caelestia. Segue as cores do Caelestia Shell (o esquema muda junto com o papel de parede) ou a cor de destaque do sistema;
- letras palavra por palavra no estilo do Apple Music, como no Metrolist: cada palavra se preenche aos poucos com uma borda suave, sobe um pouco, pulsa ao começar e as notas longas brilham; as linhas se apagam conforme se afastam da cantada;
- romaji nas letras em japonês, lido no próprio aparelho (fugashi e UniDic Lite, incluídos no Flatpak), em Preferências > Biblioteca;
- novos pacotes de ícones: Framework7 (estilo iOS), Breeze e Papirus;
- player expandido com a capa acima dos controles, em todos os temas, e a coluna "A seguir" ao lado, como no YouTube Music: a faixa atual, as próximas da fila e as da reprodução automática, até 25 faixas; a aba "Relacionadas" deu lugar a ela;
- os fundos de capa desfocada saíram (o fundo ambiente, o do player expandido e os dos cabeçalhos de álbum e artista), nos dois frontends; no lugar, "Desfoque do compositor" vale para todos os temas no Linux: as superfícies ficam translúcidas sobre o desfoque do KWin ou do Blur my Shell e, sem eles, sobre o papel de parede desfocado pelo próprio Harmonia, que agora também acha o papel de parede do Caelestia Shell;
- instalador: no Arch Linux e derivados, o Harmonia é compilado com o Meson no lugar do Flatpak, com as dependências instaladas pelo pacman e o romaji incluído;
- corrigido: o seletor Música/Vídeo do player expandido tinha sumido;
- corrigido: o desfoque do KWin atrás da janela não funcionava, porque o GTK atual não entrega ao Python a conexão Wayland nem a superfície da janela; o Harmonia agora as pede direto à biblioteca do GTK;
- corrigido: no Hyprland, o build nativo (GTK 4.24) não tinha desfoque atrás da janela, porque esse GTK registra a janela no protocolo de desfoque do Wayland sem dizer que área desfocar; o Harmonia agora pede o desfoque com `backdrop-filter`;
- corrigido: depois de abrir o player expandido pela primeira vez, o Harmonia ocupava um núcleo inteiro da CPU até ser fechado, porque um callback do laço principal se repetia para sempre; e a página inicial não pede mais um quadro novo a cada atualização da tela;
- o player expandido do tema Material Design 3 fica translúcido sobre o desfoque do compositor, como o resto da janela;
- corrigido: as capas da página inicial ficavam deslocadas no Linux, porque o título do card media a largura em letras da fonte;
- corrigido: o selo "E" de conteúdo explícito ficava à esquerda da capa nos downloads, no histórico e na busca; agora fica ao lado do título, e aparece também nas playlists locais.

## 0.1.0-beta.5 — 2026-10-13

- músicas com restrição de idade tocam a gravação original, explícita, com a sua conta, como no Metrolist e no yt-dlp: o Harmonia decifra o player do YouTube com o JavaScriptCore no Linux e com o QuickJS incluído no Windows e no Flatpak do KDE (no áudio e no vídeo); a beta.4 tocava outra publicação da mesma música no lugar, o que podia ser uma versão sem o conteúdo explícito;
- Mica no Linux com a cor certa: o papel de parede que muda ao longo do dia (GNOME) mostra a imagem do horário e acompanha a troca; a variante clara ou escura é a que o sistema está mostrando, mesmo com o Harmonia em outro tema, e muda junto quando o sistema alterna; no Plasma vale o plugin de papel de parede ativo; as Preferências dizem de qual papel de parede o Mica foi feito.

## 0.1.0-beta.4 — 2026-10-09

- músicas com restrição de idade tocam: quando o YouTube bloqueia a faixa, o Harmonia toca outra publicação da mesma gravação (mesmo título, artistas e duração; nunca ao vivo, cover ou remix) e avisa; sem nenhuma, diz que a faixa tem restrição de idade em vez de "o stream falhou";
- selo "E" de conteúdo explícito, como no YouTube Music: nas faixas dos álbuns e playlists, na busca, nas listas de músicas, no histórico, nos downloads, na fila, nos cards, no cabeçalho do álbum, na barra do player e no player expandido, nos frontends GTK e KDE;
- o vídeo deixa de consumir processamento quando não está aberto;
- reorganização interna: a janela GTK, o cliente do YouTube Music e as integrações do KDE divididos em módulos menores;
- normalização de volume por faixa com a medição do YouTube Music, também nos downloads offline; antes ela só baixava todas as faixas 6 dB por igual;
- seletor "Nível do volume" (Suave, Padrão, Alto) para a normalização;
- transição entre faixas (crossfade) de 3 a 12 segundos, em Preferências > Áudio;
- letras palavra por palavra: a linha cantada acende a cada palavra, com as letras do novo provedor LyricsPlus;
- letras em LRC estendido não mostram mais as marcas de tempo das palavras no texto;
- sincronização da biblioteca mais segura: uma resposta vazia ou incompleta do YouTube não apaga mais itens, e curtidas, inscrições e playlists salvas não somem enquanto o YouTube demora a listá-las;
- colar um link do YouTube ou do YouTube Music na busca toca a música ou abre a playlist, o álbum ou o artista;
- opção "Velocidade muda o tom", para ouvir como um disco tocado mais rápido ou mais devagar;
- erros de reprodução com o botão "Copiar relatório", para anexar a um relato de problema;
- Preferências > Biblioteca: escolha se a música salva numa playlist entra no fim ou no início;
- Mica no Linux mais robusto: tenta também a variante clara do papel de parede, abre formatos que o GdkPixbuf não conhece pelo decodificador do GTK, usa o papel de parede padrão do Plasma quando nenhum foi escolhido, e as Preferências dizem por que o Mica não aparece quando não há como mostrá-lo. Os pacotes recomendam o suporte a JPEG XL, WebP e AVIF;
- corrigido: o vídeo de algumas faixas dizia que a sessão tinha expirado mesmo com a conta funcionando;
- streaming mais resistente: os perfis de cliente do YouTube podem ser atualizados pelo repositório sem nova versão, e o cliente que funcionou por último é tentado primeiro;
- escolha do canal do YouTube Music (pessoal ou de marca) em Preferências > Conta, quando o login tem mais de um;
- backup automático do banco de dados quando o Harmonia é atualizado (os três últimos ficam guardados), e restaurar um backup de uma versão antiga recria as tabelas novas;
- perfis do AutoEQ no equalizador: importe o ParametricEQ, o FixedBandEQ ou o GraphicEQ do seu fone em Preferências > Áudio, e ele vira uma opção do equalizador;
- Mica também no Flatpak: o app lê, só para leitura, a configuração do papel de parede (dconf do GNOME ou configuração do Plasma), as imagens do sistema e as pastas de papéis de parede do usuário; quando a imagem está em outra pasta, as Preferências mostram o comando `flatpak override` que a libera.

## 0.1.0-beta.3 — 2026-10-09

- tema Windows 11 disponível também no Linux, com a cor de destaque do GNOME;
- Mica e Acrílico no Linux: o Mica usa o papel de parede desfocado do GNOME ou do Plasma; o Acrílico deixa a janela translúcida para o desfoque do compositor (Blur my Shell no GNOME, Force Blur no KDE);
- novo estilo de ícones "Fluent — ícones do Windows 11" no Linux;
- a aba ativa do player expandido mostra o indicador Fluent em vez de um fundo preenchido.

## 0.1.0-beta.2 — 2026-10-08

- pacotes `.deb` (Debian/Ubuntu) e `.rpm` (Fedora/openSUSE), além do Flatpak;
- `install.sh` baixa o release mais recente e escolhe o formato pelo sistema: `.deb` ou `.rpm` quando a libadwaita da distribuição é 1.7 ou mais nova, Flatpak nas demais, ou build com Meson (`--method source`);
- versão para Windows (instalador Inno Setup), com tema Windows 11, Mica, ícones Fluent e login pelo WebView2;
- releases publicados automaticamente a cada tag, com checksums SHA-256;
- menus de item no estilo do YouTube Music, com "Tocar a seguir" e "Adicionar à fila";
- player expandido mais leve e opção de mostrar o efeito de fundo do Windows no lugar da capa;
- reorganização interna do código em módulos menores, sem mudanças de comportamento.

## 0.1.0-beta.1 — 2026-08-13

Primeira versão beta pública.

- login integrado e autenticação manual alternativa;
- biblioteca, Home, Explorar, busca, histórico, downloads e arquivos locais;
- reprodução GStreamer, fila, rádio, letras sincronizadas e player expandido;
- integração MPRIS com transporte, posição, volume, shuffle e repetição;
- ações de biblioteca e gerenciamento de playlists;
- temas de ícones GTK e Material Expressive, com fundo ambiente opcional;
- novo ícone do aplicativo com variantes otimizadas para launchers Linux;
- integração do lançador com nome, ícone e agrupamento corretos no GNOME Shell;
- cache SQLite, Secret Service, interface completa em português e inglês e empacotamento Meson/Flatpak.

### Limitações conhecidas

- a integração depende da API InnerTube não pública;
- o manifesto Flatpak foi validado estruturalmente, mas o build completo requer `flatpak-builder`.
