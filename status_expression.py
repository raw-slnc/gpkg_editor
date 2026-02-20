# -*- coding: utf-8 -*-
"""QGIS式風のステータス式評価器。

選択行のデータに対して式を評価する。
集計関数を使用した場合はテーブル全行に対して評価する。

書式:
    "カラム名"    カラム参照（選択行の値）
    'テキスト'    文字列リテラル
    123, 3.14     数値リテラル
    ||            文字列結合
    =, !=, >, <, >=, <=  比較演算
    +, -, *, /    算術演算
    if(条件, 真, 偽)  条件分岐
    round(数値[, 桁])  四捨五入（桁は省略可）

集計関数（テーブル全行に対して評価）:
    count()          行数
    count(条件)      条件が真の行数
    sum("COL")       数値合計
    min("COL")       最小値
    max("COL")       最大値
    unique("COL")    ユニーク値数

例（選択行の値を表示）:
    "林班" || '林班' || "準林班名" || '-' || "小班_親番"
    if("小班_枝番" = 0, "小班_親番", "小班_親番" || '-' || "小班_枝番")

例（集計値を表示）:
    '設定済: ' || count("施業種" != '') || '/' || count()
"""


def evaluate_row_expr(expr, row, data=None):
    """選択行のデータに対して式を評価する。

    Args:
        expr: QGIS式風の式文字列
        row: dict（選択行のデータ）。カラム参照はこの行の値を返す。
        data: list of dict（テーブル全行）。集計関数はこの全行に対して評価。

    Returns:
        str: 評価結果の文字列
    """
    if not expr:
        return ''
    expr = expr.replace('\n', ' ').replace('\r', '')
    try:
        tokens = _tokenize(expr)
        ev = _Evaluator(tokens, data or [], row)
        result = ev.parse_concat()
        return _format(result)
    except Exception:
        return expr


# ──────────────────────────────────────────────
# トークナイザ
# ──────────────────────────────────────────────

def _tokenize(expr):
    tokens = []
    i = 0
    n = len(expr)
    while i < n:
        c = expr[i]

        if c.isspace():
            i += 1
            continue

        # 文字列リテラル 'text'
        if c == "'":
            j = i + 1
            while j < n and expr[j] != "'":
                j += 1
            tokens.append(('STR', expr[i + 1:j]))
            i = j + 1
            continue

        # カラム参照 "column_name"
        if c == '"':
            j = i + 1
            while j < n and expr[j] != '"':
                j += 1
            tokens.append(('COL', expr[i + 1:j]))
            i = j + 1
            continue

        # 数値
        if c.isdigit() or (c == '.' and i + 1 < n and expr[i + 1].isdigit()):
            j = i
            while j < n and (expr[j].isdigit() or expr[j] == '.'):
                j += 1
            tokens.append(('NUM', float(expr[i:j])))
            i = j
            continue

        # 2文字演算子
        two = expr[i:i + 2]
        if two in ('||', '!=', '>=', '<='):
            tokens.append(('OP', two))
            i += 2
            continue

        # 1文字演算子
        if c in '=><+-*/':
            tokens.append(('OP', c))
            i += 1
            continue

        if c == '(':
            tokens.append(('LPAREN', '('))
            i += 1
            continue
        if c == ')':
            tokens.append(('RPAREN', ')'))
            i += 1
            continue
        if c == ',':
            tokens.append(('COMMA', ','))
            i += 1
            continue

        # 識別子
        if c.isalpha() or c == '_':
            j = i
            while j < n and (expr[j].isalnum() or expr[j] == '_'):
                j += 1
            tokens.append(('IDENT', expr[i:j]))
            i = j
            continue

        i += 1

    return tokens


# ──────────────────────────────────────────────
# ヘルパー
# ──────────────────────────────────────────────

