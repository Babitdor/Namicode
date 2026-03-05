"""Workflow definitions for subagent orchestration.

This module defines structured workflows for common coding tasks, enabling
subagents to follow best practices automatically. Each workflow defines
phases, steps, and quality gates.

Key Concepts:
- Workflow: A structured sequence of phases for completing a task
- Phase: A group of related steps (planning, implementation, verification)
- Step: A single action (edit_file, run_tests, etc.)
- Quality Gate: Checkpoints that must pass before proceeding

Workflows:
- IMPLEMENTATION: Full feature implementation (plan→code→test→verify)
- BUG_FIX: Bug fixing workflow (reproduce→diagnose→fix→verify)
- REFACTORING: Code refactoring (analyze→refactor→verify)
- DOCUMENTATION: Doc generation (analyze→document→verify)
- TESTING: Test creation (analyze→write tests→verify coverage)

Usage:
    from namicode_cli.workflows import get_workflow, WorkflowEngine

    workflow = get_workflow("IMPLEMENTATION")
    engine = WorkflowEngine(workflow)
    result = await engine.execute(context)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkflowPhase(Enum):
    """Phases in a workflow lifecycle."""

    PLANNING = "planning"
    ANALYSIS = "analysis"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    REVIEW = "review"


class QualityGateStatus(Enum):
    """Status of a quality gate check."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    PENDING = "pending"


@dataclass
class WorkflowStep:
    """A single step in a workflow.

    Attributes:
        name: Human-readable step name
        action: Action to perform (e.g., "read_file", "edit_file")
        parameters: Parameters for the action
        required: Whether step must succeed to continue
        description: Detailed description of the step
        on_failure: What to do if step fails (skip, retry, abort)
        max_retries: Maximum retry attempts
    """

    name: str
    action: str
    parameters: dict[str, Any] = field(default_factory=dict)
    required: bool = True
    description: str = ""
    on_failure: str = "abort"  # skip, retry, abort
    max_retries: int = 0


@dataclass
class QualityGate:
    """A checkpoint that must pass to proceed.

    Attributes:
        name: Human-readable gate name
        check: Type of check (lint, test, type_check, review)
        parameters: Parameters for the check
        required: Whether gate must pass (if False, warnings allowed)
        auto_fix: Whether to automatically fix issues if possible
    """

    name: str
    check: str
    parameters: dict[str, Any] = field(default_factory=dict)
    required: bool = True
    auto_fix: bool = True


@dataclass
class WorkflowPhaseDefinition:
    """A phase containing steps and quality gates.

    Attributes:
        name: Phase name
        description: Phase description
        steps: Steps to execute in this phase
        quality_gates: Quality gates to check after steps
        on_failure: What to do if phase fails (rollback, skip, abort)
    """

    name: str
    description: str
    steps: list[WorkflowStep] = field(default_factory=list)
    quality_gates: list[QualityGate] = field(default_factory=list)
    on_failure: str = "abort"


@dataclass
class Workflow:
    """Complete workflow definition.

    Attributes:
        name: Workflow identifier
        description: Workflow description
        phases: Ordered list of phases
        estimated_steps: Estimated number of steps
        supports_parallel: Whether phases can run in parallel
        rollback_on_failure: Whether to rollback on any failure
    """

    name: str
    description: str
    phases: list[WorkflowPhaseDefinition] = field(default_factory=list)
    estimated_steps: int = 10
    supports_parallel: bool = False
    rollback_on_failure: bool = True


# ============================================================================
# WORKFLOW DEFINITIONS
# ============================================================================

