from app.pages.fix_my_repo import INTERRUPT, NODE_LABELS, planned_change_from

CHANGE = {
    "kind": "update_requirements",
    "repository": "demo_vulnerable_app",
    "branch": "security-copilot/fix-dependencies",
    "diff": "-flask==2.2.2\n+flask==3.1.3\n",
    "upgrades": {"flask": "3.1.3"},
}


def test_an_interrupt_event_yields_the_planned_change():
    event = {"node": INTERRUPT, "update": [{"value": {"planned_change": CHANGE}}]}
    assert planned_change_from(event) == CHANGE


def test_an_interrupt_sent_as_a_single_object_is_also_read():
    event = {"node": INTERRUPT, "update": {"value": {"planned_change": CHANGE}}}
    assert planned_change_from(event) == CHANGE


def test_an_ordinary_step_carries_no_planned_change():
    assert planned_change_from({"node": "scanner", "update": {"packages": []}}) is None


def test_an_interrupt_with_nothing_in_it_is_handled():
    assert planned_change_from({"node": INTERRUPT, "update": []}) is None
    assert planned_change_from({"node": INTERRUPT, "update": [{}]}) is None


def test_every_worker_has_a_label_a_person_can_read():
    for node in ("scanner", "analyst", "fixer", "reviewer", "approval", "writer"):
        assert NODE_LABELS[node]
        assert not NODE_LABELS[node].startswith(node + ":") or ": " in NODE_LABELS[node]
