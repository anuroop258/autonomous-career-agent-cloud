from src.application.common.ai_form_engine import AIFormEngine


def test_education_field_labels_override_page_wide_context():
    engine = AIFormEngine(profile={
        "candidate": {"education": "B.E./B.Tech, Electronics and Communication Engineering", "graduation_year": 2026, "cgpa": 6.8},
        "education_details": {
            "degree": "B.E./B.Tech",
            "branch": "Electronics and Communication Engineering",
            "college": "Vasavi College of Engineering",
            "graduation_year": 2026,
            "cgpa": 6.8,
            "current_year_of_study": "Final year",
            "currently_studying": True,
        },
    })
    context = "Education Highest Qualification Field / Branch College / University CGPA / % Graduation Year Current Year of Study"

    assert engine._classify(label="Highest Qualification", context=context, tag="select") == "degree"
    assert engine._classify(label="College / University", context=context, tag="input") == "college"
    assert engine._classify(label="CGPA / %", context=context, tag="input") == "cgpa"
    assert engine._classify(label="Graduation Year", context=context, tag="input") == "graduation_year"
    assert engine._classify(label="Current Year of Study", context=context, tag="input") == "current_year_of_study"
    assert engine._classify(label="I'm currently studying — still pursuing this qualification.", context=context, field_type="checkbox") == "currently_studying"


def test_education_profile_fallback_reads_canonical_education_details():
    engine = AIFormEngine(profile={
        "candidate": {"education": "B.E./B.Tech, Electronics and Communication Engineering", "graduation_year": 2026, "cgpa": 6.8},
        "education_details": {
            "degree": "B.E./B.Tech",
            "branch": "Electronics and Communication Engineering",
            "college": "Vasavi College of Engineering",
            "graduation_year": 2026,
            "cgpa": 6.8,
            "current_year_of_study": "Final year",
            "currently_studying": True,
        },
    })
    assert engine.get_profile_value("degree") == "B.E./B.Tech"
    assert engine.get_profile_value("college") == "Vasavi College of Engineering"
    assert engine.get_profile_value("cgpa") == 6.8
    assert engine.get_profile_value("graduation_year") == 2026
    assert engine.get_profile_value("current_year_of_study") == "Final year"
    assert engine.get_profile_value("currently_studying") is True
