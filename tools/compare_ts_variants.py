#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare two Qt Linguist TS files and report translation differences."""

from __future__ import annotations

import argparse
from defusedxml import ElementTree as ET


def _read_ts(path: str):
    tree = ET.parse(path)
    root = tree.getroot()
    data = {}
    for ctx in root.findall("context"):
        name = ctx.findtext("name", default="")
        for msg in ctx.findall("message"):
            source = msg.findtext("source", default="")
            translation = msg.find("translation")
            trans_text = (translation.text or "").strip() if translation is not None else ""
            trans_type = translation.attrib.get("type", "") if translation is not None else ""
            key = (name, source)
            data[key] = {
                "translated": bool(trans_text) and trans_type != "unfinished",
                "text": trans_text,
                "type": trans_type,
            }
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Compare translated message differences between two TS files."
    )
    parser.add_argument("left", help="left TS file (e.g., gpkg_editor_pt.ts)")
    parser.add_argument("right", help="right TS file (e.g., gpkg_editor_pt_BR.ts)")
    args = parser.parse_args()

    left = _read_ts(args.left)
    right = _read_ts(args.right)
    keys = sorted(set(left.keys()) | set(right.keys()))

    left_translated = sum(1 for k in keys if left.get(k, {}).get("translated"))
    right_translated = sum(1 for k in keys if right.get(k, {}).get("translated"))

    both_translated = 0
    same = 0
    different = 0
    left_only = 0
    right_only = 0

    for key in keys:
        l = left.get(key, {"translated": False, "text": ""})
        r = right.get(key, {"translated": False, "text": ""})
        if l["translated"] and r["translated"]:
            both_translated += 1
            if l["text"] == r["text"]:
                same += 1
            else:
                different += 1
        elif l["translated"]:
            left_only += 1
        elif r["translated"]:
            right_only += 1

    diff_ratio = (different / both_translated * 100.0) if both_translated else 0.0

    print(f"Total source messages: {len(keys)}")
    print(f"Left translated: {left_translated}")
    print(f"Right translated: {right_translated}")
    print(f"Both translated: {both_translated}")
    print(f"Same translation (both translated): {same}")
    print(f"Different translation (both translated): {different}")
    print(f"Left-only translated: {left_only}")
    print(f"Right-only translated: {right_only}")
    print(f"Difference ratio (different / both translated): {diff_ratio:.2f}%")

    if both_translated:
        print("\nSample differences (up to 20):")
        shown = 0
        for key in keys:
            l = left.get(key, {"translated": False, "text": ""})
            r = right.get(key, {"translated": False, "text": ""})
            if l["translated"] and r["translated"] and l["text"] != r["text"]:
                ctx, source = key
                print(f"- [{ctx}] {source}")
                print(f"  L: {l['text']}")
                print(f"  R: {r['text']}")
                shown += 1
                if shown >= 20:
                    break


if __name__ == "__main__":
    main()
