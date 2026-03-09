#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Populate gpkg_editor_es.ts with baseline Spanish translations."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET


ES_MAP = {
    "カラム設定": "Configuración de columnas",
    "全て": "Todos",
    "非表示": "Oculto",
    "表示": "Mostrar",
    "編集": "Editar",
    "情報": "Información",
    "表示のみ": "Solo visualización",
    "表示編集のみ": "Solo visualizar/editar",
    "情報のみ": "Solo información",
    "選択無し": "Sin selección",
    "▼ ショートカット": "▼ Atajos",
    "▶ ショートカット": "▶ Atajos",
    "-- 選択してください --": "-- Seleccione --",
    "GPKGレイヤーを選択してください": "Seleccione una capa GPKG",
    "エラー": "Error",
    "読込完了: {}": "Carga completada: {}",
    "ロック中": "Bloqueado",
    "ロック": "Bloquear",
    "地物が選択されていません": "No hay entidades seleccionadas",
    "交差するフィーチャーがありません": "No hay entidades que intersecten",
    "{} 件のフィーチャーが見つかりました": "Se encontraron {} entidades",
    "表示カラムが設定されていません。カラム設定を行ってください。": "No hay columnas visibles configuradas. Configure las columnas.",
    "保存エラー": "Error al guardar",
    "編集の保存に失敗しました: {}": "No se pudieron guardar las ediciones: {}",
    "フィーチャー数: -": "Número de entidades: -",
    "-- 計画を選択 --": "-- Seleccionar plan --",
    "計画「{}」を読み込みました ({} 件)": "Plan \"{}\" cargado ({} elementos)",
    "計画名を入力してください。": "Ingrese el nombre del plan.",
    "テーブルにデータがありません。\n地物を選択してから保存してください。": "No hay datos en la tabla.\nSeleccione entidades antes de guardar.",
    "計画「{}」を保存しました": "Plan \"{}\" guardado",
    "削除エラー": "Error al eliminar",
    "削除する計画を選択してください。": "Seleccione un plan para eliminar.",
    "確認": "Confirmación",
    "計画「{}」を削除しますか？": "¿Eliminar el plan \"{}\"?",
    "計画「{}」を削除しました": "Plan \"{}\" eliminado",
    "フィーチャー数: {}": "Número de entidades: {}",
    "フィーチャーの追加": "Agregar entidades",
    "メインウィンドウでフィーチャーを選択してください（複数選択可）": "Seleccione entidades en la ventana principal (se permite selección múltiple)",
    "フィーチャーの追加をキャンセルしました": "Se canceló la adición de entidades",
    "追加": "Agregar",
    "追加対象のフィーチャーがありません。": "No hay entidades para agregar.",
    "選択されたフィーチャーはすべて計画に含まれています": "Todas las entidades seleccionadas ya están incluidas en el plan",
    "{} 件のフィーチャーを追加します。よろしいですか？": "Se agregarán {} entidades. ¿Continuar?",
    "{} 件のフィーチャーを追加しました (計 {} 件)": "Se agregaron {} entidades (total: {})",
    "選択を確定する": "Confirmar selección",
    "キャンセル": "Cancelar",
    "テーブルから削除するフィーチャーを選択してください。": "Seleccione en la tabla las entidades a eliminar.",
    "選択された {} 件のフィーチャーを削除します。よろしいですか？": "Se eliminarán {} entidades seleccionadas. ¿Continuar?",
    "{} 件のフィーチャーを削除しました (計 {} 件)": "Se eliminaron {} entidades (total: {})",
    "ステータス1行目": "Estado línea 1",
    "ステータス2行目": "Estado línea 2",
    "出力エラー": "Error de exportación",
    "テーブルにデータがありません。\n地物を選択または計画を読み込んでから出力してください。": "No hay datos en la tabla.\nSeleccione entidades o cargue un plan antes de exportar.",
    "GPKG出力先を選択": "Seleccione destino de exportación GPKG",
    "完了": "Completado",
    "GPKGファイルを出力しました:\n{}": "Archivo GPKG exportado:\n{}",
    "GPKG出力に失敗しました: {}": "Falló la exportación GPKG: {}",
    "情報": "Información",
    "保存する編集がありません。": "No hay ediciones para guardar.",
    "上書き確認": "Confirmación de sobrescritura",
    "元のGPKGファイルに編集を書き込みます:\n{}\n\nこの操作は取り消せません。よろしいですか？": "Se escribirán las ediciones en el archivo GPKG original:\n{}\n\nEsta acción no se puede deshacer. ¿Continuar?",
    "上書き保存が完了しました": "Sobrescritura completada",
    "GPKGファイルに編集を書き込みました:\n{}": "Ediciones escritas en el archivo GPKG:\n{}",
    "上書き保存に失敗しました: {}": "Falló la sobrescritura: {}",
    "CSV出力先を選択": "Seleccione destino de exportación CSV",
    "CSVファイルを出力しました:\n{}": "Archivo CSV exportado:\n{}",
    "CSV出力に失敗しました: {}": "Falló la exportación CSV: {}",
    "レイヤー": "Capa",
    "GPKGレイヤー:": "Capa GPKG:",
    "プロジェクト内のGPKGレイヤーを選択": "Seleccione una capa GPKG del proyecto",
    "計画": "Plan",
    "計画:": "Plan:",
    "計画名:": "Nombre del plan:",
    "計画名を入力...": "Ingrese nombre del plan...",
    "保存": "Guardar",
    "削除": "Eliminar",
    "フィーチャーの削除": "Eliminar entidades",
    "操作": "Operaciones",
    "GPKG出力": "Exportar GPKG",
    "CSV出力": "Exportar CSV",
    "GPKGレイヤーに上書き保存する": "Sobrescribir en capa GPKG",
    "計画範囲のみ出力": "Exportar solo alcance del plan",
    "ステータス表示設定": "Configuración de visualización de estado",
    "1行目": "Línea 1",
    "2行目": "Línea 2",
    "セルをコピー（タブ区切り）": "Copiar celdas (separadas por tabulaciones)",
    "クリップボードから貼り付け": "Pegar desde el portapapeles",
    "横スクロール": "Desplazamiento horizontal",
    "末端セルへ移動": "Ir a la celda final",
    "末端セルまで選択": "Seleccionar hasta la celda final",
    "セル編集モード切替": "Alternar modo de edición de celda",
    "ステータス": "Estado",
    "パネルを閉じる": "Cerrar panel",
    "フィーチャー全件を描画": "Dibujar todas las entidades",
    "全画面表示": "Pantalla completa",
    "■ 表示のみ": "■ Solo visualización",
    "■ 編集可能": "■ Editable",
    "■ 編集済み": "■ Editado",
    "言語": "Idioma",
    "QGIS式風の書式（選択行の値を表示）\n\n\"カラム名\"  選択行のカラム値\n'テキスト'  文字列リテラル\n||  文字列結合    =, !=, >, <  比較\nif(条件, 真, 偽)  条件分岐\nround(数値[, 桁])  四捨五入（桁は省略可）\n\n集計関数（全行対象）:\n  count() / sum(\"COL\") / unique(\"COL\")\n\n例: \"名称\" || ' - ' || \"種別\" || '  (' || count() || '件)'":
    "Formato estilo expresión de QGIS (muestra valores de la fila seleccionada)\n\n\"columna\"  valor de la columna de la fila seleccionada\n'texto'  literal de cadena\n||  concatenación    =, !=, >, <  comparación\nif(condición, verdadero, falso)  condicional\nround(número[, decimales])  redondeo\n\nFunciones de agregación (todas las filas):\n  count() / sum(\"COL\") / unique(\"COL\")\n\nEj.: \"Nombre\" || ' - ' || \"Tipo\" || ' (' || count() || ' elementos)'",
}


def is_japanese(text: str) -> bool:
    return bool(re.search(r"[ぁ-んァ-ン一-龯]", text))


def main():
    path = "i18n/gpkg_editor_es.ts"
    tree = ET.parse(path)
    root = tree.getroot()

    for msg in root.findall(".//message"):
        src = msg.findtext("source", default="")
        tr = msg.find("translation")
        if tr is None:
            tr = ET.SubElement(msg, "translation")

        if src in ES_MAP:
            tr.text = ES_MAP[src]
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
