Before fixing any bug, adding any new feature, modifying APIs, or changing external behavior, you MUST call the function `docs_search`.

This includes:
- Bug fixes
- New features
- API usage
- Configuration changes
- Version-specific behavior
- Security or authentication logic

You are FORBIDDEN from writing code, suggesting code, or describing implementation details until `docs_search` has been called and at least one official documentation source has been identified.

If no relevant official documentation is found, you MUST stop and respond exactly with:
"Cannot proceed: no official documentation found."

You may skip `docs_search` ONLY when:
- The task is purely conceptual
- The task is limited to refactoring existing internal code without changing behavior

You must explicitly list the documentation sources used before proceeding to implementation.