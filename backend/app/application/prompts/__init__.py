"""Application-layer prompt templates.

Each module in this package owns the prompts for exactly one agent.
Prompt construction is kept separate from node logic so that:
  - Prompts can be reviewed, versioned, and tested in isolation.
  - Node implementations stay focused on LLM I/O and state mutations.
  - Prompt content never leaks into infrastructure or domain layers.

Import convention:
    from app.application.prompts.requirements_analyst import (
        build_requirements_analyst_messages,
    )
"""
