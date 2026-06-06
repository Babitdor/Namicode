# MASTER'S THESIS PROPOSAL

## Development of an Extensible Multi-Agent Harness for Automated MBSE

## Goals

This thesis designs, implements, and evaluates a modular multi-agent system that automates the transition across the four phases of Systems Engineering — Requirements, Functional, Logical, and Physical — in the context of warehouse concept development.

The specific goals are:

1. **Design and implement the Agent Harness** — a FastAPI orchestrator running the LangGraph *deepagents* framework, persisting per-thread state through a SQLite checkpointer and conversation history in Postgres, with each chat session bound to its own Docker sandbox that hosts a shared **Artifact-Based Workspace** as the single source of truth across all engineering phases.
2. **Define the Handover Protocol** — a formal sub-agent interface (artifact dependency declaration, output schema, skill manifest, optional tool list) enabling plug-and-play extensibility. The protocol is exercised at runtime by a user-facing *Agents Tab* in which end-users define custom subagents that are live-injected into every orchestrator without code changes or restarts.
3. **Implement a tool-mediated validation loop** integrating ANTLR4-based SysML v2 parsing, syntax reference lookup, and retrieval over a FAPS-archive corpus, all invoked as tool calls inside the SysML agent before any artifact is committed to the workspace.
4. **Build a Skill Library** of versioned, structured *Skill Documents* per SysML v2 diagram type — loaded into the relevant subagents at inference time via the deepagents *SkillsMiddleware* — to enable correct artifact generation without model fine-tuning.
5. **Release** the Harness API specification, artifact schemas, Skill Library, annotated benchmark dataset, and a containerized reference deployment (docker-compose stack: backend + Next.js UI + Postgres + Eclipse SysON visualizer) as open artefacts for future MBSE automation research.

## Research Questions

The thesis is structured around four research questions. Each is paired with a concrete, measurable success criterion that defines what "answered" means.

| ID  | Research Question |
|-----|------------------|
| **RQ1** | How effectively does the *Artifact-Based Workspace* prevent constraint loss across engineering phases, measured by traceability retention from raw requirements ingestion through to physical layout, when downstream agents must declare their upstream artifact dependencies explicitly? |
| **RQ2** | What interface specification — artifact dependencies, output schema, skill manifest, optional tool bindings — is necessary and sufficient to allow a new sub-agent to integrate with the Harness without modifying existing agents or the orchestrator? Validated by the runtime *custom subagent* mechanism: user-created agents become discoverable through `@mention` and are live-propagated into every active orchestrator. |
| **RQ3** | To what extent does the *tool-mediated validation loop* — where the SysML agent must invoke an ANTLR4 parser, a syntax reference tool, and an example-retrieval tool before emitting any `.sysml` file — improve SysML v2 syntactic validity and requirement coverage compared to a non-validated baseline? |
| **RQ4** | What Skill Document structure — syntax rules, validated few-shot example counts, error-avoidance patterns, artifact-to-SysML naming conventions — minimizes SysML v2 parse errors for each diagram type without model fine-tuning? |

## Proposed Architecture

### Three-Layer Design

The framework is organized into three vertically independent layers:

1. **Agent Harness** — manages workspace state, orchestration, sandbox lifecycle, and tracing. This is the primary scientific contribution.
2. **Sub-Agents** — domain-specialist LLM agents, each responsible for one engineering artifact family, conforming to the Handover Protocol.
3. **Skill Library** — structured in-context knowledge enabling SysML-v2 generation without fine-tuning.

The key design principle: **the Harness is the product**. Sub-agents are interchangeable — if a better LLM ships, the agent spec is swapped. The artifact schemas, validation tools, Skill Library, and Handover Protocol remain valid.

### Layer 1: The Agent Harness

#### 1.1 Artifact-Based Workspace (Central Memory)

Each chat thread owns a deterministically named Docker container (`harness-<thread_id>`), bind-mounted to a project workspace at `/workspace/project_<id>/`. Inside that workspace, an `artifacts/` directory accumulates the system model as a set of structured markdown files and validated SysML v2 packages. Every agent reads upstream artifacts from this workspace and writes its outputs back — never directly to another agent.

| Artifact | Producer | Description |
|----------|----------|-------------|
| `REQUIREMENTS.md` | @Ingestion | Typed requirements with IDs, KPI bounds, source-question references |
| `BOX.md` | @Ingestion | Morphological box of solution principles |
| `RULES.md` | @Ingestion | Cross-cutting design rules and constraints |
| `USECASES.md` | @Requirements | Actors and use cases linked to requirement IDs |
| `ACTIVITIES.md` | @Functional | Activity flows linked to use case IDs |
| `PRINCIPLE_SOLUTIONS.md` | @Functional | Selected solution principles from the morphological box |
| `BDD.md`, `IBD.md` | @Logical | Block definitions and internal block structure |
| `sysml/*.sysml` | @SysML | ANTLR4-validated SysML v2 packages (requirement diagram, BDD, IBD, etc.) |
| `sankey.html` | @Sankey | Interactive material/information flow visualization |
| `layout/*` | @Optimization | Layout variants satisfying BDD/IBD/RULES constraints |

