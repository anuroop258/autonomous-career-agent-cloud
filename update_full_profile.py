import json
from pathlib import Path
from copy import deepcopy

ROOT = Path(__file__).resolve().parent

# Source-grounded master profile assembled from the existing project profile and
# the user's resume/project details already stored with this agent.  Numeric
# "experience years" remain 0 because the user is a fresher; hands-on project
# work is represented separately.
master = json.loads((ROOT / 'profile.json').read_text(encoding='utf-8'))

master['candidate'].update({
    'full_name': 'Kudire Venkata Sain Anuroop',
    'display_name': 'Anuroop Kudire',
    'first_name': 'Anuroop',
    'middle_name': 'Venkata Sain',
    'last_name': 'Kudire',
    'current_designation': 'Fresher / 2026 Graduate',
    'professional_experience_years': 0,
    'career_stage': 'Entry-level / Fresher',
    'student_status': 'Final-year / 2026 graduate',
    'hands_on_project_experience': True,
    'internship_experience': False,
})

skills = [
    'Python','C++','Java','C','HTML','CSS','JavaScript','SQL','MySQL','PostgreSQL','SQLite',
    'LangChain','LangGraph','LLMs','Generative AI','AI Agents','Agentic AI','RAG','NLP',
    'Prompt Engineering','FAISS','ChromaDB','Sentence Transformers','Google Gemini API','Ollama',
    'PyTorch','TensorFlow','Keras','scikit-learn','Statistical Modeling','Statistical Analysis',
    'Anomaly Detection','Pandas','NumPy','Matplotlib','Plotly','Flask','FastAPI','REST APIs',
    'Streamlit','n8n','Webhooks','Browser Automation','Web Automation','Playwright',
    'Chrome DevTools Protocol','CDP','Workflow Automation','Docker','Kubernetes','Git',
    'GitHub','GitHub Actions','CI/CD','AWS','GCP','Azure','EC2','S3','IAM','RDS',
    'Power BI (Basic)','Tableau (Basic)','Microsoft Excel','Office 365','Outlook',
    'TCP/IP','DNS','DHCP','VPN','Operating Systems','Active Directory (Basic)',
    'Hardware/Software Troubleshooting','ServiceNow','Ticket Management',
]
master['skills'] = skills
master['skill_experience_years'] = {s: 0 for s in skills}
# Keep common aliases that the existing deterministic matcher expects.
master['skill_experience_years'].update({
    'Google Gemini API': 0,
    'Gemini API': 0,
    'LLMs': 0,
    'Generative AI': 0,
    'RAG': 0,
    'FAISS': 0,
    'ChromaDB': 0,
    'LangChain': 0,
    'Playwright': 0,
    'Browser Automation': 0,
    'Chrome DevTools Protocol': 0,
    'CDP': 0,
})

master['contact'].update({
    'full_name': 'Kudire Venkata Sain Anuroop',
    'display_name': 'Anuroop Kudire',
    'first_name': 'Anuroop',
    'middle_name': 'Venkata Sain',
    'last_name': 'Kudire',
    'email': 'anuroop954@gmail.com',
    'phone': '7032164500',
    'city': 'Hyderabad',
    'state': 'Telangana',
    'country': 'India',
    'pin_code': '500089',
    'nationality': 'Indian',
    'gender': 'Male',
})

master['education_details'] = {
    'degree': 'B.E./B.Tech',
    'branch': 'Electronics and Communication Engineering',
    'college': 'Vasavi College of Engineering',
    'college_city': 'Hyderabad',
    'start_year': 2022,
    'graduation_year': 2026,
    'cgpa': 6.8,
    'percentage_equivalent': 68,
    'junior_college': 'Narayana Junior College',
    'junior_college_percentage': 94.1,
    'class_10_percentage': 95,
    'class_12_percentage': 94,
    'student_status': 'Final-year / 2026 graduate',
}

master['candidate']['cgpa'] = 6.8
master['candidate']['be_percentage'] = 68
master['candidate']['class_10_percentage'] = 95
master['candidate']['class_12_percentage'] = 94
master['candidate']['authorized_to_work_in_india'] = True
master['candidate']['work_country'] = 'India'
master['candidate']['visa_sponsorship_required'] = False
master['candidate']['available_to_join_immediately'] = True
master['candidate']['has_active_offer'] = False
master['candidate']['currently_employed'] = False
master['candidate']['notice_period_days'] = 0
master['candidate']['employment_bond_willing'] = False
master['candidate']['night_shift'] = True
master['candidate']['onsite'] = True
master['candidate']['remote'] = True
master['candidate']['hybrid'] = True

