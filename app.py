import streamlit as st
import requests
from requests.auth import HTTPBasicAuth
import re
from html import unescape
import anthropic
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import letter
from reportlab.lib.enums import TA_JUSTIFY

# ===== CONFIG =====
ORG = "techmobius"
PAT = st.secrets["AZURE_PAT"]
client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

# ===== SESSION STATE =====
if "theme" not in st.session_state:
    st.session_state.theme = "dark"

if "release_notes" not in st.session_state:
    st.session_state.release_notes = None

# ===== TOGGLE =====
col1, col2 = st.columns([10, 1])
with col2:
    if st.button("🌙" if st.session_state.theme == "dark" else "☀️"):
        st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"
        st.rerun()

# ===== THEME =====
if st.session_state.theme == "dark":
    bg_main = "#020617"
    bg_secondary = "#0f172a"
    text_primary = "#f9fafb"
    text_secondary = "#d1d5db"
    input_bg = "#111827"
    border = "#374151"
else:
    bg_main = "#f9fafb"
    bg_secondary = "#ffffff"
    text_primary = "#111827"
    text_secondary = "#374151"
    input_bg = "#ffffff"
    border = "#d1d5db"

# ===== UI =====
st.markdown(f"""
<style>
.stApp {{
    background: linear-gradient(180deg, {bg_secondary}, {bg_main});
}}
h1 {{
    color: {text_primary};
    text-align:center;
}}
input {{
    background-color: {input_bg} !important;
    color: {text_primary} !important;
    border: 1px solid {border} !important;
    border-radius: 10px !important;
}}
.stButton > button {{
    background: linear-gradient(135deg, #10b981, #059669);
    color: white;
    border-radius: 10px;
    padding: 12px 20px;
}}
</style>
""", unsafe_allow_html=True)

# ===== HEADER =====
st.markdown("<h1>XDAS Release Notes</h1>", unsafe_allow_html=True)

# ===== HELPERS =====

def clean_html(raw_html):
    clean = re.sub('<.*?>', ' ', raw_html or "")
    return re.sub(r'\s+', ' ', unescape(clean)).strip()

def get_iterations(project, ITERATIONS):
    url = f"https://dev.azure.com/{ORG}/{project}/_apis/work/teamsettings/iterations?api-version=7.0"
    r = requests.get(url, auth=HTTPBasicAuth('', PAT)).json()
    return [it["path"] for it in r.get("value", []) if any(x in it["name"] for x in ITERATIONS)]

def get_work_item_ids(project, ITERATIONS):
    url = f"https://dev.azure.com/{ORG}/{project}/_apis/wit/wiql?api-version=7.0"
    paths = get_iterations(project, ITERATIONS)
    if not paths:
        return []

    filt = " OR ".join([f"[System.IterationPath] UNDER '{p}'" for p in paths])

    query = {
        "query": f"""
        SELECT [System.Id]
        FROM WorkItems
        WHERE
            [System.WorkItemType] = 'User Story'
            AND [System.State] = 'Closed'
            AND ({filt})
        """
    }

    r = requests.post(url, json=query, auth=HTTPBasicAuth('', PAT)).json()
    return [i["id"] for i in r.get("workItems", [])]

def get_work_item_details(ids):
    if not ids:
        return []
    url = f"https://dev.azure.com/{ORG}/_apis/wit/workitems?ids={','.join(map(str, ids))}&api-version=7.0"
    return requests.get(url, auth=HTTPBasicAuth('', PAT)).json().get("value", [])

# ===== CORE =====

def generate_release_notes(cleaned_stories):

    combined_input = ""
    project_list = []

    for project, stories in cleaned_stories.items():
        project_list.append(project)
        combined_input += f"\nPROJECT: {project}\n{stories}\n"

    project_string = ", ".join(project_list)

    prompt = f"""
You are a Product Marketing Manager writing high-quality release notes for the XDAS platform.

STRICT FORMAT:

INTRODUCTION

We are excited to introduce the latest XDAS platform release covering: {project_string}

PROJECT SUMMARIES:
Write 2–3 lines per project.

PROJECT FORMAT:

**Project Name**

**Feature Name**

Description (4–6 lines)

RULES:
- Do NOT include QA/testing
- Do NOT add conclusions
- Do NOT merge sections
"""

    res = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    return res.content[0].text

def create_pdf(text):
    doc = SimpleDocTemplate("Release_Notes.pdf", pagesize=letter)
    style = ParagraphStyle('Normal', fontSize=11, leading=16)
    content = []

    for line in text.split("\n"):
        if not line.strip():
            content.append(Spacer(1, 6))
        else:
            content.append(Paragraph(re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", line), style))

    doc.build(content)

# ===== INPUT =====
sprint = st.text_input("Sprint")
projects = st.text_input("Projects")

# ===== RUN =====
if st.button("Generate Release Notes"):

    ITERATIONS = [f"NS-{sprint}", f"NS {sprint}"]
    PROJECTS = [p.strip() for p in projects.split(",")]

    with st.spinner("Fetching..."):
        all_stories = {}
        for p in PROJECTS:
            ids = get_work_item_ids(p, ITERATIONS)
            details = get_work_item_details(ids)

            all_stories[p] = [{
                "title": d["fields"].get("System.Title", ""),
                "ac": clean_html(d["fields"].get("Microsoft.VSTS.Common.AcceptanceCriteria", ""))
            } for d in details]

    with st.spinner("Generating..."):
        st.session_state.release_notes = generate_release_notes(all_stories)

    create_pdf(st.session_state.release_notes)

# ===== DISPLAY =====
if st.session_state.release_notes:
    st.markdown("### Release Notes")
    st.markdown(st.session_state.release_notes)

    with open("Release_Notes.pdf", "rb") as f:
        st.download_button("Download PDF", f)
