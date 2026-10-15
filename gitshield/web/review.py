"""PR review pipeline: GitShield scan -> LLM review -> LLM verification -> draft issues."""

import logging
from pathlib import Path
from typing import Any

from gitshield.core.models import RuleType
from gitshield.core.scanner import Scanner
from gitshield.web.config import settings
from gitshield.web.db import Database, now
from gitshield.web.github import GitHubClient, GitHubError
from gitshield.web.llm import LLMProvider, LLMUnavailable
from gitshield.web.notify import notify_review
from gitshield.web.review_diff import (  # noqa: E402, F401
    HUNK_FULL,
    HUNK_HEADER,
    annotate_patch,
    build_diff,
    map_old_line,
)
from gitshield.web.review_followups import (  # noqa: E402, F401
    check_followups,
    find_previous_review,
)
from gitshield.web.review_format import (  # noqa: E402, F401
    draft_issue_body,
    format_comment_markdown,
)
from gitshield.web.review_memory import (  # noqa: E402, F401
    _norm,
    fingerprint,
    memory_prompt,
    suppressing_memory,
)
from gitshield.web.review_progress import (  # noqa: E402, F401
    STEPS,
    Progress,
    initial_progress,
)

# Re-exports: these names used to live in this module.
from gitshield.web.review_schemas import (  # noqa: E402, F401
    FOLLOWUP_SYSTEM,
    ISSUE_SEVERITIES,
    REVIEW_SYSTEM,
    SEVERITY_ICON,
    VERIFY_SYSTEM,
    FollowupItem,
    FollowupOutput,
    LLMComment,
    ReviewOutput,
    Severity,
    Verdict,
    VerificationItem,
    VerificationOutput,
)

log = logging.getLogger(__name__)


# ---- Pipeline ---------------------------------------------------------------------


def begin_review(db: Database, pr: dict[str, Any], full_name: str,
                 provider: LLMProvider | None, origin: str = "manual") -> int:
    """Create the review row (status running) with an all-pending progress template.

    ``origin`` records who started it: manual (the user), auto (the watcher) or batch
    (dependency batch approval)."""
    review_id = db.create_review(
        full_name, pr["number"], pr["title"], pr["head"]["sha"],
        provider.name if provider else "none", provider.model if provider else "",
    )
    db.update_review(review_id, progress=initial_progress(), origin=origin)
    return review_id


