from venus_interop.methods.deck_state import absent_at_start, first_roles, is_destination

SEQUENCES = {
  "Move_Plate_Handoff": [("Plate_Handoff", "A1")],
  "Move_Plate": [("Plate", "A1")],
  "Plate_lid": [("Plate_lid", "1")],
  "Lid_parking": [("Lid_parking", "1")],
  "Wells": [("Plate", "A1"), ("Plate", "B1")],
  "Series_to": [("Plate", "A2"), ("Waste_trough", "A1")],
  "Elution_1": [("EP_on_device", "A1")],
}


def test_a_move_destination_named_first_is_not_there_at_start():
  trace = [
    "> [robot] MovePlateWithLid(move_from_seq = ML_STAR.Move_Plate_Handoff, move_to_seq = ML_STAR.Move_Plate)",
    "> [robot] MoveLid(lid_from_seq = ML_STAR.Plate_lid, lid_to_seq = ML_STAR.Lid_parking)",
    "  - SequenceName = ML_STAR.Wells",
  ]
  assert absent_at_start(trace, SEQUENCES) == ["Lid_parking", "Plate"]
  assert first_roles(trace, SEQUENCES)["Plate_Handoff"] == "used"


def test_a_labware_used_before_it_is_a_destination_is_there():
  trace = [
    "  - SequenceName = ML_STAR.Wells",
    "> [robot] MovePlate(move_from_seq = ML_STAR.Move_Plate_Handoff, move_to_seq = ML_STAR.Move_Plate)",
  ]
  assert "Plate" not in absent_at_start(trace, SEQUENCES)


def test_a_pipetting_helpers_to_seq_is_not_a_move():
  trace = ["> [robot] pipette_dil_series(from_seq = ML_STAR.Wells, to_seq = ML_STAR.Series_to)"]
  assert absent_at_start(trace, SEQUENCES) == []
  assert not is_destination("to_seq") and is_destination("move_to_seq") and is_destination("lid_to_seq")


def test_putting_a_sequence_into_an_array_is_not_a_use():
  trace = [
    "  BP_arr.AddAsLast(ML_STAR.Elution_1);",
    "> [robot] MovePlate(move_from_seq = ML_STAR.Move_Plate_Handoff, move_to_seq = ML_STAR.Elution_1)",
  ]
  assert absent_at_start(trace, SEQUENCES) == ["EP_on_device"]
