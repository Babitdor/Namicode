#!/usr/bin/env python3
"""Create workflow template files for Ralph Agents."""

import json
from pathlib import Path

# Create workflow templates
templates = {
    'python_package.json': {
        'workflow_id': 'python_package_dev',
        'name': 'Python Package Development',
        'description': 'Complete workflow for creating a Python package from scratch including setup, implementation, testing, documentation, and packaging.',
        'steps': [
            {
                'step_id': 'setup_project',
                'name': 'Project Setup',
                'agent': 'ralph',
                'task': 'Set up the Python package project structure with proper directory layout, pyproject.toml, setup.py, and initial README. Include proper package hierarchy with src/ directory layout. Add .gitignore for Python projects.',
                'dependencies': [],
                'iterations': 3,
                'on_failure': 'stop'
            },
            {
                'step_id': 'implement_core',
                'name': 'Core Implementation',
                'agent': 'coder',
                'task': 'Implement the core functionality of the package. Write clean, well-documented Python code following PEP 8 standards. Include type hints and docstrings for all public APIs.',
                'dependencies': ['setup_project'],
                'iterations': 10,
                'on_failure': 'retry'
            },
            {
                'step_id': 'write_tests',
                'name': 'Write Tests',
                'agent': 'tester',
                'task': 'Write comprehensive unit tests using pytest. Include tests for all public functions and classes. Use fixtures where appropriate. Aim for high code coverage.',
                'dependencies': ['implement_core'],
                'iterations': 5,
                'on_failure': 'continue'
            },
            {
                'step_id': 'integration_tests',
                'name': 'Integration Tests',
                'agent': 'tester',
                'task': 'Write integration tests that verify the package works end-to-end. Test error handling and edge cases.',
                'dependencies': ['write_tests'],
                'iterations': 3,
                'on_failure': 'continue'
            },
            {
                'step_id': 'documentation',
                'name': 'Documentation',
                'agent': 'ralph',
                'task': 'Create comprehensive documentation including README, API docs, usage examples, and changelog. Add inline docstrings following Google or NumPy style.',
                'dependencies': ['implement_core'],
                'iterations': 5,
                'on_failure': 'continue'
            },
            {
                'step_id': 'packaging',
                'name': 'Packaging',
                'agent': 'coder',
                'task': 'Configure package build system using build and twine. Ensure proper package metadata, dependencies, and entry points. Add MANIFEST.in if needed.',
                'dependencies': ['setup_project'],
                'iterations': 3,
                'on_failure': 'stop'
            },
            {
                'step_id': 'final_review',
                'name': 'Final Review',
                'agent': 'ralph',
                'task': 'Review the complete package. Check that all files are present, documentation is accurate, tests pass, and package can be installed and imported. Generate a final summary.',
                'dependencies': ['write_tests', 'documentation', 'packaging'],
                'iterations': 2,
                'on_failure': 'continue'
            }
        ]
    },
    'web_application.json': {
        'workflow_id': 'web_app_dev',
        'name': 'Web Application Development',
        'description': 'Full-stack web application development workflow including frontend, backend, database integration, testing, and deployment preparation.',
        'steps': [
            {
                'step_id': 'project_setup',
                'name': 'Project Setup',
                'agent': 'ralph',
                'task': 'Set up the web application project structure. Choose an appropriate tech stack (e.g., React + Node.js, Vue + Python, etc.). Configure build tools, package manager, and development environment.',
                'dependencies': [],
                'iterations': 3,
                'on_failure': 'stop'
            },
            {
                'step_id': 'backend_api',
                'name': 'Backend API Development',
                'agent': 'coder',
                'task': 'Develop the backend REST API. Design database schema, implement endpoints, add authentication/authorization, and handle errors properly. Use best practices for the chosen framework.',
                'dependencies': ['project_setup'],
                'iterations': 10,
                'on_failure': 'retry'
            },
            {
                'step_id': 'frontend_ui',
                'name': 'Frontend UI Development',
                'agent': 'coder',
                'task': 'Build the frontend user interface. Create responsive components, implement state management, connect to the API, and add proper routing and navigation.',
                'dependencies': ['project_setup'],
                'iterations': 10,
                'on_failure': 'retry'
            },
            {
                'step_id': 'database_integration',
                'name': 'Database Integration',
                'agent': 'coder',
                'task': 'Set up and integrate the database. Create migrations, seed initial data, optimize queries, and implement proper data validation and relationships.',
                'dependencies': ['backend_api'],
                'iterations': 5,
                'on_failure': 'stop'
            },
            {
                'step_id': 'api_testing',
                'name': 'API Testing',
                'agent': 'tester',
                'task': 'Write comprehensive tests for the backend API. Test all endpoints, authentication, error handling, and edge cases. Include integration tests.',
                'dependencies': ['backend_api'],
                'iterations': 5,
                'on_failure': 'continue'
            },
            {
                'step_id': 'frontend_testing',
                'name': 'Frontend Testing',
                'agent': 'tester',
                'task': 'Write tests for the frontend components. Test UI rendering, user interactions, state management, and API integration. Use appropriate testing framework.',
                'dependencies': ['frontend_ui'],
                'iterations': 5,
                'on_failure': 'continue'
            },
            {
                'step_id': 'deployment_prep',
                'name': 'Deployment Preparation',
                'agent': 'ralph',
                'task': 'Prepare the application for deployment. Create Docker containers, configure CI/CD pipelines, set up environment variables, and prepare deployment documentation.',
                'dependencies': ['api_testing', 'frontend_testing', 'database_integration'],
                'iterations': 3,
                'on_failure': 'stop'
            },
            {
                'step_id': 'documentation',
                'name': 'Documentation',
                'agent': 'ralph',
                'task': 'Create comprehensive documentation including README, API documentation, deployment guide, and user manual. Add code comments and document configuration options.',
                'dependencies': ['deployment_prep'],
                'iterations': 3,
                'on_failure': 'continue'
            }
        ]
    },
    'rest_api.json': {
        'workflow_id': 'rest_api_dev',
        'name': 'REST API Development',
        'description': 'API-first development workflow including API design, endpoint implementation, authentication, testing, and documentation.',
        'steps': [
            {
                'step_id': 'api_design',
                'name': 'API Design',
                'agent': 'ralph',
                'task': 'Design the REST API architecture. Define endpoints, request/response formats, data models, authentication scheme, and versioning strategy. Create API specification in OpenAPI/Swagger format.',
                'dependencies': [],
                'iterations': 3,
                'on_failure': 'stop'
            },
            {
                'step_id': 'project_setup',
                'name': 'Project Setup',
                'agent': 'ralph',
                'task': 'Set up the API project with appropriate framework (e.g., FastAPI, Flask, Express). Configure project structure, dependencies, development tools, and initial configuration files.',
                'dependencies': ['api_design'],
                'iterations': 2,
                'on_failure': 'stop'
            },
            {
                'step_id': 'data_models',
                'name': 'Data Models',
                'agent': 'coder',
                'task': 'Implement data models and schemas based on the API design. Set up database ORM, define tables/relations, and add validation rules.',
                'dependencies': ['project_setup'],
                'iterations': 5,
                'on_failure': 'stop'
            },
            {
                'step_id': 'endpoints',
                'name': 'Endpoint Implementation',
                'agent': 'coder',
                'task': 'Implement all API endpoints following REST principles. Add proper error handling, status codes, and input validation. Implement business logic and data access layer.',
                'dependencies': ['data_models'],
                'iterations': 10,
                'on_failure': 'retry'
            },
            {
                'step_id': 'authentication',
                'name': 'Authentication & Authorization',
                'agent': 'coder',
                'task': 'Implement authentication (JWT, OAuth, API keys) and authorization (role-based access control, permissions). Secure sensitive endpoints and add rate limiting.',
                'dependencies': ['endpoints'],
                'iterations': 5,
                'on_failure': 'stop'
            },
            {
                'step_id': 'api_testing',
                'name': 'API Testing',
                'agent': 'tester',
                'task': 'Write comprehensive tests for the API. Test all endpoints, authentication, error handling, edge cases, and performance. Include unit, integration, and end-to-end tests.',
                'dependencies': ['authentication'],
                'iterations': 5,
                'on_failure': 'continue'
            },
            {
                'step_id': 'api_docs',
                'name': 'API Documentation',
                'agent': 'ralph',
                'task': 'Generate comprehensive API documentation. Create interactive API docs (Swagger/OpenAPI UI), write usage examples, and document authentication and error codes.',
                'dependencies': ['endpoints'],
                'iterations': 3,
                'on_failure': 'continue'
            },
            {
                'step_id': 'deployment',
                'name': 'Deployment Setup',
                'agent': 'coder',
                'task': 'Prepare API for deployment. Create Docker container, configure environment variables, set up health checks, and prepare production deployment scripts.',
                'dependencies': ['api_testing', 'api_docs'],
                'iterations': 3,
                'on_failure': 'stop'
            }
        ]
    },
    'testing_workflow.json': {
        'workflow_id': 'testing_workflow',
        'name': 'Comprehensive Testing Workflow',
        'description': 'Complete testing workflow covering test planning, unit tests, integration tests, test execution, and coverage analysis.',
        'steps': [
            {
                'step_id': 'test_planning',
                'name': 'Test Planning',
                'agent': 'ralph',
                'task': 'Analyze the codebase and create a comprehensive test plan. Identify testable components, define test categories (unit, integration, e2e), and prioritize test coverage areas.',
                'dependencies': [],
                'iterations': 2,
                'on_failure': 'stop'
            },
            {
                'step_id': 'test_setup',
                'name': 'Test Environment Setup',
                'agent': 'coder',
                'task': 'Set up the testing environment. Configure test framework (pytest, jest, etc.), set up test databases, mock external services, and configure CI/CD for automated testing.',
                'dependencies': ['test_planning'],
                'iterations': 2,
                'on_failure': 'stop'
            },
            {
                'step_id': 'unit_tests',
                'name': 'Unit Tests',
                'agent': 'tester',
                'task': 'Write comprehensive unit tests for all functions, classes, and modules. Use fixtures, mocks, and parameterized tests. Aim for high coverage of business logic.',
                'dependencies': ['test_setup'],
                'iterations': 8,
                'on_failure': 'continue'
            },
            {
                'step_id': 'integration_tests',
                'name': 'Integration Tests',
                'agent': 'tester',
                'task': 'Write integration tests that verify components work together correctly. Test API integrations, database operations, and service interactions.',
                'dependencies': ['unit_tests'],
                'iterations': 6,
                'on_failure': 'continue'
            },
            {
                'step_id': 'e2e_tests',
                'name': 'End-to-End Tests',
                'agent': 'tester',
                'task': 'Write end-to-end tests that verify complete user workflows and system behavior. Test critical paths from user perspective.',
                'dependencies': ['integration_tests'],
                'iterations': 5,
                'on_failure': 'continue'
            },
            {
                'step_id': 'test_execution',
                'name': 'Test Execution',
                'agent': 'tester',
                'task': 'Execute all tests and collect results. Run tests in parallel where possible, capture output, and identify failing tests.',
                'dependencies': ['unit_tests', 'integration_tests', 'e2e_tests'],
                'iterations': 2,
                'on_failure': 'stop'
            },
            {
                'step_id': 'coverage_analysis',
                'name': 'Coverage Analysis',
                'agent': 'tester',
                'task': 'Generate and analyze test coverage reports. Identify untested code paths, calculate coverage metrics, and create gaps report for areas needing more tests.',
                'dependencies': ['test_execution'],
                'iterations': 2,
                'on_failure': 'continue'
            },
            {
                'step_id': 'bug_fixing',
                'name': 'Bug Fixing',
                'agent': 'coder',
                'task': 'Fix bugs identified during testing. Ensure fixes are properly tested and do not introduce new issues. Add regression tests for fixed bugs.',
                'dependencies': ['test_execution'],
                'iterations': 5,
                'on_failure': 'retry'
            },
            {
                'step_id': 'test_report',
                'name': 'Test Report',
                'agent': 'ralph',
                'task': 'Create comprehensive test report summarizing test results, coverage metrics, bugs found and fixed, and recommendations for improving test quality.',
                'dependencies': ['coverage_analysis', 'bug_fixing'],
                'iterations': 2,
                'on_failure': 'continue'
            }
        ]
    },
    'documentation_workflow.json': {
        'workflow_id': 'documentation_workflow',
        'name': 'Documentation Creation Workflow',
        'description': 'Complete documentation creation workflow covering README, API docs, user guides, examples, and documentation review.',
        'steps': [
            {
                'step_id': 'doc_planning',
                'name': 'Documentation Planning',
                'agent': 'ralph',
                'task': 'Analyze the codebase and create a documentation plan. Identify target audience, required documentation types (user guide, API reference, tutorials), and structure. Define documentation standards and style guide.',
                'dependencies': [],
                'iterations': 2,
                'on_failure': 'stop'
            },
            {
                'step_id': 'readme',
                'name': 'README Creation',
                'agent': 'ralph',
                'task': 'Create a comprehensive README.md. Include project description, features, installation instructions, quick start guide, usage examples, contribution guidelines, and license information.',
                'dependencies': ['doc_planning'],
                'iterations': 3,
                'on_failure': 'stop'
            },
            {
                'step_id': 'api_docs',
                'name': 'API Documentation',
                'agent': 'ralph',
                'task': 'Generate API documentation from code comments and docstrings. Document all public APIs with parameters, return types, exceptions, and usage examples. Use appropriate documentation generation tools.',
                'dependencies': ['readme'],
                'iterations': 5,
                'on_failure': 'continue'
            },
            {
                'step_id': 'user_guide',
                'name': 'User Guide',
                'agent': 'ralph',
                'task': 'Write detailed user guide covering installation, configuration, usage patterns, and common workflows. Include screenshots, diagrams, and step-by-step instructions where helpful.',
                'dependencies': ['readme'],
                'iterations': 5,
                'on_failure': 'continue'
            },
            {
                'step_id': 'examples',
                'name': 'Code Examples',
                'agent': 'coder',
                'task': 'Create practical code examples demonstrating key features and usage patterns. Write executable examples, add comments explaining the code, and include expected output.',
                'dependencies': ['user_guide'],
                'iterations': 4,
                'on_failure': 'continue'
            },
            {
                'step_id': 'tutorials',
                'name': 'Tutorials',
                'agent': 'ralph',
                'task': 'Create step-by-step tutorials for common use cases and workflows. Structure tutorials progressively from basic to advanced concepts. Include exercises and challenges.',
                'dependencies': ['examples'],
                'iterations': 4,
                'on_failure': 'continue'
            },
            {
                'step_id': 'contributing_guide',
                'name': 'Contributing Guide',
                'agent': 'ralph',
                'task': 'Write CONTRIBUTING.md covering development setup, coding standards, testing guidelines, pull request process, and code review expectations. Help contributors get started quickly.',
                'dependencies': ['readme'],
                'iterations': 3,
                'on_failure': 'continue'
            },
            {
                'step_id': 'inline_docs',
                'name': 'Inline Code Documentation',
                'agent': 'coder',
                'task': 'Review and improve inline code documentation. Add missing docstrings, improve existing ones, ensure consistent style, and document complex algorithms and design decisions.',
                'dependencies': ['api_docs'],
                'iterations': 5,
                'on_failure': 'continue'
            },
            {
                'step_id': 'changelog',
                'name': 'Changelog',
                'agent': 'ralph',
                'task': 'Create CHANGELOG.md documenting version history, new features, bug fixes, breaking changes, and migration guides. Follow semantic versioning conventions.',
                'dependencies': ['api_docs'],
                'iterations': 2,
                'on_failure': 'continue'
            },
            {
                'step_id': 'doc_review',
                'name': 'Documentation Review',
                'agent': 'tester',
                'task': 'Review all documentation for accuracy, clarity, completeness, and consistency. Test code examples for correctness, verify installation instructions, and check for outdated information.',
                'dependencies': ['api_docs', 'user_guide', 'examples', 'tutorials', 'contributing_guide', 'inline_docs', 'changelog'],
                'iterations': 3,
                'on_failure': 'continue'
            },
            {
                'step_id': 'doc_site',
                'name': 'Documentation Site Setup',
                'agent': 'coder',
                'task': 'Set up a documentation site using tools like Sphinx, MkDocs, or Docusaurus. Configure theming, search, navigation, and automated builds from markdown.',
                'dependencies': ['doc_review'],
                'iterations': 3,
                'on_failure': 'continue'
            }
        ]
    }
}

# Get template directory
template_dir = Path(__file__).parent / 'templates'
template_dir.mkdir(exist_ok=True)

# Create each template file
for filename, content in templates.items():
    filepath = template_dir / filename
    with open(filepath, 'w') as f:
        json.dump(content, f, indent=2)
    print(f'Created {filename}')

print('\nAll workflow templates created successfully!')