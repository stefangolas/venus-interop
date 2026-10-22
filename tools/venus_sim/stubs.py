"""Stand-ins for GUI and camera modules pyhamilton imports at package level that the 32-bit Python
doesn't have (no opencv wheel, no tkinter): the probes use none of them. Import before pyhamilton."""
import sys
import types

STUBS = ["cv2", "tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox", "tkinter.simpledialog",
         "tkinter.font", "matplotlib", "matplotlib.pyplot", "matplotlib.patches", "matplotlib.colors"]


class _Anything(types.ModuleType):
  def __getattr__(self, name):  # any attribute a module-level `from x import y` asks for
    return type(name, (), {})


for m in STUBS:
  sys.modules.setdefault(m, _Anything(m))
