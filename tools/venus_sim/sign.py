"""Give an HSL file a valid Venus checksum footer, in place (venus_interop.files.footer): CRLF line
endings, the footer last, its length field its own length. Venus refuses a method without one.

  python sign.py FILE.hsl [...]"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))
from venus_interop.files import footer  # noqa: E402


def sign(p: pathlib.Path) -> bool:
  data = p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
  last = data.rstrip(b"\r\n").split(b"\r\n")[-1]
  if last.startswith(b"// $$author="):  # an earlier footer: drop it
    data = data.rstrip(b"\r\n")[:-len(last)]
  line = b"// $$author=venus-sim$$valid=0$$time=2026-10-22 09:00$$checksum=00000000$$length=%03d$$"
  line = line % len(line % 0)  # the length field is the footer line's own length
  data = data.rstrip(b"\r\n") + b"\r\n" + line  # the footer ends the file, as Venus writes it
  out = footer.rewrite(data, author="venus-sim")
  p.write_bytes(out)
  return footer.ok(out)


if __name__ == "__main__":
  for name in sys.argv[1:]:
    print(name, "footer ok" if sign(pathlib.Path(name)) else "FOOTER BAD")