async def run_review(db: Database, gh: GitHubClient, provider: LLMProvider | None,
                     review_id: int, owner: str, repo: str, number: int,
                     force_full: bool = False, notify: bool = True) -> None:
    full_name = f"{owner}/{repo}"
    progress = Progress(db, review_id)
    try:
        progress.start("fetch", "PR ve diff GitHub'dan alınıyor")
        pr = await gh.get_pull(owner, repo, number)
        files = await gh.list_pull_files(owner, repo, number)
        raw_diff, annotated, commentable, skipped = build_diff(files, settings.max_diff_chars)
        fetch_detail = f"{len(files)} dosya · +{pr.get('additions', 0)} −{pr.get('deletions', 0)}"

        # Incremental mode: review only what changed since the last reviewed commit.
        previous = None if force_full else find_previous_review(
            db, full_name, number, review_id, pr["head"]["sha"])
        delta_files: list[dict[str, Any]] | None = None
        commits = 0
        if previous:
            try:
                cmp = await gh.compare(owner, repo, previous["head_sha"], pr["head"]["sha"])
                # A force-push/rebase makes history diverge; fall back to a full review then.
                if cmp.get("status") == "ahead":
                    delta_files = cmp.get("files", [])
                    commits = len(cmp.get("commits", []))
            except GitHubError:
                delta_files = None
        if previous and delta_files is not None:
            raw_diff, annotated, _, skipped = build_diff(delta_files, settings.max_diff_chars)
            db.update_review(review_id, mode="incremental", base_sha=previous["head_sha"])
            fetch_detail = (f"Artımlı: {previous['head_sha'][:7]} → {pr['head']['sha'][:7]} · "
                            f"{commits} yeni commit · {len(delta_files)} dosya")
        else:
            previous = None
        progress.done("fetch", fetch_detail)
        memory = db.list_memory(full_name, active_only=True)
        memory_text = memory_prompt(memory)

        progress.start("scan", "Kural motoru ve entropi analizi çalışıyor")
        report = Scanner().scan_diff(Path("."), raw_diff=raw_diff)
        progress.done("scan", f"{report.scanned_lines_count} eklenen satır · {len(report.findings)} bulgu")

        # Never send detected secrets to the LLM or store them in plain text.
        secrets = [f.matched_text for f in report.findings
                   if f.rule_type in (RuleType.SECRET, RuleType.ENTROPY) and len(f.matched_text) >= 6]
        for secret in secrets:
            annotated = annotated.replace(secret, "<REDACTED_SECRET>")

        candidates: list[dict[str, Any]] = []
        for finding in report.findings:
            context = finding.context or ""
            for secret in secrets:
                context = context.replace(secret, "<REDACTED_SECRET>")
            body = finding.description
            if finding.cwe:
                body += f" ({finding.cwe})"
            if context:
                body += f"\n\n```\n{context}\n```"
            candidates.append({
                "source": "scanner", "path": finding.file_path, "line": finding.line_number,
                "severity": finding.severity.value,
                "category": "security", "title": finding.title, "body": body,
                "suggestion": finding.suggested_fix or "", "rule_id": finding.rule_id,
            })

        summary = ""
        verdict = "COMMENT"
        recommended: str | None = None
        verifier_notes = ""

        if provider:
            progress.start("ai_review", f"{provider.model} diff'i okuyor")
            scanner_lines = "\n".join(
                f"- [{c['severity']}] {c['rule_id']} {c['path']}:{c['line']} {c['title']}"
                for c in candidates
            ) or "(none)"
            skipped_lines = "\n".join(f"- {s['path']}: {s['reason']}" for s in skipped) or "(none)"
            scope = ("This is an incremental review: the diff contains only the commits pushed since "
                     "the last reviewed commit. Review those changes.\n\n" if previous else "")
            review_prompt = (
                f"{scope}{memory_text}Repository: {full_name}\nPull request #{number}: {pr['title']}\n\n"
                f"<pr_description>\n{pr.get('body') or '(empty)'}\n</pr_description>\n\n"
                f"<scanner_findings>\n{scanner_lines}\n</scanner_findings>\n\n"
                f"<files_not_included>\n{skipped_lines}\n</files_not_included>\n\n"
                f"<diff>\n{annotated}\n</diff>"
            )
            review = await provider.complete(
                REVIEW_SYSTEM.format(language=settings.review_language), review_prompt, ReviewOutput
            )
            summary, verdict = review.summary, review.verdict
            for llm_comment in review.comments:
                candidates.append({
                    "source": "llm", "path": llm_comment.path, "line": llm_comment.line,
                    "severity": llm_comment.severity, "category": llm_comment.category,
                    "title": llm_comment.title, "body": llm_comment.body,
                    "suggestion": llm_comment.suggestion, "rule_id": None,
                })
            progress.done("ai_review", f"{provider.model} · {len(review.comments)} yorum"
                                       + (f" · hafızada {len(memory)} kayıt" if memory else ""))
        else:
            progress.skip("ai_review", "LLM yapılandırılmadı; yalnızca statik analiz")

        # Deterministic verification: the comment must point at a line GitHub can anchor to.
        for c in candidates:
            c["in_diff"] = c["line"] in commentable.get(c["path"], set())
            c["verification"] = "unverified"
            c["verification_note"] = ""
            if c["path"] not in commentable:
                c["verification"] = "rejected"
                c["verification_note"] = "Dosya bu PR'ın diff'inde yok."

        # Repo memory: items the maintainers dismissed are rejected before anything else sees them.
        suppressed_ids = []
        for c in candidates:
            m = suppressing_memory(c, memory)
            if m:
                c["verification"] = "rejected"
                c["verification_note"] = f"Repo hafızası: daha önce susturuldu (#{m['id']})."
                c["suppressed"] = True
                suppressed_ids.append(m["id"])
        db.bump_memory_hits(suppressed_ids)
        to_verify = [c for c in candidates if not c.get("suppressed")]

        if provider and to_verify:
            progress.start("verify", f"{len(to_verify)} yorum diff'e karşı kontrol ediliyor")
            numbered = "\n\n".join(
                f"[{i}] ({c['source']}) {c['path']}:{c['line']} [{c['severity']}/{c['category']}] "
                f"{c['title']}\n{c['body']}"
                + (f"\nSuggestion:\n{c['suggestion']}" if c["suggestion"] else "")
                for i, c in enumerate(to_verify)
            )
            verify_prompt = (
                f"{memory_text}Pull request #{number}: {pr['title']}\n\n"
                f"<comments>\n{numbered}\n</comments>\n\n<diff>\n{annotated}\n</diff>"
            )
            try:
                verification = await provider.complete(
                    VERIFY_SYSTEM.format(language=settings.review_language), verify_prompt,
                    VerificationOutput,
                )
            except LLMUnavailable as e:
                # The review itself took minutes; a verifier outage must not throw it away. The
                # comments reach the maintainer marked unverified, and nothing is sent without approval.
                log.warning("Review %s: verifier unavailable, keeping unverified comments: %s", review_id, e)
                verification = None
                verifier_notes = f"Doğrulayıcıya ulaşılamadı ({e}); yorumlar doğrulanmadan listelendi."
                progress.skip("verify", "Doğrulayıcıya ulaşılamadı; yorumlar doğrulanmadan onayına geldi")
            if verification is not None:
                recommended = verification.recommended_verdict
                verifier_notes = verification.notes
                for item in verification.items:
                    if 0 <= item.index < len(to_verify):
                        c = to_verify[item.index]
                        if c["verification"] != "rejected":
                            c["verification"] = item.status
                            c["verification_note"] = item.reason
                counts = {k: sum(1 for c in candidates if c["verification"] == k)
                          for k in ("confirmed", "uncertain", "rejected")}
                progress.done("verify", f"{counts['confirmed']} doğrulandı · {counts['uncertain']} belirsiz · "
                                        f"{counts['rejected']} reddedildi")
        elif not to_verify:
            progress.skip("verify", "Doğrulanacak yorum yok")
        else:
            progress.skip("verify", "LLM yok; yalnızca satır konumu kontrol edildi")

        if suppressed_ids:
            progress.append("verify", f"hafıza {len(suppressed_ids)} yorumu susturdu")

        followups: list[dict[str, Any]] = []
        if previous:
            followups = await check_followups(provider, previous, delta_files or [])
            open_items = [f for f in followups if f["status"] != "fixed"]
            # Comments of a review that never reached GitHub would be lost; carry the open ones over.
            if previous["status"] != "submitted":
                for f in open_items:
                    c = f["prev"]
                    if f["new_line"] is None:
                        continue
                    candidates.append({
                        "source": "carried", "path": c["path"], "line": f["new_line"],
                        "severity": c["severity"], "category": c["category"], "title": c["title"],
                        "body": c["body"], "suggestion": c["suggestion"] or "", "rule_id": c["rule_id"],
                        "in_diff": f["new_line"] in commentable.get(c["path"], set()),
                        "verification": c["verification"],
                        "verification_note": f"Önceki review'dan taşındı: {f['note']}",
                    })
            fixed = len(followups) - len(open_items)
            progress.append("verify", f"önceki {len(followups)} yorumdan {fixed} düzeltildi")

        if not provider:
            summary = (
                f"GitShield taraması {report.scanned_files_count} dosyada "
                f"{report.scanned_lines_count} eklenen satırı inceledi ve "
                f"{len(report.findings)} bulgu üretti. (LLM yapılandırılmadığı için yalnızca "
                "statik analiz sonuçları gösteriliyor.)"
            )
            verdict = "REQUEST_CHANGES" if report.has_high else "COMMENT"

        html_base = pr["head"]["repo"]["html_url"] if pr["head"].get("repo") else pr["base"]["repo"]["html_url"]
        drafts_created = 0
        for c in candidates:
            comment_id = db.add_comment(
                review_id, source=c["source"], path=c["path"], line=c["line"],
                in_diff=c["in_diff"], severity=c["severity"], category=c["category"],
                title=c["title"], body=c["body"], suggestion=c["suggestion"] or None,
                rule_id=c["rule_id"], verification=c["verification"],
                verification_note=c["verification_note"],
                included=c["verification"] != "rejected",
            )
            issue_worthy = c["verification"] == "confirmed" or (
                not provider and c["verification"] == "unverified"
            )
            if issue_worthy and c["severity"] in ISSUE_SEVERITIES:
                drafts_created += db.add_draft_issue(
                    full_name, review_id, comment_id,
                    fingerprint(c["path"], c["rule_id"] or c["title"]),
                    title=f"[{c['severity']}] {c['title']}",
                    body=draft_issue_body(c, pr, html_base),
                    severity=c["severity"],
                ) is not None

        for f in followups:
            db.add_followup(review_id, prev_comment_id=f["prev"]["id"], path=f["path"],
                            old_line=f["old_line"], new_line=f["new_line"], severity=f["severity"],
                            title=f["title"], status=f["status"], note=f["note"])

        included = sum(1 for c in candidates if c["verification"] != "rejected")
        progress.start("approve", f"{included} yorum gönderime hazır; gözden geçirip onayla")
        db.update_review(
            review_id, status="ready", summary=summary, verdict=verdict,
            recommended_verdict=recommended, verifier_notes=verifier_notes,
            skipped_files=skipped,
            stats={
                "files": len(files), "scanned_lines": report.scanned_lines_count,
                "scanner_findings": len(report.findings),
                "llm_comments": sum(1 for c in candidates if c["source"] == "llm"),
                "confirmed": sum(1 for c in candidates if c["verification"] == "confirmed"),
                "rejected": sum(1 for c in candidates if c["verification"] == "rejected"),
                "uncertain": sum(1 for c in candidates if c["verification"] == "uncertain"),
                "drafts_created": drafts_created,
            },
        )
    except Exception as e:  # surfaced to the UI; the review row records the failure
        log.exception("Review %s failed", review_id)
        message = str(e) or e.__class__.__name__
        progress.fail_running(message)
        db.update_review(review_id, status="failed", error=message)
    if notify:
        saved = db.get_review(review_id)
        if saved:
            await notify_review(saved)