def _format(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value == int(value) else str(value)
    return str(value)


def _to_str(value):
    if value is None:
        return ''
    if isinstance(value, float):
        return str(int(value)) if value == int(value) else str(value)
    return str(value)


def _compare(left, op, right):
    # 数値比較を試行
    try:
        lf = float(left) if not isinstance(left, (int, float)) else left
        rf = float(right) if not isinstance(right, (int, float)) else right
        if isinstance(lf, (int, float)) and isinstance(rf, (int, float)):
            if op == '=':
                return lf == rf
            if op == '!=':
                return lf != rf
            if op == '>':
                return lf > rf
            if op == '<':
                return lf < rf
            if op == '>=':
                return lf >= rf
            if op == '<=':
                return lf <= rf
    except (TypeError, ValueError):
        pass
    # 文字列比較
    ls = _to_str(left)
    rs = _to_str(right)
    if op == '=':
        return ls == rs
    if op == '!=':
        return ls != rs
    if op == '>':
        return ls > rs
    if op == '<':
        return ls < rs
    if op == '>=':
        return ls >= rs
    if op == '<=':
        return ls <= rs
    return False


def _is_truthy(value):
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value != ''
    return bool(value)


# ──────────────────────────────────────────────
# 再帰下降パーサ / 評価器
# ──────────────────────────────────────────────

class _Evaluator:
    """QGIS式風の再帰下降パーサ兼評価器。

    row=None のとき集計コンテキスト（トップレベル）。
    row=dict のとき行コンテキスト（集計関数の引数内）。
    """

    def __init__(self, tokens, data, row=None):
        self.tokens = tokens
        self.data = data
        self.row = row
        self.pos = 0

    def _peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def _consume(self):
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    # ── 文字列結合 ──

    def parse_concat(self):
        left = self._parse_compare()
        while self._peek() and self._peek() == ('OP', '||'):
            self._consume()
            right = self._parse_compare()
            left = _to_str(left) + _to_str(right)
        return left

    # ── 比較 ──

    def _parse_compare(self):
        left = self._parse_add()
        t = self._peek()
        if t and t[0] == 'OP' and t[1] in ('=', '!=', '>', '<', '>=', '<='):
            op = self._consume()[1]
            right = self._parse_add()
            return _compare(left, op, right)
        return left

    # ── 加減算 ──

    def _parse_add(self):
        left = self._parse_mul()
        while (self._peek() and self._peek()[0] == 'OP'
               and self._peek()[1] in ('+', '-')):
            op = self._consume()[1]
            right = self._parse_mul()
            try:
                lf = float(left)
                rf = float(right)
                left = lf + rf if op == '+' else lf - rf
            except (TypeError, ValueError):
                left = None
        return left

    # ── 乗除算 ──

    def _parse_mul(self):
        left = self._parse_unary()
        while (self._peek() and self._peek()[0] == 'OP'
               and self._peek()[1] in ('*', '/')):
            op = self._consume()[1]
            right = self._parse_unary()
            try:
                lf = float(left)
                rf = float(right)
                left = lf * rf if op == '*' else (lf / rf if rf != 0 else None)
            except (TypeError, ValueError):
                left = None
        return left

    # ── 単項マイナス ──

    def _parse_unary(self):
        if self._peek() and self._peek() == ('OP', '-'):
            self._consume()
            val = self._parse_unary()
            try:
                return -float(val)
            except (TypeError, ValueError):
                return None
        return self._parse_primary()

    # ── プライマリ ──

    def _parse_primary(self):
        t = self._peek()
        if not t:
            return None

        if t[0] == 'NUM':
            self._consume()
            return t[1]

        if t[0] == 'STR':
            self._consume()
            return t[1]

        if t[0] == 'COL':
            self._consume()
            if self.row is not None:
                return self.row.get(t[1])
            return None

        if t[0] == 'IDENT':
            name = t[1]
            self._consume()
            if self._peek() and self._peek()[0] == 'LPAREN':
                self._consume()  # LPAREN
                return self._parse_function(name.lower())
            return None

        if t[0] == 'LPAREN':
            self._consume()
            val = self.parse_concat()
            if self._peek() and self._peek()[0] == 'RPAREN':
                self._consume()
            return val

        self._consume()
        return None

    # ── 関数 ──

    def _parse_function(self, name):
        if name == 'if':
            return self._parse_if()
        if name == 'round':
            return self._parse_round()
        if name in ('count', 'sum', 'min', 'max', 'unique'):
            return self._parse_aggregate(name)
        self._skip_to_rparen()
        return None

    def _parse_if(self):
        cond = self.parse_concat()
        if self._peek() and self._peek()[0] == 'COMMA':
            self._consume()
        true_val = self.parse_concat()
        if self._peek() and self._peek()[0] == 'COMMA':
            self._consume()
        false_val = self.parse_concat()
        if self._peek() and self._peek()[0] == 'RPAREN':
            self._consume()
        return true_val if _is_truthy(cond) else false_val

    def _parse_aggregate(self, func_name):
        # 引数なし: count()
        if self._peek() and self._peek()[0] == 'RPAREN':
            self._consume()
            if func_name == 'count':
                return len(self.data)
            return None

        arg_tokens = self._collect_arg_tokens()

        # 各行で引数を評価
        results = []
        for row in self.data:
            ev = _Evaluator(arg_tokens, self.data, row)
            results.append(ev.parse_concat())

        if func_name == 'count':
            return sum(1 for v in results if _is_truthy(v))

        if func_name == 'sum':
            total = 0.0
            for v in results:
                try:
                    total += float(v)
                except (TypeError, ValueError):
                    pass
            return total

        if func_name in ('min', 'max'):
            nums = []
            for v in results:
                if v is not None and str(v) != '':
                    try:
                        nums.append(float(v))
                    except (TypeError, ValueError):
                        nums.append(str(v))
            if not nums:
                return None
            return min(nums) if func_name == 'min' else max(nums)

        if func_name == 'unique':
            vals = set()
            for v in results:
                if v is not None and str(v) != '':
                    vals.add(str(v))
            return len(vals)

        return None

    def _parse_round(self):
        value = self.parse_concat()
        ndigits = None
        if self._peek() and self._peek()[0] == 'COMMA':
            self._consume()
            ndigits = self.parse_concat()
        if self._peek() and self._peek()[0] == 'RPAREN':
            self._consume()
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None
        if ndigits is None or ndigits == '':
            return round(num)
        try:
            return round(num, int(float(ndigits)))
        except (TypeError, ValueError):
            return round(num)

    def _collect_arg_tokens(self):
        """閉じ括弧までのトークンを収集する。"""
        depth = 1
        start = self.pos
        while self.pos < len(self.tokens):
            t = self.tokens[self.pos]
            if t[0] == 'LPAREN':
                depth += 1
            elif t[0] == 'RPAREN':
                depth -= 1
                if depth == 0:
                    arg_tokens = self.tokens[start:self.pos]
                    self.pos += 1
                    return arg_tokens
            self.pos += 1
        return self.tokens[start:]

    def _skip_to_rparen(self):
        depth = 1
        while self.pos < len(self.tokens):
            t = self._consume()
            if t[0] == 'LPAREN':
                depth += 1
            elif t[0] == 'RPAREN':
                depth -= 1
                if depth == 0:
                    return
