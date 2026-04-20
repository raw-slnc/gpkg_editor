# -*- coding: utf-8 -*-
import os
import re
import sip
from datetime import datetime

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidgetItem,
    QMessageBox,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)
from qgis.PyQt.QtCore import Qt, QEvent, QItemSelection, QItemSelectionModel, QTimer, QUrl
from qgis.PyQt.QtGui import QColor, QBrush, QPainter, QPen, QPixmap, QDesktopServices
from qgis.core import (
    QgsProject,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsGeometry,
    QgsLayerTreeGroup,
    QgsPointXY,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
    QgsSingleSymbolRenderer,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsSimpleLineSymbolLayer,
    QgsUnitTypes,
)
from qgis.gui import QgsRubberBand, QgsVertexMarker, QgsMapToolPan, QgsMapToolZoom

from .gpkg_data_manager import GpkgDataManager
from .status_expression import evaluate_row_expr
from .column_config_dialog import (
    ColumnConfigDialog,
    COLUMN_HIDDEN,
    COLUMN_DISPLAY,
    COLUMN_EDITABLE,
    COLUMN_INFO,
)

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), 'gpkg_editor_dockwidget_base.ui')
)

# テキスト色
COLOR_EDITABLE = QBrush(QColor(0, 0, 255))   # 青: 編集可能（未編集）
COLOR_EDITED = QBrush(QColor(255, 0, 0))      # 赤: 編集済み


