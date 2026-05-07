#!/usr/bin/env python3
"""
Compute per-workflow run flags by matching changed files against
the same path filters PostHog's GHA workflows use (via dorny/paths-filter).

Emits a JSON object with one boolean per CCI workflow.
"""
import sys
import json
import fnmatch

# Mirror PostHog's GHA dorny/paths-filter rules.
# Each entry: list of glob patterns (negation prefix '!' supported).
# If ANY changed file matches ANY positive pattern (and no negation overrides),
# the filter is True.
FILTERS = {
    "backend": [
        "ee/**",
        "common/__init__.py",
        "common/hogli/**",
        "common/hogql_parser/**",
        "common/hogvm/**",
        "posthog/**",
        "products/**/backend/**",
        "products/**/migrations/**",
        "products/**/manifest.tsx",
        "requirements*.txt",
        "pyproject.toml",
        "uv.lock",
        "mypy.ini",
        "pytest.ini",
        ".test_durations",
        "frontend/src/queries/schema.json",
        "rust/feature-flags/src/properties/property_models.rs",
        "frontend/src/products.json",
        ".github/workflows/ci-backend.yml",
        ".github/clickhouse-versions.json",
        "docker-compose.dev.yml",
        "docker-compose.profiles.yml",
        "docker-compose.base.yml",
        "bin/wait-for-docker",
        "bin/ci-wait-for-docker",
        "frontend/public/email/**",
        "docker/clickhouse/**",
    ],
    "frontend": [
        "bin/**",
        "frontend/**",
        "ee/frontend/**",
        "common/esbuilder/**",
        "products/**/*.ts",
        "products/**/*.tsx",
        "products/**/frontend/**",
        "common/{esbuilder,mosaic,storybook,tailwind}/**",
        "package.json",
        "pnpm-lock.yaml",
        "tsconfig.json",
        ".github/workflows/ci-frontend.yml",
    ],
    "rust": [
        "rust/**",
        "proto/**",
        ".github/workflows/ci-rust.yml",
    ],
    "nodejs": [
        ".github/workflows/ci-nodejs.yml",
        "nodejs/**",
        "posthog/clickhouse/**",
        "ee/migrations/**",
        "posthog/management/commands/setup_test_environment.py",
        "posthog/migrations/**",
        "posthog/plugins/**",
        "docker*.yml",
        "*Dockerfile",
    ],
    "nodejs_container": [
        "nodejs/**",
        "common/hogvm/typescript/**",
        "common/plugin_transpiler/**",
        "common/esbuilder/**",
        "common/replay-shared/**",
        "package.json",
        "pnpm-lock.yaml",
    ],
    "rust_flags_integration": [
        "rust/feature-flags/**",
        "posthog/api/test/rust_integration/**",
        "posthog/api/feature_flag.py",
        "posthog/api/cohort.py",
        "posthog/models/feature_flag/**",
        "posthog/models/cohort/**",
        ".github/workflows/ci-rust-flags-integration.yml",
    ],
    "e2e_playwright": [
        "ee/**",
        "posthog/**",
        "bin/*",
        "frontend/**",
        "playwright/**",
        "products/**",
        "package.json",
        "pnpm-lock.yaml",
        ".github/workflows/ci-e2e-playwright.yml",
    ],
    "storybook": [
        "frontend/**",
        "products/**/*.ts",
        "products/**/*.tsx",
        "products/**/frontend/**",
        "common/esbuilder/**",
        "common/mosaic/**",
        "common/storybook/**",
        "common/tailwind/**",
        "ee/frontend/**",
    ],
    "mcp": [
        "services/mcp/**",
        "products/**/mcp/**",
        "posthog/**/*.py",
        "ee/**/*.py",
        "common/**/*.py",
    ],
    "mcp_ui_apps": [
        "services/mcp/src/ui-apps/**",
        "services/mcp/src/resources/ui-apps.generated.ts",
        "services/mcp/vite.ui-apps.config.ts",
        "services/mcp/scripts/build-ui-apps.ts",
        "services/mcp/scripts/generate-ui-apps.ts",
    ],
    "dagster": [
        "posthog/dags/**",
        "products/*/dags/**",
        "posthog/clickhouse/**",
        "posthog/models/**",
        "posthog/hogql/**",
    ],
    "hobby": [
        "Dockerfile",
        "docker-compose.base.yml",
        "docker-compose.hobby.yml",
        "bin/deploy-hobby",
        "bin/hobby-ci.py",
    ],
    "hog": [
        "common/hogvm/**",
        "posthog/hogql/**",
        "bin/hog",
        "bin/hoge",
        "package.json",
    ],
    "agent_skills": [
        "products/*/skills/**",
        "products/*/backend/max_tools.py",
        "products/posthog_ai/**",
        ".github/workflows/ci-agent-skills.yml",
    ],
    "phrocs": [
        ".github/workflows/ci-phrocs.yml",
        "tools/phrocs/**",
    ],
    "livestream": [
        ".github/workflows/ci-livestream.yml",
        "livestream/**",
    ],
    "livestream_tui": [
        ".github/workflows/ci-livestream-tui.yml",
        "livestream/**",
    ],
    "llm_gateway": [
        "services/llm-gateway/**",
        ".github/workflows/ci-llm-gateway.yml",
    ],
    "oauth_proxy": [
        "services/oauth-proxy/**",
        ".github/workflows/ci-oauth-proxy.yml",
    ],
    "proto": [
        "proto/**",
        "posthog/personhog_client/proto/generated/**",
        "bin/generate_personhog_proto.sh",
        ".github/workflows/ci-proto.yml",
    ],
    "cli": [
        "cli/**",
        ".github/workflows/ci-cli.yml",
    ],
    "migrations": [
        "posthog/migrations/*.py",
        "posthog/clickhouse/migrations/*.py",
        "products/*/backend/migrations/*.py",
        "ee/migrations/*.py",
        "rust/persons_migrations/*.sql",
        "rust/behavioral_cohorts_migrations/*.sql",
        "rust/cyclotron-core/migrations/*.sql",
    ],
    # Workflows that always run on every PR (no path filter on GHA)
    "always_run": ["**"],
}


