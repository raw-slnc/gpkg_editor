#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Populate gpkg_editor_pt.ts with baseline Portuguese translations."""

from __future__ import annotations

import re
from defusedxml import ElementTree as ET


PT_MAP = {
    "カラム設定": "Configuração de colunas",
    "全て": "Todos",
    "非表示": "Oculto",
    "表示": "Exibir",
    "編集": "Editar",
    "情報": "Informações",
    "表示のみ": "Somente exibição",
    "表示編集のみ": "Somente exibição/edição",
    "情報のみ": "Somente informações",
    "選択無し": "Sem seleção",
    "▼ ショートカット": "▼ Atalhos",
    "▶ ショートカット": "▶ Atalhos",
    "-- 選択してください --": "-- Selecione --",
    "GPKGレイヤーを選択してください": "Selecione uma camada GPKG",
    "エラー": "Erro",
    "読込完了: {}": "Carregamento concluído: {}",
    "ロック中": "Bloqueado",
    "ロック": "Bloquear",
    "地物が選択されていません": "Nenhuma feição selecionada",
    "交差するフィーチャーがありません": "Não há feições intersectantes",
    "{} 件のフィーチャーが見つかりました": "{} feições encontradas",
    "表示カラムが設定されていません。カラム設定を行ってください。": "Nenhuma coluna visível configurada. Configure as colunas.",
    "保存エラー": "Erro ao salvar",
    "編集の保存に失敗しました: {}": "Falha ao salvar edições: {}",
    "フィーチャー数: -": "Número de feições: -",
    "-- 計画を選択 --": "-- Selecionar plano --",
    "計画「{}」を読み込みました ({} 件)": "Plano \"{}\" carregado ({} itens)",
    "計画名を入力してください。": "Digite o nome do plano.",
    "テーブルにデータがありません。\n地物を選択してから保存してください。": "Não há dados na tabela.\nSelecione feições antes de salvar.",
    "計画「{}」を保存しました": "Plano \"{}\" salvo",
    "削除エラー": "Erro ao excluir",
    "削除する計画を選択してください。": "Selecione um plano para excluir.",
    "確認": "Confirmação",
    "計画「{}」を削除しますか？": "Deseja excluir o plano \"{}\"?",
    "計画「{}」を削除しました": "Plano \"{}\" excluído",
    "フィーチャー数: {}": "Número de feições: {}",
    "フィーチャーの追加": "Adicionar feições",
    "メインウィンドウでフィーチャーを選択してください（複数選択可）": "Selecione feições na janela principal (seleção múltipla permitida)",
    "フィーチャーの追加をキャンセルしました": "Adição de feições cancelada",
    "追加": "Adicionar",
    "追加対象のフィーチャーがありません。": "Não há feições para adicionar.",
    "選択されたフィーチャーはすべて計画に含まれています": "Todas as feições selecionadas já estão no plano",
    "{} 件のフィーチャーを追加します。よろしいですか？": "Adicionar {} feições. Continuar?",
    "{} 件のフィーチャーを追加しました (計 {} 件)": "{} feições adicionadas (total: {})",
    "選択を確定する": "Confirmar seleção",
    "キャンセル": "Cancelar",
    "テーブルから削除するフィーチャーを選択してください。": "Selecione na tabela as feições a excluir.",
    "選択された {} 件のフィーチャーを削除します。よろしいですか？": "Excluir {} feições selecionadas. Continuar?",
    "{} 件のフィーチャーを削除しました (計 {} 件)": "{} feições removidas (total: {})",
    "ステータス1行目": "Status - linha 1",
    "ステータス2行目": "Status - linha 2",
    "出力エラー": "Erro de exportação",
    "テーブルにデータがありません。\n地物を選択または計画を読み込んでから出力してください。": "Não há dados na tabela.\nSelecione feições ou carregue um plano antes de exportar.",
    "GPKG出力先を選択": "Selecionar destino de exportação GPKG",
    "完了": "Concluído",
    "GPKGファイルを出力しました:\n{}": "Arquivo GPKG exportado:\n{}",
    "GPKG出力に失敗しました: {}": "Falha na exportação GPKG: {}",
    "情報": "Informação",
    "保存する編集がありません。": "Não há edições para salvar.",
    "上書き確認": "Confirmação de sobrescrita",
    "元のGPKGファイルに編集を書き込みます:\n{}\n\nこの操作は取り消せません。よろしいですか？": "As edições serão gravadas no arquivo GPKG original:\n{}\n\nEsta operação não pode ser desfeita. Continuar?",
    "上書き保存が完了しました": "Sobrescrita concluída",
    "GPKGファイルに編集を書き込みました:\n{}": "Edições gravadas no arquivo GPKG:\n{}",
    "上書き保存に失敗しました: {}": "Falha na sobrescrita: {}",
    "CSV出力先を選択": "Selecionar destino de exportação CSV",
    "CSVファイルを出力しました:\n{}": "Arquivo CSV exportado:\n{}",
    "CSV出力に失敗しました: {}": "Falha na exportação CSV: {}",
    "レイヤー": "Camada",
    "GPKGレイヤー:": "Camada GPKG:",
    "プロジェクト内のGPKGレイヤーを選択": "Selecione uma camada GPKG do projeto",
    "計画": "Plano",
    "計画:": "Plano:",
    "計画名:": "Nome do plano:",
    "計画名を入力...": "Digite o nome do plano...",
    "保存": "Salvar",
    "削除": "Excluir",
    "フィーチャーの削除": "Remover feições",
    "操作": "Operações",
    "GPKG出力": "Exportar GPKG",
    "CSV出力": "Exportar CSV",
    "GPKGレイヤーに上書き保存する": "Sobrescrever camada GPKG",
    "計画範囲のみ出力": "Exportar apenas escopo do plano",
    "ステータス表示設定": "Configuração de exibição de status",
    "1行目": "Linha 1",
    "2行目": "Linha 2",
    "セルをコピー（タブ区切り）": "Copiar células (separadas por tabulação)",
    "クリップボードから貼り付け": "Colar da área de transferência",
    "横スクロール": "Rolagem horizontal",
    "末端セルへ移動": "Ir para a célula final",
    "末端セルまで選択": "Selecionar até a célula final",
    "セル編集モード切替": "Alternar modo de edição da célula",
    "ステータス": "Status",
    "パネルを閉じる": "Fechar painel",
    "フィーチャー全件を描画": "Desenhar todas as feições",
    "全画面表示": "Tela cheia",
    "■ 表示のみ": "■ Somente exibição",
    "■ 編集可能": "■ Editável",
    "■ 編集済み": "■ Editado",
    "言語": "Idioma",
    "QGIS式風の書式（選択行の値を表示）\n\n\"カラム名\"  選択行のカラム値\n'テキスト'  文字列リテラル\n||  文字列結合    =, !=, >, <  比較\nif(条件, 真, 偽)  条件分岐\nround(数値[, 桁])  四捨五入（桁は省略可）\n\n集計関数（全行対象）:\n  count() / sum(\"COL\") / unique(\"COL\")\n\n例: \"名称\" || ' - ' || \"種別\" || '  (' || count() || '件)'":
    "Formato estilo expressão do QGIS (exibe valores da linha selecionada)\n\n\"NomeColuna\"  valor da coluna na linha selecionada\n'texto'  literal de string\n||  concatenação    =, !=, >, <  comparação\nif(condição, verdadeiro, falso)  condição\nround(número[, casas])  arredondamento\n\nFunções de agregação (todas as linhas):\n  count() / sum(\"COL\") / unique(\"COL\")\n\nEx.: \"Nome\" || ' - ' || \"Tipo\" || ' (' || count() || ' itens)'",
}


def is_japanese(text: str) -> bool:
    return bool(re.search(r"[ぁ-んァ-ン一-龯]", text))


def main():
    path = "i18n/gpkg_editor_pt.ts"
    tree = ET.parse(path)
    root = tree.getroot()

    for msg in root.findall(".//message"):
        src = msg.findtext("source", default="")
        tr = msg.find("translation")
        if tr is None:
            tr = ET.SubElement(msg, "translation")

        if src in PT_MAP:
            tr.text = PT_MAP[src]
            tr.attrib.pop("type", None)
            continue

        # Keep style/code-like strings unchanged but translated.
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

        # If non-Japanese source, keep source text as translation baseline.
        if not is_japanese(src):
            tr.text = src
            tr.attrib.pop("type", None)
        else:
            tr.attrib["type"] = "unfinished"

    tree.write(path, encoding="utf-8", xml_declaration=True)
    print(f"Updated: {path}")


if __name__ == "__main__":
    main()
