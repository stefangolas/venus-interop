# Examples: hand-built PLR decks for Venus layouts

| File | Deck | Notes |
|---|---|---|
| `kapa_deck.py`, `kapa_compare_to_lay.py` | NGS STAR KAPA HyperPlus (`NGS-Protocols/protocols/KAPA_HyperPrep/KAPA_HyperPlus_Deck.lay`) | [docs/notes/VENUS_TO_PLR_kapa.md](../docs/notes/VENUS_TO_PLR_kapa.md) |
| `tc_deck.py` | The tissue-culture STARlet deck | [docs/notes/VENUS_TO_PLR_tissue_culture.md](../docs/notes/VENUS_TO_PLR_tissue_culture.md) |

These are the "physical" counterpart to the converter's faithful decks: one resource per physical object, built from pylabrobot factories. They import from the `plr-viz3d` fork at `fork/viz3d-motion` (multiflex, ODTC, CPAC, heater shakers) and from `plr-viz3d-scratch`, as they did where they were written. Run them in that environment, e.g. with `git archive fork/viz3d-motion pylabrobot` unpacked first on `PYTHONPATH`. They are kept as references, not tested here.
