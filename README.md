# GPKG Editor

A QGIS plugin for viewing and editing GeoPackage (GPKG) layer attributes with plan management and export support.

## Features

- **Attribute table**: Select features on the map and view/edit their attributes in a table
- **Non-destructive edits**: Edits are stored in a separate SQLite file (`{name}_data.sqlite`), leaving the original GPKG untouched
- **Plan management**: Save named plans (feature sets + column configurations) and restore them later
- **Feature management**: Add or remove features from the active plan
- **Status display**: Define expression-based status rows to show computed values for the selected row
- **Export**: Export the merged result (original + edits) as GPKG or CSV

## Column modes

Each column can be set to one of three modes in the column configuration dialog:

| Mode | Description |
|------|-------------|
| Hidden (非表示) | Not shown in the table |
| Display (表示のみ) | Shown read-only |
| Editable (表示＋編集) | Shown and editable |

## Status expression syntax

Status rows support a QGIS-expression-like syntax:

```
"column_name"          Column reference (selected row value)
'text'                 String literal
||                     String concatenation
=, !=, >, <, >=, <=   Comparison
+, -, *, /             Arithmetic
if(cond, true, false)  Conditional
round(value[, digits]) Rounding

Aggregate functions (applied to all rows):
  count()       Row count
  count(expr)   Count where expr is truthy
  sum("COL")    Numeric sum
  min("COL")    Minimum value
  max("COL")    Maximum value
  unique("COL") Count of unique values
```

## Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+F | Toggle fullscreen |
| Ctrl+S | Save current plan |
| Ctrl+C | Copy selected cells (tab-separated) |
| Ctrl+V | Paste clipboard to selected cells |
| Ctrl+Shift+Scroll | Horizontal scroll |
| Ctrl+Arrow | Move to end cell |
| Ctrl+Shift+Arrow | Select to end cell |
| Enter | Toggle edit mode for current cell |

## Requirements

- QGIS 3.0 or later

## License

This plugin is distributed under the GNU General Public License v2 or later.
See [LICENSE](LICENSE) for details.
