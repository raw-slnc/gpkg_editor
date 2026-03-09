#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Populate gpkg_editor_en.ts with baseline English translations."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET


EN_MAP = {
    "カラム設定": "Column Settings",
    "全て": "All",
    "非表示": "Hidden",
    "表示": "Display",
    "編集": "Edit",
    "情報": "Info",
    "表示のみ": "Display only",
    "表示編集のみ": "Display/Edit only",
    "情報のみ": "Info only",
    "選択無し": "None",
    "▼ ショートカット": "▼ Shortcuts",
    "▶ ショートカット": "▶ Shortcuts",
    "-- 選択してください --": "-- Please select --",
    "GPKGレイヤーを選択してください": "Please select a GPKG layer",
    "エラー": "Error",
    "読込完了: {}": "Load completed: {}",
    "ロック中": "Locked",
    "ロック": "Lock",
    "地物が選択されていません": "No features selected",
    "交差するフィーチャーがありません": "No intersecting features",
    "{} 件のフィーチャーが見つかりました": "{} features found",
    "表示カラムが設定されていません。カラム設定を行ってください。": "No visible columns are configured. Please configure columns.",
    "保存エラー": "Save Error",
    "編集の保存に失敗しました: {}": "Failed to save edits: {}",
    "フィーチャー数: -": "Feature count: -",
    "-- 計画を選択 --": "-- Select plan --",
    "計画「{}」を読み込みました ({} 件)": "Plan \"{}\" loaded ({} items)",
    "計画名を入力してください。": "Please enter a plan name.",
    "テーブルにデータがありません。\n地物を選択してから保存してください。": "No data in table.\nPlease select features before saving.",
    "計画「{}」を保存しました": "Plan \"{}\" saved",
    "削除エラー": "Delete Error",
    "削除する計画を選択してください。": "Please select a plan to delete.",
    "確認": "Confirmation",
    "計画「{}」を削除しますか？": "Delete plan \"{}\"?",
    "計画「{}」を削除しました": "Plan \"{}\" deleted",
    "フィーチャー数: {}": "Feature count: {}",
    "フィーチャーの追加": "Add Features",
    "メインウィンドウでフィーチャーを選択してください（複数選択可）": "Select features in the main window (multi-select supported)",
    "フィーチャーの追加をキャンセルしました": "Feature add canceled",
    "追加": "Add",
    "追加対象のフィーチャーがありません。": "No target features to add.",
    "選択されたフィーチャーはすべて計画に含まれています": "All selected features are already included in the plan",
    "{} 件のフィーチャーを追加します。よろしいですか？": "Add {} features. Continue?",
    "{} 件のフィーチャーを追加しました (計 {} 件)": "{} features added (total: {})",
    "選択を確定する": "Confirm Selection",
    "キャンセル": "Cancel",
    "テーブルから削除するフィーチャーを選択してください。": "Select features to delete from the table.",
    "選択された {} 件のフィーチャーを削除します。よろしいですか？": "Delete {} selected features. Continue?",
    "{} 件のフィーチャーを削除しました (計 {} 件)": "{} features deleted (total: {})",
    "ステータス1行目": "Status Line 1",
    "ステータス2行目": "Status Line 2",
    "出力エラー": "Export Error",
    "テーブルにデータがありません。\n地物を選択または計画を読み込んでから出力してください。": "No data in table.\nSelect features or load a plan before export.",
    "GPKG出力先を選択": "Select GPKG export destination",
    "完了": "Done",
    "GPKGファイルを出力しました:\n{}": "GPKG file exported:\n{}",
    "GPKG出力に失敗しました: {}": "GPKG export failed: {}",
    "情報": "Information",
    "保存する編集がありません。": "There are no edits to save.",
    "上書き確認": "Overwrite Confirmation",
    "元のGPKGファイルに編集を書き込みます:\n{}\n\nこの操作は取り消せません。よろしいですか？": "Edits will be written to the original GPKG file:\n{}\n\nThis action cannot be undone. Continue?",
    "上書き保存が完了しました": "Overwrite save completed",
    "GPKGファイルに編集を書き込みました:\n{}": "Edits written to GPKG file:\n{}",
    "上書き保存に失敗しました: {}": "Overwrite save failed: {}",
    "CSV出力先を選択": "Select CSV export destination",
    "CSVファイルを出力しました:\n{}": "CSV file exported:\n{}",
    "CSV出力に失敗しました: {}": "CSV export failed: {}",
    "レイヤー": "Layer",
    "GPKGレイヤー:": "GPKG Layer:",
    "プロジェクト内のGPKGレイヤーを選択": "Select a GPKG layer in the project",
    "計画": "Plan",
    "計画:": "Plan:",
    "計画名:": "Plan Name:",
    "計画名を入力...": "Enter plan name...",
    "保存": "Save",
    "削除": "Delete",
    "フィーチャーの削除": "Delete Features",
    "操作": "Operations",
    "GPKG出力": "Export GPKG",
    "CSV出力": "Export CSV",
    "GPKGレイヤーに上書き保存する": "Overwrite save to GPKG layer",
    "計画範囲のみ出力": "Export plan scope only",
    "ステータス表示設定": "Status Display Settings",
    "1行目": "Line 1",
    "2行目": "Line 2",
    "セルをコピー（タブ区切り）": "Copy cells (tab-delimited)",
    "クリップボードから貼り付け": "Paste from clipboard",
    "横スクロール": "Horizontal scroll",
    "末端セルへ移動": "Move to edge cell",
    "末端セルまで選択": "Select to edge cell",
    "セル編集モード切替": "Toggle cell edit mode",
    "ステータス": "Status",
    "パネルを閉じる": "Close panel",
    "フィーチャー全件を描画": "Draw all features",
    "全画面表示": "Full screen",
    "■ 表示のみ": "■ Display only",
    "■ 編集可能": "■ Editable",
    "■ 編集済み": "■ Edited",
    "言語": "Language",
    "QGIS式風の書式（選択行の値を表示）\n\n\"カラム名\"  選択行のカラム値\n'テキスト'  文字列リテラル\n||  文字列結合    =, !=, >, <  比較\nif(条件, 真, 偽)  条件分岐\nround(数値[, 桁])  四捨五入（桁は省略可）\n\n集計関数（全行対象）:\n  count() / sum(\"COL\") / unique(\"COL\")\n\n例: \"名称\" || ' - ' || \"種別\" || '  (' || count() || '件)'":
    "QGIS-style expression format (display selected row values)\n\n\"column\"  value of selected row column\n'text'  string literal\n||  string concat    =, !=, >, <  comparison\nif(cond, true, false)  conditional\nround(num[, digits])  rounding\n\nAggregate functions (all rows):\n  count() / sum(\"COL\") / unique(\"COL\")\n\nEx: \"Name\" || ' - ' || \"Type\" || ' (' || count() || ' items)'",
}


