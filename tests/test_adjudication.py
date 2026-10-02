from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from fastq_sheet_audit.adjudication import PairDecision, RoleDecision, RoleDecisionKind, resolve_pair_group
from fastq_sheet_audit.inventory import InventoryCategory, InventoryRecord
from fastq_sheet_audit.naming import parse_fastq_name
from fastq_sheet_audit.pairing import PairGroup, pair_key


AUTO = RoleDecision(RoleDecisionKind.AUTOMATIC, None)
UNASSIGN = RoleDecision(RoleDecisionKind.UNASSIGN, None)


def record(role, root="/scan"):
    relative = Path(f"A_{role}.fastq")
    return InventoryRecord(Path(root) / relative, relative, parse_fastq_name(relative.name), InventoryCategory.READ)


def group(ambiguous=False, r2=True):
    r1 = record("R1")
    return PairGroup(pair_key(r1), (r1, record("R1", "/other")) if ambiguous else (r1,),
                     (record("R2"),) if r2 else ())


def decision(group, r1=AUTO, r2=AUTO, confirmed=False):
    return PairDecision(group.key, r1, r2, confirmed)


def test_clean_automatic_complete_pair():
    evidence = group()
    result = resolve_pair_group(evidence, decision(evidence))
    assert result.effective_r1 is evidence.r1[0]
    assert result.effective_r2 is evidence.r2[0]
    assert result.unresolved_r1 == result.unresolved_r2 == ()
    assert result.resolved
    assert result.group is evidence


def test_automatic_r1_only():
    evidence = group(r2=False)
    result = resolve_pair_group(evidence, decision(evidence))
    assert result.effective_r1 == evidence.r1[0]
    assert result.effective_r2 is None
    assert result.unresolved_r2 == ()
    assert result.resolved


def test_automatic_ambiguous_r1():
    evidence = group(ambiguous=True)
    result = resolve_pair_group(evidence, decision(evidence))
    assert result.effective_r1 is None
    assert result.unresolved_r1 is evidence.r1
    assert result.effective_r2 == evidence.r2[0]
    assert not result.resolved


def test_explicit_selection_keeps_nonselected_evidence_in_order():
    evidence = group(ambiguous=True)
    selected = evidence.r1[1]
    result = resolve_pair_group(evidence, decision(evidence, RoleDecision(RoleDecisionKind.SELECT, selected)))
    assert result.effective_r1 is selected
    assert result.unresolved_r1 == ()
    assert result.resolved
    assert result.group is evidence
    assert result.group.r1 is evidence.r1
    assert result.group.r1 == (evidence.r1[0], selected)


def test_equal_duplicate_evidence_is_not_discarded():
    evidence = group()
    evidence = replace(evidence, r1=(evidence.r1[0], evidence.r1[0]))
    result = resolve_pair_group(evidence, decision(evidence, RoleDecision(RoleDecisionKind.SELECT, evidence.r1[0])))
    assert result.unresolved_r1 == ()
    assert result.resolved
    assert result.group is evidence
    assert result.group.r1 == (evidence.r1[0], evidence.r1[0])


@pytest.mark.parametrize("role", ["r1", "r2"])
def test_explicit_unassign_preserves_all_candidates(role):
    evidence = group()
    choices = {role: UNASSIGN}
    result = resolve_pair_group(evidence, decision(evidence, **choices))
    assert getattr(result, "effective_" + role) is None
    assert getattr(result, "unresolved_" + role) == ()
    assert result.group is evidence
    assert getattr(result.group, role) is getattr(evidence, role)
    assert result.resolved is (role == "r2")


def test_unassign_adjudicates_ambiguous_role_without_losing_evidence():
    evidence = group(ambiguous=True)
    result = resolve_pair_group(evidence, decision(evidence, r1=UNASSIGN, confirmed=True))
    assert result.effective_r1 is None
    assert result.unresolved_r1 == ()
    assert result.group.r1 is evidence.r1
    assert len(result.group.r1) == 2
    assert not result.resolved


