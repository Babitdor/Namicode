"""Package information tools.

This module provides tools for querying package metadata from registries.
"""

from __future__ import annotations

from typing import Any, Literal

import requests
from langchain.tools import tool


@tool
def package_info(
    name: str,
    registry: Literal["pypi", "npm"] = "pypi",
) -> dict[str, Any]:
    """Get package metadata from PyPI or npm registry.

    Useful for researching packages before adding them as dependencies,
    checking latest versions, or understanding package details.

    Args:
        name: Package name to look up
        registry: Package registry - "pypi" for Python packages, "npm" for Node.js

    Returns:
        Dictionary containing:
        - name: Package name
        - version: Latest version
        - description: Package description
        - author: Package author/maintainer
        - license: Package license
        - homepage: Project homepage URL
        - repository: Source code repository URL
        - dependencies: List of dependencies (npm) or requires (pypi)
        - keywords: Package keywords/tags

    Example:
        package_info("requests", registry="pypi")
        package_info("express", registry="npm")
    """
    try:
        if registry == "pypi":
            url = f"https://pypi.org/pypi/{name}/json"
            response = requests.get(url, timeout=10)

            if response.status_code == 404:
                return {"error": f"Package '{name}' not found on PyPI", "name": name}

            response.raise_for_status()
            data = response.json()
            info = data.get("info", {})

            return {
                "success": True,
                "registry": "pypi",
                "name": info.get("name"),
                "version": info.get("version"),
                "description": info.get("summary"),
                "author": info.get("author") or info.get("maintainer"),
                "author_email": info.get("author_email") or info.get("maintainer_email"),
                "license": info.get("license"),
                "homepage": info.get("home_page") or info.get("project_url"),
                "repository": next(
                    (
                        url
                        for key, url in (info.get("project_urls") or {}).items()
                        if "source" in key.lower()
                        or "repo" in key.lower()
                        or "github" in key.lower()
                    ),
                    None,
                ),
                "requires_python": info.get("requires_python"),
                "dependencies": info.get("requires_dist") or [],
                "keywords": (info.get("keywords", "").split(",") if info.get("keywords") else []),
                "classifiers": info.get("classifiers", [])[:10],  # Limit classifiers
            }

        if registry == "npm":
            url = f"https://registry.npmjs.org/{name}"
            response = requests.get(url, timeout=10)

            if response.status_code == 404:
                return {"error": f"Package '{name}' not found on npm", "name": name}

            response.raise_for_status()
            data = response.json()
            latest_version = data.get("dist-tags", {}).get("latest", "")
            latest_data = data.get("versions", {}).get(latest_version, {})

            # Extract repository URL
            repo = latest_data.get("repository", {})
            repo_url = repo.get("url", "") if isinstance(repo, dict) else repo
            if repo_url:
                repo_url = repo_url.replace("git+", "").replace("git://", "https://").rstrip(".git")

            return {
                "success": True,
                "registry": "npm",
                "name": data.get("name"),
                "version": latest_version,
                "description": data.get("description"),
                "author": (
                    latest_data.get("author", {}).get("name")
                    if isinstance(latest_data.get("author"), dict)
                    else latest_data.get("author")
                ),
                "license": latest_data.get("license"),
                "homepage": latest_data.get("homepage"),
                "repository": repo_url,
                "dependencies": list(latest_data.get("dependencies", {}).keys()),
                "dev_dependencies": list(latest_data.get("devDependencies", {}).keys())[:10],
                "keywords": data.get("keywords", []),
                "engines": latest_data.get("engines"),
            }

        return {"error": f"Unknown registry: {registry}. Use 'pypi' or 'npm'"}

    except requests.exceptions.Timeout:
        return {
            "error": f"Request timed out while fetching {registry} package info",
            "name": name,
        }
    except requests.exceptions.RequestException as e:
        return {"error": f"Network error: {e!s}", "name": name}
    except Exception as e:  # noqa: BLE001
        return {"error": f"Failed to get package info: {e!s}", "name": name}
