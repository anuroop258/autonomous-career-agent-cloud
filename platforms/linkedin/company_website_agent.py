"""Compatibility import for the canonical company-site application engine.

Platform navigation lives in ``linkedin_agent.py``.  Shared company-form
understanding, safety gates, and submission verification have one owner.
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.application.common.company_website_agent import (  # noqa: F401
    CompanyWebsiteAgent,
    connect_to_real_chrome,
    main,
)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
