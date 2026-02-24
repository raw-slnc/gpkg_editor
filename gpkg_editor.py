# -*- coding: utf-8 -*-
import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QDockWidget
from qgis.PyQt.QtCore import Qt


class GpkgEditor:
    """GPKG Editorプラグインのメインクラス。"""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = 'GPKG Editor'
        self.dock = None
        self.window = None

    def initGui(self):
        """プラグインUIを初期化する。"""
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        icon = QIcon(icon_path)
        action = QAction(icon, 'GPKG Editor', self.iface.mainWindow())
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

        if self.dock:
            if self.window:
                self.window.cleanup()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
            self.window = None

    def run(self):
        """プラグインを実行する。ドックを表示する。"""
        if self.dock is None:
            from .gpkg_editor_dockwidget import GpkgEditorWindow
            self.window = GpkgEditorWindow(self.iface)
            self.dock = QDockWidget('GPKG Editor', self.iface.mainWindow())
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


