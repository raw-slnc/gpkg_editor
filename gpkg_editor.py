# -*- coding: utf-8 -*-
import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QDialog, QDockWidget, QVBoxLayout
from qgis.PyQt.QtCore import (
    QCoreApplication, QSettings, Qt, QTimer, QTranslator,
)
from qgis.core import QgsApplication, QgsProject


class GpkgEditor:
    """GPKG Editorプラグインのメインクラス。"""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = self.tr('GPKG Editor')
        self.dock = None
        self.dialog = None
        self.window = None
        self._translator = None
        self._active_locale = 'ja'
        self._switching_container = False

    @staticmethod
    def tr(message):
        return QCoreApplication.translate('GpkgEditor', message)

    def _detect_locale_candidates(self):
        raw = str(QSettings().value('locale/userLocale', 'en'))
        normalized = raw.replace('-', '_').split('.', 1)[0].split('@', 1)[0]
        lang = normalized.split('_')[0].lower()
        region = normalized.split('_')[1].upper() if '_' in normalized else ''

        candidates = []
        if lang and lang != 'en':
            if region:
                candidates.append(f'{lang}_{region}')
            candidates.append(lang)
        return candidates

    def _install_translator(self):
        self.set_language(None)

    def _remove_translator(self):
        if self._translator:
            QCoreApplication.removeTranslator(self._translator)
            self._translator = None

    def get_active_locale(self):
        return self._active_locale

    def _locale_candidates(self, locale):
        if locale is None:
            return self._detect_locale_candidates()
        normalized = (
            str(locale).replace('-', '_').split('.', 1)[0].split('@', 1)[0]
        )
        if normalized in ('ja', ''):
            return []
        if normalized == 'en':
            return ['en']
        if '_' in normalized:
            lang, region = normalized.split('_', 1)
            return [f'{lang.lower()}_{region.upper()}', lang.lower()]
        return [normalized.lower()]

    def set_language(self, locale):
        """Switch plugin translation at runtime. locale=None uses system
        locale."""
        if locale is not None:
            QSettings().setValue('gpkg_editor/language', locale)
        self._remove_translator()
        loaded_locale = 'ja'
        i18n_dir = os.path.join(self.plugin_dir, 'i18n')
        for cand in self._locale_candidates(locale):
            qm_path = os.path.join(i18n_dir, f'gpkg_editor_{cand}.qm')
            if not os.path.exists(qm_path):
                continue
            translator = QTranslator()
            if translator.load(qm_path):
                QCoreApplication.installTranslator(translator)
                self._translator = translator
                loaded_locale = cand
                break
        if locale in ('en', 'ja'):
            loaded_locale = locale
        self._active_locale = loaded_locale

        # Refresh already-created top-level labels.
        if self.actions:
            self.actions[0].setText(self.tr('GPKG Editor'))
        if self.dock:
            self.dock.setWindowTitle(self.tr('GPKG Editor'))
        if self.dialog:
            self.dialog.setWindowTitle(self.tr('GPKG Editor'))
        if self.window and hasattr(self.window, 'retranslate_ui'):
            self.window.retranslate_ui()

    def initGui(self):
        """プラグインUIを初期化する。"""
        saved = QSettings().value('gpkg_editor/language', None)
        self.set_language(saved)
        self.menu = self.tr('GPKG Editor')
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        icon = QIcon(icon_path)
        action = QAction(icon, self.tr('GPKG Editor'), self.iface.mainWindow())
        action.triggered.connect(self.run)
        action.setEnabled(True)

        self.iface.addVectorToolBarIcon(action)
        self.iface.addPluginToVectorMenu(self.menu, action)
        self.actions.append(action)

        QgsApplication.instance().aboutToQuit.connect(self._on_about_to_quit)
        QgsProject.instance().readProject.connect(self._on_project_read)

    def _on_about_to_quit(self):
        """QGIS終了時のフック。ドック/別ウィンドウを閉じずに残したまま終了した
        場合でも、実行中のプロジェクトから一時（計画）レイヤーを外しておく
        （終了時点で既に保存済みのファイルまでは書き戻せないため、あくまで
        メモリ上のクリーンアップ。ファイル側の保険は_on_project_read側）。"""
        if self.window is not None:
            self.window._remove_temp_layer()

    def _on_project_read(self, *_args):
        """プロジェクト読み込み時のフック。一時レイヤーが残ったまま保存された
        プロジェクトを開いた場合に備え、読み込み直後に一時レイヤーを削除する。
        gpkg_editorのウィンドウを一度も開いていないセッションでも効くよう、
        ウィンドウ生成を待たずここで直接呼ぶ。readProjectシグナルのハンドラ内は
        QGIS本体側のプロジェクト読み込み処理（スナッピング設定の構築等）がまだ
        完了しきっていない可能性があるため、1イベントループ後に遅延実行する
        （removeMapLayerを呼んでもスナッピング設定側に反映されないタイミング問題を回避）。"""
        from .gpkg_editor_dockwidget import GpkgEditorWindow
        QTimer.singleShot(0, GpkgEditorWindow._cleanup_orphan_temp_layers)

    def unload(self):
        """プラグインをアンロードする。"""
        try:
            QgsApplication.instance().aboutToQuit.disconnect(
                self._on_about_to_quit
            )
        except TypeError:
            pass
        try:
            QgsProject.instance().readProject.disconnect(
                self._on_project_read
            )
        except TypeError:
            pass

        for action in self.actions:
            self.iface.removePluginVectorMenu(self.menu, action)
            self.iface.removeVectorToolBarIcon(action)
        self.actions = []

        if self.window:
            self.window.cleanup()
        if self.dialog:
            self._save_dialog_geometry()
            self.dialog.hide()
            self.dialog.deleteLater()
            self.dialog = None
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        self.window = None
        self._remove_translator()

    def _ensure_window(self):
        if self.window is None:
            from .gpkg_editor_dockwidget import (
                GpkgEditorWindow,
            )
            self.window = GpkgEditorWindow(
                self.iface,
                self.plugin_dir,
                self.set_language,
                self.get_active_locale,
            )
            self.window.set_window_mode_callback(self._set_window_mode)

    def _create_dock(self):
        if self.dock is not None:
            return
        from .gpkg_editor_dockwidget import GpkgEditorDockWidget

        self._ensure_window()
        self.dock = GpkgEditorDockWidget(
            self.tr('GPKG Editor'), self.iface.mainWindow()
        )
        self.dock.setObjectName('GpkgEditorDock')
        self.dock.setWidget(self.window)
        self.window.attach_dock_widget(self.dock)
        self.dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea
            | Qt.DockWidgetArea.TopDockWidgetArea
        )
        self.dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.iface.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self.dock
        )
        self.dock.visibilityChanged.connect(
            self.window._on_visibility_changed
        )

    def _create_dialog(self):
        if self.dialog is not None:
            return
        self._ensure_window()
        self.dialog = QDialog(None, Qt.WindowType.Window)
        self.dialog.setObjectName('GpkgEditorWindow')
        self.dialog.setWindowTitle(self.tr('GPKG Editor'))
        layout = QVBoxLayout(self.dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.window)
        self.window.attach_window_dialog(self.dialog)
        self.window.show()
        geometry = QSettings().value('gpkg_editor/window_geometry', None)
        if geometry:
            self.dialog.restoreGeometry(geometry)
        else:
            self.dialog.resize(1200, 600)
        self.dialog.finished.connect(self._on_dialog_finished)

    def _save_dialog_geometry(self):
        if self.dialog is not None:
            QSettings().setValue(
                'gpkg_editor/window_geometry', self.dialog.saveGeometry()
            )

    def _set_window_mode(self, enabled):
        self._ensure_window()
        self._switching_container = True
        self.window.set_hide_cleanup_suspended(True)
        try:
            if enabled:
                if self.dock is not None:
                    try:
                        self.dock.visibilityChanged.disconnect(
                            self.window._on_visibility_changed
                        )
                    except TypeError:
                        pass
                    self.dock.setWidget(None)
                    self.iface.removeDockWidget(self.dock)
                    self.dock.deleteLater()
                    self.dock = None
                self._create_dialog()
                self.dialog.show()
                self.dialog.raise_()
                self.dialog.activateWindow()
            else:
                if self.dialog is not None:
                    self._save_dialog_geometry()
                    layout = self.dialog.layout()
                    if layout is not None:
                        layout.removeWidget(self.window)
                    self.window.setParent(None)
                    self.dialog.hide()
                    self.dialog.deleteLater()
                    self.dialog = None
                self._create_dock()
                self.window.show()
                self.dock.show()
                self.dock.raise_()
        finally:
            self._switching_container = False
            window = self.window
            QTimer.singleShot(
                0,
                lambda: (
                    window.set_hide_cleanup_suspended(False)
                    if window is not None else None
                ),
            )

    def _on_dialog_finished(self, *_args):
        if self._switching_container or self.window is None:
            return
        self._save_dialog_geometry()
        self.window._on_visibility_changed(False)

    def run(self):
        """プラグインを実行する。ドックまたは別ウィンドウを表示する。"""
        if self.dialog is not None:
            self.dialog.show()
            self.dialog.raise_()
            self.dialog.activateWindow()
            self.window._on_visibility_changed(True)
            return

        if self.dock is None:
            self._create_dock()

        if self.dock.isVisible():
            self.dock.raise_()
        else:
            self.dock.show()
            self.dock.raise_()
