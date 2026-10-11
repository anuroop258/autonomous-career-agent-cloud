import sys
from custom_qa_cli import main as qa_main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "qa":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        raise SystemExit(qa_main())

    if len(sys.argv) > 1 and sys.argv[1] == "company-fill":
        from company_fill import main as company_fill_main
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        raise SystemExit(company_fill_main())

    print("Portal automation uses main.py. Custom Q&A uses: py career_agent_main.py qa <add|list|test|remove>")
    print("Direct company form: py career_agent_main.py company-fill <URL> [--platform linkedin|indeed|naukri]")
