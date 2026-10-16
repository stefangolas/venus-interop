"""T0/T1 for the container format: synthetic files always, the corpus when available."""
import pytest

from conftest import CORPUS, DEFINITIONS, LAYOUTS, corpus_params
from venus_interop.files import hxcfg


def sample(version=3):
  sections = [
    hxcfg.Section("DECKLAY", 5, "ML_STAR", entries=[
      ("Deck", "ML_STAR2.dck"),
      ("Labware.1.File", "ML_STAR\\PLT_CAR_L5AC_A00.tml"),
      ("Note", 'quote " newline \n tab \t latin-1 \xe9'),
      ("Long", "x" * 300),
      ("Empty", ""),
    ]),
    hxcfg.Section("SYSTEM", 1, "default", entries=[("CNT", "0")]),
  ]
  if version >= 3:
    sections.append(hxcfg.Section("SYSTEM", 1, "default", items=["ML_STAR"]))
  return hxcfg.CfgFile(version=version, sections=sections, footer=hxcfg.Footer("me", 0, "2026-10-15 12:00"))


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("binary", [True, False])
def test_synthetic_round_trip(version, binary):
  cfg = sample(version)
  data = hxcfg.write(cfg, binary=binary)
  assert hxcfg.footer_ok(data)
  back = hxcfg.read(data)
  assert back.sections == cfg.sections
  assert back.binary == binary
  assert hxcfg.write(back) == data


def test_binary_and_text_agree():
  cfg = sample()
  assert hxcfg.read(hxcfg.write_binary(cfg)).sections == hxcfg.read(hxcfg.write_text(cfg)).sections


def test_text_escapes():
  text = hxcfg.write_text(sample())
  assert b'"ML_STAR\\\\PLT_CAR_L5AC_A00.tml"' in text
  assert b'quote \\" newline \\n tab \\t latin-1 \\0xe9' in text


def test_long_string_uses_u16_length():
  data = hxcfg.write_binary(sample())
  assert b"\xff\x2c\x01" + b"x" * 300 in data


def test_footer_detects_change():
  data = hxcfg.write_binary(sample())
  assert not hxcfg.footer_ok(data.replace(b"ML_STAR2", b"ML_STAR3"))


def test_list_sections_need_version_3():
  cfg = sample(2)
  cfg.sections.append(hxcfg.Section("SYSTEM", 1, "x", items=["a"]))
  with pytest.raises(hxcfg.FormatError):
    hxcfg.write_binary(cfg)


# ------------------------------------------------------------------------------ corpus


def _crlf(data: bytes) -> bytes:
  """Some text-form files were stored by git with LF endings; Venus writes CRLF."""
  return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


@pytest.mark.parametrize("path", corpus_params(LAYOUTS + DEFINITIONS))
def test_t0_t1_corpus(path):
  data = path.read_bytes()
  if data.startswith(hxcfg.TEXT_MAGIC) and not hxcfg.footer_ok(data):
    data = _crlf(data)
  assert hxcfg.footer_ok(data)
  assert hxcfg.write(hxcfg.read(data)) == data


@pytest.mark.parametrize("path", corpus_params(LAYOUTS))
def test_text_form_matches_hamilton_converter(path):
  converted = CORPUS / "text" / path.name
  cfg = hxcfg.read(path)
  if not cfg.binary or not converted.exists():
    pytest.skip("no converter output for this file")
  ours = hxcfg.write_text(cfg)
  theirs = converted.read_bytes()
  # identical up to the footer, which carries the converter's own author and time
  assert ours[:ours.rfind(b"* $$")] == theirs[:theirs.rfind(b"* $$")]
