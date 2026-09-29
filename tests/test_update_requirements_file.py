import pytest

from copilot.agents.tools.update_requirements_file import (
    RefusedError,
    UpdateRequest,
    check_branch_is_allowed,
    check_filename_is_allowed,
    rewrite_pins,
    unified_diff,
    update_requirements_file,
)

REQUIREMENTS = """\
# Web layer, pinned on purpose.
flask==2.2.2
requests[socks]==2.27.1   # inline comment
urllib3>=1.26,<2
jinja2==3.1.2 ; python_version >= "3.7"
-e .
"""


def test_only_requirements_files_may_be_written():
    check_filename_is_allowed("requirements.txt")
    check_filename_is_allowed("requirements-dev.txt")
    for forbidden in ("pyproject.toml", "setup.py", "app.py", ".env", "requirements.yaml"):
        with pytest.raises(RefusedError, match="only writes"):
            check_filename_is_allowed(forbidden)


def test_a_path_that_ends_in_a_requirements_file_is_allowed():
    check_filename_is_allowed("services/api/requirements.txt")


def test_the_protected_branches_are_refused():
    for branch in ("main", "master", "Main", " develop "):
        with pytest.raises(RefusedError, match="new branch"):
            check_branch_is_allowed(branch)


def test_a_fix_branch_is_allowed():
    check_branch_is_allowed("security-copilot/fix-dependencies")


def test_a_pin_is_replaced_and_reported():
    after, changed, unchanged = rewrite_pins(REQUIREMENTS, {"flask": "3.1.3"})
    assert "flask==3.1.3" in after
    assert changed == ["flask 2.2.2 to 3.1.3"]
    assert unchanged == []


def test_an_inline_comment_and_extras_survive_the_rewrite():
    after, changed, _ = rewrite_pins(REQUIREMENTS, {"requests": "2.33.0"})
    assert "requests[socks]==2.33.0   # inline comment" in after
    assert changed == ["requests 2.27.1 to 2.33.0"]


def test_an_environment_marker_survives_the_rewrite():
    after, _, _ = rewrite_pins(REQUIREMENTS, {"jinja2": "3.1.6"})
    assert 'jinja2==3.1.6 ; python_version >= "3.7"' in after


def test_an_unpinned_package_is_left_alone_and_reported():
    after, changed, unchanged = rewrite_pins(REQUIREMENTS, {"urllib3": "2.8.0"})
    assert after == REQUIREMENTS
    assert changed == []
    assert unchanged == ["urllib3"]


def test_a_package_that_is_not_in_the_file_is_reported_unchanged():
    _, changed, unchanged = rewrite_pins(REQUIREMENTS, {"tornado": "6.5.0"})
    assert changed == []
    assert unchanged == ["tornado"]


def test_a_pin_already_at_the_target_version_is_not_touched():
    _, changed, _ = rewrite_pins(REQUIREMENTS, {"flask": "2.2.2"})
    assert changed == []


def test_several_packages_can_be_repinned_at_once():
    after, changed, _ = rewrite_pins(
        REQUIREMENTS, {"flask": "3.1.3", "requests": "2.33.0", "jinja2": "3.1.6"}
    )
    assert len(changed) == 3
    assert "flask==3.1.3" in after
    assert "requests[socks]==2.33.0" in after
    assert "jinja2==3.1.6" in after


def test_comments_and_options_are_never_rewritten():
    after, _, _ = rewrite_pins(REQUIREMENTS, {"flask": "3.1.3"})
    assert after.splitlines()[0] == "# Web layer, pinned on purpose."
    assert "-e ." in after


def test_the_diff_shows_only_the_changed_line():
    after, _, _ = rewrite_pins(REQUIREMENTS, {"flask": "3.1.3"})
    diff = unified_diff(REQUIREMENTS, after, "requirements.txt")
    assert "-flask==2.2.2" in diff
    assert "+flask==3.1.3" in diff
    assert "requests" not in diff.split("@@")[-1].replace("requests[socks]==2.27.1", "")


def test_nothing_is_written_when_asked_only_for_a_preview(tmp_path):
    target = tmp_path / "requirements.txt"
    target.write_text(REQUIREMENTS)
    result = update_requirements_file(
        UpdateRequest(repo_path=str(tmp_path), branch="fix/deps", upgrades={"flask": "3.1.3"}),
        write=False,
    )
    assert result.written is False
    assert result.changed == ["flask 2.2.2 to 3.1.3"]
    assert target.read_text() == REQUIREMENTS


def test_a_file_that_does_not_exist_is_refused(tmp_path):
    with pytest.raises(RefusedError, match="does not exist"):
        update_requirements_file(
            UpdateRequest(repo_path=str(tmp_path), branch="fix/deps", upgrades={"flask": "3.1.3"})
        )


def test_writing_to_main_is_refused_before_anything_is_read(tmp_path):
    with pytest.raises(RefusedError, match="new branch"):
        update_requirements_file(
            UpdateRequest(repo_path=str(tmp_path), branch="main", upgrades={"flask": "3.1.3"})
        )


def test_writing_a_file_that_is_not_a_requirements_file_is_refused(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    with pytest.raises(RefusedError, match="only writes"):
        update_requirements_file(
            UpdateRequest(
                repo_path=str(tmp_path),
                branch="fix/deps",
                upgrades={"flask": "3.1.3"},
                requirements_path="pyproject.toml",
            )
        )


def test_a_real_write_lands_on_a_new_branch(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    target = tmp_path / "requirements.txt"
    target.write_text(REQUIREMENTS)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-qm",
            "first",
        ],
        check=True,
    )

    result = update_requirements_file(
        UpdateRequest(repo_path=str(tmp_path), branch="fix/deps", upgrades={"flask": "3.1.3"})
    )
    assert result.written is True
    assert "flask==3.1.3" in target.read_text()
    branch = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert branch.stdout.strip() == "fix/deps"
