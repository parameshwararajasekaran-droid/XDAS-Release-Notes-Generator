import streamlit as st
import requests
from requests.auth import HTTPBasicAuth
import re
from html import unescape
import anthropic
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import letter

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

# ===== THEME COLORS =====
if st.session_state.theme == "dark":
    bg_main = "#020617"
    bg_secondary = "#0f172a"
else:
    bg_main = "#f9fafb"
    bg_secondary = "#ffffff"

# ===== UPDATED UI STYLING (FIXED READABILITY) =====
st.markdown(f"""
<style>

.stApp {{
    background: linear-gradient(180deg, {bg_secondary}, {bg_main});
}}

/* Title */
h1 {{
    color: #ffffff;
    font-weight: 700;
    text-align: center;
    letter-spacing: 0.5px;
}}

/* Labels */
label {{
    color: #cbd5f5 !important;
    font-weight: 500;
}}

/* Inputs */
input, textarea {{
    background-color: #0f172a !important;
    color: #f9fafb !important;
    border: 1px solid #475569 !important;
    border-radius: 10px !important;
    padding: 10px !important;
}}

/* Focus */
input:focus, textarea:focus {{
    border: 1px solid #10b981 !important;
    box-shadow: 0 0 0 1px rgba(16,185,129,0.3);
}}

/* Button */
.stButton > button {{
    background: linear-gradient(135deg, #10b981, #059669);
    color: white;
    border-radius: 10px;
    padding: 12px 20px;
    font-weight: 600;
}}

/* Download button */
.stDownloadButton > button {{
    background: #1e293b;
    color: #f9fafb;
    border: 1px solid #475569;
    border-radius: 10px;
}}

/* Output text */
.markdown-text-container {{
    color: #e5e7eb !important;
    line-height: 1.7;
    font-size: 15px;
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

# ===== CORE (YOUR PROMPT UNCHANGED) =====

def generate_release_notes(cleaned_stories):

    combined_input = ""
    project_list = []

    for project, stories in cleaned_stories.items():
        project_list.append(project)
        combined_input += f"\nPROJECT: {project}\n{stories}\n"

    project_string = ", ".join(project_list)

    prompt = f"""
You are a Product Marketing Manager writing high-quality release notes for the XDAS platform.

GOAL:
Generate clean, professional, user-friendly release notes.

----------------------------------------

STRICT FORMAT (MUST FOLLOW EXACTLY):

**INTRODUCTION**

<blank line>

We are excited to introduce the latest XDAS platform release, bringing focused enhancements across all the following modules: {project_string}.

IMPORTANT:
- You MUST include every project listed above
- Do NOT omit any project
- Do NOT rename any project except:
  - "workxtream development" MUST be written as "Manage Workflow"

<blank line>

PROJECT SUMMARIES (MANDATORY):

After the introduction, write 2–3 lines for EACH project summarizing key updates.

Rules:
- Cover EVERY project listed
- Each project must be mentioned explicitly
- Write in natural paragraph flow (no headings)
- Use natural, varied language
- DO NOT repeat the same verbs across projects
- DO NOT force words like "enhances", "improves", "introduces"
- Let wording adapt to actual updates (features, fixes, improvements)

----------------------------------------

PROJECT STRUCTURE:

Each project MUST be formatted as:

**<Project Name>**

<blank line>

**<Feature Name>**

<blank line>

<Feature explanation paragraph>

----------------------------------------

STRICT RULES:

- ALWAYS bold:
  - INTRODUCTION
  - Project names
  - Feature names

- NEVER write content on same line as headings
- ALWAYS leave one blank line after headings
- Never include any user stories that contain the following phrases in their titles: Post deployment testing, Regression testing, Deployment validation, ATS

- DO NOT include:
  ❌ Questions
  ❌ Suggestions
  ❌ "Would you like me to..."
  ❌ Any closing remarks

- End output immediately after last feature

----------------------------------------

FEATURE GUIDELINES:

- 4–6 lines per feature
- Clear, concise, product-focused

----------------------------------------

FILTER OUT:

- QA
- Testing
- Regression
- Acceptance criteria

----------------------------------------

INPUT:
{combined_input}
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
            formatted = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", line)
            content.append(Paragraph(formatted, style))

    doc.build(content)

# ===== INPUT =====
sprint = st.text_input("Sprint (e.g., 62)")
projects = st.text_input("Projects (comma separated)")

# ===== RUN =====
if st.button("Generate Release Notes"):

    ITERATIONS = [f"NS-{sprint}", f"NS {sprint}"]
    PROJECTS = [p.strip() for p in projects.split(",")]

    with st.spinner("Fetching data..."):
        all_stories = {}
        for p in PROJECTS:
            ids = get_work_item_ids(p, ITERATIONS)
            details = get_work_item_details(ids)

            all_stories[p] = [{
                "title": d["fields"].get("System.Title", ""),
                "ac": clean_html(d["fields"].get("Microsoft.VSTS.Common.AcceptanceCriteria", ""))
            } for d in details]

    with st.spinner("Generating release notes..."):
        st.session_state.release_notes = generate_release_notes(all_stories)

    with st.spinner("Creating PDF..."):
        create_pdf(st.session_state.release_notes)

    st.success("Release notes generated")

# ===== DISPLAY =====
if st.session_state.release_notes:
    st.markdown("### Release Notes")
    st.markdown(st.session_state.release_notes)

    with open("Release_Notes.pdf", "rb") as f:
        st.download_button("⬇ Download PDF", f)
