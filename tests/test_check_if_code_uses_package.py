import ast
import json

import pytest

from copilot import llm_client
from copilot.agents.tools.check_if_code_uses_package import (
    FUNCTION_NOT_CALLED,
    NOT_USED,
    USED,
    UsageRequest,
    attribute_root,
    calls_of,
    check_if_code_uses_package,
    extract_vulnerable_function,
    import_name_for,
    module_bindings,
    python_files,
)

SOURCE = """\
import requests
from jinja2 import Template
from flask import request

PAGE = Template("hi")


def fetch(url):
    response = requests.get(url, timeout=5)
    name = request.args.get("name")
    return response, name, PAGE.render()
"""


def test_an_import_name_is_guessed_from_the_package_name():
    assert import_name_for("urllib3") == "urllib3"
    assert import_name_for("typing_extensions") == "typing_extensions"


def test_a_package_whose_import_name_differs_is_looked_up():
    assert import_name_for("PyYAML") == "yaml"
    assert import_name_for("beautifulsoup4") == "bs4"
    assert import_name_for("scikit-learn") == "sklearn"


def test_a_plain_import_is_found_with_its_alias():
    lines, aliases, names = module_bindings(ast.parse(SOURCE), "requests")
    assert lines == [1]
    assert aliases == {"requests"}
    assert names == set()


def test_a_from_import_records_the_names_it_binds():
    lines, aliases, names = module_bindings(ast.parse(SOURCE), "jinja2")
    assert lines == [2]
    assert names == {"Template"}


def test_an_aliased_import_is_tracked():
    tree = ast.parse("import requests as rq\n")
    _, aliases, _ = module_bindings(tree, "requests")
    assert aliases == {"rq"}


def test_a_submodule_import_counts_as_importing_the_package():
    tree = ast.parse("from cryptography.hazmat.primitives import hashes\n")
    lines, _, names = module_bindings(tree, "cryptography")
    assert lines == [1]
    assert names == {"hashes"}


def test_a_package_that_is_not_imported_binds_nothing():
    lines, aliases, names = module_bindings(ast.parse(SOURCE), "urllib3")
    assert (lines, aliases, names) == ([], set(), set())


def test_a_call_through_the_module_counts():
    tree = ast.parse(SOURCE)
    _, aliases, names = module_bindings(tree, "requests")
    assert calls_of(tree, "get", aliases, names) == [9]


def test_the_same_method_name_on_an_unrelated_object_does_not_count():
    tree = ast.parse(SOURCE)
    _, aliases, names = module_bindings(tree, "requests")
    # request.args.get on line 10 belongs to flask, not requests.
    assert 10 not in calls_of(tree, "get", aliases, names)


def test_a_bare_call_counts_only_when_the_name_came_from_the_package():
    tree = ast.parse(SOURCE)
    _, aliases, names = module_bindings(tree, "jinja2")
    assert calls_of(tree, "Template", aliases, names) == [5]
    _, other_aliases, other_names = module_bindings(tree, "requests")
    assert calls_of(tree, "Template", other_aliases, other_names) == []


def test_the_root_of_an_attribute_chain_is_found():
    call = ast.parse("a.b.c.d()").body[0].value
    assert attribute_root(call.func) == "a"
    assert attribute_root(ast.parse("f()").body[0].value.func) == "f"
    # A chain rooted in a call result cannot be traced back to an import.
    rootless = ast.parse("factory().method()").body[0].value.func
    assert attribute_root(rootless) is None


def test_vendored_directories_are_not_scanned(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "evil.py").write_text("import requests\n")
    (tmp_path / "app.py").write_text("import requests\n")
    assert [path.name for path in python_files(tmp_path)] == ["app.py"]


def write_app(tmp_path, source=SOURCE):
    (tmp_path / "app.py").write_text(source)
    return tmp_path


def test_a_package_that_is_used_is_reported_as_used(tmp_path):
    write_app(tmp_path)
    result = check_if_code_uses_package(
        UsageRequest(repo_path=str(tmp_path), package="requests", vulnerable_function="get")
    )
    assert result.verdict == USED
    assert result.called_at[0].line == 9
    assert "requests.get" in result.called_at[0].snippet


def test_an_imported_package_whose_function_is_not_called_is_separated_out(tmp_path):
    write_app(tmp_path)
    result = check_if_code_uses_package(
        UsageRequest(repo_path=str(tmp_path), package="jinja2", vulnerable_function="from_string")
    )
    assert result.verdict == FUNCTION_NOT_CALLED
    assert result.imported_at[0].line == 2
    assert result.called_at == []


def test_a_package_that_is_never_imported_is_reported_as_unused(tmp_path):
    write_app(tmp_path)
    result = check_if_code_uses_package(UsageRequest(repo_path=str(tmp_path), package="urllib3"))
    assert result.verdict == NOT_USED
    assert result.imported_at == []


def test_an_imported_package_with_no_named_function_is_simply_used(tmp_path):
    write_app(tmp_path)
    result = check_if_code_uses_package(UsageRequest(repo_path=str(tmp_path), package="requests"))
    assert result.verdict == USED


def test_a_file_that_will_not_parse_is_skipped(tmp_path):
    (tmp_path / "broken.py").write_text("def (:\n")
    (tmp_path / "app.py").write_text("import requests\n")
    result = check_if_code_uses_package(UsageRequest(repo_path=str(tmp_path), package="requests"))
    assert result.files_scanned == 1
    assert result.verdict == USED


@pytest.fixture
def canned(monkeypatch):
    def install(reply):
        monkeypatch.setattr(llm_client, "ask_llm", lambda *a, **k: reply)

    return install


def test_a_named_function_is_extracted_from_an_advisory(canned):
    canned(json.dumps({"function_name": "from_string", "reason": "the advisory names it"}))
    assert extract_vulnerable_function("Template.from_string is unsafe") == "from_string"


def test_an_advisory_naming_no_function_gives_none(canned):
    canned(json.dumps({"function_name": None, "reason": "nothing specific"}))
    assert extract_vulnerable_function("The whole package is affected") is None


def test_a_reply_that_is_not_json_gives_none(canned):
    canned("sorry, plain text")
    assert extract_vulnerable_function("anything") is None


def test_a_reply_that_is_not_a_usable_identifier_is_rejected(canned):
    canned(json.dumps({"function_name": "not a function name", "reason": "noise"}))
    assert extract_vulnerable_function("anything") is None
