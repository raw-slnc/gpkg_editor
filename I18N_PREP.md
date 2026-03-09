# i18n Preparation (gpkg_editor)

## 方針
- UIファイル (`.ui`) の `<string>` は Qt の翻訳抽出対象。
- Python側の動的文言は `self.tr("...")` を翻訳フラグとして使用。
- 今回は `UI文言` と `ポップアップ文言` を優先して `tr()` 化済み。
- 運用言語は `en / es / pt`（`fr` は対象外）。
- UI確認用に、左パネル下段（凡例行の右端）に「言語」ボタンを追加済み。
  押下ごとに `ja -> en -> es -> pt` の順でループ切替する。

## UI翻訳対象
### 静的UI（Qt Designer）
- `gpkg_editor_dockwidget_base.ui`
- `column_config_dialog_base.ui`

上記の `<string>` は `lupdate` で抽出可能。

### 動的UI（Python）
- `gpkg_editor_dockwidget.py`
  - `setText(...)` / `addItem(...)` の固定文言
  - ショートカット見出し切替、ロック表示、ステータス表示、計画関連のボタン・ラベル文言
  - ステータス式ヘルプ文言 (`_status_help_text`)
- `column_config_dialog.py`
  - フィルタ表示文言、状態ボタン文言

## ポップアップ翻訳対象
対象API:
- `QMessageBox.critical/warning/information/question`
- `QFileDialog.getSaveFileName`

実装箇所:
- `gpkg_editor_dockwidget.py` の該当呼び出し全てを `self.tr(...)` 化
  - 例: エラー/確認/完了タイトル
  - 例: 保存失敗、削除確認、出力確認、上書き警告メッセージ

## 追加メモ
- 文字列フォーマットは `self.tr('... {} ...').format(...)` へ統一。
- 既存のカラム状態内部値（`非表示/表示のみ/表示＋編集/情報`）は互換性維持のため変更していない。
- プラグイン本体で翻訳ローダーを実装済み（`pt_BR` が無い場合は `pt` へフォールバック）。

## 生成済みファイル
- `i18n/gpkg_editor_en.ts`, `i18n/gpkg_editor_en.qm`
- `i18n/gpkg_editor_es.ts`, `i18n/gpkg_editor_es.qm`
- `i18n/gpkg_editor_pt.ts`, `i18n/gpkg_editor_pt.qm`
- `i18n/gpkg_editor_pt_BR.ts`, `i18n/gpkg_editor_pt_BR.qm`

## 更新コマンド
```bash
cd /home/masai/.qgis/plugins_dev/gpkg_editor
pylupdate5 gpkg_editor.py gpkg_editor_dockwidget.py column_config_dialog.py gpkg_editor_dockwidget_base.ui column_config_dialog_base.ui -ts i18n/gpkg_editor_en.ts i18n/gpkg_editor_es.ts i18n/gpkg_editor_pt.ts i18n/gpkg_editor_pt_BR.ts
lrelease i18n/gpkg_editor_en.ts i18n/gpkg_editor_es.ts i18n/gpkg_editor_pt.ts i18n/gpkg_editor_pt_BR.ts
```

## `pt` と `pt_BR` 差分評価
```bash
cd /home/masai/.qgis/plugins_dev/gpkg_editor
python3 tools/compare_ts_variants.py i18n/gpkg_editor_pt.ts i18n/gpkg_editor_pt_BR.ts
```

## 生成・派生スクリプト
```bash
cd /home/masai/.qgis/plugins_dev/gpkg_editor
python3 tools/populate_en_translations.py
python3 tools/populate_es_translations.py
python3 tools/populate_pt_translations.py
python3 tools/derive_pt_br_from_pt.py
lrelease i18n/gpkg_editor_en.ts i18n/gpkg_editor_es.ts i18n/gpkg_editor_pt.ts i18n/gpkg_editor_pt_BR.ts
```

## 現在の比較結果（2026-03-09）
- 比較対象: `i18n/gpkg_editor_pt.ts` vs `i18n/gpkg_editor_pt_BR.ts`
- 総メッセージ: 159
- 差分: 3
- 差分率: `1.89%`

現時点では `pt` 1本運用でも実務上は十分。将来、ブラジル向け表現調整が増えた時点で `pt_BR` 分離を再検討する。

## 抽出確認コマンド
```bash
cd /home/masai/.qgis
rg -n "QMessageBox\.(critical|warning|information|question)|QFileDialog\.getSaveFileName|setText\(self\.tr|addItem\(self\.tr" plugins_dev/gpkg_editor
```
