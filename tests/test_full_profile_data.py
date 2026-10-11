import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_profile():
    return json.loads((ROOT / 'profile.json').read_text(encoding='utf-8'))


def test_full_profile_contains_core_identity_contact_education():
    p = load_profile()
    assert p['candidate']['full_name'] == 'Kudire Venkata Sain Anuroop'
    assert p['candidate']['display_name'] == 'Anuroop Kudire'
    assert p['contact']['email'] == 'anuroop954@gmail.com'
    assert p['contact']['phone'] == '7032164500'
    assert p['education_details']['college'] == 'Vasavi College of Engineering'
    assert p['education_details']['branch'] == 'Electronics and Communication Engineering'
    assert p['education_details']['graduation_year'] == 2026


def test_full_profile_has_project_and_skill_coverage():
    p = load_profile()
    project_titles = {x['title'] for x in p['projects']}
    required_projects = {
        'AI-Powered Autonomous Job Application Agent',
        'Internal Knowledge & SOP Assistant',
        'Customer Support Triage & Resolution Agent',
        'AI Data Quality & Root-Cause Analyst',
        'Document-based RAG Chatbot',
        'DroneVision – Construction Monitoring',
        'Spectrum Sensing for Cognitive Radio using SDR',
    }
    assert required_projects.issubset(project_titles)
    for skill in ['Python','LangChain','RAG','FAISS','ChromaDB','Google Gemini API','Playwright','FastAPI','PostgreSQL','Docker','GitHub Actions']:
        assert skill in p['skills']


def test_full_profile_is_truthful_about_professional_experience_and_certifications():
    p = load_profile()
    assert p['candidate']['professional_experience_years'] == 0
    assert p['professional_experience'] == []
    assert p['internships'] == []
    assert p['certifications'] == [
        'NPTEL - Joy of Computing Using Python',
        'Cisco Networking Academy - Python Essentials',
        'Cisco Networking Academy - Data Analytics Essentials',
    ]
    assert all('IoT' not in cert for cert in p['certifications'])
    assert p['certification_details'][0]['result'] == 'Elite and Silver; Top 10 percent'


def test_all_platform_profiles_receive_full_profile_context():
    master = load_profile()
    for platform in ('indeed','shine','glassdoor','timesjobs','linkedin'):
        path = ROOT / 'platforms' / platform / 'profile.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        assert data['full_profile']['candidate']['full_name'] == master['candidate']['full_name']
        assert data['full_profile']['contact']['email'] == master['contact']['email']
        if 'form_profile' in data:
            assert data['form_profile']['full_profile_context']['projects'][0]['title'] == master['projects'][0]['title']
