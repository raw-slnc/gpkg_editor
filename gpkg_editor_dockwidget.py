# -*- coding: utf-8 -*-
import os
import time

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QTableWidgetItem,
    QMessageBox,
    QHeaderView,
    QAction,
    QVBoxLayout,
)
from qgis.PyQt.QtCore import Qt, QEvent, QItemSelection, QItemSelectionModel
from qgis.PyQt.QtGui import QColor, QBrush, QKeySequence
from qgis.core import (
    QgsProject,
    QgsFeatureRequest,
    QgsGeometry,
    QgsRectangle,
    QgsCoordinateTransform,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsRubberBand

from .gpkg_data_manager import GpkgDataManager
from .status_expression import evaluate_row_expr
from .column_config_dialog import (
    ColumnConfigDialog,
    COLUMN_HIDDEN,
    COLUMN_DISPLAY,
    COLUMN_EDITABLE,
)

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), 'gpkg_editor_dockwidget_base.ui')
)

# テキスト色
COLOR_EDITABLE = QBrush(QColor(0, 0, 255))   # 青: 編集可能（未編集）
COLOR_EDITED = QBrush(QColor(255, 0, 0))      # 赤: 編集済み


class GpkgEditorWindow(QDialog, FORM_CLASS):
    """GPKG編集用ウィンドウ。"""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        # Alt+Tabで独立ウィンドウとして表示されるようにする
        self.setWindowFlags(
            Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowMinMaxButtonsHint
        )
        self.setupUi(self)
        self.iface = iface
        self.data_manager = GpkgDataManager()
        self.column_config = {}
        self._current_fids = []
        self._editing = False
        self._locked = False
        self._rubber_bands = []
        self._plan_active = False
        self._active_plan_name = None
        self._status_expr1 = ''
        self._status_expr2 = ''
        self._current_merged_data = []
        self._shouban_add_mode = False  # フィーチャー追加フロー中かどうか
        self._canvas_press_pos = None
        self._last_canvas_click_point = None
        self._last_canvas_click_time = 0.0
        self._last_canvas_click_layer_id = None
        # GPKGレイヤー一覧を初期化
        self._refresh_layer_combo()

        # シグナル接続
        self.cmbGpkgLayer.currentIndexChanged.connect(self._on_layer_selected)
        self.btnColumnConfig.clicked.connect(self._on_column_config)
        self.btnExportGpkg.clicked.connect(self._on_export_gpkg)
        self.btnExportCsv.clicked.connect(self._on_export_csv)
        self.btnLock.toggled.connect(self._on_lock_toggled)
        self.btnPlanSave.clicked.connect(self._on_plan_save)
        self.btnPlanDelete.clicked.connect(self._on_plan_delete)
        self.btnPlanAddShouban.clicked.connect(self._on_plan_add_shouban)
        self.btnPlanDeleteShouban.clicked.connect(self._on_plan_delete_shouban)
        self.cmbPlan.currentIndexChanged.connect(self._on_plan_selected)
        self.btnStatusRow1.clicked.connect(self._on_status_row1_config)
        self.btnStatusRow2.clicked.connect(self._on_status_row2_config)
        self.tableFeatures.cellChanged.connect(self._on_cell_changed)

        # 複数選択を有効化（セル編集を維持するため SelectItems のまま）
        self.tableFeatures.setSelectionMode(
            self.tableFeatures.ExtendedSelection
        )

        # テーブル行選択→マップ中心移動（ロック中のみ有効）＋ステータス更新
        self.tableFeatures.selectionModel().currentRowChanged.connect(
            self._on_table_row_changed
        )
        self.tableFeatures.selectionModel().selectionChanged.connect(
            self._on_table_selection_changed
        )
        self.tableFeatures.selectionModel().currentRowChanged.connect(
            lambda *_: self._update_status_display()
        )

        # プロジェクトのレイヤー追加/削除を監視してコンボを自動更新
        QgsProject.instance().layersAdded.connect(self._refresh_layer_combo)
        QgsProject.instance().layersRemoved.connect(self._refresh_layer_combo)

        # マップ選択変更の監視
        self.iface.mapCanvas().selectionChanged.connect(self._on_selection_changed)
        self.iface.mapCanvas().viewport().installEventFilter(self)
        self.iface.currentLayerChanged.connect(self._on_non_selection_action)
        self.iface.mapCanvas().mapToolSet.connect(self._on_non_selection_action)

        # Ctrl+F → 全画面トグル（QAction + WindowShortcut で確実に動作）
        fullscreen_action = QAction(self)
        fullscreen_action.setShortcut(QKeySequence('Ctrl+F'))
        fullscreen_action.setShortcutContext(Qt.WindowShortcut)
        fullscreen_action.triggered.connect(self._toggle_fullscreen)
        self.addAction(fullscreen_action)

        # Ctrl+S → 計画保存
        save_action = QAction(self)
        save_action.setShortcut(QKeySequence('Ctrl+S'))
        save_action.setShortcutContext(Qt.WindowShortcut)
        save_action.triggered.connect(self._on_plan_save)
        self.addAction(save_action)

        # Ctrl+Shift+スクロール→横スクロール（eventFilter）
        self.tableFeatures.viewport().installEventFilter(self)

        # Enter→編集開始/確定トグル
        self.tableFeatures.installEventFilter(self)

    def eventFilter(self, obj, event):
        # マップキャンバスのクリック位置を記録（重なりフィーチャー判定用）
        if obj == self.iface.mapCanvas().viewport():
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._canvas_press_pos = event.pos()
            elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                if self._canvas_press_pos is not None:
                    delta = event.pos() - self._canvas_press_pos
                    if abs(delta.x()) + abs(delta.y()) <= 3:
                        map_point = (
                            self.iface.mapCanvas()
                            .mapSettings()
                            .mapToPixel()
                            .toMapCoordinates(event.pos())
                        )
                        self._last_canvas_click_point = map_point
                        self._last_canvas_click_time = time.time()
                        active = self.iface.activeLayer()
                        self._last_canvas_click_layer_id = active.id() if active else None
                self._canvas_press_pos = None
            elif event.type() == QEvent.MouseButtonPress and event.button() == Qt.RightButton:
                self._cancel_click_context()

        # Ctrl+Shift+ホイール → 横スクロール
        if obj == self.tableFeatures.viewport() and event.type() == QEvent.Wheel:
            mods = event.modifiers()
            if mods == (Qt.ControlModifier | Qt.ShiftModifier):
                sb = self.tableFeatures.horizontalScrollBar()
                sb.setValue(sb.value() - event.angleDelta().y())
                return True
            # macOS: Shift+ホイールも横スクロール
            if mods == Qt.ShiftModifier:
                sb = self.tableFeatures.horizontalScrollBar()
                sb.setValue(sb.value() - event.angleDelta().y())
                return True

        # Ctrl+C → 選択セルをタブ区切りでコピー
        if obj == self.tableFeatures and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_C and event.modifiers() == Qt.ControlModifier:
                self._copy_selected_cells()
                return True

        # Ctrl+V → クリップボードの内容を選択セルからペースト
        if obj == self.tableFeatures and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_V and event.modifiers() == Qt.ControlModifier:
                if self.tableFeatures.state() != self.tableFeatures.EditingState:
                    self._paste_to_selected_cells()
                    return True

        # Ctrl+Shift+矢印キー → 現在セルから押下方向の端まで範囲選択
        if obj == self.tableFeatures and event.type() == QEvent.KeyPress:
            if (event.modifiers() == (Qt.ControlModifier | Qt.ShiftModifier)
                    and event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right)
                    and self.tableFeatures.state() != self.tableFeatures.EditingState):
                current = self.tableFeatures.currentIndex()
                if current.isValid():
                    row, col = current.row(), current.column()
                    key = event.key()
                    if key == Qt.Key_Up:
                        target_row, target_col = 0, col
                    elif key == Qt.Key_Down:
                        target_row, target_col = self.tableFeatures.rowCount() - 1, col
                    elif key == Qt.Key_Left:
                        target_row, target_col = row, 0
                    else:  # Key_Right
                        target_row, target_col = row, self.tableFeatures.columnCount() - 1
                    target = self.tableFeatures.model().index(target_row, target_col)
                    sel = QItemSelection(current, target)
                    self.tableFeatures.selectionModel().select(
                        sel, QItemSelectionModel.ClearAndSelect
                    )
                    return True

        # Ctrl+矢印キー → 押下方向の端セルへ移動
        if obj == self.tableFeatures and event.type() == QEvent.KeyPress:
            if (event.modifiers() == Qt.ControlModifier
                    and event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right)
                    and self.tableFeatures.state() != self.tableFeatures.EditingState):
                current = self.tableFeatures.currentIndex()
                if current.isValid():
                    row, col = current.row(), current.column()
                    key = event.key()
                    if key == Qt.Key_Up:
                        target_row, target_col = 0, col
                    elif key == Qt.Key_Down:
                        target_row, target_col = self.tableFeatures.rowCount() - 1, col
                    elif key == Qt.Key_Left:
                        target_row, target_col = row, 0
                    else:  # Key_Right
                        target_row, target_col = row, self.tableFeatures.columnCount() - 1
                    self.tableFeatures.setCurrentCell(target_row, target_col)
                    return True

        # Enter キー → 編集開始/確定トグル
        if obj == self.tableFeatures and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                state = self.tableFeatures.state()
                if state == self.tableFeatures.EditingState:
                    # 編集中 → 確定（デフォルト動作に委譲）
                    return False
                else:
                    # 非編集中 → 編集開始
                    current = self.tableFeatures.currentIndex()
                    if current.isValid():
                        item = self.tableFeatures.item(
                            current.row(), current.column()
                        )
                        if item and (item.flags() & Qt.ItemIsEditable):
                            self.tableFeatures.editItem(item)
                            return True
                return False

        return super().eventFilter(obj, event)

    def _cancel_click_context(self):
        """クリック補完用の記録をクリアする。"""
        self._canvas_press_pos = None
        self._last_canvas_click_point = None
        self._last_canvas_click_time = 0.0
        self._last_canvas_click_layer_id = None

    def _on_non_selection_action(self, *_args):
        """選択以外の操作が行われたら補完コンテキストを無効化する。"""
        self._cancel_click_context()

    def closeEvent(self, event):
        """ウィンドウを閉じる時は非表示にするだけで破棄しない。"""
        event.ignore()
        self.hide()

    def cleanup(self):
        """プラグイン終了時のリソース解放。unload から呼ばれる。"""
        self._clear_rubber_bands()
        try:
            self.iface.mapCanvas().selectionChanged.disconnect(
                self._on_selection_changed
            )
        except TypeError:
            pass
        try:
            QgsProject.instance().layersAdded.disconnect(self._refresh_layer_combo)
            QgsProject.instance().layersRemoved.disconnect(self._refresh_layer_combo)
        except TypeError:
            pass
        self.data_manager.close()

    # ──────────────────────────────────────────────
    # ショートカット: ウィンドウ操作
    # ──────────────────────────────────────────────

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    # ──────────────────────────────────────────────
    # GPKGレイヤー コンボボックス
    # ──────────────────────────────────────────────

    def _refresh_layer_combo(self, *_args):
        """プロジェクト内のGPKGレイヤーでコンボボックスを更新する。"""
        prev_id = self.cmbGpkgLayer.currentData()

        self.cmbGpkgLayer.blockSignals(True)
        self.cmbGpkgLayer.clear()
        self.cmbGpkgLayer.addItem('-- 選択してください --', None)

        restore_idx = 0
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            src = layer.source().split('|')[0]
            if not src.lower().endswith('.gpkg'):
                continue
            self.cmbGpkgLayer.addItem(layer.name(), layer.id())
            if layer.id() == prev_id:
                restore_idx = self.cmbGpkgLayer.count() - 1

        self.cmbGpkgLayer.setCurrentIndex(restore_idx)
        self.cmbGpkgLayer.blockSignals(False)

    def _on_layer_selected(self, index):
        """コンボボックスでレイヤーが選択された時。"""
        # ロック・計画を解除
        if self._locked:
            self.btnLock.setChecked(False)
        self._deactivate_plan()

        layer_id = self.cmbGpkgLayer.currentData()
        if not layer_id:
            self.data_manager.close()
            self.column_config = {}
            self._clear_table()
            self.btnColumnConfig.setEnabled(False)
            self.btnExportGpkg.setEnabled(False)
            self.btnExportCsv.setEnabled(False)
            self.btnLock.setEnabled(False)
            self.btnStatusRow1.setEnabled(False)
            self.btnStatusRow2.setEnabled(False)
            self._set_plan_ui_enabled(False)
            self.lblStatus.setText('GPKGレイヤーを選択してください')
            return

        layer = QgsProject.instance().mapLayer(layer_id)
        if not layer:
            return

        gpkg_path = layer.source().split('|')[0]

        try:
            self.data_manager.load_gpkg(gpkg_path)
        except ValueError as e:
            QMessageBox.critical(self, 'エラー', str(e))
            return

        self.lblStatus.setText(f'読込完了: {layer.name()}')

        columns = self.data_manager.get_original_fields()
        self.column_config = {col: COLUMN_HIDDEN for col in columns}

        self.btnColumnConfig.setEnabled(True)
        self.btnExportGpkg.setEnabled(True)
        self.btnExportCsv.setEnabled(True)
        self.btnLock.setEnabled(True)
        self.btnStatusRow1.setEnabled(True)
        self.btnStatusRow2.setEnabled(True)
        self._set_plan_ui_enabled(True)
        self._refresh_plan_combo()

        self._clear_table()

    # ──────────────────────────────────────────────
    # カラム設定
    # ──────────────────────────────────────────────

    def _on_column_config(self):
        columns = self.data_manager.get_original_fields()
        dlg = ColumnConfigDialog(columns, self.column_config, self)
        if dlg.exec_() == ColumnConfigDialog.Accepted:
            self.column_config = dlg.get_config()
            if self._current_fids:
                self._update_table(self._current_fids)
            else:
                visible_cols = self._get_visible_cols()
                self._editing = True
                self.tableFeatures.setRowCount(0)
                self.tableFeatures.setColumnCount(len(visible_cols))
                self.tableFeatures.setHorizontalHeaderLabels(visible_cols)
                self._editing = False

    # ──────────────────────────────────────────────
    # ロックモード
    # ──────────────────────────────────────────────

    def _on_lock_toggled(self, checked):
        self._locked = checked
        if checked:
            self.btnLock.setText('ロック中')
        else:
            self.btnLock.setText('ロック')
            if not self._plan_active:
                self._clear_rubber_bands()
                self._process_selection()

    def _highlight_feature(self, fid):
        """指定フィーチャーのみをラバーバンドで強調表示する。"""
        self._highlight_features([fid] if fid is not None else [])

    def _highlight_features(self, fids):
        """複数フィーチャーをラバーバンドで強調表示する。"""
        self._clear_rubber_bands()
        if not self.data_manager.original_layer or not fids:
            return

        request = QgsFeatureRequest().setFilterFids(fids)
        for feat in self.data_manager.original_layer.getFeatures(request):
            if feat.geometry().isNull():
                continue
            geom_type = feat.geometry().type()
            rb = QgsRubberBand(self.iface.mapCanvas(), geom_type)
            rb.setStrokeColor(QColor(255, 0, 0, 180))
            rb.setFillColor(QColor(0, 0, 0, 0))
            rb.setWidth(1.3)
            rb.setToGeometry(feat.geometry(), self.data_manager.original_layer)
            self._rubber_bands.append(rb)

    def _clear_rubber_bands(self):
        for rb in self._rubber_bands:
            self.iface.mapCanvas().scene().removeItem(rb)
        self._rubber_bands.clear()

    def _on_table_row_changed(self, current, _previous):
        """ロック中または計画アクティブ時：テーブル行選択→マップ中心移動。"""
        if not self._locked and not self._plan_active:
            return
        if not current.isValid():
            return
        item = self.tableFeatures.item(current.row(), 0)
        if not item:
            return
        fid = item.data(Qt.UserRole)
        if fid is None or not self.data_manager.original_layer:
            return

        request = QgsFeatureRequest().setFilterFids([fid])
        feat = next(
            self.data_manager.original_layer.getFeatures(request), None
        )
        if feat and not feat.geometry().isNull():
            center = feat.geometry().centroid().asPoint()
            self.iface.mapCanvas().setCenter(center)
            self.iface.mapCanvas().refresh()

    def _on_table_selection_changed(self, selected, deselected):
        """テーブルの選択変更時：選択された全フィーチャーを強調表示。"""
        if not self._locked and not self._plan_active:
            return

        # 選択中の全行からfidを収集
        fids = self._get_selected_fids()
        self._highlight_features(fids)

    def _get_selected_fids(self):
        """テーブルで選択中の全行のfidリストを返す。"""
        selected_rows = set()
        for idx in self.tableFeatures.selectionModel().selectedIndexes():
            selected_rows.add(idx.row())

        fids = []
        for row in selected_rows:
            item = self.tableFeatures.item(row, 0)
            if item:
                fid = item.data(Qt.UserRole)
                if fid is not None:
                    fids.append(fid)
        return fids

    def _copy_selected_cells(self):
        """選択セルをタブ区切りテキストとしてクリップボードにコピーする。"""
        indexes = self.tableFeatures.selectionModel().selectedIndexes()
        if not indexes:
            return

        # 行・列でソート
        rows = sorted(set(idx.row() for idx in indexes))
        cols = sorted(set(idx.column() for idx in indexes))
        selected_set = {(idx.row(), idx.column()) for idx in indexes}

        lines = []
        for row in rows:
            cells = []
            for col in cols:
                if (row, col) in selected_set:
                    item = self.tableFeatures.item(row, col)
                    cells.append(item.text() if item else '')
                else:
                    cells.append('')
            lines.append('\t'.join(cells))

        QApplication.clipboard().setText('\n'.join(lines))

    def _paste_to_selected_cells(self):
        """クリップボードのテキストを選択セルからペーストする。
        コピー元が1セルの場合は選択中の全編集可能セルに同じ値を展開する。
        """
        text = QApplication.clipboard().text()
        if not text:
            return

        # タブ・改行でパース（末尾の空行は除去）
        paste_rows = [row.split('\t') for row in text.splitlines()]
        if not paste_rows:
            return

        indexes = self.tableFeatures.selectionModel().selectedIndexes()

        # ── 1セルコピー: 選択中の全編集可能セルに同じ値を展開 ──
        if len(paste_rows) == 1 and len(paste_rows[0]) == 1:
            value = paste_rows[0][0]
            targets = indexes if indexes else []
            if not targets:
                current = self.tableFeatures.currentIndex()
                if current.isValid():
                    targets = [current]
            for idx in targets:
                item = self.tableFeatures.item(idx.row(), idx.column())
                if item and (item.flags() & Qt.ItemIsEditable):
                    item.setText(value)
            return

        # ── 複数セルコピー: 左上を起点にグリッド展開 ──
        if indexes:
            start_row = min(idx.row() for idx in indexes)
            start_col = min(idx.column() for idx in indexes)
        else:
            current = self.tableFeatures.currentIndex()
            if not current.isValid():
                return
            start_row = current.row()
            start_col = current.column()

        row_count = self.tableFeatures.rowCount()
        col_count = self.tableFeatures.columnCount()

        for pr, paste_row in enumerate(paste_rows):
            target_row = start_row + pr
            if target_row >= row_count:
                break
            for pc, value in enumerate(paste_row):
                target_col = start_col + pc
                if target_col >= col_count:
                    break
                item = self.tableFeatures.item(target_row, target_col)
                if item and (item.flags() & Qt.ItemIsEditable):
                    item.setText(value)

    # ──────────────────────────────────────────────
    # 地物選択連動
    # ──────────────────────────────────────────────

    def _on_selection_changed(self, layer):
        if self._locked:
            return
        if not self.data_manager.original_layer:
            return
        if self._shouban_add_mode:
            self._update_add_mode_button()
            return
        if layer and not self._is_same_source(layer):
            return
        if self._plan_active:
            return
        self._process_selection(layer)

    def _is_same_source(self, layer):
        """レイヤーのソースがオリジナルGPKGと同じか判定する。"""
        if not layer or not self.data_manager.original_path:
            return False
        src = layer.source().split('|')[0]
        return os.path.normpath(src) == os.path.normpath(
            self.data_manager.original_path
        )

    def _process_selection(self, layer=None):
        if not self.data_manager.original_layer:
            return

        active_layer = layer or self.iface.activeLayer()
        if not active_layer:
            return
        if not self._is_same_source(active_layer):
            return

        selected = active_layer.selectedFeatures()
        selected = self._get_effective_selection(active_layer, selected)
        if not selected:
            self._clear_table()
            self.lblStatus.setText('地物が選択されていません')
            return

        # 同じGPKGレイヤーなら選択フィーチャーIDをそのまま使う
        if self._is_same_source(active_layer):
            fids = [f.id() for f in selected]
        else:
            # 異なるレイヤーの場合は空間交差で検索
            combined_geom = QgsGeometry()
            for feat in selected:
                if combined_geom.isNull():
                    combined_geom = QgsGeometry(feat.geometry())
                else:
                    combined_geom = combined_geom.combine(feat.geometry())

            if combined_geom.isNull():
                self._clear_table()
                return

            fids = self.data_manager.get_intersecting_fids(combined_geom)

        if not fids:
            self._clear_table()
            self.lblStatus.setText('交差するフィーチャーがありません')
            return

        self._current_fids = fids
        self._update_table(fids)
        self.lblStatus.setText(f'{len(fids)} 件のフィーチャーが見つかりました')

    def _get_effective_selection(self, layer, selected):
        """クリック選択時のみ、重なりフィーチャーを補完する。"""
        if not selected or len(selected) != 1:
            return selected
        if not self._last_canvas_click_point:
            return selected
        if not self._shouban_add_mode:
            if time.time() - self._last_canvas_click_time > 5.0:
                return selected
        if self._last_canvas_click_layer_id and layer:
            if layer.id() != self._last_canvas_click_layer_id:
                return selected

        click_features = self._get_features_at_canvas_point(
            layer, self._last_canvas_click_point
        )
        return click_features or selected

    def _get_features_at_canvas_point(self, layer, point):
        """クリック点周辺の全フィーチャーを取得する。"""
        if not layer or point is None:
            return []

        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        layer_crs = layer.crs()
        if canvas_crs.isValid() and layer_crs.isValid() and canvas_crs != layer_crs:
            transform = QgsCoordinateTransform(
                canvas_crs, layer_crs, QgsProject.instance()
            )
            search_point = transform.transform(point)
        else:
            search_point = point

        map_units_per_pixel = canvas.mapUnitsPerPixel()
        tolerance = map_units_per_pixel * 10
        if canvas_crs.isValid() and layer_crs.isValid() and canvas_crs != layer_crs:
            layer_extent = layer.extent()
            if layer_extent.width() > 0 and canvas.extent().width() > 0:
                scale_ratio = layer_extent.width() / canvas.extent().width()
                tolerance = tolerance * scale_ratio

        search_rect = QgsRectangle(
            search_point.x() - tolerance, search_point.y() - tolerance,
            search_point.x() + tolerance, search_point.y() + tolerance
        )

        request = QgsFeatureRequest().setFilterRect(search_rect)
        search_geom = QgsGeometry.fromPointXY(search_point)
        features = []

        for feat in layer.getFeatures(request):
            geom = feat.geometry()
            if geom.isNull():
                continue
            if geom.intersects(search_geom) or geom.distance(search_geom) <= tolerance:
                features.append(feat)

        return features

    # ──────────────────────────────────────────────
    # テーブル表示
    # ──────────────────────────────────────────────

    def _get_display_cols(self):
        return [c for c, v in self.column_config.items() if v == COLUMN_DISPLAY]

    def _get_edit_cols(self):
        return [c for c, v in self.column_config.items() if v == COLUMN_EDITABLE]

    def _get_visible_cols(self):
        return self._get_display_cols() + self._get_edit_cols()

    def _clear_table(self):
        self._editing = True
        self.tableFeatures.setRowCount(0)
        self.tableFeatures.setColumnCount(0)
        self._current_fids = []
        self._current_merged_data = []
        self._editing = False
        self._update_status_display()

    def _update_table(self, fids):
        self._editing = True

        display_cols = self._get_display_cols()
        edit_cols = self._get_edit_cols()
        visible_cols = self._get_visible_cols()

        if not visible_cols:
            self._clear_table()
            self.lblStatus.setText(
                '表示カラムが設定されていません。カラム設定を行ってください。'
            )
            self._editing = False
            return

        merged = self.data_manager.get_merged_features(fids, display_cols, edit_cols)

        self.tableFeatures.setColumnCount(len(visible_cols))
        self.tableFeatures.setHorizontalHeaderLabels(visible_cols)
        self.tableFeatures.setRowCount(len(merged))

        for row_idx, row_data in enumerate(merged):
            fid = row_data['fid']
            edited_cols = row_data.get('_edited_cols', set())

            for col_idx, col_name in enumerate(visible_cols):
                value = row_data.get(col_name, '')
                item = QTableWidgetItem(str(value) if value is not None else '')
                item.setData(Qt.UserRole, fid)
                item.setData(Qt.UserRole + 1, col_name)

                if col_name in edit_cols:
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    # 色分け: 編集済み=赤、未編集=青
                    if col_name in edited_cols:
                        item.setForeground(COLOR_EDITED)
                    else:
                        item.setForeground(COLOR_EDITABLE)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    # 表示のみ = 黒（デフォルト）

                self.tableFeatures.setItem(row_idx, col_idx, item)

        self.tableFeatures.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.tableFeatures.horizontalHeader().setMinimumSectionSize(100)
        self._editing = False
        self._current_merged_data = merged
        self._update_key1_count()
        self._update_status_display()

    # ──────────────────────────────────────────────
    # セル編集
    # ──────────────────────────────────────────────

    def _on_cell_changed(self, row, col):
        if self._editing:
            return

        item = self.tableFeatures.item(row, col)
        if not item:
            return

        fid = item.data(Qt.UserRole)
        col_name = item.data(Qt.UserRole + 1)
        new_value = item.text()

        edit_cols = self._get_edit_cols()
        if col_name not in edit_cols:
            return

        try:
            self.data_manager.save_edit(fid, col_name, new_value, edit_cols)
            # 編集済み → 赤字に変更
            item.setForeground(COLOR_EDITED)
            # merged data を更新してステータス表示に反映
            for row_data in self._current_merged_data:
                if row_data['fid'] == fid:
                    row_data[col_name] = new_value
                    break
            self._update_status_display()
        except Exception as e:
            QMessageBox.warning(self, '保存エラー', f'編集の保存に失敗しました: {e}')

    # ──────────────────────────────────────────────
    # 計画管理
    # ──────────────────────────────────────────────

    def _set_plan_ui_enabled(self, enabled):
        self.cmbPlan.setEnabled(enabled)
        self.lineEditPlanName.setEnabled(enabled)
        self.btnPlanSave.setEnabled(enabled)
        self.btnPlanDelete.setEnabled(enabled)
        self.btnPlanAddShouban.setEnabled(False)
        self.btnPlanDeleteShouban.setEnabled(False)
        if not enabled:
            self._deactivate_plan()
            self.cmbPlan.clear()
            self.lineEditPlanName.clear()
            self.lblKey1Count.setText('フィーチャー数: -')

    def _refresh_plan_combo(self):
        self.cmbPlan.blockSignals(True)
        self.cmbPlan.clear()
        self.cmbPlan.addItem('-- 計画を選択 --')
        for name in self.data_manager.list_plans():
            self.cmbPlan.addItem(name)
        self.cmbPlan.setCurrentIndex(0)
        self.cmbPlan.blockSignals(False)

    def _on_plan_selected(self, index):
        if index <= 0:
            self._deactivate_plan()
            self._clear_table()
            self.lineEditPlanName.clear()
            self.lblStatus.setText('GPKGレイヤーを選択してください')
            return
        plan_name = self.cmbPlan.currentText()
        plan = self.data_manager.load_plan(plan_name)
        if not plan:
            return

        self.column_config = plan['column_config']
        self._current_fids = plan['fids']
        self.lineEditPlanName.setText(plan_name)

        # ステータス式を復元
        status_exprs = plan.get('status_exprs', {})
        self._status_expr1 = status_exprs.get('expr1', '')
        self._status_expr2 = status_exprs.get('expr2', '')

        self._activate_plan(plan_name)
        self._update_table(self._current_fids)
        self.lblStatus.setText(
            f'計画「{plan_name}」を読み込みました '
            f'({len(self._current_fids)} 件)'
        )

    def _on_plan_save(self):
        name = self.lineEditPlanName.text().strip()
        if not name:
            QMessageBox.warning(self, '保存エラー', '計画名を入力してください。')
            return
        if not self._current_fids:
            QMessageBox.warning(
                self, '保存エラー',
                'テーブルにデータがありません。\n'
                '地物を選択してから保存してください。',
            )
            return

        self.data_manager.save_plan(
            name, self._current_fids, self.column_config,
            self._get_status_exprs(),
        )
        self._refresh_plan_combo()

        # 保存した計画を選択状態にする
        idx = self.cmbPlan.findText(name)
        if idx >= 0:
            self.cmbPlan.blockSignals(True)
            self.cmbPlan.setCurrentIndex(idx)
            self.cmbPlan.blockSignals(False)

        self._activate_plan(name)
        self.lblStatus.setText(f'計画「{name}」を保存しました')

    def _on_plan_delete(self):
        idx = self.cmbPlan.currentIndex()
        if idx <= 0:
            QMessageBox.warning(self, '削除エラー', '削除する計画を選択してください。')
            return
        name = self.cmbPlan.currentText()
        ret = QMessageBox.question(
            self, '確認',
            f'計画「{name}」を削除しますか？',
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return

        self.data_manager.delete_plan(name)
        self._deactivate_plan()
        self.lineEditPlanName.clear()
        self._clear_table()
        self._refresh_plan_combo()
        self.lblStatus.setText(f'計画「{name}」を削除しました')

    def _update_key1_count(self):
        self.lblKey1Count.setText(f'フィーチャー数: {len(self._current_fids)}')

    def _activate_plan(self, name):
        """計画をアクティブ（ロック）状態にする。"""
        self._plan_active = True
        self._active_plan_name = name
        self.btnPlanAddShouban.setEnabled(True)
        self.btnPlanDeleteShouban.setEnabled(True)

    def _deactivate_plan(self):
        """計画のアクティブ状態を解除する。"""
        self._plan_active = False
        self._active_plan_name = None
        self._shouban_add_mode = False
        self.btnPlanAddShouban.setText('フィーチャーの追加')
        self.btnPlanAddShouban.setEnabled(False)
        self.btnPlanDeleteShouban.setEnabled(False)
        if not self._locked:
            self._clear_rubber_bands()

    def _on_plan_add_shouban(self):
        """フィーチャーの追加: 2段階フロー。"""
        if not self._plan_active or not self._active_plan_name:
            return

        if not self._shouban_add_mode:
            # Step 1: 選択モードに入る
            self._shouban_add_mode = True
            self._update_add_mode_button()
            self.lblStatus.setText(
                'メインウィンドウでフィーチャーを選択してください（複数選択可）'
            )
            return

        active_layer = self._get_add_mode_layer()
        if not active_layer:
            self._shouban_add_mode = False
            self.btnPlanAddShouban.setText('フィーチャーの追加')
            self.lblStatus.setText('フィーチャーの追加をキャンセルしました')
            return

        selected = active_layer.selectedFeatures()
        selected = self._get_effective_selection(active_layer, selected)
        if not selected:
            self._shouban_add_mode = False
            self.btnPlanAddShouban.setText('フィーチャーの追加')
            self.lblStatus.setText('フィーチャーの追加をキャンセルしました')
            return

        # 追加対象のfidを取得
        if self._is_same_source(active_layer):
            new_fids = [f.id() for f in selected]
        else:
            combined_geom = QgsGeometry()
            for feat in selected:
                if combined_geom.isNull():
                    combined_geom = QgsGeometry(feat.geometry())
                else:
                    combined_geom = combined_geom.combine(feat.geometry())
            if combined_geom.isNull():
                return
            new_fids = self.data_manager.get_intersecting_fids(combined_geom)

        if not new_fids:
            QMessageBox.information(self, '追加', '追加対象のフィーチャーがありません。')
            return

        # 既存fidsと重複しないものだけ追加
        existing = set(self._current_fids)
        added = [fid for fid in new_fids if fid not in existing]

        if not added:
            self._shouban_add_mode = False
            self.btnPlanAddShouban.setText('フィーチャーの追加')
            self.lblStatus.setText('選択されたフィーチャーはすべて計画に含まれています')
            return

        # 確認ダイアログ
        ret = QMessageBox.question(
            self, '確認',
            f'{len(added)} 件のフィーチャーを追加します。よろしいですか？',
            QMessageBox.Ok | QMessageBox.Cancel,
        )
        if ret != QMessageBox.Ok:
            self._shouban_add_mode = False
            self.btnPlanAddShouban.setText('フィーチャーの追加')
            self.lblStatus.setText('フィーチャーの追加をキャンセルしました')
            return

        self._current_fids = self._current_fids + added

        # 計画を自動保存
        self.data_manager.save_plan(
            self._active_plan_name, self._current_fids, self.column_config,
            self._get_status_exprs(),
        )

        self._update_table(self._current_fids)
        self._clear_rubber_bands()

        # モードをリセット
        self._shouban_add_mode = False
        self.btnPlanAddShouban.setText('フィーチャーの追加')
        self.lblStatus.setText(
            f'{len(added)} 件のフィーチャーを追加しました '
            f'(計 {len(self._current_fids)} 件)'
        )

    def _get_add_mode_layer(self):
        """追加モードで有効なレイヤーを取得する。"""
        active_layer = self.iface.activeLayer()
        if not active_layer:
            return None
        if not self._is_same_source(active_layer):
            return None
        return active_layer

    def _update_add_mode_button(self):
        """追加モード中のボタン表示を選択状態に合わせて更新する。"""
        active_layer = self._get_add_mode_layer()
        selected = active_layer.selectedFeatures() if active_layer else []
        if selected:
            self.btnPlanAddShouban.setText('選択を確定する')
        else:
            self.btnPlanAddShouban.setText('キャンセル')

    def _on_plan_delete_shouban(self):
        """テーブルで選択中のフィーチャーを計画から削除する。"""
        if not self._plan_active or not self._active_plan_name:
            return

        # テーブルで選択されている行からfidを取得
        selected_indexes = self.tableFeatures.selectionModel().selectedIndexes()
        if not selected_indexes:
            QMessageBox.warning(
                self, '削除エラー',
                'テーブルから削除するフィーチャーを選択してください。',
            )
            return

        remove_fids = set()
        for idx in selected_indexes:
            item = self.tableFeatures.item(idx.row(), 0)
            if item:
                fid = item.data(Qt.UserRole)
                if fid is not None:
                    remove_fids.add(fid)

        if not remove_fids:
            return

        # 確認ダイアログ
        ret = QMessageBox.question(
            self, '確認',
            f'選択された {len(remove_fids)} 件のフィーチャーを削除します。よろしいですか？',
            QMessageBox.Ok | QMessageBox.Cancel,
        )
        if ret != QMessageBox.Ok:
            return

        self._current_fids = [
            fid for fid in self._current_fids if fid not in remove_fids
        ]

        # 計画を自動保存
        self.data_manager.save_plan(
            self._active_plan_name, self._current_fids, self.column_config,
            self._get_status_exprs(),
        )

        self._update_table(self._current_fids)
        self._clear_rubber_bands()
        self.lblStatus.setText(
            f'{len(remove_fids)} 件のフィーチャーを削除しました '
            f'(計 {len(self._current_fids)} 件)'
        )

    # ──────────────────────────────────────────────
    # ステータス表示
    # ──────────────────────────────────────────────

    _STATUS_HELP = (
        'QGIS式風の書式（選択行の値を表示）\n\n'
        '"カラム名"  選択行のカラム値\n'
        "'テキスト'  文字列リテラル\n"
        '||  文字列結合    =, !=, >, <  比較\n'
        'if(条件, 真, 偽)  条件分岐\n'
        'round(数値[, 桁])  四捨五入（桁は省略可）\n\n'
        '集計関数（全行対象）:\n'
        '  count() / sum("COL") / unique("COL")\n\n'
        '例: "林班" || \'林班\' || "準林班名" || \'-\' || "小班_親番"'
    )

    def _get_status_exprs(self):
        """現在のステータス式を辞書として返す。"""
        return {'expr1': self._status_expr1, 'expr2': self._status_expr2}

    def _auto_save_plan_status(self):
        """計画アクティブ時にステータス式の変更を自動保存する。"""
        if self._plan_active and self._active_plan_name:
            self.data_manager.save_plan(
                self._active_plan_name, self._current_fids, self.column_config,
                self._get_status_exprs(),
            )

    def _on_status_row1_config(self):
        text, ok = self._edit_status_expr('ステータス1行目', self._status_expr1)
        if ok:
            self._status_expr1 = text
            self._update_status_display()
            self._auto_save_plan_status()

    def _on_status_row2_config(self):
        text, ok = self._edit_status_expr('ステータス2行目', self._status_expr2)
        if ok:
            self._status_expr2 = text
            self._update_status_display()
            self._auto_save_plan_status()

    def _edit_status_expr(self, title, current_text):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setModal(True)

        layout = QVBoxLayout(dlg)

        help_label = QLabel(self._STATUS_HELP, dlg)
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        edit = QPlainTextEdit(dlg)
        edit.setPlainText(current_text or '')
        edit.setTabChangesFocus(True)
        fm = edit.fontMetrics()
        edit.setFixedHeight(fm.lineSpacing() * 2 + 12)
        layout.addWidget(edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        screen = QApplication.primaryScreen()
        if screen:
            max_width = int(screen.availableGeometry().width() * 0.9)
        else:
            max_width = 1200
        target_width = 400
        dlg.resize(min(target_width, max_width), dlg.sizeHint().height())

        if dlg.exec_() == QDialog.Accepted:
            return edit.toPlainText(), True
        return current_text, False

    def _update_status_display(self):
        """ステータス表示ラベルを選択行の式評価結果で更新する。"""
        row_data = self._get_selected_row_data()
        data = self._current_merged_data
        self.lblStatusRow1.setText(
            evaluate_row_expr(self._status_expr1, row_data, data)
        )
        self.lblStatusRow2.setText(
            evaluate_row_expr(self._status_expr2, row_data, data)
        )

    def _get_selected_row_data(self):
        """テーブルで選択中の行のデータを返す。"""
        row_idx = self.tableFeatures.currentRow()
        if row_idx < 0 or row_idx >= len(self._current_merged_data):
            return {}
        return self._current_merged_data[row_idx]

    # ──────────────────────────────────────────────
    # エクスポート
    # ──────────────────────────────────────────────

    def _get_export_fids(self):
        """「計画範囲のみ出力」チェック時は現在のfidsを、未チェック時はNoneを返す。"""
        if self.chkPlanOnly.isChecked():
            if not self._current_fids:
                QMessageBox.warning(
                    self, '出力エラー',
                    'テーブルにデータがありません。\n'
                    '地物を選択または計画を読み込んでから出力してください。',
                )
                return False, None
            return True, self._current_fids
        return True, None

    def _on_export_gpkg(self):
        ok, fids = self._get_export_fids()
        if not ok:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, 'GPKG出力先を選択', '',
            'GeoPackage Files (*.gpkg);;All Files (*)',
        )
        if not path:
            return

        try:
            self.data_manager.export_gpkg(path, fids=fids)
            QMessageBox.information(self, '完了', f'GPKGファイルを出力しました:\n{path}')
        except Exception as e:
            QMessageBox.critical(self, 'エラー', f'GPKG出力に失敗しました: {e}')

    def _on_export_csv(self):
        ok, fids = self._get_export_fids()
        if not ok:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, 'CSV出力先を選択', '',
            'CSV Files (*.csv);;All Files (*)',
        )
        if not path:
            return

        try:
            self.data_manager.export_csv(path, fids=fids)
            QMessageBox.information(self, '完了', f'CSVファイルを出力しました:\n{path}')
        except Exception as e:
            QMessageBox.critical(self, 'エラー', f'CSV出力に失敗しました: {e}')
