# Demo Resume Instructions

This file demonstrates how to place template-local agent instructions inside a
resume template directory. It is modeled after a personal resume workflow:
start from the most complete source resume, tailor it to the pasted job
description, keep the result printable, and avoid inventing experience.

## General Structure

- Treat `Resume.html` as the most detailed source resume for this example.
- Tailor the resume to the job details in the prompt: company, title, and job
  description.
- Prefer exact wording from the source resume when it already matches the job.
- Update, extract, and refine mainly the experience and project details to fit
  the job description.
- Keep the tailored resume printable within 2 pages unless the prompt gives a
  different target.
- Remove unrelated or redundant details before cutting relevant experience.
- Write the updated HTML in `ROLEMAP_RESUME_OUTPUT_DIR` as
  `<YYYY-MM-DD>-<Company Name>.html`, using the run date and company name from
  the prompt.
- Also create a matching PDF in `ROLEMAP_RESUME_OUTPUT_DIR` named
  `<YYYY-MM-DD>-<Company Name>.pdf`.
- Keep the output focused on the requested job. Do not add extra artifacts
  unless requested.
- Open the PDF for user inspection when the environment allows.

## Important

- Do not invent experience.
- Do not fake skills, dates, employers, projects, or credentials.
- Do not simplify the resume so much that the work history looks suspicious.
