# -*- coding: utf-8 -*-
import os
import re
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

    def load_gpkg(self, path, layername=None):
        """オリジナルGPKGを読み込む。layername を指定すると複数レイヤーGPKGで正しいレイヤーを開く。"""
        self.original_path = path
        base, _ = os.path.splitext(path)
        self._db_path = base + '_data.sqlite'

        if layername:
            self.layer_name = layername
            uri = f'{path}|layername={layername}'
        else:
            self.layer_name = os.path.splitext(os.path.basename(path))[0]
            uri = path

        self.original_layer = QgsVectorLayer(uri, self.layer_name + '_original', 'ogr')
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

    def get_merged_features(self, fids, display_cols, edit_cols, plan_name):
        """結合済みデータを返す。"""
        if not self.original_layer:
            return []

        all_cols = display_cols + edit_cols
        edit_data = self._load_edit_data(fids, edit_cols, plan_name)

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
        # WALモードを無効化（Windows環境で.shm/.walが残存しロックされる問題を回避）
        conn.execute('PRAGMA journal_mode=DELETE')
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
                plan_name TEXT NOT NULL,
                orig_fid INTEGER NOT NULL,
                col_name TEXT NOT NULL,
                value,
                PRIMARY KEY (plan_name, orig_fid, col_name)
            )
        ''')
        # edits テーブルのスキーママイグレーション（plan_name カラム追加）
        try:
            cols = [r[1] for r in conn.execute('PRAGMA table_info(edits)').fetchall()]
            if 'plan_name' not in cols:
                old_edits = conn.execute(
                    'SELECT orig_fid, col_name, value FROM edits'
                ).fetchall()
                plan_rows = conn.execute('SELECT name, fids FROM plans').fetchall()
                plan_fids = {}
                for pname, fids_json in plan_rows:
                    try:
                        plan_fids[pname] = set(json.loads(fids_json))
                    except Exception:  # nosec B110
                        pass
                conn.execute('DROP TABLE edits')
                conn.execute('''
                    CREATE TABLE edits (
                        plan_name TEXT NOT NULL,
                        orig_fid INTEGER NOT NULL,
                        col_name TEXT NOT NULL,
                        value,
                        PRIMARY KEY (plan_name, orig_fid, col_name)
                    )
                ''')
                for orig_fid, col_name, value in old_edits:
                    for pname, fids in plan_fids.items():
                        if orig_fid in fids:
                            conn.execute(
                                'INSERT OR IGNORE INTO edits '
                                '(plan_name, orig_fid, col_name, value) '
                                'VALUES (?, ?, ?, ?)',
                                (pname, orig_fid, col_name, value),
                            )
                conn.commit()
        except Exception:  # nosec B110
            pass
        conn.execute('''
            CREATE TABLE IF NOT EXISTS export_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_name TEXT NOT NULL,
                exported_at TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                feature_count INTEGER NOT NULL DEFAULT 0,
                edited_col_count INTEGER NOT NULL DEFAULT 0,
                author TEXT NOT NULL DEFAULT '',
                memo TEXT NOT NULL DEFAULT '',
                is_deleted INTEGER NOT NULL DEFAULT 0
            )
        ''')
        # 既存DBへの列追加（マイグレーション）
        try:
            conn.execute('ALTER TABLE export_history ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0')
            conn.commit()
        except Exception:  # nosec B110
            pass
        conn.commit()
        return conn

    # ──────────────────────────────────────────────
    # 編集データ
    # ──────────────────────────────────────────────

    def _load_edit_data(self, fids, edit_cols, plan_name):
        """編集データを読み込む。"""
        edit_data = {}
        if not self._db_path or not edit_cols or not fids or not plan_name:
            return edit_data
        if not os.path.exists(self._db_path):
            return edit_data

        conn = sqlite3.connect(self._db_path)
        try:
            placeholders = ','.join('?' for _ in fids)
            rows = conn.execute(
                f'SELECT orig_fid, col_name, value FROM edits '  # nosec B608
                f'WHERE plan_name = ? AND orig_fid IN ({placeholders})',
                [plan_name] + list(fids),
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

    def get_all_edits(self, plan_name):
        """指定計画の全編集データを返す: {orig_fid: {col_name: value}}"""
        if not self._db_path or not os.path.exists(self._db_path) or not plan_name:
            return {}
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                'SELECT orig_fid, col_name, value FROM edits WHERE plan_name = ?',
                (plan_name,),
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

    def clear_edits(self, plan_name):
        """指定計画の編集データをクリアする（上書き保存後に呼ぶ）。"""
        conn = self._open_db()
        if not conn:
            return
        try:
            conn.execute('DELETE FROM edits WHERE plan_name = ?', (plan_name,))
            conn.commit()
        finally:
            conn.close()

    def save_edit(self, fid, column, value, edit_cols, plan_name):
        """編集データを保存する。"""
        if not plan_name:
            raise ValueError('計画名が指定されていません')
        conn = self._open_db()
        if not conn:
            raise ValueError('管理用DBを開けません')
        try:
            conn.execute(
                'INSERT OR REPLACE INTO edits (plan_name, orig_fid, col_name, value) '
                'VALUES (?, ?, ?, ?)',
                (plan_name, fid, column, value),
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
            conn.execute('DELETE FROM edits WHERE plan_name = ?', (name,))
            conn.execute('DELETE FROM plans WHERE name = ?', (name,))
            conn.execute('DELETE FROM export_history WHERE plan_name = ?', (name,))
            conn.commit()
            return True
        finally:
            conn.close()

    def copy_plan(self, source_name, new_name):
        """計画をコピーする（フィーチャーセット・カラム設定・編集データをすべてコピー）。"""
        plan = self.load_plan(source_name)
        if not plan:
            return False
        if not self.save_plan(
            new_name,
            plan['fids'],
            plan['column_config'],
            plan.get('status_exprs'),
        ):
            return False
        # 編集データもコピー（計画ごとに独立した編集値を持つ）
        conn = self._open_db()
        if not conn:
            return True  # 計画自体は保存済み
        try:
            rows = conn.execute(
                'SELECT orig_fid, col_name, value FROM edits WHERE plan_name = ?',
                (source_name,),
            ).fetchall()
            for orig_fid, col_name, value in rows:
                conn.execute(
                    'INSERT OR IGNORE INTO edits (plan_name, orig_fid, col_name, value) '
                    'VALUES (?, ?, ?, ?)',
                    (new_name, orig_fid, col_name, value),
                )
            conn.commit()
            return True
        finally:
            conn.close()

    # ──────────────────────────────────────────────
    # エクスポート / ユーティリティ
    # ──────────────────────────────────────────────

    def get_all_merged_data(self, display_cols, edit_cols, plan_name):
        """全フィーチャーの結合データを返す。"""
        if not self.original_layer:
            return []

        all_fids = [f.id() for f in self.original_layer.getFeatures()]
        return self.get_merged_features(all_fids, display_cols, edit_cols, plan_name)

    def _load_all_edit_data(self, fids, plan_name):
        """指定fidsの全カラム編集データを読み込む（カラム絞り込みなし）。"""
        edit_data = {}
        if not self._db_path or not fids or not plan_name:
            return edit_data
        if not os.path.exists(self._db_path):
            return edit_data
        conn = sqlite3.connect(self._db_path)
        try:
            placeholders = ','.join('?' for _ in fids)
            rows = conn.execute(
                f'SELECT orig_fid, col_name, value FROM edits '  # nosec B608
                f'WHERE plan_name = ? AND orig_fid IN ({placeholders})',
                [plan_name] + list(fids),
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

    def export_gpkg(self, output_path, plan_name, fids=None):
        """全カラム＋編集適用でGPKGエクスポートする。fids を指定するとその範囲のみ出力。"""
        if not self.original_layer:
            return False

        fields = self.original_layer.fields()
        all_cols = [fields.at(i).name() for i in range(fields.count())]

        request = QgsFeatureRequest()
        if fids is not None:
            request.setFilterFids(fids)
            edit_data = self._load_all_edit_data(fids, plan_name)
        else:
            all_fids = [f.id() for f in self.original_layer.getFeatures()]
            edit_data = self._load_all_edit_data(all_fids, plan_name)

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

        if writer.hasError() != QgsVectorFileWriter.NoError:
            raise IOError(f'GPKGライターの初期化に失敗しました: {writer.errorMessage()}')

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

    def export_csv(self, output_path, plan_name, fids=None):
        """全カラム＋編集適用でCSVエクスポートする。fids を指定するとその範囲のみ出力。"""
        if not self.original_layer:
            return False

        fields = self.original_layer.fields()
        all_cols = [fields.at(i).name() for i in range(fields.count())]

        request = QgsFeatureRequest()
        if fids is not None:
            request.setFilterFids(fids)
            edit_data = self._load_all_edit_data(fids, plan_name)
        else:
            all_fids = [f.id() for f in self.original_layer.getFeatures()]
            edit_data = self._load_all_edit_data(all_fids, plan_name)

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

    # ──────────────────────────────────────────────
    # エクスポート履歴
    # ──────────────────────────────────────────────

    def save_export_history(self, plan_name, filename, file_type,
                            feature_count, edited_col_count, author=''):
        """エクスポート結果を export_history に記録する。"""
        conn = self._open_db()
        if not conn:
            return None
        try:
            from datetime import datetime
            exported_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cur = conn.execute(
                'INSERT INTO export_history '
                '(plan_name, exported_at, filename, file_type, '
                ' feature_count, edited_col_count, author, memo) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (plan_name, exported_at, filename, file_type,
                 feature_count, edited_col_count, author, ''),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def list_export_history(self, plan_name):
        """エクスポート履歴を新しい順で返す（削除済みフラグも含む）。"""
        if not self._db_path or not os.path.exists(self._db_path):
            return []
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                'SELECT id, exported_at, filename, file_type, '
                'feature_count, edited_col_count, author, memo, is_deleted '
                'FROM export_history WHERE plan_name = ? '
                'ORDER BY exported_at DESC',
                (plan_name,),
            ).fetchall()
            return [
                {'id': r[0], 'exported_at': r[1], 'filename': r[2],
                 'file_type': r[3], 'feature_count': r[4],
                 'edited_col_count': r[5], 'author': r[6] or '',
                 'memo': r[7] or '', 'is_deleted': bool(r[8])}
                for r in rows
            ]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def update_export_history_field(self, record_id, field, value):
        """author または memo フィールドを更新する。"""
        if field not in ('author', 'memo'):
            return False
        conn = self._open_db()
        if not conn:
            return False
        try:
            conn.execute(
                f'UPDATE export_history SET {field} = ? WHERE id = ?',  # nosec B608
                (value, record_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def delete_export_history(self, record_id):
        """エクスポート履歴レコードをソフトデリート（is_deleted=1）する。"""
        conn = self._open_db()
        if not conn:
            return False
        try:
            conn.execute(
                'UPDATE export_history SET is_deleted = 1 WHERE id = ?',
                (record_id,),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def migrate_old_filename_pattern(self, export_folder):
        """旧命名パターン {計画名}_{レイヤー名}_{番号}_{日付}_{時間}.{拡張子} のファイルを
        新パターン {計画名}_{番号}_{日付}_{時間}.{拡張子} に一括変換する。
        ファイルのリネームと export_history レコードの filename 更新を行う。
        Returns: {旧ファイル名: 新ファイル名} の辞書（変更があったもののみ）
        """
        if not self._db_path or not os.path.exists(self._db_path):
            return {}

        conn = sqlite3.connect(self._db_path)
        conn.execute('PRAGMA journal_mode=DELETE')
        renamed = {}
        try:
            rows = conn.execute(
                'SELECT id, plan_name, filename FROM export_history'
            ).fetchall()

            for rec_id, plan_name, old_filename in rows:
                sanitized = re.sub(r'[\\/:*?"<>|]', '_', plan_name)
                new_pattern = re.compile(
                    r'^' + re.escape(sanitized) + r'_\d{4}_\d{8}_\d{6}\.(gpkg|csv)$',
                    re.IGNORECASE,
                )
                if new_pattern.match(old_filename):
                    continue  # 既に新パターン

                # 旧パターンから番号・日付・時間を抽出
                # {計画名}_{レイヤー名}_{番号}_{日付}_{時間}.{拡張子}
                old_pattern = re.compile(
                    r'^' + re.escape(sanitized) + r'_.+_(\d{4})_(\d{8})_(\d{6})\.(gpkg|csv)$',
                    re.IGNORECASE,
                )
                m = old_pattern.match(old_filename)
                if not m:
                    continue  # 不明なパターン、スキップ

                num, date, time_, ext = m.group(1), m.group(2), m.group(3), m.group(4)
                new_filename = f'{sanitized}_{num}_{date}_{time_}.{ext}'

                old_path = os.path.join(export_folder, old_filename)
                new_path = os.path.join(export_folder, new_filename)
                old_exists = os.path.exists(old_path)
                new_exists = os.path.exists(new_path)

                if not old_exists and not new_exists:
                    # どちらも存在しない（別環境からの移行等）→ DBは更新しない
                    continue

                # ファイルリネーム（旧ファイルが存在し新ファイルがない場合のみ）
                if old_exists and not new_exists:
                    os.rename(old_path, new_path)

                # DB更新（ファイルが実在する場合のみここに到達）
                conn.execute(
                    'UPDATE export_history SET filename = ? WHERE id = ?',
                    (new_filename, rec_id),
                )
                renamed[old_filename] = new_filename

            if renamed:
                conn.commit()
        except Exception:  # nosec B110
            pass
        finally:
            conn.close()

        return renamed

    def cleanup_orphan_data(self):
        """孤立した edits・export_history レコードを削除する。
        - edits: plans テーブルに存在しない plan_name のレコードを削除
        - export_history: plans テーブルに存在しない plan_name のレコードを削除
        """
        conn = self._open_db()
        if not conn:
            return
        try:
            plan_names = {
                row[0] for row in
                conn.execute('SELECT name FROM plans').fetchall()
            }

            # edits: 存在しない計画名のレコードを削除
            edit_plan_names = {
                row[0] for row in
                conn.execute('SELECT DISTINCT plan_name FROM edits').fetchall()
            }
            orphan_edit_plans = list(edit_plan_names - plan_names)
            if orphan_edit_plans:
                placeholders = ','.join('?' for _ in orphan_edit_plans)
                conn.execute(
                    f'DELETE FROM edits WHERE plan_name IN ({placeholders})',  # nosec B608
                    orphan_edit_plans,
                )

            # export_history: 存在しない計画名のレコードを削除
            history_names = {
                row[0] for row in
                conn.execute('SELECT DISTINCT plan_name FROM export_history').fetchall()
            }
            orphan_names = list(history_names - plan_names)
            if orphan_names:
                placeholders = ','.join('?' for _ in orphan_names)
                conn.execute(
                    f'DELETE FROM export_history WHERE plan_name IN ({placeholders})',  # nosec B608
                    orphan_names,
                )

            if orphan_edit_plans or orphan_names:
                conn.commit()
        except Exception:  # nosec B110
            pass
        finally:
            conn.close()

    def close(self):
        """レイヤーを閉じる。"""
        self.original_layer = None
        self.original_path = None
        self._db_path = None
        self.layer_name = None
