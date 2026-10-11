from pathlib import Path

from resume_integration import MAX_GENERATED_RESUME_RELATIVE_PATH, _resume_output_dir


def test_resume_output_dir_compacts_long_windows_paths(tmp_path):
    # Simulate a deeply nested checkout plus the long employer/title strings
    # visible in the Windows extraction failure.
    root = tmp_path / ("project_" + "x" * 140) / "inspect_resume" / "v28_current"
    company = "YOUNGMINDS TECHNOLOGY SOLUTIONS (YMTS) 3.5118 Reviews"
    role = "Matlab Simulink Engineer - Tirupati - YOUNGMINDS TECHNOLOGY SOLUTIONS (YMTS) - 0 to 3 years of exper"
    output = _resume_output_dir(root, "naukri", company, role, "618beb89")

    relative = output.relative_to(root)
    assert len(str(relative / "resume.pdf")) <= MAX_GENERATED_RESUME_RELATIVE_PATH
    assert len(relative.parts[-3]) <= 23
    assert len(relative.parts[-2]) <= 27
    assert relative.name == "j-618beb89"
    assert "YOUNGMINDS TECHNOLOGY SOLUTIONS" in company
    assert role.startswith("Matlab Simulink Engineer")
