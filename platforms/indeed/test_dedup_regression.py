import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage


def run():
    old = storage.DB
    with tempfile.TemporaryDirectory() as td:
        storage.DB = Path(td) / 'applications.db'
        con = storage.db()
        a = 'https://in.indeed.com/rc/clk?jk=ABC12345&bb=tracking-one&xkcb=foo'
        b = 'https://in.indeed.com/rc/clk?jk=abc12345&bb=tracking-two&xkcb=bar'
        assert storage.canonical_job_key(a) == storage.canonical_job_key(b)
        assert not storage.seen(con, a)
        storage.app(con, a, 'Test Job', 'low_match')
        assert storage.seen(con, b), 'same Indeed job must dedupe despite different tracking URL'
        storage.app(con, b, 'Test Job', 'apply_clicked')
        rows = con.execute('SELECT COUNT(*) FROM applications').fetchone()[0]
        assert rows == 1
        con.close()
    storage.DB = old
    print('DEDUP REGRESSION: PASS')


if __name__ == '__main__':
    run()
