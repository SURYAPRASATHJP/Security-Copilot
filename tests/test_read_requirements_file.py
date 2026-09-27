from copilot.dependencies.read_requirements_file import (
    read_requirements_file,
    read_requirements_text,
)

TRICKY = """\
# Web layer, pinned on purpose.
Flask==2.0.1
requests[socks] == 2.28.1   # inline comment after two spaces
urllib3>=1.26,<2
jinja2==3.0.0 ; python_version >= "3.7"
pyyaml==\\
    5.3.1
-r base.txt
-e .
--index-url https://pypi.org/simple
cryptography==41.0.0 --hash=sha256:deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef
not a requirement at all!!
setuptools==4.*
"""


def test_reads_every_real_requirement():
    parsed = read_requirements_text(TRICKY)
    assert [r.name for r in parsed.requirements] == [
        "Flask",
        "requests",
        "urllib3",
        "jinja2",
        "pyyaml",
        "cryptography",
        "setuptools",
    ]


def test_an_inline_comment_does_not_become_part_of_the_version():
    parsed = read_requirements_text(TRICKY)
    requests = next(r for r in parsed.requirements if r.name == "requests")
    assert requests.pinned_version == "2.28.1"
    assert requests.extras == ["socks"]


def test_a_backslash_continuation_is_folded_into_one_requirement():
    pyyaml = next(r for r in read_requirements_text(TRICKY).requirements if r.name == "pyyaml")
    assert pyyaml.pinned_version == "5.3.1"


def test_an_environment_marker_is_kept_and_does_not_break_the_pin():
    jinja = next(r for r in read_requirements_text(TRICKY).requirements if r.name == "jinja2")
    assert jinja.pinned_version == "3.0.0"
    assert 'python_version >= "3.7"' in jinja.marker


def test_a_hash_option_is_stripped_before_parsing():
    crypto = next(
        r for r in read_requirements_text(TRICKY).requirements if r.name == "cryptography"
    )
    assert crypto.pinned_version == "41.0.0"


def test_an_unpinned_range_is_warned_about_but_still_returned():
    parsed = read_requirements_text(TRICKY)
    urllib3 = next(r for r in parsed.requirements if r.name == "urllib3")
    assert urllib3.pinned_version is None
    assert urllib3.specifier in (">=1.26,<2", "<2,>=1.26")
    assert any("urllib3 is not pinned" in w for w in parsed.warnings)


def test_a_wildcard_pin_does_not_count_as_pinned():
    setuptools = next(
        r for r in read_requirements_text(TRICKY).requirements if r.name == "setuptools"
    )
    assert setuptools.pinned_version is None


def test_an_include_is_reported_rather_than_followed():
    parsed = read_requirements_text(TRICKY)
    assert any("base.txt" in w and "not followed" in w for w in parsed.warnings)


def test_pip_options_and_editable_installs_are_skipped_silently():
    parsed = read_requirements_text("--index-url https://pypi.org/simple\n-e .\n")
    assert parsed.requirements == []
    assert parsed.warnings == []


def test_an_unreadable_line_is_warned_about_with_its_line_number():
    parsed = read_requirements_text(TRICKY)
    assert any("line 12" in w and "cannot read" in w for w in parsed.warnings)


def test_names_are_normalised_for_comparison():
    parsed = read_requirements_text("typing_extensions==4.0.0\nFlask==2.0.1\n")
    assert [r.canonical_name for r in parsed.requirements] == ["typing-extensions", "flask"]


def test_only_pinned_requirements_appear_in_the_pinned_list():
    parsed = read_requirements_text(TRICKY)
    assert {r.name for r in parsed.pinned} == {
        "Flask",
        "requests",
        "jinja2",
        "pyyaml",
        "cryptography",
    }


def test_reading_from_disk_records_the_path(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("requests==2.28.1\n")
    parsed = read_requirements_file(path)
    assert parsed.path == str(path)
    assert parsed.requirements[0].line_number == 1


def test_a_byte_order_mark_does_not_hide_the_first_package():
    parsed = read_requirements_text("\ufeffrequests==2.27.1\nflask==2.2.2\n")
    assert [r.name for r in parsed.requirements] == ["requests", "flask"]
    assert parsed.warnings == []


def test_windows_line_endings_are_handled():
    parsed = read_requirements_text("requests==2.27.1\r\nflask==2.2.2\r\n")
    assert [r.pinned_version for r in parsed.requirements] == ["2.27.1", "2.2.2"]


def test_a_file_of_only_comments_reads_as_empty():
    parsed = read_requirements_text("# my deps\n# nothing yet\n")
    assert parsed.requirements == []
    assert parsed.warnings == []
