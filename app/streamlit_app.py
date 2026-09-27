import httpx
import pandas as pd
import streamlit as st

from copilot.settings import get_settings

NUMERIC_COLUMNS = ("CVSS", "EPSS")
FINDING_COLUMNS = {
    "package": "Package",
    "installed_version": "Version",
    "advisory_id": "Advisory",
    "fixed_version": "Fixed in",
    "cvss_score": "CVSS",
    "epss_probability": "EPSS",
    "known_exploited": "KEV",
}
DISCLAIMER = (
    "This tool reports what public advisory databases know today. A clean result is not a "
    "guarantee that your dependencies are safe, and every suggested upgrade should be tested."
)
REQUEST_TIMEOUT = 300.0


def api_base_url() -> str:
    return st.session_state.get("api_base_url") or get_settings().api_base_url


def post(path: str, payload: dict) -> dict:
    response = httpx.post(f"{api_base_url()}{path}", json=payload, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def error_detail(error: httpx.HTTPError) -> str:
    """Turn any failed request into something readable, JSON body or not."""
    response = getattr(error, "response", None)
    if response is None:
        return f"The API could not be reached: {error}"
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict) and payload.get("detail"):
        return str(payload["detail"])
    body = response.text.strip()
    if body:
        return f"The API returned {response.status_code}: {body[:400]}"
    return f"The API returned {response.status_code} with an empty body."


def osv_link(advisory_id: str) -> str:
    return f"https://osv.dev/vulnerability/{advisory_id}"


def findings_table(findings: list[dict]) -> pd.DataFrame:
    """Turn the API's findings into the table a developer reads top to bottom."""
    rows = []
    for finding in findings:
        rows.append(
            {label: finding.get(key) for key, label in FINDING_COLUMNS.items()}
            | {"Link": osv_link(finding["advisory_id"])}
        )
    table = pd.DataFrame(rows)
    for column in NUMERIC_COLUMNS:
        if column in table:
            # A mixed float and None column renders the word None, so force it numeric.
            table[column] = pd.to_numeric(table[column], errors="coerce")
    return table


def render_answer(result: dict) -> None:
    st.markdown(result["answer"])

    if result["citations"]:
        links = " ".join(f"[[{cid}]]({osv_link(cid)})" for cid in result["citations"])
        st.caption(f"Sources: {links}")
    if result["unverified_citations"]:
        st.warning(
            "These citations were not in the retrieved advisories and have been dropped: "
            + ", ".join(result["unverified_citations"])
        )
    if result["checked_dependencies"]:
        st.caption("Your requirements file was checked before this answer was written.")

    if not result["sources"]:
        return

    with st.expander("Show sources"):
        for source in result["sources"]:
            st.markdown(
                f"**[{source['advisory_id']}]({source['url']})**  score {source['score']:.3f}"
            )
            st.text(source["text"])


def main() -> None:
    st.set_page_config(page_title="Security Copilot", page_icon="S", layout="wide")
    st.title("Security Copilot")
    st.caption("Which of your Python dependencies have known vulnerabilities, and what fixes them.")

    with st.sidebar:
        st.text_input("API base URL", value=api_base_url(), key="api_base_url")
        try:
            health = httpx.get(f"{api_base_url()}/health", timeout=10.0).json()
            st.success(f"API ready, model {health['model']}")
            if not health["groq_key_present"]:
                st.info("No Groq key is set, so the dependency check works but answers will not.")
            if not health["corpus_built"]:
                st.warning("The advisory corpus is not built. Run make data.")
        except (httpx.HTTPError, ValueError):
            st.error("The API is not reachable. Run make api in another terminal.")
        st.caption(DISCLAIMER)

    report = None
    uploaded = st.file_uploader("Upload a requirements.txt", type=["txt"])
    if uploaded is not None:
        requirements = uploaded.getvalue().decode("utf-8", errors="replace")
        st.session_state["requirements"] = requirements
        # Asking a question reruns the whole script, so the check is kept rather than repeated.
        if st.session_state.get("checked_text") != requirements:
            try:
                with st.spinner("Checking your dependencies against OSV"):
                    st.session_state["report"] = post(
                        "/check-dependencies", {"requirements": requirements}
                    )
                st.session_state["checked_text"] = requirements
            except httpx.HTTPError as error:
                st.error(error_detail(error))
                st.session_state["report"] = None
        report = st.session_state.get("report")

    if report is not None and report["packages_checked"] == 0:
        st.warning(
            "No packages could be read from that file. A requirements file needs lines like "
            "`requests==2.27.1`. Comments, pip options and editable installs are skipped."
        )
        for warning in report["warnings"]:
            st.caption(warning)
        report = None

    if report is not None:
        st.subheader(
            f"{len(report['findings'])} findings across {len(report['packages_affected'])} packages"
        )
        st.caption(f"{report['packages_checked']} packages read from the file.")
        st.caption(
            "Ordered by what to fix first: known exploited, then exploit probability, "
            "then severity."
        )
        st.dataframe(
            findings_table(report["findings"]),
            use_container_width=True,
            hide_index=True,
            column_config={"Link": st.column_config.LinkColumn("Link", display_text="osv.dev")},
        )
        for warning in report["warnings"]:
            st.caption(f"Warning: {warning}")

    st.subheader("Ask about an advisory")

    if "chat" not in st.session_state:
        st.session_state["chat"] = []

    for turn in st.session_state["chat"]:
        st.chat_message("user").write(turn["question"])
        with st.chat_message("assistant"):
            if turn.get("error"):
                st.error(turn["error"])
            else:
                render_answer(turn["result"])

    question = st.chat_input("For example: am I affected by the requests proxy header leak?")
    if question:
        turn: dict = {"question": question}
        with st.spinner("Searching the advisories"):
            try:
                turn["result"] = post(
                    "/ask",
                    {"question": question, "requirements": st.session_state.get("requirements")},
                )
            except httpx.HTTPError as error:
                turn["error"] = error_detail(error)
        st.session_state["chat"].append(turn)
        # Rerun so the new turn is drawn by the history loop above, like every earlier one.
        st.rerun()


if __name__ == "__main__":
    main()