def is_japanese(text: str) -> bool:
    return bool(re.search(r"[ぁ-んァ-ン一-龯]", text))


def main():
    path = "i18n/gpkg_editor_en.ts"
    tree = ET.parse(path)
    root = tree.getroot()

    for msg in root.findall(".//message"):
        src = msg.findtext("source", default="")
        tr = msg.find("translation")
        if tr is None:
            tr = ET.SubElement(msg, "translation")

        if src in EN_MAP:
            tr.text = EN_MAP[src]
            tr.attrib.pop("type", None)
            continue

        if (
            src.startswith("color:")
            or src.startswith("font-size:")
            or src.startswith("QPushButton{")
            or src in {"<", ">", "1/1", "Ctrl+C", "Ctrl+V", "Shift+Scroll", "Ctrl+Arrow", "Ctrl+Shift+Arrow", "Enter"}
            or src.startswith("GeoPackage Files")
            or src.startswith("CSV Files")
        ):
            tr.text = src
            tr.attrib.pop("type", None)
            continue

        if not is_japanese(src):
            tr.text = src
            tr.attrib.pop("type", None)
        else:
            tr.attrib["type"] = "unfinished"

    tree.write(path, encoding="utf-8", xml_declaration=True)
    print(f"Updated: {path}")


if __name__ == "__main__":
    main()
