import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_all_platform_full_profiles_match_canonical_root():
    root = json.loads((ROOT / 'profile.json').read_text(encoding='utf-8'))
    for platform in ('indeed', 'shine', 'glassdoor', 'timesjobs', 'linkedin'):
        data = json.loads((ROOT / 'platforms' / platform / 'profile.json').read_text(encoding='utf-8'))
        assert data.get('full_profile') == root, platform


def test_all_platform_form_profiles_have_core_contact_and_project_data():
    required_contact = {
        'email': 'anuroop954@gmail.com',
        'phone': '7032164500',
        'city': 'Hyderabad',
        'state': 'Telangana',
        'country': 'India',
        'postal_code': '500089',
    }
    required_projects = {
        'AI-Powered Autonomous Job Application Agent',
        'Internal Knowledge & SOP Assistant',
        'Customer Support Triage & Resolution Agent',
        'AI Data Quality & Root-Cause Analyst',
        'Document-based RAG Chatbot',
        'DroneVision – Construction Monitoring',
        'Spectrum Sensing for Cognitive Radio using SDR',
    }
    for platform in ('indeed', 'shine', 'glassdoor', 'timesjobs'):
        data = json.loads((ROOT / 'platforms' / platform / 'profile.json').read_text(encoding='utf-8'))
        facts = data['form_profile']['facts']
        for key, expected in required_contact.items():
            assert facts['contact'][key] == expected, (platform, key)
        assert required_projects.issubset(facts['project_experience']), platform