def test_invalid_selected_candidate_uses_full_record_equality():
    evidence = group()
    invalid = replace(evidence.r1[0], category=InventoryCategory.UNPARSED)
    with pytest.raises(ValueError, match="candidate for this role"):
        resolve_pair_group(evidence, decision(evidence, RoleDecision(RoleDecisionKind.SELECT, invalid)))


@pytest.mark.parametrize("role", ["r1", "r2"])
def test_wrong_role_candidate_rejected(role):
    evidence = group()
    wrong = evidence.r2[0] if role == "r1" else evidence.r1[0]
    with pytest.raises(ValueError, match="candidate for this role"):
        resolve_pair_group(evidence, decision(evidence, **{role: RoleDecision(RoleDecisionKind.SELECT, wrong)}))


def test_equal_record_selection_is_accepted():
    evidence = group()
    selected = replace(evidence.r1[0])
    result = resolve_pair_group(evidence, decision(evidence, RoleDecision(RoleDecisionKind.SELECT, selected)))
    assert result.effective_r1 is selected
    assert result.resolved


def test_mismatched_key_rejected():
    evidence = group()
    choices = replace(decision(evidence), key=replace(evidence.key, lane=2))
    with pytest.raises(ValueError, match="key"):
        resolve_pair_group(evidence, choices)


@pytest.mark.parametrize("confirmed", [False, True])
def test_confirmed_state_preserved_without_hiding_unresolved_evidence(confirmed):
    evidence = group(ambiguous=True)
    choices = decision(evidence, confirmed=confirmed)
    result = resolve_pair_group(evidence, choices)
    assert result.confirmed is confirmed
    assert result.decision is choices
    assert result.unresolved_r1 == evidence.r1
    assert not result.resolved


def test_confirmed_orphan_r2_is_not_resolved():
    evidence = replace(group(), r1=())
    result = resolve_pair_group(evidence, decision(evidence, confirmed=True))
    assert result.confirmed
    assert result.effective_r1 is None
    assert not result.resolved


@pytest.mark.parametrize("confirmed", [0, 1, None, "true"])
def test_confirmed_requires_actual_bool(confirmed):
    evidence = group()
    with pytest.raises(ValueError, match="boolean"):
        decision(evidence, confirmed=confirmed)


@pytest.mark.parametrize("kind, selected", [
    (RoleDecisionKind.AUTOMATIC, record("R1")),
    (RoleDecisionKind.UNASSIGN, record("R1")),
    (RoleDecisionKind.SELECT, None),
    (RoleDecisionKind.SELECT, "A_R1.fastq"),
    ("automatic", None),
])
def test_role_decision_rules(kind, selected):
    with pytest.raises(ValueError):
        RoleDecision(kind, selected)


def test_manual_inconsistent_resolution_is_not_resolved():
    evidence = group()
    result = resolve_pair_group(evidence, decision(evidence))
    assert not replace(result, effective_r1=record("R1", "/different")).resolved
    assert not replace(result, decision=replace(result.decision, key=replace(evidence.key, lane=2))).resolved


def test_immutable_structures():
    evidence = group()
    choices = decision(evidence)
    result = resolve_pair_group(evidence, choices)
    for obj, field, value in [(AUTO, "selected", evidence.r1[0]),
                              (choices, "confirmed", True), (result, "effective_r1", None)]:
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, value)


def test_inputs_unchanged_and_repeated_resolution_identical():
    evidence = group(ambiguous=True)
    original = replace(evidence)
    choices = decision(evidence, RoleDecision(RoleDecisionKind.SELECT, evidence.r1[1]))
    result = resolve_pair_group(evidence, choices)
    assert resolve_pair_group(evidence, choices) == result
    assert evidence == original
    assert evidence.r1 is original.r1
    assert result.group is evidence
    assert result.decision is choices


def test_no_filesystem_or_network_access(monkeypatch):
    evidence = group()
    choices = decision(evidence)
    def fail(*args, **kwargs):
        pytest.fail("adjudication accessed external state")
    for method in ("open", "stat", "resolve", "exists"):
        monkeypatch.setattr(Path, method, fail)
    monkeypatch.setattr("builtins.open", fail)
    monkeypatch.setattr("socket.socket", fail)
    assert resolve_pair_group(evidence, choices).resolved
