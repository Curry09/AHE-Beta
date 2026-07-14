# Harness User Manual (v0)

This is the manual for the AI coding assistant ("the harness") you are using
through your terminal. It describes what it can do and how to work with it. This
is the ground truth for THIS tool's capabilities — do not assume features that
are not listed here.

## What it is
A terminal-based AI coding assistant. You send it a request in plain natural
language; it works on it and sends back a single final reply.

## How you interact
- **One request → one reply.** You type a message (a task, question, or
  follow-up). The assistant works, then returns one final text reply.
- **It's conversational.** Within a session it remembers earlier turns, so you
  can send follow-ups ("now add tests", "that's wrong, fix X") and it keeps
  context — including after an interrupt or a request that hit an internal time
  limit (see below).
- **It works on real files.** It has a shell and a working directory (your
  project root); it can create/edit files and run commands and tests there. Its
  reply reports what it did.
- **You can interrupt a request while it's still working.** If it's taking too
  long, you can stop the current request. It halts promptly, keeps the
  conversation so far, and hands control back to you with a short note — you then
  send your next instruction (a revised request, a narrower ask, or a follow-up)
  and it continues from where things stood. Interrupting cancels only the
  in-progress request; it does not wipe the session.

## Getting good results
- Describe what you want clearly. It may ask a brief clarifying question.
- Iterate by replying with feedback.
- Prefer smaller, checkable steps over one giant request. If a request hits a
  time limit, narrow the next ask or say "continue" — the session context is
  still there.

## How it behaves
- It replies **once per request, when it is finished** (or when stopped / timed
  out). It works between your message and its reply.
- It handles **one request at a time**, in order.
- On a **very large request it can hit an internal time or iteration limit**.
  When that happens you get an explicit note (not a silent hang): the current
  step did not finish, but **the conversation context is kept** so you can
  continue, narrow the ask, or redirect. Files it already wrote in the working
  directory may still be there — say what you want done with them next.
- Messages are plain natural language.

> This manual describes the current version. The tool evolves over time; when its
> behavior changes, this manual is expected to change with it.
