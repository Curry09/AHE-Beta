# Code Comment Conventions

Write comments and docstrings in English. Explain the purpose of the code and
reference the relevant design so another contributor can trace its rationale.
The examples use Python.

## Spec References

New code uses `# Spec-NNNN/Tn: ...`, for example `# Spec-0014/T3: ...`.
Existing `# RFC-NNNN` references remain valid: Spec group `NNNN` corresponds
one-to-one with legacy RFC `NNNN`. Do not rewrite those identifiers solely to
change the prefix.

Preserve protocol keys, paths, URLs, lint directives, and quoted source data when
their exact spelling matters. Translate the explanation around them.

## Module Docstrings

Describe the module's responsibility and its relevant Spec:

```python
"""Route messages between agents.

Spec-0007/T2: Agent message relay

Receive messages, wrap them as User queries, and enqueue them for the target agent.
"""
```

## Function and Class Docstrings

Start with a short English summary, then the Spec reference and useful details:

```python
def relay_message(*, sender: str, target: str, text: str) -> None:
    """Relay a message from one agent to another.

    Spec-0007/T2: Relay messages from A to B

    Wrap sender's original text as a User query and enqueue it for target.
    """
```

## Inline Step Comments

Explain meaningful steps without repeating the statement:

```python
    # 1. Verify that the target agent exists.
    agent = _get_agent(name=target)
    # 2. Wrap the original message as a User query.
    query = f"{sender} sent you a message: {text}"
```

## Field and Attribute Comments

Describe the field's role and reference the relevant Spec:

```python
@dataclass
class AgentState:
    # Spec-0002/T1: Coding agent backend (claude code / codex / nexau).
    backend: str
```

| Level | Content | Purpose |
|---|---|---|
| Module | Responsibility, docstring, and Spec reference | File-level overview |
| Function/class | English summary, Spec reference, and relevant detail | API behavior |
| Inline step | Numbered explanation where useful | Logic flow |
| Field/attribute | Spec reference and description | Data-model meaning |