class GpkgEditorWindow(QWidget, FORM_CLASS):
    """GPKG編集用ウィンドウ。"""

    def __init__(
        self,
        iface,
        plugin_dir=None,
        set_language_callback=None,
        get_language_callback=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setupUi(self)


        self._plugin_dir = plugin_dir or os.path.dirname(__file__)
        self._set_language_callback = set_language_callback
        self._get_language_callback = get_language_callback
        self._language_cycle = ['ja', 'en', 'es', 'pt', 'de']
        self._language_labels = {
            'ja': '日本語',
            'en': 'English',
            'es': 'Español',
            'pt': 'Português',
            'de': 'Deutsch',
        }

        # 左パネル/右パネルをQSplitterに収める
        self._splitter = QSplitter(Qt.Horizontal, self)
        self.mainLayout.removeWidget(self.leftPanel)
        self.mainLayout.removeWidget(self.rightPanel)
        self._splitter.addWidget(self.leftPanel)
        self._splitter.addWidget(self.rightPanel)
        self._splitter.setSizes([380, 820])
        self._splitter.setChildrenCollapsible(True)
        self._splitter.setHandleWidth(0)
        self._splitter.splitterMoved.connect(self._on_splitter_moved)
        self.mainLayout.addWidget(self._splitter)

        # 左パネル開閉チェックボックス
        self.chkPanelClose.toggled.connect(self._on_panel_close_toggled)

        # サムネイルアコーディオン
        self.btnThumbnailToggle.toggled.connect(self._toggle_thumbnail)
        QTimer.singleShot(0, self._apply_thumbnail_closed_height)

        # ショートカットアコーディオン
        self.btnShortcutsToggle.toggled.connect(self._toggle_shortcuts)
        # 描画完了後に初期状態（閉じ）の高さ制約を適用
        QTimer.singleShot(0, self._apply_shortcuts_closed_height)

        self.iface = iface
        self.data_manager = GpkgDataManager()
        self.column_config = {}
        self._current_fids = []
        self._editing = False
        self._locked = False
        self._temp_layer = None
        self._syncing_selection = False
        self._rubber_bands = []
        self._vertex_markers = []
        self._plan_active = False
        self._active_plan_name = None
        self._temp_source_layer_id = None  # 一時レイヤーの元レイヤーID（再利用判定用）
        self._status_expr1 = ''
        self._status_expr2 = ''
        self._current_merged_data = []
        self._feature_add_mode = False  # フィーチャー追加フロー中かどうか
        self._copy_mode = False  # 計画コピーモード中かどうか
        # GPKGレイヤー一覧を初期化
        self._refresh_layer_combo()

        # シグナル接続
        self.cmbGpkgLayer.currentIndexChanged.connect(self._on_layer_selected)
        self.btnColumnConfig.clicked.connect(self._on_column_config)
        self.btnExportGpkg.clicked.connect(self._on_export_gpkg)
        self.btnExportCsv.clicked.connect(self._on_export_csv)
        self.btnLock.toggled.connect(self._on_lock_toggled)
        self.chkLock.toggled.connect(self._on_lock_toggled)
        self.chkOverwrite.toggled.connect(self._on_overwrite_toggled)
        self.chkFullscreen.toggled.connect(self._on_fullscreen_toggled)
        self.btnLanguage.clicked.connect(self._cycle_language)
        self.btnPlanSave.clicked.connect(self._on_plan_save)
        self.btnPlanDelete.clicked.connect(self._on_plan_delete)
        self.btnPlanAddFeature.clicked.connect(self._on_plan_add_feature)
        self.btnPlanDeleteFeature.clicked.connect(self._on_plan_delete_feature)
        self.cmbPlan.currentIndexChanged.connect(self._on_plan_selected)
        self.btnStatusRow1.clicked.connect(self._on_status_row1_config)
        self.btnStatusRow2.clicked.connect(self._on_status_row2_config)
        self.tableFeatures.cellChanged.connect(self._on_cell_changed)

        # 複数選択を有効化（セル編集を維持するため SelectItems のまま）
        self.tableFeatures.setSelectionMode(
            self.tableFeatures.ExtendedSelection
        )

        # テーブルのフレーム枠線を除去（下辺の横線を消す）
        self.tableFeatures.setFrameShape(QFrame.NoFrame)

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
        QgsProject.instance().layersRemoved.connect(self._on_layers_removed)

        # マップ選択変更の監視
        self.iface.mapCanvas().selectionChanged.connect(self._on_selection_changed)
        self.iface.mapCanvas().installEventFilter(self)
        self.iface.mapCanvas().viewport().installEventFilter(self)

        # Shift+スクロール→横スクロール（eventFilter）
        self.tableFeatures.viewport().installEventFilter(self)

        # Enter→編集開始/確定トグル
        self.tableFeatures.installEventFilter(self)

        # 計画コピーモード: ポップアップが閉じたときにキャンセル検知
        self.cmbPlan.view().installEventFilter(self)

        # 履歴パネル
        self._history_mode = False
        self._history_scroll_layout = None
        self._build_history_panel()
        self.btnHistory.setEnabled(False)
        self.btnHistory.toggled.connect(self._on_history_toggled)

        self.retranslate_ui()

        # 前回セッションで保存された一時レイヤーを起動時に削除
        self._cleanup_orphan_temp_layers()

    def _current_language_code(self):
        if self._get_language_callback:
            return self._get_language_callback()
        return 'ja'

    def _update_language_button(self):
        code = self._current_language_code()
        label = self._language_labels.get(code, code)
        self.btnLanguage.setText(f'Language: {label}')

    def _cycle_language(self):
        current = self._current_language_code()
        if current not in self._language_cycle:
            current = 'ja'
        idx = self._language_cycle.index(current)
        next_locale = self._language_cycle[(idx + 1) % len(self._language_cycle)]
        if self._set_language_callback:
            self._set_language_callback(next_locale)
        self.retranslate_ui()

    def retranslate_ui(self):
        # Left panel
        self.groupLayer.setTitle(self.tr('レイヤー'))
        self.lblLayer.setText(self.tr('GPKGレイヤー:'))
        self.cmbGpkgLayer.setToolTip(self.tr('プロジェクト内のGPKGレイヤーを選択'))
        if self.cmbGpkgLayer.count() > 0 and self.cmbGpkgLayer.itemData(0) is None:
            self.cmbGpkgLayer.setItemText(0, self.tr('-- 選択してください --'))
        self.groupPlan.setTitle(self.tr('計画'))
        self.lblPlan.setText(self.tr('計画:'))
        self.lblPlanName.setText(self.tr('計画名:'))
        self.lineEditPlanName.setPlaceholderText(self.tr('計画名を入力...'))
        if self.cmbPlan.count() > 0 and self.cmbPlan.currentIndex() >= 0:
            first_data = self.cmbPlan.itemData(0)
            if first_data is None:
                self.cmbPlan.setItemText(0, self.tr('-- 計画を選択 --'))
        if self._plan_active or self._get_visible_cols():
            self.btnPlanSave.setText(self.tr('登録フィーチャーの確定'))
        else:
            self.btnPlanSave.setText(self.tr('計画作成を開始する'))
        self.btnPlanDelete.setText(self.tr('削除'))
        if not self._feature_add_mode:
            self.btnPlanAddFeature.setText(self.tr('フィーチャーの追加'))
        self.btnPlanDeleteFeature.setText(self.tr('フィーチャーの削除'))
        self.groupOperations.setTitle(self.tr('操作'))
        self.btnColumnConfig.setText(self.tr('カラム設定'))
        self.btnExportGpkg.setText(self.tr('GPKG出力'))
        self.btnExportCsv.setText(self.tr('CSV出力'))
        self.btnLock.setText(self.tr('ロック中') if self._locked else self.tr('ロック'))
        self.chkLock.setText(self.tr('ロック'))
        self.chkOverwrite.setText(self.tr('GPKGレイヤーに上書き保存する'))
        self.chkPlanOnly.setText(self.tr('計画範囲のみ出力'))
        self.groupStatusConfig.setTitle(self.tr('ステータス表示設定'))
        self.btnStatusRow1.setText(self.tr('1行目'))
        self.btnStatusRow2.setText(self.tr('2行目'))
        self.btnThumbnailToggle.setText(
            self.tr('▼ マップサムネイル') if self.btnThumbnailToggle.isChecked()
            else self.tr('▶ マップサムネイル')
        )
        self.btnShortcutsToggle.setText(
            self.tr('▼ ショートカット') if self.btnShortcutsToggle.isChecked()
            else self.tr('▶ ショートカット')
        )
        self.lblDesc2.setText(self.tr('セルをコピー（タブ区切り）'))
        self.lblDesc3.setText(self.tr('クリップボードから貼り付け'))
        self.lblDesc4.setText(self.tr('横スクロール'))
        self.lblDesc5.setText(self.tr('末端セルへ移動'))
        self.lblDesc6.setText(self.tr('末端セルまで選択'))
        self.lblDesc7.setText(self.tr('セル編集モード切替'))

        # Right panel
        self.groupStatusDisplay.setTitle(self.tr('ステータス'))
        self.chkPanelClose.setText(self.tr('パネルを閉じる'))
        self.chkFullscreen.setText(self.tr('全画面表示'))
        self.lblLegendDisplay.setText(self.tr('■ 表示のみ'))
        self.lblLegendEditable.setText(self.tr('■ 編集可能'))
        self.lblLegendEdited.setText(self.tr('■ 編集済み'))
        self.lblLegendInfo.setText(self.tr('■ 情報（後列）'))
        self.btnHistory.setText(self.tr('履歴'))
        self._update_language_button()
        if self._history_mode:
            self._refresh_history_panel()

    def eventFilter(self, obj, event):
        # ロック中: パン・ズームツール操作のみブロック（選択ツール等は通す）
        canvas = self.iface.mapCanvas()
        if self._locked and obj in (canvas, canvas.viewport()):
            if event.type() == QEvent.Wheel:
                return True
            if event.type() in (
                QEvent.MouseButtonPress,
                QEvent.MouseButtonRelease,
                QEvent.MouseButtonDblClick,
                QEvent.MouseMove,
            ):
                tool = canvas.mapTool()
                if isinstance(tool, (QgsMapToolPan, QgsMapToolZoom)):
                    return True

        # Shift+ホイール → 横スクロール
        if obj == self.tableFeatures.viewport() and event.type() == QEvent.Wheel:
            if event.modifiers() == Qt.ShiftModifier:
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

        # Ctrl+(Shift+)矢印キー → 端セルへ移動または範囲選択
        if obj == self.tableFeatures and event.type() == QEvent.KeyPress:
            mods = event.modifiers()
            key = event.key()
            if (mods in (Qt.ControlModifier, Qt.ControlModifier | Qt.ShiftModifier)
                    and key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right)
                    and self.tableFeatures.state() != self.tableFeatures.EditingState):
                current = self.tableFeatures.currentIndex()
                if current.isValid():
                    row, col = current.row(), current.column()
                    if key == Qt.Key_Up:
                        target_row, target_col = 0, col
                    elif key == Qt.Key_Down:
                        target_row, target_col = self.tableFeatures.rowCount() - 1, col
                    elif key == Qt.Key_Left:
                        target_row, target_col = row, 0
                    else:  # Key_Right
                        target_row, target_col = row, self.tableFeatures.columnCount() - 1
                    if mods == (Qt.ControlModifier | Qt.ShiftModifier):
                        target = self.tableFeatures.model().index(target_row, target_col)
                        sel = QItemSelection(current, target)
                        self.tableFeatures.selectionModel().select(
                            sel, QItemSelectionModel.ClearAndSelect
                        )
                    else:
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

        # 計画コピーモード中にポップアップが閉じた → キャンセル
        if obj is self.cmbPlan.view() and event.type() == QEvent.Hide:
            if self._copy_mode:
                QTimer.singleShot(0, self._exit_copy_mode)

        return super().eventFilter(obj, event)

    def _on_visibility_changed(self, visible):
        """ドック非表示（×ボタン）時に選択・ラバーバンドを解除する。
        吸着・分離操作では一時的に False が発火するため、1イベントループ後に判定する。"""
        if not visible:
            QTimer.singleShot(0, self._on_maybe_hidden)

    def _on_maybe_hidden(self):
        """ドックが本当に非表示になった場合のみクリーンアップする。"""
        if not self.isVisible():
            self._remove_temp_layer()
            if self.data_manager.original_layer:
                self.data_manager.original_layer.removeSelection()

    def cleanup(self):
        """プラグイン終了時のリソース解放。unload から呼ばれる。"""
        self._remove_temp_layer()
        try:
            self.iface.mapCanvas().selectionChanged.disconnect(
                self._on_selection_changed
            )
        except TypeError:
            pass
        try:
            QgsProject.instance().layersAdded.disconnect(self._refresh_layer_combo)
            QgsProject.instance().layersRemoved.disconnect(self._on_layers_removed)
        except TypeError:
            pass
        self.data_manager.close()

    # ──────────────────────────────────────────────
    # 左パネル開閉
    # ──────────────────────────────────────────────

    def _on_splitter_moved(self, pos, index):
        """スプリッターのドラッグ操作を禁止して固定位置に戻す。"""
        sizes = self._splitter.sizes()
        total = sum(sizes)
        if sizes[0] > 0:
            # 左パネルが開いている場合は幅を 380 に固定
            self._splitter.setSizes([380, max(0, total - 380)])
        else:
            # 左パネルが閉じている場合はそのまま維持
            self._splitter.setSizes([0, total])

    def _on_panel_close_toggled(self, checked):
        sizes = self._splitter.sizes()
        if checked:
            self._splitter.setSizes([0, sum(sizes)])
        else:
            self._splitter.setSizes([380, max(0, sizes[1] - 380)])

    def _apply_shortcuts_closed_height(self):
        """初期・閉じ時: shortcutsSection をボタン1行分に制限し dock を縮小。
        dock 縮小はフロート時には行わない（表示崩れの原因になるため）。
        """
        h = self.btnShortcutsToggle.height()
        self.shortcutsSection.setMaximumHeight(h if h > 0 else 28)
        dock = self.parentWidget()
        # isFloating() を持つ（QDockWidget）かつ格納中のときのみ高さを強制縮小
        if dock and not getattr(dock, 'isFloating', lambda: True)():
            target = self.rightPanel.sizeHint().height()
            dock.setMaximumHeight(target)
            QTimer.singleShot(100, lambda: dock.setMaximumHeight(16777215))

    def _apply_thumbnail_closed_height(self):
        """初期・閉じ時: thumbnailSection をボタン1行分に制限し dock を縮小。"""
        h = self.btnThumbnailToggle.height()
        self.thumbnailSection.setMaximumHeight(h if h > 0 else 28)
        dock = self.parentWidget()
        if dock and not getattr(dock, 'isFloating', lambda: True)():
            target = self.rightPanel.sizeHint().height()
            dock.setMaximumHeight(target)
            QTimer.singleShot(100, lambda: dock.setMaximumHeight(16777215))

    def _toggle_thumbnail(self, checked):
        self.thumbnailContent.setVisible(checked)
        self.btnThumbnailToggle.setText(
            self.tr('▼ マップサムネイル') if checked else self.tr('▶ マップサムネイル')
        )
        if checked:
            if self.btnShortcutsToggle.isChecked():
                self.btnShortcutsToggle.setChecked(False)
            self.thumbnailSection.setMaximumHeight(16777215)
            QTimer.singleShot(0, self._render_thumbnail)
        else:
            QTimer.singleShot(0, self._apply_thumbnail_closed_height)

    def _update_thumbnail_for_layer(self):
        """レイヤー選択時にポイント判定でサムネイルアコーディオンを制御する。"""
        layer = self.data_manager.original_layer
        is_point = bool(layer and layer.geometryType() == QgsWkbTypes.PointGeometry)
        self.btnThumbnailToggle.setEnabled(not is_point)
        if is_point and self.btnThumbnailToggle.isChecked():
            self.btnThumbnailToggle.setChecked(False)
        if is_point:
            self.btnThumbnailToggle.setText(
                self.tr('▶ マップサムネイル') + '   ' + self.tr('不要')
            )
        else:
            self.btnThumbnailToggle.setText(
                self.tr('▼ マップサムネイル') if self.btnThumbnailToggle.isChecked()
                else self.tr('▶ マップサムネイル')
            )

    def _render_thumbnail(self):
        """計画フィーチャーをサムネイル描画する。"""
        if not self.btnThumbnailToggle.isChecked():
            return

        layer = self.data_manager.original_layer
        all_fids = self._current_fids

        if not layer or not all_fids:
            self.lblThumbnail.clear()
            return

        if layer.geometryType() == QgsWkbTypes.PointGeometry:
            return

        # ウィジェット幅から 16:8 サイズを決定
        w = max(self.lblThumbnail.width(), 80)
        h = w * 8 // 16
        self.lblThumbnail.setFixedHeight(h)

        PADDING = 0.08  # バウンディングボックスに対する余白率

        # 全フィーチャーのジオメトリ取得
        request = QgsFeatureRequest().setFilterFids(all_fids)
        geoms = {}
        for feat in layer.getFeatures(request):
            g = feat.geometry()
            if g and not g.isNull():
                geoms[feat.id()] = g

        if not geoms:
            self.lblThumbnail.clear()
            return

        # バウンディングボックス計算（直接集計、unaryUnion不使用）
        bbox = QgsRectangle()
        for geom in geoms.values():
            bbox.combineExtentWith(geom.boundingBox())

        bw = bbox.width()
        bh = bbox.height()

        # ポイントレイヤーまたは縮退bbox対応
        if bw == 0 and bh == 0:
            cx, cy = bbox.center().x(), bbox.center().y()
            bw = bh = 1.0
            bbox.set(cx - 0.5, cy - 0.5, cx + 0.5, cy + 0.5)
        elif bw == 0:
            bbox.set(bbox.xMinimum() - bh * 0.5, bbox.yMinimum(),
                     bbox.xMaximum() + bh * 0.5, bbox.yMaximum())
            bw = bh
        elif bh == 0:
            bbox.set(bbox.xMinimum(), bbox.yMinimum() - bw * 0.5,
                     bbox.xMaximum(), bbox.yMaximum() + bw * 0.5)
            bh = bw

        # アスペクト比をウィジェットに合わせて調整
        widget_ratio = w / h
        geo_ratio = bw / bh
        if geo_ratio > widget_ratio:
            expand = bw / widget_ratio - bh
            bbox.set(bbox.xMinimum(), bbox.yMinimum() - expand / 2,
                     bbox.xMaximum(), bbox.yMaximum() + expand / 2)
        else:
            expand = bh * widget_ratio - bw
            bbox.set(bbox.xMinimum() - expand / 2, bbox.yMinimum(),
                     bbox.xMaximum() + expand / 2, bbox.yMaximum())

        # 余白を追加
        pad_x = bbox.width() * PADDING
        pad_y = bbox.height() * PADDING
        bbox.set(bbox.xMinimum() - pad_x, bbox.yMinimum() - pad_y,
                 bbox.xMaximum() + pad_x, bbox.yMaximum() + pad_y)

        scale_x = w / bbox.width()
        scale_y = h / bbox.height()

        def to_px(x, y):
            return (
                int((x - bbox.xMinimum()) * scale_x),
                int((bbox.yMaximum() - y) * scale_y),
            )

        # 描画
        pixmap = QPixmap(w, h)
        pixmap.fill(Qt.black)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, False)

        pen_feat = QPen(QColor(255, 255, 255))
        pen_feat.setWidth(1)
        painter.setPen(pen_feat)

        geom_type = layer.geometryType()  # 0=Point, 1=Line, 2=Polygon

        for fid, geom in geoms.items():
            if geom_type == QgsWkbTypes.PointGeometry:
                pt = geom.centroid().asPoint()
                px, py = to_px(pt.x(), pt.y())
                painter.drawEllipse(px - 2, py - 2, 4, 4)
            elif geom_type == QgsWkbTypes.LineGeometry:
                for part in geom.asGeometryCollection() or [geom]:
                    pts = part.asPolyline() or []
                    if not pts:
                        for line in (part.asMultiPolyline() or []):
                            for i in range(len(line) - 1):
                                x0, y0 = to_px(line[i].x(), line[i].y())
                                x1, y1 = to_px(line[i+1].x(), line[i+1].y())
                                painter.drawLine(x0, y0, x1, y1)
                    else:
                        for i in range(len(pts) - 1):
                            x0, y0 = to_px(pts[i].x(), pts[i].y())
                            x1, y1 = to_px(pts[i+1].x(), pts[i+1].y())
                            painter.drawLine(x0, y0, x1, y1)
            else:  # Polygon
                for part in geom.asGeometryCollection() or [geom]:
                    rings = part.asPolygon() or []
                    if not rings:
                        for poly in (part.asMultiPolygon() or []):
                            for ring in poly:
                                for i in range(len(ring) - 1):
                                    x0, y0 = to_px(ring[i].x(), ring[i].y())
                                    x1, y1 = to_px(ring[i+1].x(), ring[i+1].y())
                                    painter.drawLine(x0, y0, x1, y1)
                    else:
                        for ring in rings:
                            for i in range(len(ring) - 1):
                                x0, y0 = to_px(ring[i].x(), ring[i].y())
                                x1, y1 = to_px(ring[i+1].x(), ring[i+1].y())
                                painter.drawLine(x0, y0, x1, y1)

        # 選択フィーチャーのクロスヘア描画
        selected_fids = set(self._get_selected_fids())
        if selected_fids:
            pen_sel = QPen(QColor(255, 80, 80))
            pen_sel.setWidth(1)
            painter.setPen(pen_sel)
            CROSS = 6  # クロスヘアの半径(px)
            for fid in selected_fids:
                if fid in geoms:
                    c = geoms[fid].centroid().asPoint()
                    cx, cy = to_px(c.x(), c.y())
                    painter.drawLine(cx - CROSS, cy, cx + CROSS, cy)
                    painter.drawLine(cx, cy - CROSS, cx, cy + CROSS)

        painter.end()
        self.lblThumbnail.setText('')
        self.lblThumbnail.setPixmap(pixmap)

    def _toggle_shortcuts(self, checked):
        self.shortcutsContent.setVisible(checked)
        self.btnShortcutsToggle.setText(
            self.tr('▼ ショートカット') if checked else self.tr('▶ ショートカット')
        )
        if checked:
            if self.btnThumbnailToggle.isChecked():
                self.btnThumbnailToggle.setChecked(False)
            self.shortcutsSection.setMaximumHeight(16777215)
        else:
            QTimer.singleShot(0, self._apply_shortcuts_closed_height)

    # ──────────────────────────────────────────────
    # GPKGレイヤー コンボボックス
    # ──────────────────────────────────────────────

    def _on_layers_removed(self, layer_ids):
        """レイヤー削除時に一時レイヤーと描画のクリーンアップを行ってからコンボを更新する。"""
        # パターン2: 計画の一時レイヤーが外部から削除された場合
        if self._temp_layer_valid() and self._temp_layer.id() in layer_ids:
            self._clear_rubber_bands()
            self._temp_layer = None
        self._refresh_layer_combo(layer_ids=layer_ids)

    def _refresh_layer_combo(self, *_args, layer_ids=None):
        """プロジェクト内のGPKGレイヤーでコンボボックスを更新する。"""
        prev_id = self.cmbGpkgLayer.currentData()

        self.cmbGpkgLayer.blockSignals(True)
        self.cmbGpkgLayer.clear()
        self.cmbGpkgLayer.addItem(self.tr('-- 選択してください --'), None)

        layer_tree = QgsProject.instance().layerTreeRoot()
        restore_idx = 0
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            # レイヤーツリー（パネル）に存在しないものは除外
            # （他プラグインがレジストリ未削除のままツリーからだけ消した場合の対策）
            if layer_tree.findLayer(layer.id()) is None:
                continue
            # プラグインが内部で作成した一時レイヤーは除外
            if layer.customProperty('gpkg_editor_temp'):
                continue
            src = layer.source().split('|')[0]
            if not src.lower().endswith('.gpkg'):
                continue
            self.cmbGpkgLayer.addItem(layer.name(), layer.id())
            if layer.id() == prev_id:
                restore_idx = self.cmbGpkgLayer.count() - 1

        self.cmbGpkgLayer.setCurrentIndex(restore_idx)
        self.cmbGpkgLayer.blockSignals(False)

        # パターン1: 選択中のGPKGレイヤーが削除されてコンボが index 0 に戻った場合
        # blockSignals中は _on_layer_selected が発火しないため明示的にクリーンアップ
        if restore_idx == 0 and prev_id is not None:
            self._on_layer_selected(0)

    def _on_layer_selected(self, index):
        """コンボボックスでレイヤーが選択された時。"""
        # ロック・計画を解除
        if self._locked:
            self.btnLock.setChecked(False)
        self._deactivate_plan()
        self._remove_temp_layer()  # GPKGが切り替わる場合に一時レイヤーを確実に削除

        layer_id = self.cmbGpkgLayer.currentData()
        if not layer_id:
            self.data_manager.close()
            self.column_config = {}
            self._clear_table()
            self.btnColumnConfig.setEnabled(False)
            self.btnExportGpkg.setEnabled(False)
            self.btnExportCsv.setEnabled(False)
            self.btnLock.setEnabled(False)
            self.chkLock.setEnabled(False)
            self.btnStatusRow1.setEnabled(False)
            self.btnStatusRow2.setEnabled(False)
            self._set_plan_ui_enabled(False)
            self.lblStatus.setText(self.tr('GPKGレイヤーを選択してください'))
            return

        layer = QgsProject.instance().mapLayer(layer_id)
        if not layer:
            return

        src = layer.source()
        parts = src.split('|')
        gpkg_path = parts[0]
        layername = None
        for part in parts[1:]:
            if part.startswith('layername='):
                layername = part[len('layername='):]
                break

        try:
            self.data_manager.load_gpkg(gpkg_path, layername=layername)
        except ValueError as e:
            QMessageBox.critical(self, self.tr('エラー'), str(e))
            return

        # 旧命名パターンのファイルをマイグレーション
        export_folder = self._get_export_folder()
        renamed = self.data_manager.migrate_old_filename_pattern(export_folder)
        if renamed:
            self._migrate_loaded_layer_sources(renamed, export_folder)

        # 孤立データのクリーンアップ（旧バージョンで発生した孤立 edits/export_history を削除）
        self.data_manager.cleanup_orphan_data()

        self.lblStatus.setText(self.tr('読込完了: {}').format(layer.name()))

        columns = self.data_manager.get_original_fields()
        self.column_config = {col: COLUMN_HIDDEN for col in columns}

        self.btnColumnConfig.setEnabled(True)
        self.btnExportGpkg.setEnabled(True)
        self.btnExportCsv.setEnabled(True)
        self.btnLock.setEnabled(True)
        self.chkLock.setEnabled(True)
        self.btnStatusRow1.setEnabled(True)
        self.btnStatusRow2.setEnabled(True)
        self._set_plan_ui_enabled(True)
        self._refresh_plan_combo()
        self.btnPlanSave.setText(self.tr('計画作成を開始する'))
        self._update_thumbnail_for_layer()

        self._clear_table()

    # ──────────────────────────────────────────────
    # カラム設定
    # ──────────────────────────────────────────────

    def _on_column_config(self):
        columns = self.data_manager.get_original_fields()
        dlg = ColumnConfigDialog(columns, self.column_config, self)
        if dlg.exec_() == ColumnConfigDialog.Accepted:
            self.column_config = dlg.get_config()
            self._mark_plan_dirty()
            if self._get_visible_cols():
                self.btnPlanSave.setText(self.tr('登録フィーチャーの確定'))
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
        # 2つのロックUI を同期（シグナルループ防止）
        for widget in (self.btnLock, self.chkLock):
            if widget.isChecked() != checked:
                widget.blockSignals(True)
                widget.setChecked(checked)
                widget.blockSignals(False)
        if checked:
            self.btnLock.setText(self.tr('ロック中'))
        else:
            self.btnLock.setText(self.tr('ロック'))
            if not self._plan_active:
                self._process_selection()
            else:
                self._pan_to_selected()

    def _select_features(self, fids):
        """テーブル選択をレイヤー選択に反映する。"""
        layer = (self._temp_layer if self._temp_layer_valid() else None) or self.data_manager.original_layer
        if not layer:
            return
        self._syncing_selection = True
        layer.selectByIds(fids)
        self._syncing_selection = False

    def _on_fullscreen_toggled(self, checked):
        """全画面表示チェックの切り替え処理。フロート中のみ有効。"""
        dock = self.parentWidget()
        if not dock or not getattr(dock, 'isFloating', lambda: False)():
            self.chkFullscreen.blockSignals(True)
            self.chkFullscreen.setChecked(False)
            self.chkFullscreen.blockSignals(False)
            return
        win = dock.window()
        if checked:
            win.showMaximized()
        else:
            win.showNormal()

    def _on_table_row_changed(self, current, _previous):
        """テーブル行選択→マップ中心移動（ロック中は移動しない）。
        複数選択時は全選択フィーチャーの合算バウンディングボックス中心に移動する。
        """
        if self._locked:
            return
        if not current.isValid():
            return
        if not self.data_manager.original_layer:
            return

        selected_fids = self._get_selected_fids()
        if not selected_fids:
            item = self.tableFeatures.item(current.row(), 0)
            if item:
                fid = item.data(Qt.UserRole)
                if fid is not None:
                    selected_fids = [fid]
        if not selected_fids:
            return

        layer = self.data_manager.original_layer
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        layer_crs = layer.crs()
        need_transform = (
            layer_crs.isValid() and canvas_crs.isValid() and layer_crs != canvas_crs
        )

        def to_canvas_crs(point):
            if need_transform:
                t = QgsCoordinateTransform(layer_crs, canvas_crs, QgsProject.instance())
                try:
                    return t.transform(point)
                except Exception:
                    return None
            return point

        if len(selected_fids) == 1:
            request = QgsFeatureRequest().setFilterFids(selected_fids)
            feat = next(layer.getFeatures(request), None)
            if feat and not feat.geometry().isNull():
                geom = feat.geometry()
                raw = geom.boundingBox().center()
                center = to_canvas_crs(raw)
                if center is not None:
                    canvas.setCenter(center)
                    canvas.refresh()
        else:
            # 複数選択: 全フィーチャーの合算バウンディングボックス中心へ移動
            combined_extent = None
            request = QgsFeatureRequest().setFilterFids(selected_fids)
            for feat in layer.getFeatures(request):
                if feat.geometry().isNull():
                    continue
                bbox = feat.geometry().boundingBox()
                if combined_extent is None:
                    combined_extent = QgsRectangle(bbox)
                else:
                    combined_extent.combineExtentWith(bbox)
            if combined_extent is not None:
                center = to_canvas_crs(combined_extent.center())
                if center is not None:
                    canvas.setCenter(center)
                    canvas.refresh()

    def _on_table_selection_changed(self, selected, deselected):
        """テーブルの選択変更時：ラバーバンド/クロスヘアで表示しパン。"""
        if self._syncing_selection:
            return
        if not self._locked and not self._plan_active:
            return
        fids = self._get_selected_fids()

        # ── ポイントレイヤー専用パス（一時レイヤーなし）──
        is_point = (
            self.data_manager.original_layer and
            self.data_manager.original_layer.geometryType() == QgsWkbTypes.PointGeometry
        )
        if self._plan_active and is_point:
            self._clear_rubber_bands()
            if fids:
                self._show_point_crosshairs(fids)
            self._render_thumbnail()
            self._pan_to_highlights()
            return

        # ── ポリゴン/ライン パス ──
        if self._plan_active and self._temp_layer_valid() and len(fids) == 1:
            # 単体選択: レイヤー選択を解除してラバーバンドで表示
            self._syncing_selection = True
            self._temp_layer.removeSelection()
            self._syncing_selection = False
            self._show_single_rubber_band(fids[0])
        else:
            # 複数選択または選択なし: ラバーバンドをクリアして通常選択
            self._clear_rubber_bands()
            self._select_features(fids)
        self._render_thumbnail()
        self._pan_to_highlights()

    def _pan_to_selected(self):
        """選択フィーチャーの位置にキャンバスを移動する（map→table同期用）。"""
        if self._locked:
            return
        layer = (self._temp_layer if self._temp_layer_valid() else None) or self.data_manager.original_layer
        if not layer:
            return
        if not layer.selectedFeatureIds():
            return
        bbox = layer.boundingBoxOfSelected()
        if bbox.isNull():
            return
        canvas = self.iface.mapCanvas()
        canvas.setCenter(bbox.center())
        canvas.refresh()

    def _pan_to_highlights(self):
        """ラバーバンド/マーカーの位置にキャンバスを移動する（table→map用）。"""
        if self._locked:
            return
        canvas = self.iface.mapCanvas()
        if self._vertex_markers:
            # ハロ+本体の2枚ペアなので偶数インデックスのみ使用
            pts = [self._vertex_markers[i].center()
                   for i in range(0, len(self._vertex_markers), 2)]
            if pts:
                cx = sum(p.x() for p in pts) / len(pts)
                cy = sum(p.y() for p in pts) / len(pts)
                canvas.setCenter(QgsPointXY(cx, cy))
                canvas.refresh()
        elif self._rubber_bands:
            combined = QgsRectangle()
            for rb in self._rubber_bands:
                geom = rb.asGeometry()
                if geom and not geom.isNull():
                    combined.combineExtentWith(geom.boundingBox())
            if not combined.isNull():
                canvas.setCenter(combined.center())
                canvas.refresh()

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
        if self._syncing_selection:
            return
        if self._locked:
            return
        if not self.data_manager.original_layer:
            return
        if self._feature_add_mode:
            self._update_add_mode_button()
            return
        if layer and not self._is_same_source(layer):
            return
        if self._plan_active:
            # 計画アクティブ中: 同一ソースレイヤーの地図選択をテーブルに反映
            if not layer:
                return
            self._clear_rubber_bands()
            selected_ids = set(layer.selectedFeatureIds())
            self._syncing_selection = True
            self.tableFeatures.selectionModel().clearSelection()
            for row in range(self.tableFeatures.rowCount()):
                item = self.tableFeatures.item(row, 0)
                if item:
                    fid = item.data(Qt.UserRole)
                    if fid in selected_ids:
                        self.tableFeatures.selectRow(row)
            self._syncing_selection = False
            if not self._locked:
                self._pan_to_selected()
            return
        self._process_selection(layer)

    def _is_same_source(self, layer):
        """レイヤーのソースがオリジナルGPKGと同じか判定する（パスとレイヤー名の両方を比較）。"""
        if not layer or not self.data_manager.original_path:
            return False
        parts = layer.source().split('|')
        if os.path.normpath(parts[0]) != os.path.normpath(self.data_manager.original_path):
            return False
        # layername が取得できる場合は照合する（単一レイヤーGPKGは layername なしの場合あり）
        layername = None
        for part in parts[1:]:
            if part.startswith('layername='):
                layername = part[len('layername='):]
                break
        if layername is not None and self.data_manager.layer_name:
            return layername == self.data_manager.layer_name
        return True

    def _create_temp_layer(self, plan_name):
        """計画フィーチャーを表示する一時レイヤーを作成してプロジェクトに追加する。"""
        if not self.data_manager.original_path or not self._current_fids:
            return
        # ポイントレイヤーは一時レイヤー不要
        orig = self.data_manager.original_layer
        if orig and orig.geometryType() == QgsWkbTypes.PointGeometry:
            return

        layer_id = self.cmbGpkgLayer.currentData()

        # 同一ソースの一時レイヤーが既にある場合は再利用（GPKGを再オープンしない）
        if (self._temp_layer_valid() and
                self._temp_source_layer_id == layer_id):
            fid_str = ",".join(str(f) for f in self._current_fids) if self._current_fids else "-1"
            self._temp_layer.setName(plan_name)
            self._temp_layer.setSubsetString(f"fid IN ({fid_str})")
            self._temp_layer.triggerRepaint()
            return

        # ソースが変わった or 初回: 既存の一時レイヤーを削除して新規作成
        self._remove_temp_layer()

        # プロジェクトレイヤーの source URI をそのまま使う（テーブル名がファイル名と異なる場合に対応）
        proj_layer = QgsProject.instance().mapLayer(layer_id) if layer_id else None
        if proj_layer:
            source_uri = proj_layer.source()
        else:
            path = self.data_manager.original_path
            layer_name = self.data_manager.layer_name
            source_uri = f"{path}|layername={layer_name}"
        temp = QgsVectorLayer(source_uri, plan_name, "ogr")
        if not temp.isValid():
            return
        # プロジェクトレイヤーのCRSを一時レイヤーに適用
        if proj_layer and proj_layer.crs().isValid():
            temp.setCrs(proj_layer.crs())
        fid_str = ",".join(str(f) for f in self._current_fids)
        temp.setSubsetString(f"fid IN ({fid_str})")
        self._apply_temp_layer_style(temp)
        temp.setCustomProperty('gpkg_editor_temp', True)
        QgsProject.instance().addMapLayer(temp, False)

        # 元のGPKGレイヤーの直上に挿入
        root = QgsProject.instance().layerTreeRoot()
        ref_node = root.findLayer(proj_layer.id()) if proj_layer else None
        if ref_node and ref_node.parent():
            parent = ref_node.parent()
            idx = parent.children().index(ref_node)
            parent.insertLayer(idx, temp)
        else:
            root.insertLayer(0, temp)

        self._temp_layer = temp
        self._temp_source_layer_id = layer_id
        self._temp_layer.selectionChanged.connect(self._on_temp_selection_changed)

    def _cleanup_orphan_temp_layers(self):
        """起動時に前回セッションで残存した一時レイヤーを削除する。"""
        to_remove = [
            lid for lid, layer in QgsProject.instance().mapLayers().items()
            if layer.customProperty('gpkg_editor_temp')
        ]
        for lid in to_remove:
            QgsProject.instance().removeMapLayer(lid)

    def _temp_layer_valid(self):
        """一時レイヤーが存在し C++ オブジェクトが有効かどうかを返す。"""
        return self._temp_layer is not None and not sip.isdeleted(self._temp_layer)

    def _remove_temp_layer(self):
        """一時レイヤーをプロジェクトから削除する。"""
        self._clear_rubber_bands()
        if self._temp_layer_valid():
            try:
                self._temp_layer.selectionChanged.disconnect(self._on_temp_selection_changed)
            except Exception:  # nosec B110
                pass
            QgsProject.instance().removeMapLayer(self._temp_layer.id())
        self._temp_layer = None
        self._temp_source_layer_id = None
        self.iface.mapCanvas().refresh()

    def _update_temp_layer_subset(self):
        """一時レイヤーのフィルタを現在のfidsで更新する。"""
        if not self._temp_layer_valid():
            return
        if not self._current_fids:
            self._temp_layer.setSubsetString('fid IN (-1)')
            return
        fid_str = ",".join(str(f) for f in self._current_fids)
        self._temp_layer.setSubsetString(f"fid IN ({fid_str})")

    def _clear_rubber_bands(self):
        """ラバーバンドとマーカーをすべて削除する。"""
        for rb in self._rubber_bands:
            self.iface.mapCanvas().scene().removeItem(rb)
        self._rubber_bands.clear()
        for vm in self._vertex_markers:
            self.iface.mapCanvas().scene().removeItem(vm)
        self._vertex_markers.clear()

    def _show_point_crosshairs(self, fids):
        """ポイントフィーチャーを白ハロ＋赤本体のクロスヘアで表示する。"""
        layer = self.data_manager.original_layer
        if not layer:
            return
        canvas = self.iface.mapCanvas()
        request = QgsFeatureRequest().setFilterFids(fids)
        for feat in layer.getFeatures(request):
            if feat.geometry().isNull():
                continue
            pt = feat.geometry().centroid().asPoint()
            halo = QgsVertexMarker(canvas)
            halo.setCenter(pt)
            halo.setIconType(QgsVertexMarker.ICON_CROSS)
            halo.setColor(QColor(255, 255, 255, 220))
            halo.setIconSize(16)
            halo.setPenWidth(3)
            self._vertex_markers.append(halo)
            marker = QgsVertexMarker(canvas)
            marker.setCenter(pt)
            marker.setIconType(QgsVertexMarker.ICON_CROSS)
            marker.setColor(QColor(255, 0, 0, 220))
            marker.setIconSize(14)
            marker.setPenWidth(1)
            self._vertex_markers.append(marker)

    def _show_single_rubber_band(self, fid):
        """指定fid のフィーチャーをラバーバンドで表示する。"""
        self._clear_rubber_bands()
        layer = (self._temp_layer if self._temp_layer_valid() else None) if self._plan_active else self.data_manager.original_layer
        if not layer:
            return
        request = QgsFeatureRequest().setFilterFids([fid])
        feat = next(layer.getFeatures(request), None)
        if not feat or feat.geometry().isNull():
            return
        geom_type = layer.geometryType()
        rb = QgsRubberBand(self.iface.mapCanvas(), geom_type)
        rb.setColor(QColor(255, 0, 0, 160))
        rb.setFillColor(QColor(255, 220, 0, 30))
        rb.setWidth(2)
        rb.setToGeometry(feat.geometry(), layer)
        self._rubber_bands.append(rb)

    def _apply_history_layer_style(self, layer):
        """履歴から読み込んだレイヤーにスタイルを適用する（塗りつぶし20%）。"""
        geom_type = layer.geometryType()
        if geom_type == QgsWkbTypes.PolygonGeometry:
            symbol = QgsFillSymbol.createSimple({
                'color': '0,120,255,51',       # 青・不透明度20%（51/255）
                'outline_color': '0,80,180,200',
                'outline_width': '0.4',
                'outline_width_unit': 'Point',
            })
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        elif geom_type == QgsWkbTypes.LineGeometry:
            pt = QgsUnitTypes.RenderPoints
            sl = QgsSimpleLineSymbolLayer(QColor(0, 120, 255, 200), 1.2)
            sl.setWidthUnit(pt)
            symbol = QgsLineSymbol()
            symbol.deleteSymbolLayer(0)
            symbol.appendSymbolLayer(sl)
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        else:
            symbol = QgsMarkerSymbol.createSimple({
                'color': '0,120,255,51',
                'color_border': '0,80,180,200',
                'size': '3',
                'size_unit': 'Point',
            })
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))

    def _apply_temp_layer_style(self, layer):
        """一時レイヤーにスタイルを適用する。"""
        geom_type = layer.geometryType()
        if geom_type == QgsWkbTypes.PolygonGeometry:
            symbol = QgsFillSymbol.createSimple({
                'color': '0,0,0,0',
                'outline_color': '255,0,0,200',
                'outline_width': '0.4',
                'outline_width_unit': 'Point',
            })
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        elif geom_type == QgsWkbTypes.LineGeometry:
            # 黒1.46pt を下層、黄色0.86pt を上層に重ねる
            pt = QgsUnitTypes.RenderPoints
            sl_black = QgsSimpleLineSymbolLayer(QColor(0, 0, 0, 255), 1.7)
            sl_black.setWidthUnit(pt)
            sl_yellow = QgsSimpleLineSymbolLayer(QColor(255, 255, 13, 255), 1.5)
            sl_yellow.setWidthUnit(pt)
            symbol = QgsLineSymbol()
            symbol.deleteSymbolLayer(0)
            symbol.appendSymbolLayer(sl_black)
            symbol.appendSymbolLayer(sl_yellow)
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        else:
            symbol = QgsMarkerSymbol.createSimple({
                'color': '255,0,0,200',
                'color_border': '255,0,0,255',
                'size': '3',
                'size_unit': 'Point',
            })
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))

    def _on_temp_selection_changed(self):
        """一時レイヤーの選択変更をテーブルに反映する。"""
        if self._syncing_selection or not self._temp_layer_valid():
            return
        selected_ids = set(self._temp_layer.selectedFeatureIds())
        # 地図からの選択ではラバーバンドをクリア（レイヤー選択で表示）
        self._clear_rubber_bands()
        self._syncing_selection = True
        self.tableFeatures.selectionModel().clearSelection()
        for row in range(self.tableFeatures.rowCount()):
            item = self.tableFeatures.item(row, 0)
            if item:
                fid = item.data(Qt.UserRole)
                if fid in selected_ids:
                    self.tableFeatures.selectRow(row)
        self._syncing_selection = False
        if not self._locked:
            self._pan_to_selected()

    def _process_selection(self, layer=None):
        if not self.data_manager.original_layer:
            return

        active_layer = layer or self.iface.activeLayer()
        if not active_layer:
            return
        if not self._is_same_source(active_layer):
            return

        selected = active_layer.selectedFeatures()
        if not selected:
            self._clear_table()
            self.lblStatus.setText(self.tr('地物が選択されていません'))
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
            self.lblStatus.setText(self.tr('交差するフィーチャーがありません'))
            return

        self._current_fids = fids
        self._mark_plan_dirty()
        self._update_table(fids)
        self.lblStatus.setText(
            self.tr('{} 件のフィーチャーが見つかりました').format(len(fids))
        )

    # ──────────────────────────────────────────────
    # テーブル表示
    # ──────────────────────────────────────────────

    def _get_display_cols(self):
        return [c for c, v in self.column_config.items() if v == COLUMN_DISPLAY]

    def _get_edit_cols(self):
        return [c for c, v in self.column_config.items() if v == COLUMN_EDITABLE]

    def _get_info_cols(self):
        return [c for c, v in self.column_config.items() if v == COLUMN_INFO]

    def _get_visible_cols(self):
        return self._get_display_cols() + self._get_edit_cols() + self._get_info_cols()

    def _clear_table(self):
        self._editing = True
        self.tableFeatures.setRowCount(0)
        self.tableFeatures.setColumnCount(0)
        self._current_fids = []
        self._current_merged_data = []
        self._editing = False
        self._update_status_display()

    def _update_table(self, fids):
        import time
        from qgis.core import QgsMessageLog, Qgis
        _plan = self._active_plan_name or '(no plan)'
        _ut0 = time.perf_counter()

        self._editing = True

        display_cols = self._get_display_cols()
        edit_cols = self._get_edit_cols()
        info_cols = self._get_info_cols()
        visible_cols = self._get_visible_cols()

        if not visible_cols:
            self._clear_table()
            self.lblStatus.setText(
                self.tr('表示カラムが設定されていません。カラム設定を行ってください。')
            )
            self._editing = False
            return

        merged = self.data_manager.get_merged_features(
            fids, display_cols + info_cols, edit_cols, self._active_plan_name
        )
        _ut1 = time.perf_counter()

        self.tableFeatures.setColumnCount(len(visible_cols))
        self.tableFeatures.setHorizontalHeaderLabels(visible_cols)
        self.tableFeatures.setRowCount(len(merged))
        _ut2 = time.perf_counter()

        self.tableFeatures.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
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

        _ut3 = time.perf_counter()

        self.tableFeatures.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.tableFeatures.horizontalHeader().setMinimumSectionSize(100)
        _ut4 = time.perf_counter()

        self._editing = False
        self._current_merged_data = merged
        self._update_feature_count()
        self._update_status_display()

        QgsMessageLog.logMessage(
            f'[update_table] plan={_plan!r} '
            f'get_merged={_ut1-_ut0:.3f}s '
            f'setup={_ut2-_ut1:.3f}s '
            f'setItem={_ut3-_ut2:.3f}s '
            f'resize={_ut4-_ut3:.3f}s '
            f'total={_ut4-_ut0:.3f}s',
            'GPKG Editor', Qgis.Info
        )

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
            self.data_manager.save_edit(fid, col_name, new_value, edit_cols, self._active_plan_name)
            # 編集済み → 赤字に変更
            item.setForeground(COLOR_EDITED)
            # merged data を更新してステータス表示に反映
            for row_data in self._current_merged_data:
                if row_data['fid'] == fid:
                    row_data[col_name] = new_value
                    break
            self._update_status_display()
        except Exception as e:
            QMessageBox.warning(
                self,
                self.tr('保存エラー'),
                self.tr('編集の保存に失敗しました: {}').format(e),
            )

    # ──────────────────────────────────────────────
    # 計画管理
    # ──────────────────────────────────────────────

    def _set_plan_ui_enabled(self, enabled):
        self.cmbPlan.setEnabled(enabled)
        self.lineEditPlanName.setEnabled(enabled)
        self.btnPlanSave.setEnabled(enabled)
        self.btnPlanDelete.setEnabled(enabled)
        self.btnPlanAddFeature.setEnabled(False)
        self.btnPlanDeleteFeature.setEnabled(False)
        if not enabled:
            self._deactivate_plan()
            self.cmbPlan.clear()
            self.lineEditPlanName.clear()
            self.lblFeatureCount.setText(self.tr('フィーチャー数: -'))

    _COPY_SENTINEL = '__copy_plan__'

    def _enter_copy_mode(self):
        self._copy_mode = True
        self.lblStatus.setText(
            self.tr('コピー元の計画を選択してください（Escでキャンセル）')
        )
        self.cmbPlan.blockSignals(True)
        self.cmbPlan.clear()
        for name in self.data_manager.list_plans():
            self.cmbPlan.addItem(name)
        self.cmbPlan.setCurrentIndex(-1)
        self.cmbPlan.blockSignals(False)
        QTimer.singleShot(0, self.cmbPlan.showPopup)

    def _exit_copy_mode(self):
        if not self._copy_mode:
            return
        self._copy_mode = False
        self._refresh_plan_combo()
        if self._active_plan_name:
            self.lblStatus.setText(
                self.tr('計画「{}」を読み込みました ({} 件)').format(
                    self._active_plan_name, len(self._current_fids)
                )
            )
        else:
            self.lblStatus.setText(self.tr('GPKGレイヤーを選択してください'))

    def _unique_copy_name(self, source_name):
        existing = set(self.data_manager.list_plans())
        i = 0
        while True:
            name = f'{source_name}_{i:03d}'
            if name not in existing:
                return name
            i += 1

    def _mark_plan_dirty(self):
        self.btnPlanSave.setStyleSheet(
            'QPushButton { background-color: #e8a020; color: white; }'
        )

    def _mark_plan_clean(self):
        self.btnPlanSave.setStyleSheet('')

    def _do_copy_plan(self, source_name):
        new_name = self._unique_copy_name(source_name)
        self.data_manager.copy_plan(source_name, new_name)
        self._refresh_plan_combo()
        idx = self.cmbPlan.findText(new_name)
        if idx >= 0:
            self.cmbPlan.setCurrentIndex(idx)

    def _refresh_plan_combo(self):
        self.cmbPlan.blockSignals(True)
        self.cmbPlan.clear()
        self.cmbPlan.addItem(self.tr('-- 計画を選択 --'))
        plans = self.data_manager.list_plans()
        for name in plans:
            self.cmbPlan.addItem(name)
        if plans:
            self.cmbPlan.insertSeparator(self.cmbPlan.count())
            self.cmbPlan.addItem(self.tr('-- 計画をコピーして開始 --'))
            self.cmbPlan.setItemData(
                self.cmbPlan.count() - 1, self._COPY_SENTINEL
            )
        self.cmbPlan.setCurrentIndex(0)
        self.cmbPlan.blockSignals(False)

    def _on_plan_selected(self, index):
        if self._copy_mode:
            if index >= 0:
                source_name = self.cmbPlan.itemText(index)
                self._copy_mode = False
                self._do_copy_plan(source_name)
            return
        if self.cmbPlan.itemData(index) == self._COPY_SENTINEL:
            self._enter_copy_mode()
            return
        if index <= 0:
            self._deactivate_plan()
            self._clear_table()
            self.lineEditPlanName.clear()
            self.lblStatus.setText(self.tr('GPKGレイヤーを選択してください'))
            self.btnPlanSave.setText(self.tr('計画作成を開始する'))
            return
        plan_name = self.cmbPlan.currentText()
        plan = self.data_manager.load_plan(plan_name)
        if not plan:
            return

        raw_config = plan['column_config']
        raw_config.pop('__col_order__', None)  # 旧バージョンの残存キーを除去
        self.column_config = raw_config
        self._current_fids = plan['fids']
        self.lineEditPlanName.setText(plan_name)

        # ステータス式を復元
        status_exprs = plan.get('status_exprs', {})
        self._status_expr1 = status_exprs.get('expr1', '')
        self._status_expr2 = status_exprs.get('expr2', '')

        import time
        _t0 = time.perf_counter()
        self._activate_plan(plan_name)
        _t1 = time.perf_counter()
        self._mark_plan_clean()
        self.btnPlanSave.setText(self.tr('登録フィーチャーの確定'))
        self._update_table(self._current_fids)
        _t2 = time.perf_counter()
        self._render_thumbnail()
        _t3 = time.perf_counter()
        self.lblStatus.setText(
            self.tr('計画「{}」を読み込みました ({} 件)').format(
                plan_name, len(self._current_fids)
            )
        )
        if self._history_mode:
            self._refresh_history_panel()
        _t4 = time.perf_counter()
        from qgis.core import QgsMessageLog, Qgis
        QgsMessageLog.logMessage(
            f'[gpkg_editor] plan={plan_name} '
            f'activate={_t1-_t0:.3f}s '
            f'update_table={_t2-_t1:.3f}s '
            f'thumbnail={_t3-_t2:.3f}s '
            f'history={_t4-_t3:.3f}s '
            f'total={_t4-_t0:.3f}s',
            'GPKG Editor', Qgis.Info
        )

    def _on_plan_save(self):
        name = self.lineEditPlanName.text().strip()
        if not name:
            QMessageBox.warning(
                self, self.tr('保存エラー'), self.tr('計画名を入力してください。')
            )
            return
        if not self._get_visible_cols():
            self.lblStatus.setText(
                self.tr('表示カラムが設定されていません。カラム設定を行ってください。')
            )
            self._on_column_config()
            return
        if not self._current_fids:
            QMessageBox.warning(
                self,
                self.tr('保存エラー'),
                self.tr('テーブルにデータがありません。\n地物を選択してから保存してください。'),
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
        self._mark_plan_clean()
        self.lblStatus.setText(self.tr('計画「{}」を保存しました').format(name))

    def _on_plan_delete(self):
        idx = self.cmbPlan.currentIndex()
        if idx <= 0:
            QMessageBox.warning(
                self, self.tr('削除エラー'), self.tr('削除する計画を選択してください。')
            )
            return
        name = self.cmbPlan.currentText()
        ret = QMessageBox.question(
            self,
            self.tr('確認'),
            self.tr('計画「{}」を削除しますか？').format(name),
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return

        self.data_manager.delete_plan(name)
        self._deactivate_plan()
        self.lineEditPlanName.clear()
        self._clear_table()
        self._refresh_plan_combo()
        self.lblStatus.setText(self.tr('計画「{}」を削除しました').format(name))

    def _update_feature_count(self):
        self.lblFeatureCount.setText(
            self.tr('フィーチャー数: {}').format(len(self._current_fids))
        )

    def _activate_plan(self, name):
        """計画をアクティブ状態にする。"""
        self._plan_active = True
        self._active_plan_name = name
        self.btnPlanAddFeature.setEnabled(True)
        self.btnPlanDeleteFeature.setEnabled(True)
        self.btnHistory.setEnabled(True)
        self._create_temp_layer(name)
        self._zoom_to_plan_extent()

    def _zoom_to_plan_extent(self):
        """計画フィーチャーの範囲にキャンバスをズームする。"""
        if not self._current_fids or not self.data_manager.original_layer:
            return
        layer = (self._temp_layer if self._temp_layer_valid() else None) or self.data_manager.original_layer
        request = QgsFeatureRequest().setFilterFids(self._current_fids)
        extent = QgsRectangle()
        for feat in layer.getFeatures(request):
            if not feat.geometry().isNull():
                extent.combineExtentWith(feat.geometry().boundingBox())
        if extent.isNull():
            return
        canvas = self.iface.mapCanvas()
        layer_crs = layer.crs()
        canvas_crs = canvas.mapSettings().destinationCrs()
        if layer_crs.isValid() and canvas_crs.isValid() and layer_crs != canvas_crs:
            transform = QgsCoordinateTransform(layer_crs, canvas_crs, QgsProject.instance())
            try:
                extent = transform.transformBoundingBox(extent)
            except Exception:  # nosec B110
                pass
        extent.scale(1.1)
        canvas.setExtent(extent)
        canvas.refresh()

    def _deactivate_plan(self):
        """計画のアクティブ状態を解除する。"""
        self._plan_active = False
        self._active_plan_name = None
        self._feature_add_mode = False
        self._mark_plan_clean()
        self.btnPlanAddFeature.setText(self.tr('フィーチャーの追加'))
        self.btnPlanAddFeature.setEnabled(False)
        self.btnPlanDeleteFeature.setEnabled(False)
        # 履歴モードを閉じる
        if self._history_mode:
            self.btnHistory.blockSignals(True)
            self.btnHistory.setChecked(False)
            self.btnHistory.blockSignals(False)
            self._on_history_toggled(False)
        self.btnHistory.setEnabled(False)
        self._remove_temp_layer()
        if self.data_manager.original_layer:
            self.data_manager.original_layer.removeSelection()

    def _on_plan_add_feature(self):
        """フィーチャーの追加: 2段階フロー。"""
        if not self._plan_active or not self._active_plan_name:
            return

        if not self._feature_add_mode:
            # Step 1: 選択モードに入る
            self._feature_add_mode = True
            self._update_add_mode_button()
            self.lblStatus.setText(
                self.tr('メインウィンドウでフィーチャーを選択してください（複数選択可）')
            )
            return

        active_layer = self._get_add_mode_layer()
        if not active_layer:
            self._feature_add_mode = False
            self.btnPlanAddFeature.setText(self.tr('フィーチャーの追加'))
            self.lblStatus.setText(self.tr('フィーチャーの追加をキャンセルしました'))
            return

        selected = active_layer.selectedFeatures()
        if not selected:
            self._feature_add_mode = False
            self.btnPlanAddFeature.setText(self.tr('フィーチャーの追加'))
            self.lblStatus.setText(self.tr('フィーチャーの追加をキャンセルしました'))
            return

        # 追加対象のfidを取得（_get_add_mode_layer は同一ソースのみ返す）
        new_fids = [f.id() for f in selected]

        if not new_fids:
            QMessageBox.information(
                self, self.tr('追加'), self.tr('追加対象のフィーチャーがありません。')
            )
            return

        # 既存fidsと重複しないものだけ追加
        existing = set(self._current_fids)
        added = [fid for fid in new_fids if fid not in existing]

        if not added:
            self._feature_add_mode = False
            self.btnPlanAddFeature.setText(self.tr('フィーチャーの追加'))
            self.lblStatus.setText(
                self.tr('選択されたフィーチャーはすべて計画に含まれています')
            )
            return

        # 確認ダイアログ
        ret = QMessageBox.question(
            self,
            self.tr('確認'),
            self.tr('{} 件のフィーチャーを追加します。よろしいですか？').format(len(added)),
            QMessageBox.Ok | QMessageBox.Cancel,
        )
        if ret != QMessageBox.Ok:
            self._feature_add_mode = False
            self.btnPlanAddFeature.setText(self.tr('フィーチャーの追加'))
            self.lblStatus.setText(self.tr('フィーチャーの追加をキャンセルしました'))
            return

        self._current_fids = self._current_fids + added

        # 計画を自動保存
        self.data_manager.save_plan(
            self._active_plan_name, self._current_fids, self.column_config,
            self._get_status_exprs(),
        )
        self._mark_plan_clean()

        self._update_table(self._current_fids)
        self._update_temp_layer_subset()

        # モードをリセット
        self._feature_add_mode = False
        self.btnPlanAddFeature.setText(self.tr('フィーチャーの追加'))
        self.lblStatus.setText(
            self.tr('{} 件のフィーチャーを追加しました (計 {} 件)').format(
                len(added), len(self._current_fids)
            )
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
            self.btnPlanAddFeature.setText(self.tr('選択を確定する'))
        else:
            self.btnPlanAddFeature.setText(self.tr('キャンセル'))

    def _on_plan_delete_feature(self):
        """テーブルで選択中のフィーチャーを計画から削除する。"""
        if not self._plan_active or not self._active_plan_name:
            return

        # テーブルで選択されている行からfidを取得
        selected_indexes = self.tableFeatures.selectionModel().selectedIndexes()
        if not selected_indexes:
            QMessageBox.warning(
                self,
                self.tr('削除エラー'),
                self.tr('テーブルから削除するフィーチャーを選択してください。'),
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
            self,
            self.tr('確認'),
            self.tr('選択された {} 件のフィーチャーを削除します。よろしいですか？').format(
                len(remove_fids)
            ),
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
        self._mark_plan_clean()

        self._update_table(self._current_fids)
        self._update_temp_layer_subset()
        self.lblStatus.setText(
            self.tr('{} 件のフィーチャーを削除しました (計 {} 件)').format(
                len(remove_fids), len(self._current_fids)
            )
        )

    # ──────────────────────────────────────────────
    # ステータス表示
    # ──────────────────────────────────────────────

    def _status_help_text(self):
        return self.tr(
            'QGIS式風の書式（選択行の値を表示）\n\n'
            '"カラム名"  選択行のカラム値\n'
            "'テキスト'  文字列リテラル\n"
            '||  文字列結合    =, !=, >, <  比較\n'
            'if(条件, 真, 偽)  条件分岐\n'
            'round(数値[, 桁])  四捨五入（桁は省略可）\n\n'
            '集計関数（全行対象）:\n'
            '  count() / sum("COL") / unique("COL")\n\n'
            '例: "名称" || \' - \' || "種別" || \'  (\' || count() || \'件)\''
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
        text, ok = self._edit_status_expr(self.tr('ステータス1行目'), self._status_expr1)
        if ok:
            self._status_expr1 = text
            self._update_status_display()
            self._auto_save_plan_status()

    def _on_status_row2_config(self):
        text, ok = self._edit_status_expr(self.tr('ステータス2行目'), self._status_expr2)
        if ok:
            self._status_expr2 = text
            self._update_status_display()
            self._auto_save_plan_status()

    # 関数挿入ボタンの定義: (ボタンラベル, 挿入テキスト)
    _INSERT_SNIPPETS = [
        ('||',        ' || '),
        ('if()',      'if(, , )'),
        ('round()',   'round(, )'),
        ('count()',   'count()'),
        ('sum()',     'sum("")'),
        ('unique()',  'unique("")'),
    ]

    def _edit_status_expr(self, title, current_text):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setModal(True)

        layout = QVBoxLayout(dlg)

        help_label = QLabel(self._status_help_text(), dlg)
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        edit = QPlainTextEdit(dlg)
        edit.setPlainText(current_text or '')
        edit.setTabChangesFocus(True)
        font = edit.font()
        ps = font.pointSize()
        if ps > 0:
            font.setPointSize(ps + 1)
        edit.setFont(font)
        fm = edit.fontMetrics()
        edit.setFixedHeight(fm.lineSpacing() * 6 + 12)
        layout.addWidget(edit)

        # 関数挿入ボタン
        btn_layout = QHBoxLayout()
        for label, snippet in self._INSERT_SNIPPETS:
            btn = QPushButton(label, dlg)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.clicked.connect(
                lambda _, s=snippet: edit.insertPlainText(s)
            )
            btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)

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
        target_width = 560
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
                    self,
                    self.tr('出力エラー'),
                    self.tr(
                        'テーブルにデータがありません。\n'
                        '地物を選択または計画を読み込んでから出力してください。'
                    ),
                )
                return False, None
            return True, self._current_fids
        return True, None

    def _on_overwrite_toggled(self, checked):
        """上書き保存チェック時は「計画範囲のみ出力」を無効化する。"""
        self.chkPlanOnly.setEnabled(not checked)

    def _on_export_gpkg(self):
        if self.chkOverwrite.isChecked():
            self._overwrite_gpkg()
            return

        ok, fids = self._get_export_fids()
        if not ok:
            return

        plan_name = self._active_plan_name or 'noplan'
        folder = self._get_export_folder()
        num = self._next_export_number(folder, plan_name)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = self._sanitize_filename(plan_name) + '_' + num + '_' + ts + '.gpkg'
        path = os.path.join(folder, filename)

        try:
            self.data_manager.export_gpkg(path, plan_name, fids=fids)
            feature_count = len(fids) if fids is not None else self.data_manager.original_layer.featureCount()
            edited_col_count = self._count_editable_columns()
            try:
                author = os.getlogin()
            except Exception:
                author = ''
            self.data_manager.save_export_history(
                plan_name, filename, 'gpkg', feature_count, edited_col_count, author)
            if self._history_mode:
                self._refresh_history_panel()
            QMessageBox.information(
                self,
                self.tr('完了'),
                self.tr('{} に保存されました').format(path),
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                self.tr('エラー'),
                self.tr('GPKG出力に失敗しました: {}').format(e),
            )

    def _overwrite_gpkg(self):
        """編集内容をQGIS標準編集APIでGPKGに直接書き込む（FID・未編集属性を保持）。"""
        path = self.data_manager.original_path
        if not path:
            return

        layer_id = self.cmbGpkgLayer.currentData()
        layer = QgsProject.instance().mapLayer(layer_id)
        if not layer:
            return

        all_edits = self.data_manager.get_all_edits(self._active_plan_name)
        if not all_edits:
            QMessageBox.information(
                self, self.tr('情報'), self.tr('保存する編集がありません。')
            )
            return

        ret = QMessageBox.warning(
            self,
            self.tr('上書き確認'),
            self.tr(
                '元のGPKGファイルに編集を書き込みます:\n{}\n\n'
                'この操作は取り消せません。よろしいですか？'
            ).format(path),
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return

        try:
            layer.startEditing()
            fields = layer.fields()

            for fid, col_edits in all_edits.items():
                for col_name, value in col_edits.items():
                    field_idx = fields.indexOf(col_name)
                    if field_idx < 0:
                        continue
                    layer.changeAttributeValue(fid, field_idx, value)

            if not layer.commitChanges():
                errors = layer.commitErrors()
                raise Exception('\n'.join(errors))

            # 編集データをクリア（GPKGに反映済み）
            self.data_manager.clear_edits(self._active_plan_name)

            # data_manager の original_layer を再読み込み（キャッシュリセット）
            self.data_manager.load_gpkg(path)

            # テーブルを更新（編集フラグをリセット）
            if self._current_fids:
                self._update_table(self._current_fids)

            self.lblStatus.setText(self.tr('上書き保存が完了しました'))
            QMessageBox.information(
                self,
                self.tr('完了'),
                self.tr('GPKGファイルに編集を書き込みました:\n{}').format(path),
            )
        except Exception as e:
            layer.rollBack()
            QMessageBox.critical(
                self,
                self.tr('エラー'),
                self.tr('上書き保存に失敗しました: {}').format(e),
            )

    def _on_export_csv(self):
        ok, fids = self._get_export_fids()
        if not ok:
            return

        plan_name = self._active_plan_name or 'noplan'
        folder = self._get_export_folder()
        num = self._next_export_number(folder, plan_name)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = self._sanitize_filename(plan_name) + '_' + num + '_' + ts + '.csv'
        path = os.path.join(folder, filename)

        try:
            self.data_manager.export_csv(path, plan_name, fids=fids)
            feature_count = len(fids) if fids is not None else self.data_manager.original_layer.featureCount()
            edited_col_count = self._count_editable_columns()
            try:
                author = os.getlogin()
            except Exception:
                author = ''
            self.data_manager.save_export_history(
                plan_name, filename, 'csv', feature_count, edited_col_count, author)
            if self._history_mode:
                self._refresh_history_panel()
            QMessageBox.information(
                self,
                self.tr('完了'),
                self.tr('{} に保存されました').format(path),
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                self.tr('エラー'),
                self.tr('CSV出力に失敗しました: {}').format(e),
            )

    # ──────────────────────────────────────────────
    # エクスポートユーティリティ
    # ──────────────────────────────────────────────

    def _count_editable_columns(self):
        """現在の column_config で編集モードのカラム数を返す。"""
        return sum(1 for v in self.column_config.values() if v == COLUMN_EDITABLE)

    def _migrate_loaded_layer_sources(self, renamed, export_folder):
        """QGISにロード済みのレイヤーのソースパスを旧→新ファイル名に更新する。"""
        for layer in QgsProject.instance().mapLayers().values():
            src = layer.source()
            for old_name, new_name in renamed.items():
                # QGISのソースURIは常に '/' 区切りのためスラッシュに統一して比較
                old_path = os.path.join(export_folder, old_name).replace('\\', '/')
                if old_path not in src:
                    continue
                new_path = os.path.join(export_folder, new_name).replace('\\', '/')
                new_src = src.replace(old_path, new_path)
                new_stem = os.path.splitext(new_name)[0]
                m = re.search(r'(\d{4}_\d{8}_\d{6})$', new_stem)
                new_layer_name = m.group(1) if m else new_stem
                try:
                    layer.setDataSource(new_src, new_layer_name, layer.providerType())
                except Exception:  # nosec B110
                    pass
                break

    def _get_export_folder(self):
        """出力フォルダ (GPKG_Editor_exports) のパスを返す。なければ作成する。"""
        proj_path = QgsProject.instance().absoluteFilePath()
        if proj_path:
            base_dir = os.path.dirname(proj_path)
        elif self.data_manager.original_path:
            base_dir = os.path.dirname(self.data_manager.original_path)
        else:
            base_dir = os.path.expanduser('~')
        folder = os.path.join(base_dir, 'GPKG_Editor_exports')
        os.makedirs(folder, exist_ok=True)
        return folder

    def _next_export_number(self, folder, plan_name):
        """フォルダ内の既存ファイルをスキャンし、次の通し番号（4桁）を返す。"""
        prefix = self._sanitize_filename(plan_name) + '_'
        pattern = re.compile(
            r'^' + re.escape(prefix) + r'(\d{4})_\d{8}_\d{6}\.(gpkg|csv)$',
            re.IGNORECASE,
        )
        max_num = 0
        if os.path.isdir(folder):
            for fname in os.listdir(folder):
                m = pattern.match(fname)
                if m:
                    max_num = max(max_num, int(m.group(1)))
        return str(max_num + 1).zfill(4)

    @staticmethod
    def _sanitize_filename(name):
        """ファイル名に使えない文字を除去する。"""
        return re.sub(r'[\\/:*?"<>|]', '_', name)

    # ──────────────────────────────────────────────
    # 履歴パネル
    # ──────────────────────────────────────────────

    def _build_history_panel(self):
        """エクスポート履歴パネルを構築して rightPanel の tableFeatures 直後に挿入する。"""
        panel = QWidget()
        vlay = QVBoxLayout(panel)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)

        contents = QWidget()
        self._history_scroll_layout = QVBoxLayout(contents)
        self._history_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._history_scroll_layout.setSpacing(2)
        self._history_scroll_layout.addStretch()
        scroll.setWidget(contents)
        vlay.addWidget(scroll)

        rlay = self.rightPanel.layout()
        for i in range(rlay.count()):
            item = rlay.itemAt(i)
            if item and item.widget() == self.tableFeatures:
                rlay.insertWidget(i + 1, panel)
                break

        panel.setVisible(False)
        self._history_panel = panel

    def _on_history_toggled(self, checked):
        """履歴ボタントグル: 履歴パネルとテーブルを切り替える。"""
        self._history_mode = checked
        if checked:
            self.btnHistory.setStyleSheet(
                'QPushButton { background-color: #4a90d9; color: white; }'
            )
            self.tableFeatures.setVisible(False)
            self._history_panel.setVisible(True)
            self._refresh_history_panel()
        else:
            self.btnHistory.setStyleSheet('')
            self._history_panel.setVisible(False)
            self.tableFeatures.setVisible(True)

    def _refresh_history_panel(self):
        """エクスポート履歴パネルを再構築する（新しい順）。"""
        lay = self._history_scroll_layout
        while lay.count() > 1:
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        records = []
        if self._active_plan_name:
            records = self.data_manager.list_export_history(self._active_plan_name)

        if not records:
            lbl = QLabel(self.tr('エクスポート履歴はありません'))
            lbl.setStyleSheet('color: #999999; font-size: 11px;')
            lbl.setAlignment(Qt.AlignCenter)
            lay.insertWidget(0, lbl)
            return

        folder = self._get_export_folder()
        for rec in records:
            if rec['is_deleted']:
                widget = self._build_export_history_deleted_row(rec)
            elif not os.path.exists(os.path.join(folder, rec['filename'])):
                widget = self._build_export_history_missing_row(rec)
            else:
                widget = self._build_export_history_row(rec)
            lay.insertWidget(lay.count() - 1, widget)

    def _build_export_history_missing_row(self, rec):
        """ファイルがディレクトリから削除された場合の1行メッセージ行を返す。"""
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet(
            'QFrame { border: 1px solid #dddddd; border-radius: 3px; background: #fff8e1; }'
        )
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(6, 4, 6, 4)
        msg = self.tr('{}はディレクトリから削除されました。').format(rec['filename'])
        lbl = QLabel(msg)
        lbl.setStyleSheet('font-size: 11px; color: #b8860b;')
        lay.addWidget(lbl)
        return frame

    def _build_export_history_deleted_row(self, rec):
        """削除済みレコードの1行メッセージ行を返す。"""
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet(
            'QFrame { border: 1px solid #dddddd; border-radius: 3px; background: #f8f8f8; }'
        )
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(6, 4, 6, 4)
        msg = self.tr('{}は削除されました。').format(rec['filename'])
        lbl = QLabel(msg)
        lbl.setStyleSheet('font-size: 11px; color: #999999;')
        lay.addWidget(lbl)
        return frame

    def _build_export_history_row(self, rec):
        """エクスポート履歴1行のウィジェットを返す。"""
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet('QFrame { border: 1px solid #cccccc; border-radius: 3px; }')

        grid = QGridLayout(frame)
        grid.setContentsMargins(4, 3, 4, 3)
        grid.setSpacing(3)
        grid.setColumnStretch(1, 1)

        is_gpkg = rec['file_type'] == 'gpkg'
        info = (f"{rec['filename']}  |  {rec['exported_at']}  |  "
                f"{rec['feature_count']}{self.tr('件')}  |  "
                f"{rec['edited_col_count']}{self.tr('編集列')}")
        lbl_info = QLabel(info)
        lbl_info.setStyleSheet('font-size: 11px;')
        lbl_info.setWordWrap(False)
        lbl_info.setFixedHeight(18)

        btn_action = QPushButton(self.tr('読込') if is_gpkg else self.tr('表示'))
        btn_action.setFixedHeight(22)
        btn_action.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        btn_delete = QPushButton(self.tr('削除'))
        btn_delete.setFixedHeight(22)
        btn_delete.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        edit_author = QLineEdit(rec['author'])
        edit_author.setPlaceholderText(self.tr('計画者'))
        edit_author.setFixedHeight(22)
        edit_memo = QLineEdit(rec['memo'])
        edit_memo.setPlaceholderText(self.tr('メモ'))
        edit_memo.setFixedHeight(22)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(2)
        btn_col.addWidget(btn_action)
        btn_col.addWidget(btn_delete)
        btn_widget = QWidget()
        btn_widget.setLayout(btn_col)
        btn_widget.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        author_memo = QHBoxLayout()
        author_memo.setSpacing(4)
        author_memo.addWidget(edit_author)
        author_memo.addWidget(edit_memo)

        right_col = QVBoxLayout()
        right_col.setSpacing(2)
        right_col.addWidget(lbl_info)
        right_col.addLayout(author_memo)
        right_widget = QWidget()
        right_widget.setLayout(right_col)

        grid.addWidget(btn_widget,   0, 0, 2, 1)
        grid.addWidget(right_widget, 0, 1, 2, 1)

        rec_id = rec['id']
        rec_filename = rec['filename']
        frame._filename = rec_filename

        if is_gpkg:
            btn_action.clicked.connect(
                lambda _, rid=rec_id, fn=rec_filename, f=frame:
                    self._on_export_history_load(rid, fn, f))
        else:
            btn_action.clicked.connect(
                lambda _, fn=rec_filename, f=frame:
                    self._on_export_history_show(fn, f))

        btn_delete.clicked.connect(
            lambda _, rid=rec_id, f=frame: self._on_export_history_delete(rid, f))

        edit_author.editingFinished.connect(
            lambda rid=rec_id, w=edit_author: self.data_manager.update_export_history_field(
                rid, 'author', w.text()))
        edit_memo.editingFinished.connect(
            lambda rid=rec_id, w=edit_memo: self.data_manager.update_export_history_field(
                rid, 'memo', w.text()))

        return frame

    @staticmethod
    def _grayout_row(frame):
        """履歴行をグレーアウトして操作不可にする。"""
        frame.setStyleSheet(
            'QFrame { border: 1px solid #dddddd; border-radius: 3px; background: #f0f0f0; }'
        )
        frame.setEnabled(False)

    def _on_export_history_load(self, record_id, filename, frame):
        """GPKG エクスポート履歴を QGIS レイヤーとして読み込む（計画レイヤー直下）。"""
        folder = self._get_export_folder()
        path = os.path.join(folder, filename)
        if not os.path.exists(path):
            QMessageBox.warning(self, self.tr('エラー'),
                                self.tr('ファイルが見つかりません:\n{}').format(path))
            self._grayout_row(frame)
            return

        stem = os.path.splitext(filename)[0]
        m = re.search(r'(\d{4}_\d{8}_\d{6})$', stem)
        layer_name = m.group(1) if m else stem
        layer = QgsVectorLayer(path, layer_name, 'ogr')
        if not layer.isValid():
            QMessageBox.warning(self, self.tr('エラー'),
                                self.tr('レイヤーの読み込みに失敗しました:\n{}').format(path))
            self._grayout_row(frame)
            return
        self._apply_history_layer_style(layer)

        QgsProject.instance().addMapLayer(layer, False)

        # 計画レイヤーの直上に "[計画名] Group" グループを作り、その中に挿入
        group_name = '{} Group'.format(self._active_plan_name or layer_name)
        root = QgsProject.instance().layerTreeRoot()
        ref_node = None
        if self._temp_layer_valid():
            ref_node = root.findLayer(self._temp_layer.id())

        if ref_node and ref_node.parent():
            parent = ref_node.parent()
            idx = parent.children().index(ref_node)
            # 同名グループが既にあれば再利用、なければ計画レイヤーの直上に新規作成
            group = None
            for child in parent.children():
                if isinstance(child, QgsLayerTreeGroup) and child.name() == group_name:
                    group = child
                    break
            if group is None:
                group = parent.insertGroup(idx, group_name)
        else:
            # 計画レイヤーが見つからない場合はルート先頭にグループを作成
            group = None
            for child in root.children():
                if isinstance(child, QgsLayerTreeGroup) and child.name() == group_name:
                    group = child
                    break
            if group is None:
                group = root.insertGroup(0, group_name)

        group.addLayer(layer)

    def _on_export_history_show(self, filename, frame):
        """CSV エクスポート履歴をファイルマネージャーで表示する。"""
        folder = self._get_export_folder()
        path = os.path.join(folder, filename)
        if not os.path.exists(path):
            QMessageBox.warning(self, self.tr('エラー'),
                                self.tr('ファイルが見つかりません:\n{}').format(path))
            self._grayout_row(frame)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def _on_export_history_delete(self, record_id, frame):
        """エクスポート履歴レコードを削除する（確認あり）。ファイル実体も削除しソフトデリート。"""
        filename = getattr(frame, '_filename', '')
        folder = self._get_export_folder()
        path = os.path.join(folder, filename)

        # プロジェクト内でこのファイルを使用中のレイヤーを検索
        using_layers = [
            layer for layer in QgsProject.instance().mapLayers().values()
            if os.path.normpath(layer.source().split('|')[0]) == os.path.normpath(path)
        ]

        if using_layers:
            msg = self.tr(
                'このファイルはレイヤーで使用中です。\n'
                '削除するとレイヤーも除去されます。\n\n'
                '削除しますか？'
            )
        else:
            msg = self.tr('この履歴レコードを削除しますか？')

        ret = QMessageBox.question(
            self,
            self.tr('削除の確認'),
            msg,
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return

        # 使用中レイヤーをプロジェクトから除去
        for layer in using_layers:
            QgsProject.instance().removeMapLayer(layer.id())

        # ファイル実体を削除
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:  # nosec B110
                pass

        # DB をソフトデリート
        self.data_manager.delete_export_history(record_id)

        # 行の中身を「削除されました」1行メッセージに差し替え
        old_layout = frame.layout()
        while old_layout.count():
            item = old_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                sub = item.layout()
                while sub.count():
                    si = sub.takeAt(0)
                    if si.widget():
                        si.widget().deleteLater()

        msg = self.tr('{}は削除されました。').format(filename)
        lbl = QLabel(msg)
        lbl.setStyleSheet('font-size: 11px; color: #999999; padding: 4px;')
        old_layout.addWidget(lbl)
        frame.setStyleSheet(
            'QFrame { border: 1px solid #dddddd; border-radius: 3px; background: #f8f8f8; }'
        )
