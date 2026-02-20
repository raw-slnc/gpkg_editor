# -*- coding: utf-8 -*-
import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction


class GpkgEditor:
    """GPKG Editorプラグインのメインクラス。"""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = 'GPKG Editor'
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

        if self.window:
            self.window.cleanup()
            self.window.close()
            self.window.deleteLater()
            self.window = None

    def run(self):
        """プラグインを実行する。ウィンドウを表示する。"""
        if self.window is None:
            from .gpkg_editor_dockwidget import GpkgEditorWindow
            self.window = GpkgEditorWindow(self.iface, self.iface.mainWindow())
            # メインウィンドウが表示されているモニターの左上に配置
            main_win = self.iface.mainWindow()
            screen = main_win.screen() if main_win else None
            if screen:
                geo = screen.availableGeometry()
                self.window.move(geo.topLeft())

        if self.window.isVisible():
            self.window.raise_()
            self.window.activateWindow()
        else:
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()