**Conflict resolution**: when the SysML agent's validator rejects a draft (parse error, missing requirement reference), the failure is returned to the agent with a structured error report, and the agent retries against the same artifact slot before the file is allowed into `artifacts/sysml/`.

#### 1.2 Context Orchestration

The orchestrator is implemented on the LangGraph *deepagents* framework. To prevent context overflow, sub-agents declare their upstream artifact dependencies in their description; the orchestrator resolves the dependency DAG and feeds each sub-agent only the slice it needs rather than the full workspace contents. Per-thread state — message history, tool-call records, and pending sub-agent invocations — is persisted via a SQLite checkpointer so chats survive backend restarts. Conversation metadata (titles, message history for UI hydration) is persisted in Postgres.

#### 1.3 Tool-Mediated Validation Loop

Rather than introducing a separate "Reviewer" agent, validation responsibilities are embedded as **typed tool calls** that the SysML agent must invoke:

- **`sysml_validator_tool`** — runs the ANTLR4-generated SysML v2 parser over the candidate file and returns line-numbered errors.
- **`sysml_syntax_tool`** — returns canonical grammar patterns for the requested diagram type.
- **`sysml_example_search_tool`** — RAG lookup against the FAPS SysML v2 dataset for analogous validated examples.

A draft `.sysml` artifact is committed to the workspace only after the validator returns zero errors. Failures trigger targeted repair: the structured error report is fed back into the agent's next turn alongside the syntax reference and a retrieved exemplar. All tool calls are logged to LangSmith, providing the trace data used to answer RQ3 and RQ4.

### Layer 2: Sub-Agents

Seven core agents are implemented, each conforming to the Handover Protocol. Extensibility (RQ2) is demonstrated by the *custom subagent* runtime mechanism — end-users define agents in the UI (name, description, system prompt); the orchestrator is invalidated and rebuilt with the new roster on the next message, without code changes or service restart.

| Agent | Reads | Produces |
|-------|-------|----------|
| **@Ingestion** | Raw uploads (PDF / XLSX / DOCX / text) | `REQUIREMENTS.md`, `BOX.md`, `RULES.md` |
| **@Requirements** | `REQUIREMENTS.md` | `USECASES.md` |
| **@Functional** | `USECASES.md`, `BOX.md` | `ACTIVITIES.md`, `PRINCIPLE_SOLUTIONS.md` |
| **@Logical** | `ACTIVITIES.md`, `RULES.md` | `BDD.md`, `IBD.md` |
| **@SysML** | `REQUIREMENTS.md`, `USECASES.md`, `BDD.md`, `IBD.md`, `RULES.md` | Validated `sysml/*.sysml` packages |
| **@Sankey** | `BDD.md`, `IBD.md` | Interactive HTML Sankey diagram |
| **@Optimization** | `BDD.md`, `IBD.md`, `RULES.md` | Layout variants |

The **Optimization** agent is a special case: the LLM operates as a zone-assignment planner that proposes layout candidates, with rule-checking against `RULES.md` constraints (minimum aisle widths, area allocations, throughput bounds) enforced before a variant is committed. The hybrid approach avoids asking the LLM to solve bin-packing unaided; tighter constraint-satisfaction integration is identified as future work.

**SysON integration**: validated `.sysml` artifacts can be published directly to an Eclipse SysON v2 web editor via its GraphQL `insertTextualSysMLv2` mutation, giving stakeholders an interactive graphical view of the system model without leaving the workflow.

### Layer 3: Skill Library

Each sub-agent loads a *Skill Document* at inference time — a structured `SKILL.md` file version-controlled alongside the codebase under `backend/src/mbse/skills/`. Skills are mounted into the relevant subagents through the deepagents *SkillsMiddleware*. The current library covers:

- `requirement-diagram/SKILL.md`
- `use-case-diagram/SKILL.md`
- `activity-diagram/SKILL.md`
- `block-definition-diagram/SKILL.md`
- `internal-block-diagram/SKILL.md`
- `sankey-diagram/SKILL.md`
- `layout-generation/SKILL.md`

Each document encodes four content types:

1. **Syntax rules** — canonical SysML v2 grammar patterns for the diagram type, with explicit do/don't examples.
2. **Validated few-shot examples** — 3–5 complete ANTLR4-validated SysML v2 packages drawn from the FAPS archives.
3. **Error-avoidance patterns** — a distilled catalog of frequent parse errors with correct counterparts, populated from observed validator failures.
4. **Artifact binding conventions** — how workspace artifact fields map to SysML element names (e.g., `requirement.id` → `REQ-F-001` scheme).

The Skill Library is iteratively refined: when validation-failure analysis reveals a recurring error class, the relevant rule is tightened. The evolution of the library across iterations is itself a logged data artefact (commit history + LangSmith trace deltas) used for RQ4 analysis.