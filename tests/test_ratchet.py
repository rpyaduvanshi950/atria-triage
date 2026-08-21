"""The escalation invariant: machines escalate, only clinicians relent."""
import pytest

from layer2.ratchet import Source, apply

MACHINES = [Source.RULE, Source.MODEL, Source.TRAJECTORY]


@pytest.mark.parametrize("source", MACHINES)
def test_machines_may_escalate(source):
    assert apply(4, 2, source) == 2


@pytest.mark.parametrize("source", MACHINES)
def test_machines_may_never_de_escalate(source):
    assert apply(2, 4, source) == 2


@pytest.mark.parametrize("source", MACHINES)
def test_no_machine_can_suppress_a_red_flag(source):
    """Layer 0 fired and set priority 1. No model output may undo that."""
    assert apply(1, 5, source) == 1


def test_only_a_clinician_can_de_escalate():
    assert apply(1, 4, Source.HUMAN) == 4


def test_priorities_must_be_in_range():
    with pytest.raises(ValueError):
        apply(0, 3, Source.MODEL)
    with pytest.raises(ValueError):
        apply(3, 6, Source.MODEL)


@pytest.mark.parametrize("source", MACHINES)
def test_monotone_under_any_sequence(source):
    """Whatever order proposals arrive in, machine-driven priority never rises."""
    priority = 5
    for proposed in [3, 5, 2, 4, 5, 1, 5]:
        new = apply(priority, proposed, source)
        assert new <= priority
        priority = new
    assert priority == 1