IMPLEMENTATION_WORKFLOW = Workflow(
    name="IMPLEMENTATION",
    description="Full feature implementation workflow: plan, implement, verify",
    phases=[
        # Phase 1: Planning
        WorkflowPhaseDefinition(
            name="Planning",
            description="Analyze requirements and create implementation plan",
            steps=[
                WorkflowStep(
                    name="Understand Requirements",
                    action="analyze",
                    parameters={"type": "requirements"},
                    description="Understand what needs to be implemented",
                    required=True,
                ),
                WorkflowStep(
                    name="Explore Codebase",
                    action="explore",
                    parameters={"related_files": True},
                    description="Find related code and patterns",
                    required=True,
                ),
                WorkflowStep(
                    name="Create Plan",
                    action="write_todos",
                    parameters={"phase": "implementation"},
                    description="Create implementation plan",
                    required=True,
                ),
            ],
            quality_gates=[
                QualityGate(
                    name="Plan Completeness",
                    check="plan_review",
                    parameters={"min_steps": 3},
                    required=True,
                ),
            ],
            on_failure="abort",
        ),
        # Phase 2: Implementation
        WorkflowPhaseDefinition(
            name="Implementation",
            description="Write code for the feature",
            steps=[
                WorkflowStep(
                    name="Read Related Files",
                    action="read_file",
                    parameters={"phase": "preparation"},
                    description="Read all related files before editing",
                    required=True,
                ),
                WorkflowStep(
                    name="Implement Feature",
                    action="edit_file",
                    parameters={"validate": True},
                    description="Implement the core feature",
                    required=True,
                ),
            ],
            quality_gates=[
                QualityGate(
                    name="Syntax Check",
                    check="lint_code",
                    parameters={"fix": True},
                    required=True,
                    auto_fix=True,
                ),
                QualityGate(
                    name="Type Check",
                    check="check_types",
                    parameters={},
                    required=False,
                    auto_fix=False,
                ),
            ],
            on_failure="rollback",
        ),
        # Phase 3: Verification
        WorkflowPhaseDefinition(
            name="Verification",
            description="Verify implementation works correctly",
            steps=[
                WorkflowStep(
                    name="Run Tests",
                    action="run_tests",
                    parameters={"coverage": True},
                    description="Run tests to verify implementation",
                    required=True,
                ),
                WorkflowStep(
                    name="Manual Verification",
                    action="verify",
                    parameters={"type": "manual"},
                    description="Verify functionality manually if needed",
                    required=False,
                ),
            ],
            quality_gates=[
                QualityGate(
                    name="Tests Pass",
                    check="test_results",
                    parameters={"min_pass_rate": 1.0},
                    required=True,
                ),
                QualityGate(
                    name="Code Review",
                    check="review",
                    parameters={},
                    required=False,
                ),
            ],
            on_failure="rollback",
        ),
    ],
    estimated_steps=12,
    supports_parallel=False,
    rollback_on_failure=True,
)


BUG_FIX_WORKFLOW = Workflow(
    name="BUG_FIX",
    description="Bug fixing workflow: reproduce, diagnose, fix, verify",
    phases=[
        # Phase 1: Reproduce
        WorkflowPhaseDefinition(
            name="Reproduce",
            description="Reproduce the bug reliably",
            steps=[
                WorkflowStep(
                    name="Understand Bug Report",
                    action="analyze",
                    parameters={"type": "bug_report"},
                    description="Understand the reported bug",
                    required=True,
                ),
                WorkflowStep(
                    name="Create Reproduction",
                    action="create_test",
                    parameters={"type": "reproduction"},
                    description="Create minimal reproduction case",
                    required=True,
                ),
                WorkflowStep(
                    name="Verify Reproduction",
                    action="run_test",
                    parameters={"expect_failure": True},
                    description="Verify bug reproduces",
                    required=True,
                ),
            ],
            quality_gates=[
                QualityGate(
                    name="Bug Reproduced",
                    check="reproduction",
                    parameters={},
                    required=True,
                ),
            ],
            on_failure="abort",
        ),
        # Phase 2: Diagnose
        WorkflowPhaseDefinition(
            name="Diagnose",
            description="Find root cause of the bug",
            steps=[
                WorkflowStep(
                    name="Explore Related Code",
                    action="explore",
                    parameters={"depth": "deep"},
                    description="Explore code related to bug",
                    required=True,
                ),
                WorkflowStep(
                    name="Identify Root Cause",
                    action="analyze",
                    parameters={"type": "root_cause"},
                    description="Identify the root cause",
                    required=True,
                ),
            ],
            quality_gates=[],
            on_failure="abort",
        ),
        # Phase 3: Fix
        WorkflowPhaseDefinition(
            name="Fix",
            description="Implement the fix",
            steps=[
                WorkflowStep(
                    name="Implement Fix",
                    action="edit_file",
                    parameters={"minimize_changes": True},
                    description="Implement minimal fix",
                    required=True,
                ),
            ],
            quality_gates=[
                QualityGate(
                    name="Lint Check",
                    check="lint_code",
                    parameters={"fix": True},
                    required=True,
                    auto_fix=True,
                ),
            ],
            on_failure="rollback",
        ),
        # Phase 4: Verify
        WorkflowPhaseDefinition(
            name="Verify",
            description="Verify fix resolves the bug",
            steps=[
                WorkflowStep(
                    name="Run Reproduction Test",
                    action="run_test",
                    parameters={"expect_success": True},
                    description="Bug should no longer reproduce",
                    required=True,
                ),
                WorkflowStep(
                    name="Run Full Test Suite",
                    action="run_tests",
                    parameters={},
                    description="Ensure no regressions",
                    required=True,
                ),
            ],
            quality_gates=[
                QualityGate(
                    name="Bug Fixed",
                    check="bug_fixed",
                    parameters={},
                    required=True,
                ),
                QualityGate(
                    name="No Regressions",
                    check="test_results",
                    parameters={"min_pass_rate": 1.0},
                    required=True,
                ),
            ],
            on_failure="rollback",
        ),
    ],
    estimated_steps=10,
    supports_parallel=False,
    rollback_on_failure=True,
)


