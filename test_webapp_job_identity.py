from webapp.backend.main import _all_applications, _resolve_job_ref


def test_job_refs_are_globally_unique_across_portals():
    rows = _all_applications()
    refs = [r['job_ref'] for r in rows]
    assert len(refs) == len(set(refs)), 'job_ref collision across portal DBs'


def test_job_ref_resolves_to_platform_and_database_row():
    rows = _all_applications()
    assert rows
    for row in rows[:20]:
        resolved = _resolve_job_ref(row['job_ref'])
        assert resolved is not None
        assert resolved['platform'] == row['source']
        assert int(resolved['id']) == int(row['db_id'])
