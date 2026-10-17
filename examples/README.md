# Examples: hand-built PLR decks for Venus layouts

| File | Deck | Notes |
|---|---|---|
| `kapa_deck.py`, `kapa_compare_to_lay.py` | NGS STAR KAPA HyperPlus (`NGS-Protocols/protocols/KAPA_HyperPrep/KAPA_HyperPlus_Deck.lay`) | [docs/notes/VENUS_TO_PLR_kapa.md](../docs/notes/VENUS_TO_PLR_kapa.md) |
| `kapa_demo.py` | The same deck, running a slice of the protocol: a 96-head bead cleanup and an ODTC run | `--view` plays it in the 3D viewer; headless by default |
| `tc_deck.py` | The tissue-culture STARlet deck | [docs/notes/VENUS_TO_PLR_tissue_culture.md](../docs/notes/VENUS_TO_PLR_tissue_culture.md) |

These are the "physical" counterpart to the converter's faithful decks: one resource per physical object, built from pylabrobot factories. They import from the `plr-viz3d` fork at `fork/viz3d-motion` (multiflex, ODTC, CPAC, heater shakers) and from `plr-viz3d-scratch`, as they did where they were written. Run them in that environment, e.g. with `git archive fork/viz3d-motion pylabrobot` unpacked first on `PYTHONPATH`. They are kept as references, not tested here.

`kapa_demo.py` needs more than `fork/viz3d-motion`: it uses the CO-RE gripper, the tip support and the iSWAP collision check together, and as of 2026-10-16 only the uncommitted fork state of 2026-09-30 (kept as a stash on `viz3d-pr`) has all three. Run it on that tree, and with `--no-collision-check`: the ODTC's collision mesh is too coarse, so the check refuses the iSWAP's reach into it.