master['preferences'] = {
    'willing_to_relocate': True,
    'remote': True,
    'hybrid': True,
    'onsite': True,
    'night_shift': True,
    'primary_city': 'Hyderabad',
    'location_restriction': False,
    'preferred_locations': ['Hyderabad', 'India'],
    'open_to_other_locations': True,
    'target_roles': [
        'Generative AI Engineer','GenAI Engineer','AI Engineer','Machine Learning Engineer',
        'AI/ML Engineer','LLM Engineer','RAG Engineer','AI Support Engineer',
        'Data Analyst','Data/AI Analyst','Software Engineer','Application Engineer',
        'Production Support','Site Reliability / Application Support (entry-level)',
    ],
    'job_level': 'Entry-level / Fresher',
}

master['compensation'] = {
    'current_ctc': 0,
    'expected_ctc': 400000,
    'expected_ctc_lpa': 4,
    'expected_hourly_rate_usd': 10,
    'contractor_compensation_only': True,
}

master['professional_summary'] = (
    '2026 Electronics and Communication Engineering graduate from Vasavi College of Engineering '
    'with hands-on project experience in Generative AI, LLMs, RAG, AI agents, data analysis, '
    'browser automation and machine learning. Built document-based RAG and internal knowledge '
    'assistants using LangChain, FAISS/ChromaDB, embeddings and Streamlit; built AI data-quality '
    'and root-cause analysis, customer-support triage, and autonomous job-application automation '
    'using Python, Playwright, Chrome DevTools Protocol, Gemini API and Ollama. Also worked on '
    'computer-vision and SDR/cognitive-radio academic projects. Fresher with 0 professional years, '
    'available to join immediately and open to relocation, remote, hybrid and onsite roles.'
)
master['career_summary'] = master['professional_summary']

