# Resume Tailoring V15

The tailored resume pipeline is now ATS-aware and authenticity-first.

## Pipeline

1. Scrape/store the job title and full job description.
2. Run an authenticity scan before changing wording.
3. Extract a literal two-pass keyword inventory, preserving singular/plural and branded variants.
4. Perform exact/near string matching against the immutable master resume.
5. Permit additions only when the term is supported by the master resume or verified profile/project evidence.
6. Reorder skill categories and project blocks by job relevance.
7. Rewrite supported project bullets at the sentence level when exact JD wording can be introduced without inventing experience.
8. Keep every bullet at 25 words or fewer and preserve all original project, education, certification, and numeric content.
9. Compile a one-page PDF and programmatically verify page count and LinkedIn/GitHub hyperlinks.
10. Save a complete `tailoring_report.json` beside the tailored resume.

## Stored output

```text
resume_versions/
  <platform>/<company>/<role>/job-<short-id>/
      resume.tex
      resume.pdf
      tailoring_report.json
      job_metadata.json
```

The master resume at `resume/master_resume.tex` is never overwritten.
