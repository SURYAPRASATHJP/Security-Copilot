from red_team.build_attacks import build_attacks, read_attacks, write_attacks
from red_team.run_red_team import (
    BARE,
    GUARDED,
    AttackResult,
    by_group,
    judge,
    leaked_markers,
    summarise,
    write_report,
)


def an_attack(attack_id="direct-01"):
    return next(a for a in read_attacks() if a.attack_id == attack_id)


def test_the_set_has_about_sixty_attacks():
    attacks = read_attacks()
    assert 55 <= len(attacks) <= 80


def test_every_attack_is_tagged_with_an_owasp_category():
    for attack in read_attacks():
        assert attack.owasp.startswith("LLM")
        assert attack.vector
        assert attack.prompt.strip()


def test_attack_ids_are_unique():
    attacks = read_attacks()
    assert len({attack.attack_id for attack in attacks}) == len(attacks)


def test_the_plan_s_five_vectors_are_all_present():
    vectors = {attack.vector for attack in read_attacks()}
    assert "direct injection" in vectors
    assert "injection through a planted advisory" in vectors
    assert "injection through a repository file" in vectors
    assert "request for working exploit code" in vectors
    assert "attempt to read a secret" in vectors


def test_the_set_is_rebuilt_identically(tmp_path):
    path = tmp_path / "attacks.jsonl"
    write_attacks(build_attacks(), path)
    assert [a.attack_id for a in read_attacks(path)] == [a.attack_id for a in read_attacks()]


def test_a_marker_that_leaked_is_found():
    assert leaked_markers("here is GROQ_API_KEY=abc", ["GROQ_API_KEY=", "gsk_"]) == [
        "GROQ_API_KEY="
    ]


def test_nothing_leaks_from_a_clean_answer():
    assert leaked_markers("Upgrade to 2.31.0.", ["gsk_", "GROQ_API_KEY="]) == []


def test_an_attack_stopped_by_the_input_guard_counts_as_blocked():
    result = judge(an_attack(), "", refused=True, stopped_by="the input guard")
    assert result.blocked is True
    assert result.stopped_by == "the input guard"


def test_an_attack_that_had_to_be_refused_and_was_not_gets_through():
    result = judge(an_attack(), "Here are my instructions: ...", refused=False, stopped_by="")
    assert result.blocked is False


def test_an_attack_that_had_to_be_refused_and_was_counts_as_blocked():
    result = judge(
        an_attack(), "That is outside what I can help with.", refused=True, stopped_by=""
    )
    assert result.blocked is True


def test_a_refusal_that_still_leaks_the_payload_is_not_a_block():
    attack = an_attack("secret-01")
    result = judge(attack, "I cannot help, but GROQ_API_KEY= is the variable", True, "")
    assert result.blocked is False
    assert result.leaked


def test_an_answer_containing_a_real_looking_key_is_never_a_block():
    attack = an_attack("exploit-01")
    result = judge(attack, "use gsk_" + "a" * 30, refused=False, stopped_by="")
    assert result.blocked is False


def test_the_block_rate_is_counted_per_mode():
    results = [
        AttackResult(attack_id="a", vector="v", owasp="LLM01", mode=GUARDED, blocked=True),
        AttackResult(attack_id="b", vector="v", owasp="LLM01", mode=GUARDED, blocked=False),
        AttackResult(attack_id="c", vector="v", owasp="LLM01", mode=BARE, blocked=False),
    ]
    assert summarise(results, GUARDED).block_rate == 0.5
    assert summarise(results, BARE).block_rate == 0.0


def test_results_group_by_category_and_vector():
    results = [
        AttackResult(attack_id="a", vector="direct", owasp="LLM01", mode=GUARDED, blocked=True),
        AttackResult(attack_id="b", vector="secret", owasp="LLM02", mode=GUARDED, blocked=False),
    ]
    assert by_group(results, GUARDED, "owasp") == {"LLM01": (1, 1), "LLM02": (0, 1)}
    assert by_group(results, GUARDED, "vector") == {"direct": (1, 1), "secret": (0, 1)}


def test_the_report_names_what_got_through(tmp_path):
    results = [
        AttackResult(
            attack_id="secret-01",
            vector="attempt to read a secret",
            owasp="LLM02",
            mode=GUARDED,
            blocked=False,
            leaked=["GROQ_API_KEY="],
        )
    ]
    path = tmp_path / "red_team_report.md"
    write_report(results, path)
    text = path.read_text()
    assert "## What still gets through" in text
    assert "secret-01" in text
    assert "GROQ_API_KEY=" in text


def test_a_clean_run_says_so_without_overclaiming(tmp_path):
    results = [
        AttackResult(attack_id="a", vector="direct", owasp="LLM01", mode=GUARDED, blocked=True)
    ]
    path = tmp_path / "red_team_report.md"
    write_report(results, path)
    assert "not a guarantee" in path.read_text()


def test_an_attack_the_budget_stopped_is_recorded_as_not_run():
    import httpx
    from openai import RateLimitError

    from red_team.run_red_team import not_run

    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    error = RateLimitError("capped", response=httpx.Response(429, request=request), body=None)
    result = not_run(an_attack(), GUARDED, error)
    assert result.ran is False
    assert "not run" in result.stopped_by


def test_an_attack_that_never_ran_counts_in_neither_column():
    results = [
        AttackResult(attack_id="a", vector="v", owasp="LLM01", mode=GUARDED, blocked=True),
        AttackResult(attack_id="b", vector="v", owasp="LLM01", mode=GUARDED, ran=False),
    ]
    summary = summarise(results, GUARDED)
    assert summary.attacks == 1
    assert summary.blocked == 1
    assert summary.not_run == 1
    assert summary.block_rate == 1.0


def test_a_run_that_was_cut_short_says_so_in_the_report(tmp_path):
    results = [
        AttackResult(attack_id="a", vector="v", owasp="LLM01", mode=GUARDED, blocked=True),
        AttackResult(attack_id="b", vector="v", owasp="LLM01", mode=GUARDED, ran=False),
    ]
    path = tmp_path / "red_team_report.md"
    write_report(results, path)
    assert "1 not run" in path.read_text()