def matches(path: str, pattern: str) -> bool:
    """Glob match supporting `**` recursive wildcards."""
    # Convert ** to fnmatch-friendly form: fnmatch supports * but not **.
    # We'll do a simple translation: replace `/**/` with a marker, then use fnmatch.
    if pattern.startswith("!"):
        return False  # negations handled at filter level
    # fnmatch handles ** if we use translate manually
    import re
    regex_parts = []
    i = 0
    while i < len(pattern):
        if pattern[i:i+3] == "**/" or pattern[i:i+3] == "/**":
            regex_parts.append(".*")
            i += 3
        elif pattern[i:i+2] == "**":
            regex_parts.append(".*")
            i += 2
        elif pattern[i] == "*":
            regex_parts.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            regex_parts.append(".")
            i += 1
        elif pattern[i] == ".":
            regex_parts.append(r"\.")
            i += 1
        elif pattern[i] == "{":
            # Handle simple alternation like {a,b,c}
            close = pattern.index("}", i)
            alts = pattern[i+1:close].split(",")
            regex_parts.append("(" + "|".join(re.escape(a) for a in alts) + ")")
            i = close + 1
        else:
            regex_parts.append(re.escape(pattern[i]))
            i += 1
    regex = "^" + "".join(regex_parts) + "$"
    return bool(re.match(regex, path))


def filter_matches(filter_paths, changed_files):
    positives = [p for p in filter_paths if not p.startswith("!")]
    negatives = [p[1:] for p in filter_paths if p.startswith("!")]
    for f in changed_files:
        if any(matches(f, p) for p in positives):
            if not any(matches(f, n) for n in negatives):
                return True
    return False


def main():
    changed_files_path = sys.argv[1]
    force_all = sys.argv[2] == "1"
    with open(changed_files_path) as f:
        changed = [line.strip() for line in f if line.strip()]

    # Map filters to CCI workflow run flags
    if force_all or not changed:
        flags = {k: True for k in (
            "run-posthog-ci", "run-e2e-playwright-ci", "run-storybook-ci",
            "run-mcp-ci", "run-mcp-ui-apps-ci", "run-dagster-ci",
            "run-nodejs-container-ci", "run-rust-flags-integration-ci",
            "run-llm-gateway-ci", "run-hobby-ci", "run-oauth-proxy-ci",
            "run-cli-ci", "run-phrocs-ci", "run-livestream-ci",
            "run-livestream-tui-ci", "run-proto-ci", "run-agent-skills-ci",
            "run-ai-ci", "run-shellcheck-ci", "run-security-ci",
            "run-turbo-ci", "run-test-selection-shadow-ci",
            "run-container-images-ci", "run-migrations-check-ci",
            "run-django", "run-rust", "run-nodejs", "run-frontend",
        )}
    else:
        backend = filter_matches(FILTERS["backend"], changed)
        frontend = filter_matches(FILTERS["frontend"], changed)
        rust = filter_matches(FILTERS["rust"], changed)
        nodejs = filter_matches(FILTERS["nodejs"], changed)
        flags = {
            # Composite posthog-ci workflow (django + rust + nodejs + frontend); run if any segment changed
            "run-posthog-ci": backend or frontend or rust or nodejs,
            # Per-segment job flags (used inside posthog-ci to gate jobs)
            "run-django": backend,
            "run-rust": rust,
            "run-nodejs": nodejs,
            "run-frontend": frontend,
            # Independent workflows
            "run-e2e-playwright-ci": filter_matches(FILTERS["e2e_playwright"], changed),
            "run-storybook-ci": filter_matches(FILTERS["storybook"], changed),
            "run-mcp-ci": filter_matches(FILTERS["mcp"], changed),
            "run-mcp-ui-apps-ci": filter_matches(FILTERS["mcp_ui_apps"], changed),
            "run-dagster-ci": filter_matches(FILTERS["dagster"], changed),
            "run-nodejs-container-ci": filter_matches(FILTERS["nodejs_container"], changed),
            "run-rust-flags-integration-ci": filter_matches(FILTERS["rust_flags_integration"], changed),
            "run-llm-gateway-ci": filter_matches(FILTERS["llm_gateway"], changed),
            "run-hobby-ci": filter_matches(FILTERS["hobby"], changed),
            "run-oauth-proxy-ci": filter_matches(FILTERS["oauth_proxy"], changed),
            "run-cli-ci": filter_matches(FILTERS["cli"], changed),
            "run-phrocs-ci": filter_matches(FILTERS["phrocs"], changed),
            "run-livestream-ci": filter_matches(FILTERS["livestream"], changed),
            "run-livestream-tui-ci": filter_matches(FILTERS["livestream_tui"], changed),
            "run-proto-ci": filter_matches(FILTERS["proto"], changed),
            "run-agent-skills-ci": filter_matches(FILTERS["agent_skills"], changed),
            "run-migrations-check-ci": filter_matches(FILTERS["migrations"], changed),
            # Always-run workflows (no GHA path filter)
            "run-ai-ci": True,
            "run-shellcheck-ci": True,
            "run-security-ci": True,
            "run-turbo-ci": True,
            "run-test-selection-shadow-ci": True,
            "run-container-images-ci": True,
        }

    print(json.dumps(flags, indent=2))


if __name__ == "__main__":
    main()
