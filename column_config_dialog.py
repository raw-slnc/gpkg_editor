# -*- coding: utf-8 -*-
import os
import math

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import (
    QDialog,
    QPushButton,
    QLabel,
    QGridLayout,
    QSizePolicy,
    QSpacerItem,
)
from qgis.PyQt.QtCore import Qt

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), 'column_config_dialog_base.ui')
)

COLUMN_HIDDEN = '非表示'
COLUMN_DISPLAY = '表示のみ'
COLUMN_EDITABLE = '表示＋編集'

_STATES = [COLUMN_HIDDEN, COLUMN_DISPLAY, COLUMN_EDITABLE]
_BTN_TEXT = {COLUMN_HIDDEN: '非表示', COLUMN_DISPLAY: '表示', COLUMN_EDITABLE: '編集'}
_BTN_STYLE = {
    COLUMN_HIDDEN: 'QPushButton{background:#cccccc;color:#666666;border:1px solid #aaa;padding:2px 8px;}',
    COLUMN_DISPLAY: 'QPushButton{background:#4a90d9;color:white;border:1px solid #357abd;padding:2px 8px;}',
    COLUMN_EDITABLE: 'QPushButton{background:#27ae60;color:white;border:1px solid #1e8449;padding:2px 8px;}',
}

_FILTER_ALL = '全て'
_FILTER_DISPLAY = '表示のみ'
_FILTER_EDITABLE = '表示編集のみ'
_FILTER_HIDDEN = '選択無し'
_FILTERS = [_FILTER_ALL, _FILTER_DISPLAY, _FILTER_EDITABLE, _FILTER_HIDDEN]


class ColumnConfigDialog(QDialog, FORM_CLASS):
    """カラムの表示・編集設定をトグルボタンで行うモーダルダイアログ。

    2カラム×20行のページ表示。
    各項目のボタンをクリック/Spaceで 非表示→表示→編集 を巡回。
    右下のフィルタボタンで表示対象を絞り込み。
    """

    ROWS_PER_PAGE = 20
    GRID_COLS = 2
    ITEMS_PER_PAGE = ROWS_PER_PAGE * GRID_COLS

    def __init__(self, columns, current_config=None, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.columns = list(columns)
        self._config = {}
        for col in self.columns:
            self._config[col] = (current_config or {}).get(col, COLUMN_HIDDEN)

        self._current_page = 0
        self._current_filter_idx = 0
        self._grid_widgets = []

        self._grid_layout = QGridLayout(self.gridContainer)
        self._grid_layout.setSpacing(2)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)

        # 下部エリアを左右50:50に分割
        self.bottomArea.setStretch(0, 1)  # spacer
        self.bottomArea.setStretch(1, 1)  # rightControls

        self.btnPrev.clicked.connect(self._prev_page)
        self.btnNext.clicked.connect(self._next_page)
        self.btnFilter.clicked.connect(self._cycle_filter)

        self._rebuild_grid()

    def _get_filtered_columns(self):
        f = _FILTERS[self._current_filter_idx]
        if f == _FILTER_ALL:
            return self.columns
        elif f == _FILTER_DISPLAY:
            return [c for c in self.columns if self._config[c] == COLUMN_DISPLAY]
        elif f == _FILTER_EDITABLE:
            return [c for c in self.columns if self._config[c] == COLUMN_EDITABLE]
        elif f == _FILTER_HIDDEN:
            return [c for c in self.columns if self._config[c] == COLUMN_HIDDEN]
        return self.columns

    def _total_pages(self, filtered):
        return max(1, math.ceil(len(filtered) / self.ITEMS_PER_PAGE))

    def _clear_grid(self):
        for widgets in self._grid_widgets:
            for w in widgets:
                self._grid_layout.removeWidget(w)
                w.setParent(None)
        self._grid_widgets.clear()
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

    def _rebuild_grid(self):
        self._clear_grid()

        filtered = self._get_filtered_columns()
        total_pages = self._total_pages(filtered)
        self._current_page = max(0, min(self._current_page, total_pages - 1))

        start = self._current_page * self.ITEMS_PER_PAGE
        end = min(start + self.ITEMS_PER_PAGE, len(filtered))
        page_items = filtered[start:end]

        # Build original index map for numbering
        col_indices = {c: i + 1 for i, c in enumerate(self.columns)}

        for i, col_name in enumerate(page_items):
            grid_col = i // self.ROWS_PER_PAGE
            grid_row = i % self.ROWS_PER_PAGE

            num = col_indices[col_name]
            label = QLabel(f'{num}: {col_name}')
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

            btn = QPushButton()
            btn.setMinimumWidth(60)
            btn.setFocusPolicy(Qt.StrongFocus)
            self._apply_btn_state(btn, self._config[col_name])
            btn.clicked.connect(
                lambda _, cn=col_name, b=btn: self._cycle_state(cn, b)
            )

            base_col = grid_col * 2
            self._grid_layout.addWidget(label, grid_row, base_col)
            self._grid_layout.addWidget(btn, grid_row, base_col + 1)
            self._grid_widgets.append((label, btn))

        # Column stretch: labels expand, buttons don't
        self._grid_layout.setColumnStretch(0, 1)
        self._grid_layout.setColumnStretch(1, 0)
        self._grid_layout.setColumnStretch(2, 1)
        self._grid_layout.setColumnStretch(3, 0)

        # Vertical spacer to push items up
        max_row = min(len(page_items), self.ROWS_PER_PAGE)
        spacer = QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding)
        self._grid_layout.addItem(spacer, max_row, 0)

        # Navigation state
        self.lblPage.setText(f'{self._current_page + 1}/{total_pages}')
        self.btnPrev.setEnabled(self._current_page > 0)
        self.btnNext.setEnabled(self._current_page < total_pages - 1)
        self.btnFilter.setText(_FILTERS[self._current_filter_idx])

    def _apply_btn_state(self, btn, state):
        btn.setText(_BTN_TEXT[state])
        btn.setStyleSheet(_BTN_STYLE[state])

    def _cycle_state(self, col_name, btn):
        current = self._config[col_name]
        idx = _STATES.index(current)
        next_state = _STATES[(idx + 1) % len(_STATES)]
        self._config[col_name] = next_state
        self._apply_btn_state(btn, next_state)

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._rebuild_grid()

    def _next_page(self):
        filtered = self._get_filtered_columns()
        if self._current_page < self._total_pages(filtered) - 1:
            self._current_page += 1
            self._rebuild_grid()

    def _cycle_filter(self):
        self._current_filter_idx = (self._current_filter_idx + 1) % len(_FILTERS)
        self._current_page = 0
        self._rebuild_grid()

    def get_config(self):
        return dict(self._config)

    def get_display_columns(self):
        return [c for c, v in self._config.items() if v == COLUMN_DISPLAY]

    def get_editable_columns(self):
        return [c for c, v in self._config.items() if v == COLUMN_EDITABLE]

    def get_visible_columns(self):
        return [
            c for c, v in self._config.items()
            if v in (COLUMN_DISPLAY, COLUMN_EDITABLE)
        ]
