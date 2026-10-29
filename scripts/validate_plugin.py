"""Validate the Claude plugin manifests, MCP config, and skill frontmatter.

The checks are structural. They do not read README.md, so wording edits
there do not fail this script. `claude plugin validate` checks the manifests
against Claude Code's own schema; this script adds the Pokit Note rules on
top, such as the production server URL.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]

# Fields from the Claude Code plugin and marketplace references. Anything else
# is flagged so a typo or a leftover Cursor field (displayName, logo,
# variables) does not slip through.
PLUGIN_KEYS = {
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "privacyPolicyUrl",
    "displayName",
    "icon",
    "commands",
    "agents",
    "skills",
    "hooks",
    "mcpServers",
    "lspServers",
    "outputStyles",
    "userConfig",
}
PATH_FIELDS = ("commands", "agents", "skills", "hooks", "mcpServers", "lspServers", "outputStyles")
MARKETPLACE_KEYS = {"$schema", "name", "description", "owner", "metadata", "plugins"}
PLUGIN_ENTRY_KEYS = {
    "name",
    "source",
    "description",
    "version",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "category",
    "tags",
    "strict",
}
MCP_SERVER_KEYS = {"type", "url", "oauth"}
OAUTH_KEYS = {"scopes"}
KEBAB = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?$"
)
SECRET_KEYS = {
    "client_secret",
    "clientsecret",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "password",
    "secret",
    "token",
    "authorization",
}
PRODUCTION_HOST = "pokitnote.com"
PRODUCTION_MCP_URL = "https://pokitnote.com/mcp"
# ${VAR} or ${VAR:-default}. A bare ${VAR} with no default fails to load when
# the variable is unset, so the server URL must always carry a default.
PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def finish(self) -> None:
        if self.errors:
            for message in self.errors:
                print(f"error: {message}", file=sys.stderr)
            raise SystemExit(1)
        print("Plugin manifests, MCP config, and skill frontmatter are valid.")


def load_json(path: Path, report: Report) -> object | None:
    display = path.relative_to(ROOT).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        report.error(f"{display}: {exc.strerror}")
        return None

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        parsed: dict[str, object] = {}
        for key, value in items:
            if key in parsed:
                report.error(f"{display}: duplicate key {key!r}")
            parsed[key] = value
        return parsed

    try:
        return json.loads(text, object_pairs_hook=pairs)
    except json.JSONDecodeError as exc:
        report.error(f"{display}: {exc.msg} (line {exc.lineno})")
        return None


def require_object(value: object, label: str, report: Report) -> dict[str, object] | None:
    if not isinstance(value, dict):
        report.error(f"{label}: expected a JSON object")
        return None
    return value


def unknown_keys(data: dict[str, object], allowed: set[str], label: str, report: Report) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        report.error(f"{label}: unknown fields {', '.join(extra)}")


def safe_relative(value: object, label: str, report: Report) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        report.error(f"{label}: expected a non-empty path")
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        report.error(f"{label}: path must stay inside the repository ({value})")
        return None
    located = (ROOT / path).resolve()
    root = ROOT.resolve()
    if located != root and root not in located.parents:
        report.error(f"{label}: path must stay inside the repository ({value})")
        return None
    if not located.exists():
        report.error(f"{label}: {value} does not exist")
        return None
    return located


def check_name(value: object, label: str, report: Report, pattern: re.Pattern[str] = KEBAB) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        report.error(f"{label}: expected a lowercase kebab-case name")


def check_https_url(value: object, label: str, report: Report) -> None:
    if not isinstance(value, str):
        report.error(f"{label}: expected a string")
        return
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        report.error(f"{label}: expected an https URL")


def check_author(value: object, label: str, report: Report) -> None:
    author = require_object(value, label, report)
    if author is None:
        return
    unknown_keys(author, {"name", "email", "url"}, label, report)
    if not isinstance(author.get("name"), str) or not author["name"].strip():
        report.error(f"{label}: missing required field name")


def validate_plugin(report: Report) -> dict[str, object] | None:
    label = ".claude-plugin/plugin.json"
    data = require_object(load_json(ROOT / ".claude-plugin" / "plugin.json", report), label, report)
    if data is None:
        return None
    unknown_keys(data, PLUGIN_KEYS, label, report)
    if "name" not in data:
        report.error(f"{label}: missing required field name")
    else:
        check_name(data["name"], f"{label} name", report)
    version = data.get("version")
    if version is not None and (not isinstance(version, str) or SEMVER.fullmatch(version) is None):
        report.error(f"{label} version: expected semantic version X.Y.Z")
    if "author" in data:
        check_author(data["author"], f"{label} author", report)
    for field in ("homepage", "repository", "privacyPolicyUrl"):
        if field in data:
            check_https_url(data[field], f"{label} {field}", report)
    if "keywords" in data:
        keywords = data["keywords"]
        if not isinstance(keywords, list) or not all(isinstance(item, str) and item for item in keywords):
            report.error(f"{label} keywords: expected an array of strings")
    for field in PATH_FIELDS:
        value = data.get(field)
        if value is None or isinstance(value, dict):
            continue
        values = value if isinstance(value, list) else [value]
        for index, item in enumerate(values):
            item_label = f"{label} {field}" if not isinstance(value, list) else f"{label} {field}[{index}]"
            safe_relative(item, item_label, report)
    return data


def validate_marketplace(report: Report) -> None:
    label = ".claude-plugin/marketplace.json"
    data = require_object(load_json(ROOT / ".claude-plugin" / "marketplace.json", report), label, report)
    if data is None:
        return
    unknown_keys(data, MARKETPLACE_KEYS, label, report)
    for field in ("name", "owner", "plugins"):
        if field not in data:
            report.error(f"{label}: missing required field {field}")
    if "name" in data:
        check_name(data["name"], f"{label} name", report)
    if "owner" in data:
        check_author(data["owner"], f"{label} owner", report)
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        return
    if not plugins:
        report.error(f"{label}: plugins must list at least one plugin")
        return
    seen: set[str] = set()
    for index, entry in enumerate(plugins):
        entry_label = f"{label} plugins[{index}]"
        entry_object = require_object(entry, entry_label, report)
        if entry_object is None:
            continue
        unknown_keys(entry_object, PLUGIN_ENTRY_KEYS, entry_label, report)
        for field in ("name", "source"):
            if field not in entry_object:
                report.error(f"{entry_label}: missing required field {field}")
        name = entry_object.get("name")
        if "name" in entry_object:
            check_name(name, f"{entry_label} name", report)
            if isinstance(name, str):
                if name in seen:
                    report.error(f"{entry_label}: duplicate plugin name {name}")
                seen.add(name)
        source = entry_object.get("source")
        if not isinstance(source, str):
            continue
        located = safe_relative(source, f"{entry_label} source", report)
        if located is None:
            continue
        manifest = located / ".claude-plugin" / "plugin.json"
        if not manifest.is_file():
            report.error(f"{entry_label}: {source} has no .claude-plugin/plugin.json")
            continue
        manifest_data = load_json(manifest, report)
        manifest_name = manifest_data.get("name") if isinstance(manifest_data, dict) else None
        if isinstance(name, str) and manifest_name != name:
            display = manifest.relative_to(ROOT).as_posix()
            report.error(f"{entry_label}: name {name!r} does not match {display} name {manifest_name!r}")


def production_url_problem(value: str) -> str | None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != PRODUCTION_HOST:
        return (
            f"server URL must be https://{PRODUCTION_HOST} "
            f"(api.{PRODUCTION_HOST} and stage.{PRODUCTION_HOST} are not the production default)"
        )
    if parsed.port not in {None, 443} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return "server URL must not include a port, user, query, or fragment"
    if parsed.path != "/mcp" or value.endswith("/"):
        return f"server URL must be {PRODUCTION_MCP_URL} with no trailing slash"
    return None


def resolved_mcp_url_problem(value: object) -> str | None:
    """Reject a server URL whose default is not production.

    A literal URL has to be the production MCP URL. A placeholder must be
    ``${VAR:-default}``, and substituting every default has to produce
    ``https://pokitnote.com/mcp`` with no trailing slash, so people who never
    set the variable get production. A trailing slash breaks sign-in.
    """
    if not isinstance(value, str) or not value.strip():
        return "expected a URL"
    problems: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        if default is None:
            problems.append(
                f"${{{name}}} needs a default, written ${{{name}:-{PRODUCTION_MCP_URL}}}, "
                "so the connector loads when the variable is unset"
            )
            return ""
        return default

    resolved = PLACEHOLDER.sub(substitute, value)
    if problems:
        return "; ".join(problems)
    if "${" in resolved or "$" in resolved:
        return "server URL has a placeholder this check cannot read"
    if resolved != PRODUCTION_MCP_URL:
        host_problem = production_url_problem(resolved)
        if host_problem:
            return host_problem
        return f"with defaults applied, the server URL must be {PRODUCTION_MCP_URL}"
    return None


def reject_secrets(value: object, label: str, report: Report) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in SECRET_KEYS:
                report.error(f"{label}: {key} does not belong in the plugin config")
            reject_secrets(item, f"{label}.{key}", report)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_secrets(item, f"{label}[{index}]", report)


def validate_mcp(report: Report) -> None:
    label = ".mcp.json"
    data = require_object(load_json(ROOT / ".mcp.json", report), label, report)
    if data is None:
        return
    if not data:
        report.error(f"{label}: expected at least one server")
        return
    if "mcpServers" in data:
        report.error(f"{label}: list servers at the top level, as Claude Code plugins do, not under mcpServers")
        return
    for name, server in data.items():
        server_label = f"{label} {name}"
        server_object = require_object(server, server_label, report)
        if server_object is None:
            continue
        unknown_keys(server_object, MCP_SERVER_KEYS, server_label, report)
        if server_object.get("type") != "http":
            report.error(f"{server_label}: type must be http")
        if "url" not in server_object:
            report.error(f"{server_label}: missing required field url")
        else:
            problem = resolved_mcp_url_problem(server_object["url"])
            if problem:
                report.error(f"{server_label} url: {problem}")
        oauth = server_object.get("oauth")
        if oauth is not None:
            oauth_object = require_object(oauth, f"{server_label} oauth", report)
            if oauth_object is not None:
                # Claude registers its own client (CIMD or DCR); a fixed
                # client id such as Cursor's grok-bot would not have Claude's
                # redirect URIs.
                unknown_keys(oauth_object, OAUTH_KEYS, f"{server_label} oauth", report)
                scopes = oauth_object.get("scopes")
                if not isinstance(scopes, str) or not scopes.strip():
                    report.error(f"{server_label} oauth scopes: expected a space-separated string")
        reject_secrets(server_object, server_label, report)


def parse_frontmatter(path: Path, report: Report) -> dict[str, str] | None:
    display = path.relative_to(ROOT).as_posix()
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        report.error(f"{display}: missing frontmatter")
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        report.error(f"{display}: frontmatter is not closed")
        return None
    fields: dict[str, str] = {}
    current: str | None = None
    for line_number, line in enumerate(text[4:end].split("\n"), start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] not in " \t":
            if ":" not in line:
                report.error(f"{display}:{line_number}: expected 'key: value'")
                current = None
                continue
            key, raw_value = line.split(":", 1)
            key = key.strip()
            value = raw_value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            if value in {">", "|", ">-", "|-", ">+", "|+"}:
                value = ""
            if key in fields:
                report.error(f"{display}: duplicate frontmatter field {key}")
            fields[key] = value
            current = key
            continue
        if current is None:
            report.error(f"{display}:{line_number}: continuation without a field")
            continue
        extra = line.strip()
        fields[current] = f"{fields[current]} {extra}".strip() if fields[current] else extra
    return fields


def validate_skills(report: Report) -> None:
    skill_files = sorted(path for path in (ROOT / "skills").rglob("SKILL.md") if path.is_file())
    if not skill_files:
        report.error("skills: expected at least one skills/*/SKILL.md")
        return
    for path in skill_files:
        display = path.relative_to(ROOT).as_posix()
        fields = parse_frontmatter(path, report)
        if fields is None:
            continue
        name = fields.get("name", "")
        description = fields.get("description", "")
        if "name" not in fields:
            report.error(f"{display}: missing frontmatter field name")
        elif SKILL_NAME.fullmatch(name) is None:
            report.error(f"{display}: name must be lowercase kebab-case")
        elif name != path.parent.name:
            report.error(f"{display}: name {name!r} must match directory {path.parent.name!r}")
        if "description" not in fields:
            report.error(f"{display}: missing frontmatter field description")
        elif not description.strip():
            report.error(f"{display}: description must not be empty")


def validate_commands(report: Report) -> None:
    for path in sorted((ROOT / "commands").glob("*.md")):
        display = path.relative_to(ROOT).as_posix()
        fields = parse_frontmatter(path, report)
        if fields is None:
            continue
        if not fields.get("description", "").strip():
            report.error(f"{display}: missing frontmatter field description")


def main() -> None:
    report = Report()
    if (ROOT / ".cursor-plugin").exists() or (ROOT / "mcp.json").exists():
        report.error(".cursor-plugin/ and mcp.json are Cursor files; this repository ships the Claude plugin")
    validate_plugin(report)
    validate_marketplace(report)
    validate_mcp(report)
    validate_skills(report)
    validate_commands(report)
    report.finish()


if __name__ == "__main__":
    main()
