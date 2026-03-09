# -*- coding: utf-8 -*-
import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QDockWidget
from qgis.PyQt.QtCore import QCoreApplication, QSettings, Qt, QTranslator


class GpkgEditor:
    """GPKG Editorプラグインのメインクラス。"""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = self.tr('GPKG Editor')
        self.dock = None
        self.window = None
        self._translator = None
        self._active_locale = 'ja'

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
        normalized = str(locale).replace('-', '_').split('.', 1)[0].split('@', 1)[0]
        if normalized in ('ja', ''):
            return []
        if normalized == 'en':
            return ['en']
        if '_' in normalized:
            lang, region = normalized.split('_', 1)
            return [f'{lang.lower()}_{region.upper()}', lang.lower()]
        return [normalized.lower()]

    def set_language(self, locale):
        """Switch plugin translation at runtime. locale=None uses system locale."""
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
        if self.window and hasattr(self.window, 'retranslate_ui'):
            self.window.retranslate_ui()

    def initGui(self):
        """プラグインUIを初期化する。"""
        self.set_language(None)
        self.menu = self.tr('GPKG Editor')
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        icon = QIcon(icon_path)
        action = QAction(icon, self.tr('GPKG Editor'), self.iface.mainWindow())
        action.triggered.connect(self.run)
        action.setEnabled(True)

        self.iface.addVectorToolBarIcon(action)
        self.iface.addPluginToVectorMenu(self.menu, action)
        self.actions.append(action)

    def unload(self):
        """プラグインをアンロードする。"""
        for action in self.actions:
            self.iface.removePluginVectorMenu(self.menu, action)
            self.iface.removeVectorToolBarIcon(action)
        self.actions = []

        if self.dock:
            if self.window:
                self.window.cleanup()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
            self.window = None
        self._remove_translator()

    def run(self):
        """プラグインを実行する。ドックを表示する。"""
        if self.dock is None:
            from .gpkg_editor_dockwidget import GpkgEditorWindow
            self.window = GpkgEditorWindow(
                self.iface,
                self.plugin_dir,
                self.set_language,
                self.get_active_locale,
            )
            self.dock = QDockWidget(self.tr('GPKG Editor'), self.iface.mainWindow())
            self.dock.setObjectName('GpkgEditorDock')
            self.dock.setWidget(self.window)
            self.dock.setAllowedAreas(
                Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea
            )
            self.iface.addDockWidget(Qt.BottomDockWidgetArea, self.dock)

        if self.dock.isVisible():
            self.dock.raise_()
        else:
            self.dock.show()
            self.dock.raise_()
