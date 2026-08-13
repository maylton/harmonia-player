# Changelog

Todas as mudanças relevantes do projeto serão documentadas neste arquivo.

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