# ---- Submission -----------------------------------------------------------------


async def submit_review(db: Database, gh: GitHubClient, review: dict[str, Any],
                        event: str | None = None) -> dict[str, Any]:
    owner, repo = review["repo"].split("/", 1)
    included = [c for c in review["comments"] if c["included"]]
    inline = [c for c in included if c["in_diff"]]
    general = [c for c in included if not c["in_diff"]]

    body = f"## 🛡️ GitShield Review\n\n{review['summary']}\n"
    followups = review.get("followups") or []
    if followups:
        icon = {"fixed": "✅", "still_open": "⏳", "unclear": "❔"}
        counts = {k: sum(1 for f in followups if f["status"] == k) for k in icon}
        body += (f"\n### Önceki review'a göre\n\n✅ {counts['fixed']} düzeltildi · "
                 f"⏳ {counts['still_open']} hâlâ açık · ❔ {counts['unclear']} belirsiz\n\n")
        body += "\n".join(f"- {icon[f['status']]} `{f['path']}:{f['new_line'] or f['old_line']}` {f['title']}"
                          for f in followups[:15]) + "\n"
    if general:
        body += "\n### Diff dışı bulgular\n\n" + "\n\n".join(
            f"- `{c['path']}:{c['line']}` — {format_comment_markdown(c)}" for c in general
        )
    body += (
        f"\n\n---\n<sub>GitShield · {review['provider']} {review['model']} · "
        f"{len(included)} yorum, "
        + ("statik taramayla kontrol edildi" if review["provider"] == "none" else "ikinci geçişte doğrulandı")
        + " ve insan onayıyla gönderildi.</sub>"
    )
    comments = [
        {"path": c["path"], "line": c["line"], "side": "RIGHT", "body": format_comment_markdown(c)}
        for c in inline
    ]
    event = event or review["verdict"]

    try:
        result = await gh.create_review(owner, repo, review["pr_number"], review["head_sha"],
                                        body, event, comments)
    except GitHubError as e:
        # GitHub forbids approving / requesting changes on your own PR; fall back to a comment.
        if e.status_code == 422 and event != "COMMENT" and "own pull request" in e.message:
            result = await gh.create_review(owner, repo, review["pr_number"], review["head_sha"],
                                            body, "COMMENT", comments)
        else:
            raise

    progress = Progress(db, review["id"], review.get("progress"))
    verdict_tr = {"APPROVE": "Onay", "REQUEST_CHANGES": "Değişiklik iste", "COMMENT": "Yorum"}.get(event, event)
    progress.done("approve", f"{len(included)} / {len(review['comments'])} yorum onaylandı"
                  if review["comments"] else "Yorumsuz onaylandı")
    progress.done("submit", f"Karar: {verdict_tr}" + (f" · {len(inline)} satır içi · {len(general)} özette"
                                                      if included else ""))
    db.update_review(review["id"], status="submitted", submitted_at=now(),
                     github_review_url=result.get("html_url"))
    return result


def comment_to_issue(db: Database, comment: dict[str, Any], review: dict[str, Any],
                     pr: dict[str, Any]) -> int | None:
    html_base = pr["head"]["repo"]["html_url"] if pr["head"].get("repo") else pr["base"]["repo"]["html_url"]
    return db.add_draft_issue(
        review["repo"], review["id"], comment["id"],
        fingerprint(comment["path"], comment["rule_id"] or comment["title"]),
        title=f"[{comment['severity']}] {comment['title']}",
        body=draft_issue_body(comment, pr, html_base),
        severity=comment["severity"],
    )
