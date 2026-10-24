"""Corpus layout identifiers survive relocation and incremental builds."""
import csv
import hashlib

from venus_interop import corpora


def test_layout_names_survive_relocation_and_keep_bytes(tmp_path):
  payload = b"layout\r\n\x00\xff"
  expected = hashlib.sha1(payload).hexdigest()[:12]
  for name in ("first", "relocated"):
    root = tmp_path / name
    root.mkdir()
    source = root / "example.lay"
    source.write_bytes(payload)
    out = root / "corpus"
    assert corpora.build(out, [source], [], source="sample", root=root) == {
      "layouts": 1, "definitions": 0}
    assert (out / "raw" / (expected + ".lay")).read_bytes() == payload
    with (out / "index.tsv").open(newline="", encoding="utf-8") as f:
      assert list(csv.reader(f, delimiter="\t")) == [
        [expected, "sample", "example.lay", str(len(payload))]]
    second = root / "second.lay"
    second.write_bytes(b"different")
    corpora.build(out, [second], [], root=root)
    corpora.build(out, [source], [], source="sample", root=root)
    with (out / "index.tsv").open(newline="", encoding="utf-8") as f:
      rows = list(csv.reader(f, delimiter="\t"))
    assert len(rows) == 2
    assert {row[0] + ".lay" for row in rows} == {p.name for p in (out / "raw").iterdir()}
