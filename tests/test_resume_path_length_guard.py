from pathlib import Path

from resume_integration import MAX_GENERATED_RESUME_RELATIVE_PATH, _resume_output_dir

ROOT = Path(__file__).resolve().parents[1]


def test_resume_path_has_bounded_relative_length():
    output = _resume_output_dir(
        ROOT,
        "indeed",
        "Matlab Simulink Engineer - Tirupati - YOUNGMYNDS TECHNOLOGY SOLUTIONS (YMTS) - 0 to 3 years of experience",
        "Matlab Simulink Engineer - Tirupati - YOUNGMYNDS TECHNOLOGY SOLUTIONS (YMTS) - 0 to 3 years of experience",
        "618beb89",
    )
    relative_pdf = output.relative_to(ROOT) / "resume.pdf"
    assert len(str(relative_pdf)) <= MAX_GENERATED_RESUME_RELATIVE_PATH
    assert output.parts[-2].startswith("Matlab Simulink")
    assert output.parts[-1] == "j-618beb89"


def test_resume_path_keeps_platform_and_collision_safe_keys():
    output = _resume_output_dir(ROOT, "linkedin", "Example Company", "AI Engineer", "abcd1234")
    relative = output.relative_to(ROOT)
    assert relative.parts[0:2] == ("resume_versions", "linkedin")
    assert relative.parts[-1] == "j-abcd1234"
