import json

import httpx
import streamlit as st

from app.streamlit_app import api_base_url, error_detail, osv_link

INTERRUPT = "__interrupt__"
STREAM_TIMEOUT = 900.0
NODE_LABELS = {
    "scanner": "Scanner: finding packages and their vulnerabilities",
    "analyst": "Analyst: checking what the code really uses, then ranking",
    "fixer": "Fixer: finding safe versions and testing the upgrade",
    "reviewer": "Reviewer: checking the fixer's work",
    "approval": "Waiting for you",
    "writer": "Writer: applying the approved change",
}


def stream_scan(repository: str, thread_id: str):  # noqa: ANN201
    """Yield one event per agent step as the server produces it."""
    with httpx.stream(
        "POST",
        f"{api_base_url()}/scan-repo",
        json={"repository": repository, "thread_id": thread_id},
        timeout=STREAM_TIMEOUT,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.strip():
                yield json.loads(line)


def planned_change_from(event: dict) -> dict | None:
    update = event.get("update")
    if event.get("node") != INTERRUPT or not update:
        return None
    first = update[0] if isinstance(update, list) else update
    value = first.get("value") if isinstance(first, dict) else None
    return (value or {}).get("planned_change")


def show_step(event: dict) -> None:
    node = event.get("node", "")
    st.markdown(f"**{NODE_LABELS.get(node, node)}**")
    update = event.get("update") or {}
    if not isinstance(update, dict):
        return

    for note in update.get("plan") or []:
        st.caption(note)
    report = update.get("report")
    if report and report.get("ranked"):
        st.caption(f"{report['findings_considered']} findings ranked, worst first")
        for risk in report["ranked"][:5]:
            link = osv_link(risk["advisory_id"])
            st.markdown(
                f"{risk['rank']}. `{risk['package']}` [{risk['advisory_id']}]({link}) "
                f"to {risk['fixed_version'] or 'no fix listed'} ({risk['usage']})"
            )
    if update.get("upgrades"):
        st.caption("proposed: " + ", ".join(f"{p} to {v}" for p, v in update["upgrades"].items()))
    tests = update.get("test_results")
    if tests:
        st.caption("tests passed" if tests.get("passed") else "tests did not pass")
    review = update.get("review")
    if review:
        st.caption(review.get("reason", ""))


def send_decision(thread_id: str, decision: str, upgrades: dict, reason: str = "") -> None:
    try:
        response = httpx.post(
            f"{api_base_url()}/approve",
            json={
                "thread_id": thread_id,
                "decision": decision,
                "upgrades": upgrades,
                "reason": reason,
            },
            timeout=STREAM_TIMEOUT,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        st.error(error_detail(error))
        return
    st.session_state["fix_result"] = response.json()
    st.session_state["pending_change"] = None
    st.rerun()


def main() -> None:
    st.set_page_config(page_title="Fix my repo", page_icon="F", layout="wide")
    st.title("Fix my repo")
    st.caption(
        "The team scans, ranks by what your code actually uses, tests the upgrade, and then "
        "stops. Nothing is written until you approve the diff."
    )

    repository = st.text_input("Repository path or GitHub URL", value="demo_vulnerable_app")
    if st.button("Scan", type="primary"):
        st.session_state["thread_id"] = f"scan-{abs(hash(repository))}"
        st.session_state["pending_change"] = None
        st.session_state["fix_result"] = None
        with st.status("Running the team", expanded=True) as status:
            try:
                for event in stream_scan(repository, st.session_state["thread_id"]):
                    if event["event"] == "error":
                        st.error(event["detail"])
                        break
                    if event["event"] != "step":
                        continue
                    change = planned_change_from(event)
                    if change:
                        st.session_state["pending_change"] = change
                        break
                    show_step(event)
            except httpx.HTTPError as error:
                st.error(error_detail(error))
            status.update(label="The team has finished", state="complete")

    change = st.session_state.get("pending_change")
    if change:
        st.subheader("Approve this change")
        st.caption(f"on branch {change['branch']} in {change['repository']}")
        st.code(change["diff"] or "no diff", language="diff")

        chosen = {}
        for package, version in sorted(change["upgrades"].items()):
            if st.checkbox(f"{package} to {version}", value=True, key=f"pick-{package}"):
                chosen[package] = version

        approve, reject = st.columns(2)
        thread_id = st.session_state["thread_id"]
        if approve.button("Approve", type="primary", disabled=not chosen):
            decision = "approved" if chosen == change["upgrades"] else "edited"
            send_decision(thread_id, decision, chosen)
        if reject.button("Reject"):
            send_decision(thread_id, "rejected", {}, reason="rejected in the interface")

    result = st.session_state.get("fix_result")
    if result:
        if result["decision"] == "rejected":
            st.info("Nothing was written.")
        else:
            st.success(f"Written on branch {result['branch']}")
            for note in result.get("plan") or []:
                st.caption(note)


if __name__ == "__main__":
    main()
