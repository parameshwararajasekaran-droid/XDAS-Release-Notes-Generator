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

# ===== TOP RIGHT TOGGLE =====
col1, col2 = st.columns([10, 1])
with col2:
    if st.button("🌙" if st.session_state.theme == "dark" else "☀️"):
        st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"
        st.rerun()

# ===== THEME COLORS =====
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

# ===== UI STYLING =====
st.markdown(f"""
<style>
.stApp {{
    background: linear-gradient(180deg, {bg_secondary}, {bg_main});
    color: {text_secondary};
}}

h1 {{
    color: {text_primary};
    font-weight: 700;
    text-align: center;
}}

label {{
    color: {text_secondary} !important;
}}

input, textarea {{
    background-color: {input_bg} !important;
    color: {text_primary} !important;
    border: 1px solid {border} !important;
    border-radius: 10px !important;
    padding: 10px !important;
}}

input:focus, textarea:focus {{
    border: 1px solid #10b981 !important;
    box-shadow: 0 0 0 1px #10b98133;
}}

.stButton > button {{
    background: linear-gradient(135deg, #10b981, #059669);
    color: white;
    border-radius: 10px;
    border: none;
    padding: 12px 20px;
    font-weight: 600;
}}

.stDownloadButton > button {{
    background: #1f2937;
    color: #f9fafb;
    border: 1px solid #374151;
    border-radius: 10px;
    padding: 10px 18px;
    font-weight: 600;
}}

.stDownloadButton > button:hover {{
    border: 1px solid #10b981;
    box-shadow: 0 0 10px rgba(16,185,129,0.3);
}}

.markdown-text-container {{
    line-height: 1.7;
    font-size: 0.95rem;
}}
</style>
""", unsafe_allow_html=True)

# ===== HEADER =====
st.markdown("<h1>XDAS Release Notes</h1>", unsafe_allow_html=True)
st.markdown("<br>", unsafe_allow_html=True)

# ===== HELPERS =====

def clean_html(raw_html):
    if not raw_html:
        return ""
    clean = re.sub('<.*?>', ' ', raw_html)
    clean = unescape(clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def get_iterations(project, ITERATIONS):
    url = f"https://dev.azure.com/{ORG}/{project}/_apis/work/teamsettings/iterations?api-version=7.0"
    response = requests.get(url, auth=HTTPBasicAuth('', PAT))
    data = response.json()

    iterations = []
    for it in data.get("value", []):
        name = it.get("name", "")
        if any(iter_name in name for iter_name in ITERATIONS):
            iterations.append(it.get("path"))

    return iterations


def get_work_item_ids(project, ITERATIONS):
    url = f"https://dev.azure.com/{ORG}/{project}/_apis/wit/wiql?api-version=7.0"

    iteration_paths = get_iterations(project, ITERATIONS)

    if not iteration_paths:
        return []

    iteration_filter = " OR ".join([
        f"[System.IterationPath] UNDER '{it}'" for it in iteration_paths
    ])

    query = {
        "query": f"""
        SELECT [System.Id]
        FROM WorkItems
        WHERE
            [System.WorkItemType] = 'User Story'
            AND [System.State] = 'Closed'
            AND ({iteration_filter})
        """
    }

    response = requests.post(url, json=query, auth=HTTPBasicAuth('', PAT))
    return [item["id"] for item in response.json().get("workItems", [])]


def get_work_item_details(ids):
    if not ids:
        return []

    ids_str = ",".join(map(str, ids))
    url = f"https://dev.azure.com/{ORG}/_apis/wit/workitems?ids={ids_str}&api-version=7.0"

    response = requests.get(url, auth=HTTPBasicAuth('', PAT))
    return response.json().get("value", [])


# ===== CORE =====

def generate_release_notes(cleaned_stories):

    combined_input = ""
    project_list = []

    for project, stories in cleaned_stories.items():
        project_list.append(project)
        combined_input += f"\nPROJECT: {project}\n{stories}\n"

    project_string = ", ".join(project_list)

    prompt = f"""<KEEP YOUR ORIGINAL PROMPT HERE EXACTLY>"""

    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text


def create_pdf(release_notes):
    doc = SimpleDocTemplate("Release_Notes.pdf", pagesize=letter)

    style = ParagraphStyle(
        'Normal',
        fontName='Helvetica',
        fontSize=11,
        leading=17,
        alignment=TA_JUSTIFY
    )

    content = []

    for line in release_notes.split("\n"):
        line = line.strip()

        if not line:
            content.append(Spacer(1, 6))
            continue

        formatted_line = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", line)
        content.append(Paragraph(formatted_line, style))
        content.append(Spacer(1, 6))

    doc.build(content)


# ===== INPUT =====
sprint = st.text_input("Sprint (e.g., 62)")
projects = st.text_input("Projects (comma separated)")

# ===== ACTION =====
if st.button("Generate Release Notes"):

    if not sprint or not projects:
        st.warning("Please enter both Sprint and Projects")
        st.stop()

    ITERATIONS = [f"NS-{sprint}", f"NS {sprint}"]
    PROJECTS = [p.strip() for p in projects.split(",")]

    with st.spinner("🔄 Fetching data..."):
        all_stories = {}

        for project in PROJECTS:
            ids = get_work_item_ids(project, ITERATIONS)
            details = get_work_item_details(ids)

            all_stories[project] = []

            for item in details:
                fields = item.get("fields", {})
                all_stories[project].append({
                    "title": fields.get("System.Title", ""),
                    "ac": fields.get("Microsoft.VSTS.Common.AcceptanceCriteria", "")
                })

    with st.spinner("🧹 Cleaning data..."):
        cleaned_stories = {}

        for project, stories in all_stories.items():
            cleaned_stories[project] = []

            for story in stories:
                cleaned_stories[project].append({
                    "title": story["title"],
                    "ac": clean_html(story["ac"])
                })

    with st.spinner("🤖 Generating release notes..."):
        st.session_state.release_notes = generate_release_notes(cleaned_stories)

    with st.spinner("📄 Creating PDF..."):
        create_pdf(st.session_state.release_notes)

    st.success("✅ Release notes generated")


# ===== DISPLAY (PERSISTENT) =====
if st.session_state.release_notes:
    st.markdown("### Release Notes")
    st.markdown(st.session_state.release_notes)

    with open("Release_Notes.pdf", "rb") as f:
        st.download_button("⬇ Download PDF", f, file_name="Release_Notes.pdf")
