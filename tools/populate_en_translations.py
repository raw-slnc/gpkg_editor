#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Populate gpkg_editor_en.ts with baseline English translations."""

from __future__ import annotations

import re
from defusedxml import ElementTree as ET


EN_MAP = {
    "計画を保存": "Save Plan",
    "▼ マップサムネイル": "▼ Map Thumbnail",
    "▶ マップサムネイル": "▶ Map Thumbnail",
    "不要": "Not required",
    "■ 情報（後列）": "■ Info (back row)",
    "{} に保存されました": "Saved to {}",
    "別ウィンドウ表示": "Separate Window",
    "コピー元の計画を選択してください（Escでキャンセル）":
        "Select the plan to copy from (Esc to cancel)",
    "-- 計画をコピーして開始 --": "-- Copy a plan to start --",
    "カラム設定": "Column Settings",
    "全て": "All",
    "非表示": "Hidden",
    "表示": "Display",
    "編集": "Edit",
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
    "表示カラムが設定されていません。カラム設定を行ってください。":
        "No visible columns are configured. Please configure columns.",
    "保存エラー": "Save Error",
    "編集の保存に失敗しました: {}": "Failed to save edits: {}",
    "対象数: -": "Target count: -",
    "-- 計画を選択 --": "-- Select plan --",
    "計画「{}」を読み込みました ({} 件)": "Plan \"{}\" loaded ({} items)",
    "計画名を入力してください。": "Please enter a plan name.",
    "テーブルにデータがありません。\n地物を選択してから保存してください。":
        "No data in table.\nPlease select features before saving.",
    "計画「{}」を保存しました": "Plan \"{}\" saved",
    "削除エラー": "Delete Error",
    "削除する計画を選択してください。": "Please select a plan to delete.",
    "確認": "Confirmation",
    "計画「{}」を削除しますか？": "Delete plan \"{}\"?",
    "計画「{}」を削除しました": "Plan \"{}\" deleted",
    "対象数: {}": "Target count: {}",
    "対象を追加":
        "Add Targets",
    "メインウィンドウでフィーチャーを選択してください（複数選択可）":
        "Select features in the main window (multi-select supported)",
    "対象の追加をキャンセルしました":
        "Adding targets canceled",
    "追加": "Add",
    "追加する対象がありません。": "No targets to add.",
    "選択したものはすべて計画の対象に含まれています":
        "All selected features are already targets of the plan",
    "{} 件を計画の対象に追加します。よろしいですか？":
        "Add {} targets to the plan. Continue?",
    "{} 件を計画の対象に追加しました (計 {} 件)":
        "{} targets added to the plan (total: {})",
    "選択を確定する": "Confirm Selection",
    "キャンセル": "Cancel",
    "計画から外す対象をテーブルで選択してください。":
        "Select targets to remove from the plan in the table.",
    "選択した {} 件の対象を計画から外します。よろしいですか？":
        "Remove {} selected targets from the plan. Continue?",
    "{} 件の対象を計画から外しました (計 {} 件)":
        "{} targets removed from the plan (total: {})",
    "ステータス1行目": "Status Line 1",
    "ステータス2行目": "Status Line 2",
    "出力エラー": "Export Error",
    "テーブルにデータがありません。\n地物を選択または計画を読み込んでから出力してください。":
        "No data in table.\nSelect features or load a plan before export.",
    "GPKG出力先を選択": "Select GPKG export destination",
    "完了": "Done",
    "GPKGファイルを出力しました:\n{}": "GPKG file exported:\n{}",
    "GPKG出力に失敗しました: {}": "GPKG export failed: {}",
    "情報": "Information",
    "保存する編集がありません。": "There are no edits to save.",
    "上書き確認": "Overwrite Confirmation",
    "元のGPKGファイルに編集を書き込みます:\n{}\n\nこの操作は取り消せません。よろしいですか？":
        "Edits will be written to the original GPKG file:\n{}\n\n"
        "This action cannot be undone. Continue?",
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
    "-- 新規計画を追加 --": "-- Add New Plan --",
    "計画名を入力し、対象を選択してください":
        "Enter a plan name and select targets",
    "同名の計画があります。別の名前を入力してください。":
        "A plan with this name already exists. Please enter another name.",
    "計画名の変更に失敗しました。": "Failed to rename the plan.",
    "計画名を入力...": "Enter plan name...",
    "保存": "Save",
    "削除": "Delete",
    "対象を外す":
        "Remove Targets",
    "操作": "Operations",
    "GPKG出力": "Export GPKG",
    "CSV出力": "Export CSV",
    "GPKGレイヤーに上書き保存する": "Overwrite save to GPKG layer",
    "計画範囲のみ出力": "Export plan scope only",
    "▼ ステータス表示設定": "▼ Status Display Settings",
    "▶ ステータス表示設定": "▶ Status Display Settings",
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
    "■ 表示のみ": "■ Display only",
    "■ 編集可能": "■ Editable",
    "■ 編集済み": "■ Edited",
    "言語": "Language",
    (
        "QGIS式風の書式（選択行の値を表示）\n"
        "\n"
        "\"カラム名\"  選択行のカラム値\n"
        "'テキスト'  文字列リテラル\n"
        "||  文字列結合    =, !=, >, <  比較\n"
        "if(条件, 真, 偽)  条件分岐\n"
        "round(数値[, 桁])  四捨五入（桁は省略可）\n"
        "\n"
        "集計関数（全行対象）:\n"
        "  count() / sum(\"COL\") / unique(\"COL\")\n"
        "\n"
        "例: \"名称\" || ' - ' || \"種別\" || '  (' || count() || '件)'"
    ):
        (
            "QGIS-style expression format (display selected row values)\n"
            "\n"
            "\"column\"  value of selected row column\n"
            "'text'  string literal\n"
            "||  string concat    =, !=, >, <  comparison\n"
            "if(cond, true, false)  conditional\n"
            "round(num[, digits])  rounding\n"
            "\n"
            "Aggregate functions (all rows):\n"
            "  count() / sum(\"COL\") / unique(\"COL\")\n"
            "\n"
            "Ex: \"Name\" || ' - ' || \"Type\" || ' (' || count() || ' items)'"
        ),
}

