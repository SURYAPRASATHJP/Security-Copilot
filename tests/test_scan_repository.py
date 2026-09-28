from copilot.agents.tools.scan_repository import (
    ScanRequest,
    find_manifests,
    looks_like_a_url,
    packages_from_pyproject,
    requirement_strings_from_pyproject,
    scan_repository,
)

PYPROJECT = """\
[project]
name = "example"
dependencies = ["requests==2.27.1", "urllib3>=1.26"]

[project.optional-dependencies]
dev = ["pytest==8.0.0"]

[dependency-groups]
lint = ["ruff==0.8.0"]
"""


def test_a_github_url_is_recognised():
    assert looks_like_a_url("https://github.com/owner/repo") is True
    assert looks_like_a_url("git@github.com:owner/repo.git") is True


def test_a_local_path_is_not_mistaken_for_a_url():
    assert looks_like_a_url("demo_vulnerable_app") is False
    assert looks_like_a_url("/Users/someone/project") is False


def test_requirements_and_pyproject_are_both_found(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.27.1\n")
    (tmp_path / "requirements-dev.txt").write_text("pytest==8.0.0\n")
    (tmp_path / "pyproject.toml").write_text(PYPROJECT)
    names = sorted(path.name for path in find_manifests(tmp_path))
    assert names == ["pyproject.toml", "requirements-dev.txt", "requirements.txt"]


def test_vendored_directories_are_skipped(tmp_path):
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "requirements.txt").write_text("evil==1.0\n")
    (tmp_path / "requirements.txt").write_text("requests==2.27.1\n")
    assert [path.name for path in find_manifests(tmp_path)] == ["requirements.txt"]


def test_a_manifest_deeper_than_the_limit_is_ignored(tmp_path):
    deep = tmp_path / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (deep / "requirements.txt").write_text("deep==1.0\n")
    assert find_manifests(tmp_path, max_depth=3) == []


def test_every_dependency_table_in_a_pyproject_is_read():
    data = {
        "project": {
            "dependencies": ["requests==2.27.1"],
            "optional-dependencies": {"dev": ["pytest==8.0.0"]},
        },
        "dependency-groups": {"lint": ["ruff==0.8.0"]},
    }
    assert requirement_strings_from_pyproject(data) == [
        "requests==2.27.1",
        "pytest==8.0.0",
        "ruff==0.8.0",
    ]


def test_pyproject_pins_are_read_as_pinned(tmp_path):
    path = tmp_path / "pyproject.toml"
    path.write_text(PYPROJECT)
    packages, warnings = packages_from_pyproject(path)
    assert warnings == []
    by_name = {package.canonical_name: package for package in packages}
    assert by_name["requests"].pinned_version == "2.27.1"
    assert by_name["urllib3"].pinned_version is None


def test_a_broken_pyproject_is_reported_not_raised(tmp_path):
    path = tmp_path / "pyproject.toml"
    path.write_text("[project\nbroken")
    packages, warnings = packages_from_pyproject(path)
    assert packages == []
    assert "cannot be read" in warnings[0]


def test_an_unreadable_dependency_string_is_warned_about(tmp_path):
    path = tmp_path / "pyproject.toml"
    path.write_text('[project]\ndependencies = ["not a requirement!!"]\n')
    packages, warnings = packages_from_pyproject(path)
    assert packages == []
    assert "cannot read" in warnings[0]


def test_scanning_the_demo_app_lists_its_packages():
    result = scan_repository(ScanRequest(source="demo_vulnerable_app"))
    assert result.manifests == ["requirements.txt"]
    assert result.package_names == [
        "certifi",
        "cryptography",
        "flask",
        "idna",
        "jinja2",
        "requests",
        "urllib3",
        "werkzeug",
    ]


def test_the_same_pin_in_two_manifests_is_listed_once(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.27.1\n")
    (tmp_path / "requirements-dev.txt").write_text("requests==2.27.1\npytest==8.0.0\n")
    result = scan_repository(ScanRequest(source=str(tmp_path)))
    assert result.package_names == ["pytest", "requests"]


def test_a_repository_with_no_manifest_says_so(tmp_path):
    (tmp_path / "README.md").write_text("nothing to see")
    result = scan_repository(ScanRequest(source=str(tmp_path)))
    assert result.packages == []
    assert "no requirements file or pyproject.toml was found" in result.warnings


def test_a_path_that_is_not_a_directory_is_reported(tmp_path):
    missing = tmp_path / "does-not-exist"
    result = scan_repository(ScanRequest(source=str(missing)))
    assert result.packages == []
    assert "is not a directory" in result.warnings[0]
