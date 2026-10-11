from pathlib import Path

SOURCE = Path(__file__).with_name('indeed_agent.py')


def test_upload_copy_is_job_and_content_specific():
    text = SOURCE.read_text(encoding='utf-8')
    assert 'source_sha = hashlib.sha256(source.read_bytes()).hexdigest()[:12]' in text
    assert 'Anuroop_Kudire_{source_sha}_{job_token}_tailored_resume.pdf' in text


def test_continue_cannot_fake_upload_confirmation():
    text = SOURCE.read_text(encoding='utf-8')
    marker = 'upload_confirmed = False'
    start = text.index(marker)
    end = text.index('if not upload_confirmed:', start)
    upload_block = text[start:end]
    assert 'upload_confirmed = True' in upload_block
    assert not any('Continue' in line and 'upload_confirmed = True' in line for line in upload_block.splitlines())


def test_review_success_requires_exact_filename():
    text = SOURCE.read_text(encoding='utf-8')
    assert 'actual_name = await self._wait_for_exact_resume_filename(' in text
    assert 'verified filename={actual_name}' in text
    assert 'refusing to' in text
    assert 'mark replacement complete.' in text
