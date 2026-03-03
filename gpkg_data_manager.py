# -*- coding: utf-8 -*-
import os
import csv
import json
import sqlite3

from qgis.core import (
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsProject,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsFeatureRequest,
    QgsCoordinateTransformContext,
)
from qgis.PyQt.QtCore import QVariant


class GpkgDataManager:
    """GPKGデータの読み書き・結合を管理するクラス。

    オリジナルGPKG と管理用SQLite (計画＋編集データ) を分離管理し、
    出力時に結合する。
    """

    def __init__(self):
        self.original_path = None
        self.original_layer = None  # QgsVectorLayer
        self.layer_name = None
        self._db_path = None        # 管理用SQLiteパス

    def load_gpkg(self, path):
        """オリジナルGPKGを読み込む。"""
        self.original_path = path
        base, _ = os.path.splitext(path)
        self._db_path = base + '_data.sqlite'
        self.layer_name = os.path.splitext(os.path.basename(path))[0]

        self.original_layer = QgsVectorLayer(path, self.layer_name + '_original', 'ogr')
        if not self.original_layer.isValid():
            raise ValueError(f'GPKGファイルを読み込めません: {path}')

        # 旧形式の _plans.sqlite があれば _data.sqlite にマイグレーション
        self._migrate_legacy_db(base)

        return self.original_layer

    def _migrate_legacy_db(self, base):
        """旧 _plans.sqlite のデータを _data.sqlite にマイグレーションする。"""
        old_path = base + '_plans.sqlite'
        if not os.path.exists(old_path):
            return
        if os.path.exists(self._db_path):
            return  # 既にマイグレーション済み

        # 旧DBからデータをコピー
        old_conn = sqlite3.connect(old_path)
        try:
            # plansテーブルがあるか確認
            tables = old_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='plans'"
            ).fetchall()
            if not tables:
                return

            conn = self._open_db()
            if not conn:
                return
            try:
                # カラム情報を取得して status_exprs の有無を判定
                columns = [
                    r[1] for r in old_conn.execute('PRAGMA table_info(plans)')
                ]
                has_status = 'status_exprs' in columns

                if has_status:
                    rows = old_conn.execute(
                        'SELECT name, fids, column_config, status_exprs FROM plans'
                    ).fetchall()
                    for name, fids, cc, se in rows:
                        conn.execute(
                            'INSERT OR IGNORE INTO plans '
                            '(name, fids, column_config, status_exprs) '
                            'VALUES (?, ?, ?, ?)',
                            (name, fids, cc, se),
                        )
                else:
                    rows = old_conn.execute(
                        'SELECT name, fids, column_config FROM plans'
                    ).fetchall()
                    for name, fids, cc in rows:
                        conn.execute(
                            'INSERT OR IGNORE INTO plans '
                            '(name, fids, column_config) VALUES (?, ?, ?)',
                            (name, fids, cc),
                        )
                conn.commit()
            finally:
                conn.close()
        finally:
            old_conn.close()

    def get_original_fields(self):
        """オリジナルレイヤーのフィールド名リストを返す。"""
        if not self.original_layer:
            return []
        return [field.name() for field in self.original_layer.fields()]

    def get_intersecting_fids(self, geometry, crs=None):
        """指定ジオメトリと交差するフィーチャーのfidリストを返す。"""
        if not self.original_layer:
            return []

        request = QgsFeatureRequest()
        request.setFilterRect(geometry.boundingBox())

        fids = []
        for feat in self.original_layer.getFeatures(request):
            if feat.geometry().intersects(geometry):
                fids.append(feat.id())
        return fids

    def get_merged_features(self, fids, display_cols, edit_cols):
        """結合済みデータを返す。"""
        if not self.original_layer:
            return []

        all_cols = display_cols + edit_cols
        edit_data = self._load_edit_data(fids, edit_cols)

        result = []
        request = QgsFeatureRequest()
        request.setFilterFids(fids)

        for feat in self.original_layer.getFeatures(request):
            fid = feat.id()
            row = {'fid': fid}
            for col in all_cols:
                idx = self.original_layer.fields().indexOf(col)
                if idx >= 0:
                    row[col] = feat.attribute(idx)
                else:
                    row[col] = None

            edited_cols = set()
            if fid in edit_data:
                for col in edit_cols:
                    if col in edit_data[fid]:
                        row[col] = edit_data[fid][col]
                        edited_cols.add(col)
            row['_edited_cols'] = edited_cols

            result.append(row)
        return result

    # ──────────────────────────────────────────────
    # 管理用SQLite (計画 + 編集データ)
    # ──────────────────────────────────────────────

    def _open_db(self):
        """管理用SQLiteを開く（なければ作成）。"""
        if not self._db_path:
            return None
        conn = sqlite3.connect(self._db_path)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                fids TEXT NOT NULL,
                column_config TEXT NOT NULL,
                status_exprs TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS edits (
                orig_fid INTEGER NOT NULL,
                col_name TEXT NOT NULL,
                value,
                PRIMARY KEY (orig_fid, col_name)
            )
        ''')
        conn.commit()
        return conn

    # ──────────────────────────────────────────────
    # 編集データ
    # ──────────────────────────────────────────────

    def _load_edit_data(self, fids, edit_cols):
        """編集データを読み込む。"""
        edit_data = {}
        if not self._db_path or not edit_cols or not fids:
            return edit_data
        if not os.path.exists(self._db_path):
            return edit_data

        conn = sqlite3.connect(self._db_path)
        try:
            placeholders = ','.join('?' for _ in fids)
            rows = conn.execute(
                f'SELECT orig_fid, col_name, value FROM edits '
                f'WHERE orig_fid IN ({placeholders})',
                list(fids),
            ).fetchall()
            for orig_fid, col_name, value in rows:
                if col_name in edit_cols:
                    if orig_fid not in edit_data:
                        edit_data[orig_fid] = {}
                    edit_data[orig_fid][col_name] = value
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()
        return edit_data

    def get_all_edits(self):
        """全編集データを返す: {orig_fid: {col_name: value}}"""
        if not self._db_path or not os.path.exists(self._db_path):
            return {}
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                'SELECT orig_fid, col_name, value FROM edits'
            ).fetchall()
            result = {}
            for orig_fid, col_name, value in rows:
                if orig_fid not in result:
                    result[orig_fid] = {}
                result[orig_fid][col_name] = value
            return result
        except sqlite3.OperationalError:
            return {}
        finally:
            conn.close()

    def clear_edits(self):
        """編集データをすべてクリアする（上書き保存後に呼ぶ）。"""
        conn = self._open_db()
        if not conn:
            return
        try:
            conn.execute('DELETE FROM edits')
            conn.commit()
        finally:
            conn.close()

    def save_edit(self, fid, column, value, edit_cols):
        """編集データを保存する。"""
        conn = self._open_db()
        if not conn:
            raise ValueError('管理用DBを開けません')
        try:
            conn.execute(
                'INSERT OR REPLACE INTO edits (orig_fid, col_name, value) '
                'VALUES (?, ?, ?)',
                (fid, column, value),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    # ──────────────────────────────────────────────
    # 計画管理
    # ──────────────────────────────────────────────

    def list_plans(self):
        if not self._db_path or not os.path.exists(self._db_path):
            return []
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                'SELECT name FROM plans ORDER BY name'
            ).fetchall()
            return [r[0] for r in rows]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def save_plan(self, name, fids, column_config, status_exprs=None):
        conn = self._open_db()
        if not conn:
            return False
        try:
            conn.execute(
                'INSERT OR REPLACE INTO plans '
                '(name, fids, column_config, status_exprs) '
                'VALUES (?, ?, ?, ?)',
                (name, json.dumps(fids), json.dumps(column_config),
                 json.dumps(status_exprs) if status_exprs else None),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def load_plan(self, name):
        conn = self._open_db()
        if not conn:
            return None
        try:
            row = conn.execute(
                'SELECT fids, column_config, status_exprs FROM plans '
                'WHERE name = ?',
                (name,),
            ).fetchone()
            if not row:
                return None
            result = {
                'fids': json.loads(row[0]),
                'column_config': json.loads(row[1]),
            }
            if row[2]:
                result['status_exprs'] = json.loads(row[2])
            else:
                result['status_exprs'] = {}
            return result
        finally:
            conn.close()

    def delete_plan(self, name):
        conn = self._open_db()
        if not conn:
            return False
        try:
            conn.execute('DELETE FROM plans WHERE name = ?', (name,))
            conn.commit()
            return True
        finally:
            conn.close()

    # ──────────────────────────────────────────────
    # エクスポート / ユーティリティ
    # ──────────────────────────────────────────────

    def get_all_merged_data(self, display_cols, edit_cols):
        """全フィーチャーの結合データを返す。"""
        if not self.original_layer:
            return []

        all_fids = [f.id() for f in self.original_layer.getFeatures()]
        return self.get_merged_features(all_fids, display_cols, edit_cols)

    def _load_all_edit_data(self, fids):
        """指定fidsの全カラム編集データを読み込む（カラム絞り込みなし）。"""
        edit_data = {}
        if not self._db_path or not fids:
            return edit_data
        if not os.path.exists(self._db_path):
            return edit_data
        conn = sqlite3.connect(self._db_path)
        try:
            placeholders = ','.join('?' for _ in fids)
            rows = conn.execute(
                f'SELECT orig_fid, col_name, value FROM edits '
                f'WHERE orig_fid IN ({placeholders})',
                list(fids),
            ).fetchall()
            for orig_fid, col_name, value in rows:
                if orig_fid not in edit_data:
                    edit_data[orig_fid] = {}
                edit_data[orig_fid][col_name] = value
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()
        return edit_data

    def export_gpkg(self, output_path, fids=None):
        """全カラム＋編集適用でGPKGエクスポートする。fids を指定するとその範囲のみ出力。"""
        if not self.original_layer:
            return False

        fields = self.original_layer.fields()
        all_cols = [fields.at(i).name() for i in range(fields.count())]

        request = QgsFeatureRequest()
        if fids is not None:
            request.setFilterFids(fids)
            edit_data = self._load_all_edit_data(fids)
        else:
            all_fids = [f.id() for f in self.original_layer.getFeatures()]
            edit_data = self._load_all_edit_data(all_fids)

        writer_options = QgsVectorFileWriter.SaveVectorOptions()
        writer_options.driverName = 'GPKG'
        writer_options.fileEncoding = 'UTF-8'

        transform_context = QgsProject.instance().transformContext()
        writer = QgsVectorFileWriter.create(
            output_path,
            fields,
            self.original_layer.wkbType(),
            self.original_layer.crs(),
            transform_context,
            writer_options,
        )

        for orig_feat in self.original_layer.getFeatures(request):
            fid = orig_feat.id()
            new_feat = QgsFeature(fields)
            new_feat.setGeometry(orig_feat.geometry())
            for col_name in all_cols:
                if fid in edit_data and col_name in edit_data[fid]:
                    new_feat.setAttribute(col_name, edit_data[fid][col_name])
                else:
                    new_feat.setAttribute(col_name, orig_feat.attribute(col_name))
            writer.addFeature(new_feat)

        del writer
        return True

    def export_csv(self, output_path, fids=None):
        """全カラム＋編集適用でCSVエクスポートする。fids を指定するとその範囲のみ出力。"""
        if not self.original_layer:
            return False

        fields = self.original_layer.fields()
        all_cols = [fields.at(i).name() for i in range(fields.count())]

        request = QgsFeatureRequest()
        if fids is not None:
            request.setFilterFids(fids)
            edit_data = self._load_all_edit_data(fids)
        else:
            all_fids = [f.id() for f in self.original_layer.getFeatures()]
            edit_data = self._load_all_edit_data(all_fids)

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(all_cols)
            for feat in self.original_layer.getFeatures(request):
                fid = feat.id()
                row = []
                for col_name in all_cols:
                    if fid in edit_data and col_name in edit_data[fid]:
                        row.append(edit_data[fid][col_name])
                    else:
                        val = feat.attribute(col_name)
                        row.append(val if val is not None else '')
                writer.writerow(row)
        return True

    def close(self):
        """レイヤーを閉じる。"""
        self.original_layer = None
        self.original_path = None
        self._db_path = None
        self.layer_name = None