master['projects'] = [
    {
        'title': 'AI-Powered Autonomous Job Application Agent',
        'type': 'Personal / engineering project',
        'technologies': ['Python','Playwright','Chrome DevTools Protocol','Gemini API','Ollama','LLMs','Browser Automation','n8n'],
        'details': (
            'Built an autonomous job-application agent using Python, Playwright, Chrome DevTools Protocol (CDP), '
            'Gemini API, Ollama, LLMs and browser automation. Implemented observe → reason → act → verify → recover '
            'workflow with deterministic → Gemini → Ollama fallback, JD matching and experience/skill eligibility '
            'gates, job deduplication, native application flows, resume tailoring/upload, dynamic form analysis, '
            'profile-grounded question answering, human intervention handling for CAPTCHA/OTP, and multi-tab CDP state management.'
        ),
    },
    {
        'title': 'Internal Knowledge & SOP Assistant',
        'type': 'GenAI / RAG project',
        'technologies': ['Python','LangChain','RAG','FAISS','Sentence Transformers','LLMs','Streamlit','n8n'],
        'details': (
            'Built a RAG-based internal knowledge and SOP assistant with document processing, chunking, embeddings, '
            'FAISS vector retrieval, hybrid semantic/lexical retrieval, grounded-response controls and section-level citations. '
            'Evaluated on 100 synthetic queries with 91.7% retrieval hit rate, 91.7% grounded-answer rate and 90.0% correct refusal rate.'
        ),
    },
    {
        'title': 'Customer Support Triage & Resolution Agent',
        'type': 'GenAI / agent project',
        'technologies': ['Python','LLMs','RAG','Decision Logic','n8n','Streamlit'],
        'details': (
            'Built an AI support agent that classifies requests, retrieves relevant knowledge, checks customer/order data, '
            'and determines whether a request is safe to resolve automatically. Earlier evaluation on 100 realistic support cases '
            'reported 95% intent-classification accuracy and 72% safe auto-resolution; a later adversarial held-out evaluation '
            'reported 83.3% intent accuracy and 100% escalation of predefined high-risk cases.'
        ),
    },
    {
        'title': 'AI Data Quality & Root-Cause Analyst',
        'type': 'AI/data project',
        'technologies': ['Python','Pandas','PostgreSQL','SQL','scikit-learn','Google Gemini API','FastAPI','Streamlit','Plotly'],
        'details': (
            'Built data-quality and root-cause analysis pipelines over 12,000+ sales transactions across 800 SKUs. '
            'Implemented statistical/anomaly analysis, sales-velocity and inventory decision logic, generated 300+ reorder recommendations, '
            'integrated Gemini for natural-language inventory analysis, and built a FastAPI + Streamlit dashboard. Project notes report '
            'roughly 30% lower simulated stockout risk versus a baseline while processing 1,000 SKUs in about 12 seconds.'
        ),
    },
    {
        'title': 'Document-based RAG Chatbot',
        'type': 'GenAI / RAG project',
        'technologies': ['Python','LangChain','LLMs','RAG','FAISS','Embeddings','Sentence Transformers','Streamlit'],
        'details': (
            'Built a document-grounded question-answering chatbot using document ingestion, chunking, embeddings, FAISS vector '
            'similarity search and source citations with a Streamlit interface.'
        ),
    },
    {
        'title': 'DroneVision – Construction Monitoring',
        'type': 'Computer vision project',
        'technologies': ['Python','PyTorch/TensorFlow','ResNet','U-Net','Semantic Segmentation','SSIM'],
        'details': (
            'Worked on construction-monitoring computer vision using ResNet + U-Net semantic segmentation and SSIM-based change detection. '
            'The stored project README used synthetic/placeholder data and documented example metrics such as 0.89 IoU and F1 0.91; these should be '
            'treated as project-demo metrics rather than independently reproduced production measurements.'
        ),
    },
    {
        'title': 'Spectrum Sensing for Cognitive Radio using SDR',
        'type': 'Academic project',
        'technologies': ['PlutoSDR','GNU Radio','FFT','DBSCAN','Dynamic Spectrum Access','FDNE','FDED'],
        'details': (
            'Academic work on spectrum sensing for cognitive radio using PlutoSDR and GNU Radio, including dynamic spectrum access, FFT-based '
            'signal processing, FDNE/FDED techniques and DBSCAN clustering.'
        ),
    },
]

master['project_experience'] = deepcopy(master['projects'])

master['certifications'] = [
    {
        'name': 'NPTEL - Joy of Computing Using Python',
        'date': 'January 2024',
        'result': 'Elite and Silver; Top 10 percent',
    },
    {
        'name': 'Cisco Networking Academy - Python Essentials',
        'date': 'January 2025',
        'result': 'Completed',
    },
    {
        'name': 'Cisco Networking Academy - Data Analytics Essentials',
        'date': 'June 2026',
        'result': 'Completed',
    },
]

master['online_profiles'] = {
    'linkedin': 'https://www.linkedin.com/in/anuroop-kudire-b7a322268/',
    'github': 'https://github.com/anuroop258',
    'github_username': 'anuroop258',
}

master['professional_experience'] = []
master['employment_history'] = []
master['internships'] = []
master['professional_experience_statement'] = '0 months / 0 years of professional employment experience; fresher. Hands-on experience is through academic, personal and engineering projects.'

master['tools_and_workflows'] = {
    'automation_tools': ['n8n','Playwright','Apify','LoopCV','LazyApply'],
    'developer_tools': ['Git','GitHub','Docker','GitHub Actions','CI/CD'],
    'cloud': ['AWS','GCP','Azure'],
    'support_and_it': ['ServiceNow','Ticket Management','Windows','Office 365','Outlook','Active Directory (Basic)','TCP/IP','DNS','DHCP','VPN'],
}

