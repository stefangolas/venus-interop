"""Read Venus's liquid-class database (`Config\\ML_STARLiquids.mdb`) into JSON, and check it against
PyLabRobot's STAR liquid classes.

  python tools/liquid_classes.py ML_STARLiquids.mdb --out classes.json
  python tools/liquid_classes.py ML_STARLiquids.mdb --check-plr        every class PLR also has, compared

The database is Access (JET 4). It is read with `access-parser` (pip install access-parser), a
pure-Python reader, with two fixes to how it reads a row: the null bitmap is sized by the field
count the row stores (not the table's current column count), and variable-length fields are
placed by each column's variable-column number, deleted columns included (not by column order).
Without them the database's rows lose their names and curves, or read shifted.

Each class: its LiquidClassName, LiquidName, TipType and DispenseMode (Venus's codes), whether it
is one of Hamilton's (OriginalLiquid), the correction curve (target volume -> piston volume, the
CorrectionCurve blob read as pairs of doubles), and the aspirate and dispense parameters under
PLR's HamiltonLiquidClass names. venus_interop.plr.liquid_classes turns the JSON into PLR classes.
"""
import argparse
import json
import logging
import pathlib
import struct
import sys
import types

# The database's columns under HamiltonLiquidClass's argument names
PARAMETERS = {
  "AsFlowRate": "aspiration_flow_rate", "AsMixFlowRate": "aspiration_mix_flow_rate",
  "AsAirTransportVolume": "aspiration_air_transport_volume", "AsBlowOutVolume": "aspiration_blow_out_volume",
  "AsSwapSpeed": "aspiration_swap_speed", "AsSettlingTime": "aspiration_settling_time",
  "AsOverAspirateVolume": "aspiration_over_aspirate_volume", "AsClotRetractHeight": "aspiration_clot_retract_height",
  "DsFlowRate": "dispense_flow_rate", "DispenseMode": "dispense_mode", "DsMixFlowRate": "dispense_mix_flow_rate",
  "DsAirTransportVolume": "dispense_air_transport_volume", "DsBlowOutVolume": "dispense_blow_out_volume",
  "DsSwapSpeed": "dispense_swap_speed", "DsSettlingTime": "dispense_settling_time",
  "DsStopFlowRate": "dispense_stop_flow_rate", "DsStopBackVolume": "dispense_stop_back_volume",
}


def _patch(ap):
  """access-parser's row reading, fixed (see the module docstring)."""
  def _parse_row(self, record):
    if self.version > 3:
      field_count, body = struct.unpack_from("h", record)[0], record[2:]
    else:
      field_count, body = struct.unpack_from("b", record)[0], record[1:]
    null_len = (field_count + 7) // 8
    if not null_len or null_len >= len(record):
      return
    bits = record[-null_len:]
    nulls = [(bits[i // 8] & (1 << (i % 8))) != 0 for i in range(null_len * 8)]
    variable = {}
    for column in self.columns.values():
      if not column.column_flags.fixed_length:
        variable[column.variable_column_number] = column
      elif column.column_id < len(nulls):  # else added after the row was written: null
        self._parse_fixed_length_data(body, column, nulls)
    if not variable:
      return
    placeholder = types.SimpleNamespace(col_name_str="_deleted", column_id=1 << 20, type=9)
    ordered = {n: variable.get(n, placeholder) for n in range(max(variable) + 1)}
    metadata = self._parse_dynamic_length_records_metadata(record[::-1], record, null_len)
    if metadata and metadata.variable_length_field_offsets:
      self._parse_dynamic_length_data(record, metadata, ordered, nulls)

  ap.AccessTable._parse_row = _parse_row


def read(path: pathlib.Path) -> list[dict]:
  """Every liquid class in the database, as plain data."""
  logging.getLogger("access_parser").setLevel(logging.ERROR)
  from access_parser import access_parser as ap

  _patch(ap)
  table = ap.AccessParser(str(path)).parse_table("LiquidClass")
  out = []
  for i, name in enumerate(table["LiquidClassName"]):
    blob = table["CorrectionCurve"][i] or b""
    if isinstance(blob, str):
      blob = blob.encode("latin-1")
    values = struct.unpack(f"<{len(blob) // 8}d", blob[: len(blob) // 8 * 8])
    out.append({
      "name": name, "liquid": table["LiquidName"][i], "tip_type": table["TipType"][i],
      "dispense_mode": table["DispenseMode"][i], "hamilton": bool(table["OriginalLiquid"][i]),
      "curve": [[values[k], values[k + 1]] for k in range(0, len(values) - 1, 2)],
      "parameters": {plr: table[col][i] for col, plr in PARAMETERS.items()},
    })
  return out


def check_plr(classes: list[dict]) -> int:
  """Compare with PLR's STAR classes of the same name; the number of differences."""
  from pylabrobot.hamilton.star.liquid_classes import mapping

  diffs = compared = 0
  for c in classes:
    plr = getattr(mapping, c["name"], None)
    if plr is None:
      continue
    compared += 1
    # the database's doubles as read (1.2000000000000002); PLR's table has them rounded (1.2)
    mine = {round(a, 9): round(b, 9) for a, b in c["curve"]}
    if {round(float(k), 9): round(float(v), 9) for k, v in plr.curve.items()} != mine:
      diffs += 1
      print(f"{c['name']}: curve differs")
    for arg, value in c["parameters"].items():
      if float(getattr(plr, arg)) != float(value):
        diffs += 1
        print(f"{c['name']}: {arg} {value} here, {getattr(plr, arg)} in PLR")
  print(f"{len(classes)} classes; {compared} also in PLR; {diffs} differences")
  return diffs


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("database", type=pathlib.Path)
  ap.add_argument("--out", type=pathlib.Path)
  ap.add_argument("--check-plr", action="store_true")
  a = ap.parse_args()
  sys.stdout.reconfigure(encoding="utf-8")
  classes = read(a.database)
  if a.out:
    a.out.write_text(json.dumps(classes, indent=1), encoding="utf-8")
    print(f"{len(classes)} classes written to {a.out}")
  if a.check_plr:
    sys.exit(1 if check_plr(classes) else 0)


if __name__ == "__main__":
  main()
