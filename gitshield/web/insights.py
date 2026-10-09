"""Explainable PR risk scoring and dependency-update detection (no LLM involved)."""

import math
import re
from typing import Any, Dict, List, Optional

BOT_AUTHORS = {"dependabot[bot]", "dependabot", "renovate[bot]", "renovate"}

# (category, label, points, path pattern) — each category counts once per PR.
SENSITIVE_PATHS = [
    ("auth", "Kimlik doğrulama / güvenlik koduna dokunuyor", 20,
     re.compile(r"(auth|login|passw|token|secret|crypt|permission|session|oauth|jwt|security)", re.I)),
    ("ci", "CI/CD yapılandırmasını değiştiriyor", 15,
     re.compile(r"(^\.github/workflows/|^\.gitlab-ci|Jenkinsfile|^\.circleci/|azure-pipelines)", re.I)),
    ("migration", "Veritabanı migration / şema değişikliği", 15,
     re.compile(r"(migrations?/|\.sql$|schema\.(prisma|rb|graphql)$)", re.I)),
    ("infra", "Altyapı / container yapılandırması", 10,
     re.compile(r"(Dockerfile|docker-compose|\.tf$|terraform/|k8s/|helm/|\.ya?ml\.tpl$)", re.I)),
    ("env", "Ortam / gizli yapılandırma dosyası", 15,
     re.compile(r"(^|/)\.env(\.|$)|(^|/)(secrets?|credentials?)\.", re.I)),
    ("deps", "Bağımlılık manifesti değişiyor", 10,
     re.compile(r"(package\.json|requirements[^/]*\.txt|pyproject\.toml|Pipfile|pubspec\.yaml|go\.mod|"
                r"Cargo\.toml|Gemfile|composer\.json|build\.gradle|pom\.xml)$", re.I)),
]
LOCKFILE = re.compile(r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|uv\.lock|"
                      r"pubspec\.lock|go\.sum|Cargo\.lock|Gemfile\.lock|composer\.lock)$", re.I)
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec|test_)|(_test|\.test|\.spec)\.", re.I)
CODE_EXT = re.compile(r"\.(py|ts|tsx|js|jsx|dart|go|rs|java|kt|rb|php|cs|swift|c|cpp|h)$", re.I)

NEW_AUTHOR = {"FIRST_TIME_CONTRIBUTOR": 15, "FIRST_TIMER": 15, "NONE": 15, "CONTRIBUTOR": 5}

BUMP = re.compile(
    r"bump (?P<pkg>\S+)(?: from (?P<from>v?[\w.\-+]+) to (?P<to>v?[\w.\-+]+))?", re.I)
GROUP_BUMP = re.compile(r"bump the (?P<group>\S+) group", re.I)


def _version_parts(v: str) -> List[int]:
    return [int(x) for x in re.findall(r"\d+", v)[:3]]


def change_type(old: str, new: str) -> str:
    a, b = _version_parts(old), _version_parts(new)
    if not a or not b:
        return "unknown"
    a += [0] * (3 - len(a))
    b += [0] * (3 - len(b))
    # 0.x releases treat the minor version as breaking (semver convention).
    if a[0] != b[0] or (a[0] == 0 and a[1] != b[1]):
        return "major"
    if a[1] != b[1]:
        return "minor"
    return "patch"


def parse_dependency_update(title: str, author: str) -> Optional[Dict[str, Any]]:
    """Detect dependency-bump PRs (Dependabot/Renovate style titles)."""
    group = GROUP_BUMP.search(title)
    if group:
        # Group titles don't state versions; dependabot names groups after the allowed update types.
        name = group.group("group")
        kind = "major" if "major" in name.lower() else (
            "minor" if re.search(r"minor|patch|uyumlu|compatible", name, re.I) else "unknown")
        return {"package": f"{name} (grup)", "from": None, "to": None, "change": kind, "group": True,
                "bot": author in BOT_AUTHORS}
    m = BUMP.search(title)
    if not m or not (author in BOT_AUTHORS or m.group("from")):
        return None
    old, new = m.group("from"), m.group("to")
    return {"package": m.group("pkg"), "from": old, "to": new,
            "change": change_type(old, new) if old and new else "unknown", "group": False,
            "bot": author in BOT_AUTHORS}


