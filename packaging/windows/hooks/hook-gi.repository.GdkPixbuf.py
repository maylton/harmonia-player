# PyInstaller's GdkPixbuf hook bundles every gdk-pixbuf loader. MSYS2's HEIF and
# JPEG XL loaders drag in the x265, AOM, SVT-AV1 and rav1e encoders (about
# 55 MB) for formats YouTube Music artwork never uses, so this wraps the
# upstream hook and leaves those loaders out of the bundle and its cache.
# ruff: noqa

import importlib.util
import os

import PyInstaller.hooks

SKIPPED_LOADERS = ("heif", "jxl", "avif")

_path = os.path.join(os.path.dirname(PyInstaller.hooks.__file__), "hook-gi.repository.GdkPixbuf.py")
_spec = importlib.util.spec_from_file_location("_upstream_gdkpixbuf_hook", _path)
_upstream = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_upstream)
_collect_all_loaders = _upstream._collect_loaders


def _collect_loaders(libdir):
    return [
        path
        for path in _collect_all_loaders(libdir)
        if not any(name in os.path.basename(path).lower() for name in SKIPPED_LOADERS)
    ]


_upstream._collect_loaders = _collect_loaders
hook = _upstream.hook
