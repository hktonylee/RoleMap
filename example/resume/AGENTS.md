# Demo Resume Instructions

This file demonstrates how to place template-local agent instructions inside a
resume template directory. When RoleMap starts a Codex session from this folder,
the agent should follow these instructions while generating a resume.

## General Structure

- Use resume files in this directory as source material.
- Tailor the resume to the job details in the prompt: company, title, and
  description.
- Prefer exact wording from the source resume when it already matches the job.
- Remove unrelated or redundant details when the resume needs to fit a target
  page count.
- Keep the output focused on the requested job. Do not add extra artifacts
  unless requested.

## Important

- Do not invent experience.
- Do not fake skills, dates, employers, projects, or credentials.
- Do not simplify the resume so much that the work history looks suspicious.
