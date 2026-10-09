# Changelog

Todas as mudanças relevantes do projeto serão documentadas neste arquivo.

## Não publicado

- normalização de volume por faixa com a medição do YouTube Music, também nos downloads offline; antes ela só baixava todas as faixas 6 dB por igual;
- seletor "Nível do volume" (Suave, Padrão, Alto) para a normalização;
- transição entre faixas (crossfade) de 3 a 12 segundos, em Preferências > Áudio;
- letras palavra por palavra: a linha cantada acende a cada palavra, com as letras do novo provedor LyricsPlus;
- letras em LRC estendido não mostram mais as marcas de tempo das palavras no texto;
- sincronização da biblioteca mais segura: uma resposta vazia ou incompleta do YouTube não apaga mais itens, e curtidas, inscrições e playlists salvas não somem enquanto o YouTube demora a listá-las;
- colar um link do YouTube ou do YouTube Music na busca toca a música ou abre a playlist, o álbum ou o artista;
- opção "Velocidade muda o tom", para ouvir como um disco tocado mais rápido ou mais devagar.

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