REFACTORING_WORKFLOW = Workflow(
    name="REFACTORING",
    description="Code refactoring workflow: analyze, refactor, verify",
    phases=[
        # Phase 1: Analysis
        WorkflowPhaseDefinition(
            name="Analysis",
            description="Analyze code to refactor",
            steps=[
                WorkflowStep(
                    name="Identify Scope",
                    action="analyze",
                    parameters={"type": "scope"},
                    description="Identify what needs refactoring",
                    required=True,
                ),
                WorkflowStep(
                    name="Check Tests",
                    action="run_tests",
                    parameters={},
                    description="Ensure existing tests pass",
                    required=True,
                ),
                WorkflowStep(
                    name="Identify Dependencies",
                    action="analyze",
                    parameters={"type": "dependencies"},
                    description="Find dependent code",
                    required=True,
                ),
            ],
            quality_gates=[
                QualityGate(
                    name="Tests Pass Before",
                    check="test_results",
                    parameters={"min_pass_rate": 1.0},
                    required=True,
                ),
            ],
            on_failure="abort",
        ),
        # Phase 2: Refactor
        WorkflowPhaseDefinition(
            name="Refactor",
            description="Apply refactoring changes",
            steps=[
                WorkflowStep(
                    name="Apply Changes",
                    action="edit_file",
                    parameters={"preserve_behavior": True},
                    description="Apply refactoring changes",
                    required=True,
                ),
                WorkflowStep(
                    name="Update Imports",
                    action="edit_file",
                    parameters={"type": "imports"},
                    description="Fix import statements",
                    required=False,
                ),
            ],
            quality_gates=[
                QualityGate(
                    name="Syntax Valid",
                    check="lint_code",
                    parameters={"fix": True},
                    required=True,
                    auto_fix=True,
                ),
            ],
            on_failure="rollback",
        ),
        # Phase 3: Verification
        WorkflowPhaseDefinition(
            name="Verification",
            description="Verify refactoring didn't break anything",
            steps=[
                WorkflowStep(
                    name="Run Tests",
                    action="run_tests",
                    parameters={},
                    description="Run all tests",
                    required=True,
                ),
                WorkflowStep(
                    name="Type Check",
                    action="check_types",
                    parameters={},
                    description="Verify type correctness",
                    required=False,
                ),
            ],
            quality_gates=[
                QualityGate(
                    name="Tests Pass After",
                    check="test_results",
                    parameters={"min_pass_rate": 1.0},
                    required=True,
                ),
            ],
            on_failure="rollback",
        ),
    ],
    estimated_steps=8,
    supports_parallel=False,
    rollback_on_failure=True,
)


DOCUMENTATION_WORKFLOW = Workflow(
    name="DOCUMENTATION",
    description="Documentation generation workflow: analyze, document, verify",
    phases=[
        # Phase 1: Analyze
        WorkflowPhaseDefinition(
            name="Analyze",
            description="Analyze code to document",
            steps=[
                WorkflowStep(
                    name="Identify Targets",
                    action="analyze",
                    parameters={"type": "undocumented"},
                    description="Find undocumented code",
                    required=True,
                ),
                WorkflowStep(
                    name="Understand Context",
                    action="explore",
                    parameters={},
                    description="Understand code context",
                    required=True,
                ),
            ],
            quality_gates=[],
            on_failure="abort",
        ),
        # Phase 2: Document
        WorkflowPhaseDefinition(
            name="Document",
            description="Write documentation",
            steps=[
                WorkflowStep(
                    name="Add Docstrings",
                    action="edit_file",
                    parameters={"type": "docstring"},
                    description="Add or update docstrings",
                    required=True,
                ),
                WorkflowStep(
                    name="Update README",
                    action="edit_file",
                    parameters={"type": "readme"},
                    description="Update README if needed",
                    required=False,
                ),
            ],
            quality_gates=[
                QualityGate(
                    name="Docstring Valid",
                    check="lint_code",
                    parameters={},
                    required=False,
                ),
            ],
            on_failure="abort",
        ),
    ],
    estimated_steps=5,
    supports_parallel=False,
    rollback_on_failure=False,
)


