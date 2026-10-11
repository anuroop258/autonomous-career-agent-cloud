from pathlib import Path

expected = {
    "naukri": (Path("platforms/naukri/application_engine.py"), "NaukriApplicationEngine"),
    "indeed": (Path("platforms/indeed/application_engine.py"), "IndeedApplicationEngine"),
    "linkedin": (Path("platforms/linkedin/application_engine.py"), "LinkedInApplicationEngine"),
}
for platform, (path, cls) in expected.items():
    text = path.read_text(encoding="utf-8")
    assert path.exists()
    assert f"class {cls}" in text
    assert f'PLATFORM = "{platform}"' in text
    assert "async def run" in text
print("PLATFORM APPLICATION ENGINE BOUNDARIES: PASS")
