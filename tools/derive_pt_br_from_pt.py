#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Derive pt_BR translations from pt with small locale-specific wording changes."""

from __future__ import annotations

from defusedxml import ElementTree as ET


REPLACEMENTS = [
    ("feição", "feição"),
    ("ficheiro", "arquivo"),
    ("área de transferência", "área de transferência"),
    ("Continuar?", "Deseja continuar?"),
    ("Camada", "Camada"),
]


def main():
    src_path = "i18n/gpkg_editor_pt.ts"
    dst_path = "i18n/gpkg_editor_pt_BR.ts"

    tree = ET.parse(src_path)
    root = tree.getroot()
    root.set("language", "pt_BR")

    for tr in root.findall(".//translation"):
        text = tr.text or ""
        if not text:
            continue
        for old, new in REPLACEMENTS:
            text = text.replace(old, new)
        tr.text = text

    tree.write(dst_path, encoding="utf-8", xml_declaration=True)
    print(f"Updated: {dst_path}")


if __name__ == "__main__":
    main()