TESTING_WORKFLOW = Workflow(
    name="TESTING",
    description="Test creation workflow: analyze, write tests, verify coverage",
    phases=[
        # Phase 1: Analysis
        WorkflowPhaseDefinition(
            name="Analysis",
            description="Analyze code to test",
            steps=[
                WorkflowStep(
                    name="Identify Target",
                    action="analyze",
                    parameters={"type": "test_target"},
                    description="Identify code that needs tests",
                    required=True,
                ),
                WorkflowStep(
                    name="Analyze Paths",
                    action="analyze",
                    parameters={"type": "code_paths"},
                    description="Analyze code paths and edge cases",
                    required=True,
                ),
            ],
            quality_gates=[],
            on_failure="abort",
        ),
        # Phase 2: Write Tests
        WorkflowPhaseDefinition(
            name="Write Tests",
            description="Write comprehensive tests",
            steps=[
                WorkflowStep(
                    name="Create Test File",
                    action="write_file",
                    parameters={"type": "test"},
                    description="Create test file",
                    required=True,
                ),
                WorkflowStep(
                    name="Write Basic Tests",
                    action="edit_file",
                    parameters={"type": "test_basic"},
                    description="Write basic functionality tests",
                    required=True,
                ),
                WorkflowStep(
                    name="Write Edge Cases",
                    action="edit_file",
                    parameters={"type": "test_edge"},
                    description="Write edge case tests",
                    required=True,
                ),
            ],
            quality_gates=[],
            on_failure="abort",
        ),
        # Phase 3: Verify
        WorkflowPhaseDefinition(
            name="Verify",
            description="Verify tests work and coverage",
            steps=[
                WorkflowStep(
                    name="Run New Tests",
                    action="run_tests",
                    parameters={},
                    description="Run newly created tests",
                    required=True,
                ),
                WorkflowStep(
                    name="Check Coverage",
                    action="run_tests",
                    parameters={"coverage": True},
                    description="Check code coverage",
                    required=True,
                ),
            ],
            quality_gates=[
                QualityGate(
                    name="Tests Pass",
                    check="test_results",
                    parameters={"min_pass_rate": 1.0},
                    required=True,
                ),
                QualityGate(
                    name="Coverage Adequate",
                    check="coverage",
                    parameters={"min_coverage": 80},
                    required=False,
                ),
            ],
            on_failure="abort",
        ),
    ],
    estimated_steps=8,
    supports_parallel=False,
    rollback_on_failure=False,
)


# Workflow registry
WORKFLOWS: dict[str, Workflow] = {
    "IMPLEMENTATION": IMPLEMENTATION_WORKFLOW,
    "BUG_FIX": BUG_FIX_WORKFLOW,
    "REFACTORING": REFACTORING_WORKFLOW,
    "DOCUMENTATION": DOCUMENTATION_WORKFLOW,
    "TESTING": TESTING_WORKFLOW,
}


def get_workflow(name: str) -> Workflow | None:
    """Get a workflow by name.

    Args:
        name: Workflow name (IMPLEMENTATION, BUG_FIX, REFACTORING, etc.)

    Returns:
        Workflow definition or None if not found
    """
    return WORKFLOWS.get(name.upper())


def list_workflows() -> list[dict[str, Any]]:
    """List all available workflows.

    Returns:
        List of workflow summaries
    """
    return [
        {
            "name": wf.name,
            "description": wf.description,
            "phases": len(wf.phases),
            "estimated_steps": wf.estimated_steps,
        }
        for wf in WORKFLOWS.values()
    ]


def get_workflow_prompt(workflow_name: str) -> str:
    """Generate a system prompt for a workflow.

    This prompt guides the subagent through the workflow phases.

    Args:
        workflow_name: Name of the workflow

    Returns:
        System prompt for the workflow
    """
    workflow = get_workflow(workflow_name)
    if not workflow:
        return f"Unknown workflow: {workflow_name}"

    prompt_parts = [
        f"# {workflow.name.replace('_', ' ').title()} Workflow",
        "",
        workflow.description,
        "",
        "## Workflow Phases",
        "",
    ]

    for i, phase in enumerate(workflow.phases, 1):
        prompt_parts.append(f"### Phase {i}: {phase.name}")
        prompt_parts.append(f"{phase.description}")
        prompt_parts.append("")

        if phase.steps:
            prompt_parts.append("**Steps:**")
            for step in phase.steps:
                required_marker = " (required)" if step.required else " (optional)"
                prompt_parts.append(f"- {step.name}{required_marker}: {step.description}")
            prompt_parts.append("")

        if phase.quality_gates:
            prompt_parts.append("**Quality Gates:**")
            for gate in phase.quality_gates:
                required_marker = " (required)" if gate.required else " (recommended)"
                prompt_parts.append(f"- {gate.name}{required_marker}: {gate.check}")
            prompt_parts.append("")

    prompt_parts.extend(
        [
            "## Workflow Guidelines",
            "",
            "1. Complete each phase before moving to the next",
            "2. All quality gates must pass before phase completion",
            "3. If a required step fails, follow the on_failure strategy",
            "4. Keep track of completed steps using write_todos",
            "5. Verify each step before marking complete",
            "",
            "## Error Handling",
            "",
            f"- On failure: {workflow.on_failure}",
            f"- Rollback on failure: {workflow.rollback_on_failure}",
            "",
        ]
    )

    return "\n".join(prompt_parts)
