#!/usr/bin/env python3
"""Create additional workflow templates for Ralph Agents."""

import json
from pathlib import Path

# Additional workflow templates
additional_templates = {
    'ml_model.json': {
        'workflow_id': 'ml_model_dev',
        'name': 'Machine Learning Model Development',
        'description': 'Complete machine learning model development workflow including data preparation, model training, evaluation, and deployment.',
        'steps': [
            {
                'step_id': 'problem_definition',
                'name': 'Problem Definition',
                'agent': 'ralph',
                'task': 'Define the machine learning problem, identify target variables, set evaluation metrics, and establish success criteria. Document the problem statement and constraints.',
                'dependencies': [],
                'iterations': 2,
                'on_failure': 'stop'
            },
            {
                'step_id': 'data_collection',
                'name': 'Data Collection',
                'agent': 'ralph',
                'task': 'Collect and gather relevant datasets. Identify data sources, set up data pipelines, and perform initial data quality checks. Ensure proper data licensing and privacy compliance.',
                'dependencies': ['problem_definition'],
                'iterations': 3,
                'on_failure': 'stop'
            },
            {
                'step_id': 'data_preprocessing',
                'name': 'Data Preprocessing',
                'agent': 'coder',
                'task': 'Implement comprehensive data preprocessing pipeline. Handle missing values, outliers, categorical encoding, feature scaling, and data normalization. Create train/validation/test splits.',
                'dependencies': ['data_collection'],
                'iterations': 8,
                'on_failure': 'retry'
            },
            {
                'step_id': 'feature_engineering',
                'name': 'Feature Engineering',
                'agent': 'coder',
                'task': 'Develop and select features for the model. Create new features through domain knowledge, perform feature selection, and engineer transformations. Analyze feature importance and correlations.',
                'dependencies': ['data_preprocessing'],
                'iterations': 6,
                'on_failure': 'continue'
            },
            {
                'step_id': 'model_selection',
                'name': 'Model Selection',
                'agent': 'coder',
                'task': 'Select and implement baseline models. Try multiple algorithms (linear models, tree-based, neural networks, etc.). Set up cross-validation and initial hyperparameter tuning.',
                'dependencies': ['feature_engineering'],
                'iterations': 8,
                'on_failure': 'continue'
            },
            {
                'step_id': 'model_training',
                'name': 'Model Training',
                'agent': 'coder',
                'task': 'Train selected models with optimized hyperparameters. Implement proper training pipelines, use cross-validation, and track training metrics. Save trained models with versioning.',
                'dependencies': ['model_selection'],
                'iterations': 10,
                'on_failure': 'retry'
            },
            {
                'step_id': 'model_evaluation',
                'name': 'Model Evaluation',
                'agent': 'tester',
                'task': 'Comprehensively evaluate model performance using defined metrics. Generate confusion matrices, ROC curves, precision-recall curves. Perform error analysis and identify failure modes.',
                'dependencies': ['model_training'],
                'iterations': 5,
                'on_failure': 'continue'
            },
            {
                'step_id': 'model_optimization',
                'name': 'Model Optimization',
                'agent': 'coder',
                'task': 'Optimize model for production. Perform hyperparameter tuning, implement model distillation or pruning if needed, optimize inference speed, and reduce model size.',
                'dependencies': ['model_evaluation'],
                'iterations': 6,
                'on_failure': 'continue'
            },
            {
                'step_id': 'model_testing',
                'name': 'Model Testing',
                'agent': 'tester',
                'task': 'Write comprehensive tests for the model pipeline. Test preprocessing, inference, edge cases, and data drift detection. Ensure reproducibility of results.',
                'dependencies': ['model_optimization'],
                'iterations': 4,
                'on_failure': 'continue'
            },
            {
                'step_id': 'model_documentation',
                'name': 'Model Documentation',
                'agent': 'ralph',
                'task': 'Create comprehensive model documentation. Include model cards, data sheets, performance benchmarks, usage examples, and API documentation. Document limitations and ethical considerations.',
                'dependencies': ['model_evaluation'],
                'iterations': 3,
                'on_failure': 'continue'
            },
            {
                'step_id': 'deployment_prep',
                'name': 'Deployment Preparation',
                'agent': 'coder',
                'task': 'Prepare model for deployment. Create prediction APIs, containerize the model service, set up monitoring and logging, and prepare CI/CD pipelines for model updates.',
                'dependencies': ['model_testing', 'model_documentation'],
                'iterations': 4,
                'on_failure': 'stop'
            }
        ]
    },
    'devops_pipeline.json': {
        'workflow_id': 'devops_pipeline',
        'name': 'DevOps/CI-CD Pipeline Development',
        'description': 'Complete DevOps workflow including infrastructure setup, CI/CD pipeline creation, monitoring, and security implementation.',
        'steps': [
            {
                'step_id': 'infrastructure_planning',
                'name': 'Infrastructure Planning',
                'agent': 'ralph',
                'task': 'Plan infrastructure architecture. Define cloud provider, regions, availability zones, and resource requirements. Create infrastructure diagrams and cost estimates.',
                'dependencies': [],
                'iterations': 3,
                'on_failure': 'stop'
            },
            {
                'step_id': 'iac_setup',
                'name': 'Infrastructure as Code',
                'agent': 'coder',
                'task': 'Implement infrastructure using IaC tools (Terraform, CloudFormation, Pulumi). Define resources, create modules, set up state management, and implement best practices for modularity and reusability.',
                'dependencies': ['infrastructure_planning'],
                'iterations': 8,
                'on_failure': 'retry'
            },
            {
                'step_id': 'containerization',
                'name': 'Containerization',
                'agent': 'coder',
                'task': 'Create Docker containers for the application. Write optimized Dockerfiles, set up multi-stage builds, create docker-compose for local development, and implement security best practices.',
                'dependencies': ['iac_setup'],
                'iterations': 5,
                'on_failure': 'stop'
            },
            {
                'step_id': 'ci_pipeline',
                'name': 'CI Pipeline',
                'agent': 'coder',
                'task': 'Build continuous integration pipeline. Set up automated testing, code quality checks, security scanning, and artifact building. Configure branch protection and pull request checks.',
                'dependencies': ['containerization'],
                'iterations': 6,
                'on_failure': 'stop'
            },
            {
                'step_id': 'cd_pipeline',
                'name': 'CD Pipeline',
                'agent': 'coder',
                'task': 'Build continuous deployment pipeline. Implement deployment strategies (blue-green, canary), automated rollback mechanisms, and environment promotion workflows.',
                'dependencies': ['ci_pipeline'],
                'iterations': 6,
                'on_failure': 'retry'
            },
            {
                'step_id': 'monitoring_setup',
                'name': 'Monitoring Setup',
                'agent': 'coder',
                'task': 'Set up comprehensive monitoring and observability. Implement metrics collection, logging, distributed tracing, and alerting. Create dashboards for system health.',
                'dependencies': ['cd_pipeline'],
                'iterations': 6,
                'on_failure': 'continue'
            },
            {
                'step_id': 'security_hardening',
                'name': 'Security Hardening',
                'agent': 'coder',
                'task': 'Implement security best practices. Set up secrets management, configure network security, implement authentication/authorization, and enable security scanning in CI/CD.',
                'dependencies': ['iac_setup', 'monitoring_setup'],
                'iterations': 6,
                'on_failure': 'stop'
            },
            {
                'step_id': 'backup_disaster',
                'name': 'Backup and Disaster Recovery',
                'agent': 'coder',
                'task': 'Implement backup and disaster recovery strategies. Set up automated backups, test restore procedures, create disaster recovery runbooks, and implement RTO/RPO targets.',
                'dependencies': ['security_hardening'],
                'iterations': 4,
                'on_failure': 'continue'
            },
            {
                'step_id': 'pipeline_testing',
                'name': 'Pipeline Testing',
                'agent': 'tester',
                'task': 'Test the complete DevOps pipeline. Verify CI/CD workflows, test deployment scenarios, validate monitoring alerts, and perform disaster recovery drills.',
                'dependencies': ['backup_disaster'],
                'iterations': 4,
                'on_failure': 'continue'
            },
            {
                'step_id': 'documentation',
                'name': 'Documentation',
                'agent': 'ralph',
                'task': 'Create comprehensive DevOps documentation. Document infrastructure, CI/CD processes, runbooks, troubleshooting guides, and onboarding procedures.',
                'dependencies': ['pipeline_testing'],
                'iterations': 3,
                'on_failure': 'continue'
            }
        ]
    },
    'data_processing.json': {
        'workflow_id': 'data_processing_pipeline',
        'name': 'Data Processing Pipeline Development',
        'description': 'Complete data pipeline development workflow including ingestion, processing, storage, and analysis.',
        'steps': [
            {
                'step_id': 'requirements_analysis',
                'name': 'Requirements Analysis',
                'agent': 'ralph',
                'task': 'Analyze data processing requirements. Define data sources, processing logic, output formats, performance requirements, and data quality standards.',
                'dependencies': [],
                'iterations': 2,
                'on_failure': 'stop'
            },
            {
                'step_id': 'data_ingestion',
                'name': 'Data Ingestion',
                'agent': 'coder',
                'task': 'Implement data ingestion layer. Set up connections to data sources (databases, APIs, files), implement data fetching, handle authentication, and create initial data validation.',
                'dependencies': ['requirements_analysis'],
                'iterations': 6,
                'on_failure': 'retry'
            },
            {
                'step_id': 'data_transformation',
                'name': 'Data Transformation',
                'agent': 'coder',
                'task': 'Implement data transformation logic. Build ETL/ELT processes, handle data type conversions, apply business rules, and implement data cleaning and enrichment.',
                'dependencies': ['data_ingestion'],
                'iterations': 8,
                'on_failure': 'retry'
            },
            {
                'step_id': 'data_validation',
                'name': 'Data Validation',
                'agent': 'tester',
                'task': 'Implement comprehensive data validation. Create schema validation, data quality checks, anomaly detection, and validation reports. Handle invalid data appropriately.',
                'dependencies': ['data_transformation'],
                'iterations': 5,
                'on_failure': 'continue'
            },
            {
                'step_id': 'data_storage',
                'name': 'Data Storage',
                'agent': 'coder',
                'task': 'Set up data storage solution. Design database schema, implement data storage logic, optimize queries, and set up data archiving and retention policies.',
                'dependencies': ['data_validation'],
                'iterations': 6,
                'on_failure': 'stop'
            },
            {
                'step_id': 'pipeline_orchestration',
                'name': 'Pipeline Orchestration',
                'agent': 'coder',
                'task': 'Implement pipeline orchestration. Use workflow orchestrator (Airflow, Dagster, Prefect), define dependencies, schedule runs, and handle failures and retries.',
                'dependencies': ['data_storage'],
                'iterations': 6,
                'on_failure': 'retry'
            },
            {
                'step_id': 'performance_optimization',
                'name': 'Performance Optimization',
                'agent': 'coder',
                'task': 'Optimize pipeline performance. Implement parallelization, batching, caching, and incremental processing. Profile and identify bottlenecks.',
                'dependencies': ['pipeline_orchestration'],
                'iterations': 5,
                'on_failure': 'continue'
            },
            {
                'step_id': 'testing',
                'name': 'Pipeline Testing',
                'agent': 'tester',
                'task': 'Write comprehensive tests for the pipeline. Test individual components, integration tests, end-to-end tests, and performance tests. Test error handling and recovery.',
                'dependencies': ['performance_optimization'],
                'iterations': 5,
                'on_failure': 'continue'
            },
            {
                'step_id': 'monitoring_alerting',
                'name': 'Monitoring and Alerting',
                'agent': 'coder',
                'task': 'Set up pipeline monitoring and alerting. Track pipeline runs, data quality metrics, processing times, and error rates. Create dashboards and alert rules.',
                'dependencies': ['testing'],
                'iterations': 4,
                'on_failure': 'continue'
            },
            {
                'step_id': 'documentation',
                'name': 'Documentation',
                'agent': 'ralph',
                'task': 'Create comprehensive pipeline documentation. Document data flow, dependencies, configurations, troubleshooting guides, and data lineage.',
                'dependencies': ['monitoring_alerting'],
                'iterations': 3,
                'on_failure': 'continue'
            }
        ]
    },
    'microservices.json': {
        'workflow_id': 'microservices_architecture',
        'name': 'Microservices Architecture Development',
        'description': 'Complete microservices development workflow including service design, implementation, inter-service communication, and deployment.',
        'steps': [
            {
                'step_id': 'architecture_design',
                'name': 'Architecture Design',
                'agent': 'ralph',
                'task': 'Design microservices architecture. Define service boundaries, identify domain-driven design contexts, create service contracts, and design communication patterns.',
                'dependencies': [],
                'iterations': 3,
                'on_failure': 'stop'
            },
            {
                'step_id': 'api_design',
                'name': 'API Design',
                'agent': 'ralph',
                'task': 'Design APIs for all services. Create OpenAPI specifications, define request/response formats, implement versioning strategy, and document API contracts.',
                'dependencies': ['architecture_design'],
                'iterations': 4,
                'on_failure': 'stop'
            },
            {
                'step_id': 'service_skeleton',
                'name': 'Service Skeleton Creation',
                'agent': 'coder',
                'task': 'Create project skeletons for all microservices. Set up project structure, dependency management, build tools, and local development environment.',
                'dependencies': ['api_design'],
                'iterations': 4,
                'on_failure': 'stop'
            },
            {
                'step_id': 'service_implementation',
                'name': 'Service Implementation',
                'agent': 'coder',
                'task': 'Implement core business logic for each service. Follow clean architecture principles, implement domain models, and ensure proper separation of concerns.',
                'dependencies': ['service_skeleton'],
                'iterations': 10,
                'on_failure': 'retry'
            },
            {
                'step_id': 'inter_service_communication',
                'name': 'Inter-Service Communication',
                'agent': 'coder',
                'task': 'Implement communication between services. Set up synchronous (REST/gRPC) and asynchronous (message queue) communication, implement circuit breakers, and handle failures gracefully.',
                'dependencies': ['service_implementation'],
                'iterations': 8,
                'on_failure': 'retry'
            },
            {
                'step_id': 'data_management',
                'name': 'Data Management',
                'agent': 'coder',
                'task': 'Design and implement data management strategy. Define database per service pattern, implement data synchronization, handle transactions, and set up database migrations.',
                'dependencies': ['service_implementation'],
                'iterations': 6,
                'on_failure': 'stop'
            },
            {
                'step_id': 'authentication_authorization',
                'name': 'Authentication & Authorization',
                'agent': 'coder',
                'task': 'Implement centralized authentication and authorization. Set up OAuth2/OIDC, implement service-to-service authentication, and define role-based access control.',
                'dependencies': ['service_skeleton'],
                'iterations': 5,
                'on_failure': 'stop'
            },
            {
                'step_id': 'observability',
                'name': 'Observability',
                'agent': 'coder',
                'task': 'Implement observability across services. Add distributed tracing, structured logging, metrics collection, and correlation IDs. Create centralized dashboards.',
                'dependencies': ['service_implementation'],
                'iterations': 5,
                'on_failure': 'continue'
            },
            {
                'step_id': 'testing',
                'name': 'Testing',
                'agent': 'tester',
                'task': 'Implement comprehensive testing strategy. Write unit tests for each service, integration tests for communication, contract tests, and end-to-end tests.',
                'dependencies': ['inter_service_communication', 'data_management'],
                'iterations': 8,
                'on_failure': 'continue'
            },
            {
                'step_id': 'containerization',
                'name': 'Containerization',
                'agent': 'coder',
                'task': 'Containerize all microservices. Create optimized Dockerfiles, set up docker-compose for local development, and prepare container images for deployment.',
                'dependencies': ['testing'],
                'iterations': 4,
                'on_failure': 'stop'
            },
            {
                'step_id': 'deployment',
                'name': 'Deployment',
                'agent': 'coder',
                'task': 'Set up deployment infrastructure. Implement service mesh (if needed), configure load balancing, set up service discovery, and prepare Kubernetes manifests.',
                'dependencies': ['containerization'],
                'iterations': 6,
                'on_failure': 'retry'
            },
            {
                'step_id': 'documentation',
                'name': 'Documentation',
                'agent': 'ralph',
                'task': 'Create comprehensive microservices documentation. Document architecture, service boundaries, API specs, deployment guides, and runbooks.',
                'dependencies': ['deployment'],
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
for filename, content in additional_templates.items():
    filepath = template_dir / filename
    with open(filepath, 'w') as f:
        json.dump(content, f, indent=2)
    print(f'Created {filename}')

print('\nAdditional workflow templates created successfully!')