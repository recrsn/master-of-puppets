# Agent instructions

## Git

- Commit straight to `main` and push `main`. Do not make a branch or a pull
  request unless the user asks for one.
- Commit and push only when the user asks.

## Public repository

This repository is public. Keep every file general: it must work for any
user, machine and team.

- Never add names from a private setup: an employer's or a customer's
  internal tools, services, hosts, paths, repositories, branches, flags,
  people, PR numbers or data. This covers code, docs, examples, evals, tests,
  commit messages and branch names. Use made-up examples instead
  (`owner/repo`, `example.com`, `size=large`).
- A script for one machine, one repository or a private tool does not belong
  here. It lives outside the repository (the coordinator skill, "Scripts for
  your setup").
- A public third-party product may appear only in its own optional
  reference that is read only when a setup uses it (for example
  `references/coderabbit.md`). Other text points to it as "if you use X,
  read Y".
- When you quote the user, leave out the private names.
- Before each commit, read the diff and the commit message for such names.
  When you are not sure that a name is public, ask the user.
