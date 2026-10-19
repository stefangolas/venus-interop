"""The HSL interpreter's language rules, on small programs with known results.

Each case is the HSL reference's rule or what Venus libraries rely on; the port tests then run real
libraries on top of these rules.
"""
import pathlib

from venus_interop.methods import hsl_eval, protocol, sequences as sq


def run(body: str, decls: str = "", functions: str = "", answers=None) -> hsl_eval.Run:
  src = (f"{decls}\n"
         f"namespace LIB {{ {functions} }}\n"
         f"namespace _Method {{ method main() void {{\n{body}\n}} }}\n")
  pre = hsl_eval.Preprocessor([], lambda p: "")
  text = pre.expand(pathlib.Path("t.hsl"), text=src)
  parser = hsl_eval.Parser(hsl_eval.lex(text))
  parser.unit()
  r = hsl_eval.Run(parser, protocol.load_stps([]), {}, answers=answers or {})
  r.src = text.splitlines()
  r.run()
  return r


def g(r: hsl_eval.Run, name: str):
  for scope in r.globals.values():
    for k, c in scope.items():
      if k.lower() == name.lower():
        return c.value
  raise KeyError(name)


def test_arithmetic_and_control_flow():
  r = run("""
    x = 0; i = 0;
    for (i = 0; i < 5;) { i = i + 1; x = x + i * 2; }
    while (x > 25) { x = x - 3; }
    if (x == 24) { y = 1; } else { y = 2; }
  """, decls="variable x; variable i; variable y;")
  assert r.stopped is None and (g(r, "x"), g(r, "y")) == (24, 1)


def test_by_reference_and_by_value_parameters():
  r = run("""
    a = 1; b = 1;
    LIB::Bump(a, b);
  """, decls="variable a; variable b;",
     functions="function Bump(variable & r, variable v) void { r = r + 1; v = v + 1; }")
  assert (g(r, "a"), g(r, "b")) == (2, 1)


def test_an_array_assigned_is_copied():
  r = run("""
    a.SetSize(0); a.AddAsLast(1); a.AddAsLast(2);
    b = a; b.AddAsLast(3);
    n = a.GetSize(); m = b.GetSize();
  """, decls="variable a[]; variable b[]; variable n; variable m;")
  assert (g(r, "n"), g(r, "m")) == (2, 3)


def test_a_sequence_by_value_is_a_copy_and_by_reference_the_object():
  r = run("""
    s.Add("P", "A1"); s.Add("P", "B1"); s.Add("P", "C1");
    s.SetCurrentPosition(1);
    LIB::Advance(s, s);
    cur = s.GetCurrentPosition();
  """, decls="sequence s; variable cur;",
     functions="function Advance(sequence & byref, sequence byval) void "
               "{ byref.SetCurrentPosition(3); byval.SetCurrentPosition(2); }")
  assert g(r, "cur") == 3


def test_a_decision_on_an_unknown_stops_and_says_why():
  r = run("if (u.Missing() == 1) { x = 1; }", decls="object u; variable x;")
  assert r.stopped is not None and "unknown" in r.stopped


def test_a_function_can_be_run_by_its_python_model():
  def model(run_, p):
    p["out"].value = p["x"].value * 10
    return 7
  r = run("ret = LIB::Compiled(5, got);", decls="variable ret; variable got;",
          functions="function Compiled(variable x, variable & out) variable { out = -1; return(0); }",
          answers={"functions": {"lib::compiled": model}})
  assert (g(r, "ret"), g(r, "got")) == (7, 50)
  assert any("Python model" in n for n in r.notes)


def test_sequence_properties_set_and_read():
  r = run("""
    s.Add("P", "A1"); s.Add("P", "B1");
    s.SetSequenceProperty(2, "conc", 1.5);
    v = s.GetSequenceProperty(2, "conc");
  """, decls="sequence s; variable v;")
  assert g(r, "v") == 1.5
  s = g(r, "s")
  assert isinstance(s, sq.Sequence) and s.properties == {2: {"conc": 1.5}}


def test_a_stub_body_does_not_replace_a_definition():
  # Hamilton's .hs_ headers carry stubs (`{ return(0); }`); the .hsi's definition is the function
  r = run("ret = LIB::F(2);", decls="variable ret;",
          functions="function F(variable x) variable { return(0); } function F(variable x) variable { return(x * 3); }")
  assert g(r, "ret") == 6


def test_an_unqualified_name_is_not_a_namesake_in_another_namespace():
  # GetFileName() in a library is Venus's own (the current file), not HSLExtensions::File's
  r = run(r'n = GetFileName(); m = LIB::FILE::GetFileName("C:\\a\\b.xls");', decls="variable n; variable m;",
          functions="namespace FILE { function GetFileName(variable p) variable { variable r; r = \"lib\"; return(r); } }")
  assert (g(r, "n"), g(r, "m")) == ("method", "lib")


def test_file_system_object_gives_a_paths_file_name():
  r = run(r'o.CreateObject("Scripting.FileSystemObject"); n = o.GetFileName("C:\\x\\TEMP_SORT_FILE.xls");',
          decls="object o; variable n;")
  assert g(r, "n") == "TEMP_SORT_FILE.xls"


def test_labware_positions_come_from_the_answers():
  r = run('DevGetLabwarePositionEx(d, "T1", "A2", x, y, z, a);', decls="variable d; variable x; variable y; "
          "variable z; variable a;", answers={"labware_position": lambda lab, pos: (100.0 + int(pos[1:]), 300.0, 5.0)})
  assert (g(r, "x"), g(r, "y"), g(r, "z"), g(r, "a")) == (102.0, 300.0, 5.0, 0.0)


def test_a_workbook_query_takes_index_as_a_column_name():
  # Jet takes a bare INDEX (STAR Tip Tools' sort file); SQLite reserves it
  r = run("""
    f.AddField("INDEX", i, hslInteger); f.Open("w.xls SORT", hslWrite);
    i = 1; f.WriteRecord(); i = 2; f.WriteRecord(); f.Close(); f.RemoveFields();
    f.AddField("INDEX", i, hslInteger); f.Open("w.xls SORT", hslRead, "UPDATE SORT SET INDEX = 5 WHERE INDEX IN(2)");
    f.Close(); i = 0;
    f.Open("w.xls SORT", hslRead, "SELECT INDEX FROM SORT ORDER BY INDEX DESC"); f.ReadRecord(); f.Close();
  """, decls="file f; variable i;")
  assert r.stopped is None and g(r, "i") == 5
