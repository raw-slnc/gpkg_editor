# -*- coding: utf-8 -*-


def classFactory(iface):
    from .gpkg_editor import GpkgEditor
    return GpkgEditor(iface)