# 同じ日本語ソースでもコンテキスト（クラス）によって意味が異なるものの個別訳。
# 例: "情報" はColumnConfigDialogでは短い状態ラベル、GpkgEditorWindowでは
# QMessageBoxのタイトル。
CONTEXT_OVERRIDES = {
    ("ColumnConfigDialog", "情報"): "Info",
}


def is_japanese(text: str) -> bool:
    return bool(re.search(r"[ぁ-んァ-ン一-龯]", text))


def main():
    path = "i18n/gpkg_editor_en.ts"
    tree = ET.parse(path)
    root = tree.getroot()

    for ctx in root.findall(".//context"):
        ctx_name = ctx.findtext("name", default="")
        for msg in ctx.findall("message"):
            src = msg.findtext("source", default="")
            tr = msg.find("translation")
            if tr is None:
                tr = ET.SubElement(msg, "translation")

            if (ctx_name, src) in CONTEXT_OVERRIDES:
                tr.text = CONTEXT_OVERRIDES[(ctx_name, src)]
                tr.attrib.pop("type", None)
                continue

            if src in EN_MAP:
                tr.text = EN_MAP[src]
                tr.attrib.pop("type", None)
                continue

            if (
                src.startswith("color:")
                or src.startswith("font-size:")
                or src.startswith("QPushButton{")
                or src in {
                    "<", ">", "1/1", "Ctrl+C", "Ctrl+V", "Shift+Scroll",
                    "Ctrl+Arrow", "Ctrl+Shift+Arrow", "Enter",
                }
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