def compute_risk(pr: Dict[str, Any], review: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Score 0-100 with the factors that produced it.

    ``pr`` is a GraphQL pull request node: additions, deletions, changedFiles,
    authorAssociation, author.login, title, files.nodes[] (path, additions, deletions)
    and commits.nodes[-1].commit.statusCheckRollup.
    """
    factors: List[Dict[str, Any]] = []

    def add(label: str, points: int) -> None:
        if points > 0:
            factors.append({"label": label, "points": points})

    file_nodes = (pr.get("files") or {}).get("nodes", [])
    files = [f["path"] for f in file_nodes]
    if file_nodes:
        # Generated lockfile churn says nothing about review risk; count hand-written lines only.
        lines = sum((f.get("additions") or 0) + (f.get("deletions") or 0)
                    for f in file_nodes if not LOCKFILE.search(f["path"]))
    else:
        lines = (pr.get("additions") or 0) + (pr.get("deletions") or 0)
    if lines:
        # 10 lines ≈ 9 pts, 100 ≈ 17, 1000+ ≈ 25 — size matters, but with diminishing returns.
        add(f"{lines} satır değişiklik", min(25, round(math.log10(lines + 1) * 8.5)))
    changed = pr.get("changedFiles") or len(files)
    if changed > 20:
        add(f"{changed} dosyaya yayılıyor", 10)

    code_files = [f for f in files if not LOCKFILE.search(f)]
    for category, label, points, pattern in SENSITIVE_PATHS:
        hits = [f for f in code_files if pattern.search(f)]
        if hits:
            add(f"{label} ({hits[0]}{' +' + str(len(hits) - 1) if len(hits) > 1 else ''})", points)
    if files and not code_files:
        add("Yalnızca lock dosyası değişiyor", 3)

    author = (pr.get("author") or {}).get("login", "")
    if author not in BOT_AUTHORS:
        assoc = pr.get("authorAssociation", "")
        if assoc in NEW_AUTHOR:
            add("Yazar repoya yeni katkı veriyor" if NEW_AUTHOR[assoc] > 5 else "Yazar dış katkıcı",
                NEW_AUTHOR[assoc])

    source_changed = sum(1 for f in files if CODE_EXT.search(f) and not TEST_PATH.search(f))
    if source_changed and lines > 50 and not any(TEST_PATH.search(f) for f in files):
        add("Kod değişmiş ama test eklenmemiş", 8)

    dep = parse_dependency_update(pr.get("title", ""), author)
    if dep and dep["change"] == "major":
        add("Major sürüm atlaması (kırıcı değişiklik olabilir)", 15)

    ci = pr_ci_state(pr)
    if ci == "failure":
        add("CI başarısız", 20)

    if review and review.get("status") in ("ready", "submitted"):
        critical, high = review.get("critical_findings", 0), review.get("high_findings", 0)
        if critical:
            add(f"GitShield {critical} kritik bulgu buldu", 25)
        elif high:
            add(f"GitShield {high} yüksek önemli bulgu buldu", 15)

    score = min(100, sum(f["points"] for f in factors))
    level = "high" if score >= 55 else "medium" if score >= 25 else "low"
    factors.sort(key=lambda f: -f["points"])
    return {"score": score, "level": level, "factors": factors}


def pr_ci_state(pr: Dict[str, Any]) -> str:
    commits = (pr.get("commits") or {}).get("nodes") or []
    rollup = (commits[-1]["commit"].get("statusCheckRollup") or {}).get("state") if commits else None
    return ci_state(rollup)


def ci_state(rollup: Optional[str]) -> str:
    """Map GitHub's statusCheckRollup state to success / failure / pending / none."""
    return {"SUCCESS": "success", "FAILURE": "failure", "ERROR": "failure",
            "PENDING": "pending", "EXPECTED": "pending"}.get(rollup or "", "none")


def pr_insights(node: Optional[Dict[str, Any]], review: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Risk, CI state and dependency info for one PR; empty values when GitHub returned no detail."""
    if not node:
        return {"risk": None, "ci": "none", "dependency": None}
    return {
        "risk": compute_risk(node, review),
        "ci": pr_ci_state(node),
        "dependency": parse_dependency_update(node.get("title", ""), (node.get("author") or {}).get("login", "")),
    }