master['hands_on_project_skills'] = {
    'generative_ai': ['LLMs','Generative AI','Prompt Engineering','RAG','AI Agents','Agentic AI'],
    'llm_stack': ['LangChain','LangGraph','FAISS','ChromaDB','Sentence Transformers','Google Gemini API','Ollama'],
    'ml_dl': ['PyTorch','TensorFlow','Keras','scikit-learn','Statistical Modeling','Anomaly Detection','NLP','Computer Vision'],
    'data': ['Pandas','NumPy','Matplotlib','Plotly','SQL','MySQL','PostgreSQL','SQLite'],
    'backend': ['Flask','FastAPI','REST APIs','Webhooks'],
    'ui': ['Streamlit','Power BI (Basic)','Tableau (Basic)','Microsoft Excel'],
    'automation': ['Python','Playwright','Browser Automation','Web Automation','CDP','Chrome DevTools Protocol','n8n'],
    'cloud_devops': ['AWS','GCP','Azure','Docker','Kubernetes','GitHub Actions','CI/CD'],
    'networking_it_support': ['TCP/IP','DNS','DHCP','VPN','Operating Systems','Active Directory (Basic)','Hardware/Software Troubleshooting','ServiceNow'],
}

master['answer_profile'] = {
    'self_introduction': (
        'I am Anuroop Kudire, a 2026 Electronics and Communication Engineering graduate from Vasavi College of Engineering. '
        'I am a fresher with hands-on project experience in Generative AI, LLMs, RAG, AI agents, data analysis and browser automation. '
        'I have built projects including a document RAG chatbot, internal knowledge/SOP assistant, AI data-quality and root-cause analyst, '
        'customer-support triage agent, autonomous job-application agent, DroneVision construction monitoring, and an SDR-based cognitive-radio project. '
        'My main technologies include Python, LangChain, RAG, FAISS/ChromaDB, Gemini API, Playwright, FastAPI, SQL, Streamlit and cloud/devops tools.'
    ),
    'experience_statement': 'I have 0 years of professional experience and am applying as a fresher. My experience is hands-on project experience rather than paid professional employment.',
    'strengths': ['Python','Generative AI','RAG','LLM application development','AI agents','data analysis','browser automation','problem solving','rapid project prototyping'],
    'career_focus': ['GenAI/LLM','AI/ML','RAG','AI automation','Data/AI analytics','Software engineering','AI support/application engineering'],
}

master['questionnaire_facts'] = {
    **master.get('questionnaire_facts', {}),
    'full_name': 'Kudire Venkata Sain Anuroop',
    'display_name': 'Anuroop Kudire',
    'first_name': 'Anuroop',
    'last_name': 'Kudire',
    'professional_experience_years': 0,
    'hands_on_project_experience': True,
    'cgpa': 6.8,
    'graduation_year': 2026,
    'college': 'Vasavi College of Engineering',
    'degree': 'B.E./B.Tech',
    'branch': 'Electronics and Communication Engineering',
    'class_10_percentage': 95,
    'class_12_percentage': 94,
    'junior_college_percentage': 94.1,
    'city': 'Hyderabad',
    'state': 'Telangana',
    'country': 'India',
    'pin_code': '500089',
    'email': 'anuroop954@gmail.com',
    'phone': '7032164500',
    'currently_employed': False,
    'available_to_join_immediately': True,
    'notice_period_days': 0,
    'has_active_offer': False,
    'willing_to_relocate': True,
    'remote': True,
    'hybrid': True,
    'onsite': True,
    'night_shift': True,
    'visa_sponsorship_required': False,
    'authorized_to_work_in_india': True,
    'current_ctc': 0,
    'expected_ctc': 400000,
    'expected_ctc_lpa': 4,
    'expected_hourly_rate_usd': 10,
    'contractor_compensation_only': True,
    'skills': skills,
    'certifications': [c['name'] for c in master['certifications']],
    'linkedin': master['online_profiles']['linkedin'],
    'github': master['online_profiles']['github'],
    'professional_summary': master['professional_summary'],
}

master['truthfulness_rules'] = {
    'professional_experience_years': 0,
    'do_not_convert_project_experience_to_professional_years': True,
    'do_not_claim_employer_experience': True,
    'do_not_claim_unlisted_certification': True,
    'do_not_invent_personal_facts': True,
    'unknown_answers': 'UNKNOWN / UNRESOLVED instead of guessing',
}

