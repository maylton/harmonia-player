# GTK ↔ Qt parity audit — 2026-08-28

This pass reviewed the Qt/Kirigami presentation against the GTK/libadwaita frontend, with emphasis on icon ownership, settings, and the persistent player footer.

## Corrected in this pass

- Plasma/Breeze icons in the Qt sidebar use their native small geometry again instead of inheriting the larger Harmonia glyph box.
- Harmonia-owned monochrome glyphs can opt into a larger box independently; the liked-songs heart is the first explicit override.
- Settings section icons are no longer forced through a white monochrome mask. Native Plasma icon rendering is preserved inside the section badge.
- The Qt player footer now follows the GTK layout principle of stable side controls and a bounded center transport area.
- The seek bar has explicit minimum, preferred, and maximum widths.
- The volume slider has explicit minimum, preferred, and maximum widths instead of expanding with the window.
- Secondary footer controls collapse at 920 px, matching the GTK compact-footer threshold; volume controls require 1080 px so the footer does not become cramped.

## Functional parity checked

The Qt frontend already exposes the major GTK capabilities through the shared core: Home/Explore/search, all library origins, detail views, remote and local playlists, likes/subscriptions, downloads and offline playback, queue editing, shuffle/repeat/autoplay/radio, lyrics and translation, history/insights, audio processing, account/session handling, backup, MPRIS, Last.fm, Discord Rich Presence, Listen Together, music recognition, and UPnP/DLNA casting.

## Intentional toolkit difference

GTK exposes an “icon style” preference that can switch the GTK process between the system icon theme and Harmonia Material Expressive. The Qt frontend should not mirror this by replacing the process-wide `QIcon` theme: doing so would override Plasma/Breeze icons and recreate the visual ownership problem corrected here. Qt therefore keeps Plasma icons native while app-specific glyphs are styled locally.

## Small UX gaps still worth tracking

- GTK asks for destructive confirmation before restoring a backup; the Qt file picker currently restores immediately after selection.
- GTK exposes a dedicated “Copy” action for a Listen Together share URL; Qt exposes the URL in a selectable read-only field but has no one-click copy button.

These do not represent missing playback/catalog functionality, but they are useful interaction-parity follow-ups.