# The project already has deterministic question mappings. Add patterns for
# the richer profile without changing the meaning of the existing fields.
qm = master.setdefault('question_mappings', {})
extra = {
    'email': {'patterns':['email','email address','contact email'], 'field':'contact.email','kind':'text'},
    'phone': {'patterns':['phone number','mobile number','contact number','phone'], 'field':'contact.phone','kind':'text'},
    'city': {'patterns':['current city','city','where are you located','current location'], 'field':'contact.city','kind':'text'},
    'linkedin': {'patterns':['linkedin','linkedin profile','linkedin url'], 'field':'online_profiles.linkedin','kind':'text'},
    'github': {'patterns':['github','github profile','github url'], 'field':'online_profiles.github','kind':'text'},
    'expected_ctc': {'patterns':['expected ctc','expected salary','salary expectation'], 'field':'compensation.expected_ctc','kind':'number'},
    'current_ctc': {'patterns':['current ctc','current salary'], 'field':'compensation.current_ctc','kind':'number'},
}
qm.update(extra)

# Remove the outdated IoT certification from any questionnaire facts while
# retaining project truthfulness.
master['questionnaire_facts']['certifications'] = [c['name'] for c in master['certifications']]

# Write master profile.
(ROOT / 'profile.json').write_text(json.dumps(master, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

# Synchronize all platform profiles with a non-destructive `full_profile`
# section and update their visible fact banks where safe.
platforms = ['indeed','shine','glassdoor','timesjobs','linkedin']
for platform in platforms:
    p = ROOT / 'platforms' / platform / 'profile.json'
    if not p.exists():
        continue
    data = json.loads(p.read_text(encoding='utf-8'))
    data['full_profile'] = deepcopy(master)
    if 'form_profile' in data:
        fp = data['form_profile']
        facts = fp.setdefault('facts', {})
        facts['identity'] = {
            **facts.get('identity', {}),
            'full_name':'Kudire Venkata Sain Anuroop',
            'display_name':'Anuroop Kudire',
            'first_name':'Anuroop','last_name':'Kudire','middle_name':'Venkata Sain',
            'gender':'Male','nationality':'Indian',
        }
        facts['contact'] = {
            **facts.get('contact', {}),
            'city':'Hyderabad','state':'Telangana','country':'India','postal_code':'500089',
            'location_full':'Hyderabad, Telangana, India',
            'email':'anuroop954@gmail.com','phone':'7032164500',
            'linkedin_url':master['online_profiles']['linkedin'],
            'github_username':'anuroop258',
        }
        facts['education'] = {
            **facts.get('education', {}),
            'degree':'B.E./B.Tech','branch':'Electronics and Communication Engineering',
            'college':'Vasavi College of Engineering','graduation_year':2026,'cgpa':6.8,
            'percentage_equivalent':68,'tenth_percentage':95,'twelfth_percentage':94,
            'junior_college':'Narayana Junior College','junior_college_percentage':94.1,
        }
        facts['employment'] = {
            **facts.get('employment', {}),
            'professional_experience_years':0,'experience_status':'Fresher','notice_period_days':0,
            'joinability':'Immediate','currently_employed':False,'has_active_offer':False,
            'current_ctc_inr':0,'expected_ctc_inr':400000,'expected_hourly_rate_usd':10,
            'contractor_compensation_only':True,
        }
        facts['work_preferences'] = {
            **facts.get('work_preferences', {}),
            'willing_to_relocate':True,'onsite':True,'remote':True,'hybrid':True,'night_shift':True,
            'work_authorization_country':'India','visa_sponsorship_required':False,
            'primary_city':'Hyderabad','open_to_other_locations':True,
        }
        facts['professional_summary'] = master['professional_summary']
        facts['project_experience'] = {p['title']: p['details'] for p in master['projects']}
        facts['certifications'] = {c['name']: c['result'] for c in master['certifications']}
        fp['full_profile_context'] = deepcopy(master)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

# Human-readable manifest for the user/reviewer.
manifest = {
    'profile_source_of_truth': 'profile.json',
    'platform_profiles_synchronized': platforms,
    'professional_experience_years': 0,
    'graduation_year': 2026,
    'skills_count': len(skills),
    'project_count': len(master['projects']),
    'certification_count': len(master['certifications']),
    'contact_fields_present': ['name','email','phone','city','state','country','pin_code','LinkedIn','GitHub'],
    'career_targets': master['preferences']['target_roles'],
    'important_truthfulness_rule': 'Project/academic experience is never converted into professional years.',
}
(ROOT / 'PROFILE_DATA_UPDATE_MANIFEST.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(json.dumps(manifest, indent=2, ensure_ascii=False))
