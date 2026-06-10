"""KB build report — scans marker files and prints a human-readable summary.

Called automatically at the end of knowledge_acquisition.py.
Output: console + {kb_path}/report/kb_report.md (latest) + kb_report_{timestamp}.md (archive).
"""

import os
import json
import time


def generate(kb_path):
    """Scan the KB and emit a build report to console, kb_report.md, and
    a timestamped copy."""
    r = _scan(kb_path)
    ts = time.strftime("%Y%m%d_%H%M%S")
    md = _format_markdown(r, ts)
    print(md)

    report_dir = os.path.join(kb_path, "report")
    os.makedirs(report_dir, exist_ok=True)

    # Latest report (overwritten each run)
    report_path = os.path.join(report_dir, "kb_report.md")
    with open(report_path, "w") as f:
        f.write(md)

    # Timestamped archive
    archive_path = os.path.join(report_dir, f"kb_report_{ts}.md")
    with open(archive_path, "w") as f:
        f.write(md)

    return r


def _scan(kb_path):
    libs_dir = os.path.join(kb_path, "libraries")
    api_dir = os.path.join(kb_path, "library_api")
    cmap_path = os.path.join(kb_path, "call_module_map.json")

    cmap = {}
    if os.path.exists(cmap_path):
        try:
            with open(cmap_path) as f:
                cmap = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    total = ok = skipped = failed = 0
    by_library = {}
    issues = []

    if not os.path.isdir(libs_dir):
        return {"total": 0, "ok": 0, "skipped": 0, "failed": 0,
                "by_library": {}, "issues": []}

    for lib in sorted(os.listdir(libs_dir)):
        lib_dir = os.path.join(libs_dir, lib)
        if not os.path.isdir(lib_dir):
            continue

        lib_ok = lib_skipped = lib_failed = 0
        lib_issues = []

        for ver_dir_name in sorted(os.listdir(lib_dir)):
            ver_path = os.path.join(lib_dir, ver_dir_name)
            if not os.path.isdir(ver_path):
                continue

            # Extract version from directory name: {lib}{version}
            ver = ver_dir_name[len(lib):] if ver_dir_name.startswith(lib) else ver_dir_name
            total += 1

            call_module_file = os.path.join(ver_path, ".call_module")
            call_module_failed = os.path.join(ver_path, ".call_module_failed")
            no_source = os.path.join(ver_path, ".no_source")

            # Check API JSON
            json_path = os.path.join(api_dir, lib, f"{ver}.json")
            json_failed = json_path + ".failed"

            if os.path.exists(call_module_file):
                if os.path.exists(json_path):
                    lib_ok += 1
                    ok += 1
                else:
                    # call_module OK but API JSON missing — extraction may not have run yet
                    lib_ok += 1
                    ok += 1
            elif os.path.exists(no_source):
                lib_skipped += 1
                skipped += 1
            elif os.path.exists(call_module_failed):
                lib_failed += 1
                failed += 1
                # Diagnose
                fix = _diagnose_failure(lib, cmap)
                lib_issues.append({"library": lib, "version": ver,
                                   "status": "identification_failed",
                                   "reason": "call_module not identified",
                                   "fix": fix})
            elif os.path.exists(json_failed):
                lib_failed += 1
                failed += 1
                fix = _diagnose_failure(lib, cmap)
                lib_issues.append({"library": lib, "version": ver,
                                   "status": "empty_extraction",
                                   "reason": "API extraction produced empty modules",
                                   "fix": fix})
            elif os.path.exists(json_path):
                lib_ok += 1
                ok += 1
            else:
                # No markers at all — download likely failed or not attempted
                artifacts = [f for f in os.listdir(ver_path)
                            if f.endswith(('.tar.gz', '.zip', '.whl'))]
                if artifacts:
                    lib_failed += 1
                    failed += 1
                    lib_issues.append({"library": lib, "version": ver,
                                       "status": "unexpected_state",
                                       "reason": "archive saved but no markers",
                                       "fix": "delete directory and re-download"})
                else:
                    lib_failed += 1
                    failed += 1
                    lib_issues.append({"library": lib, "version": ver,
                                       "status": "download_failed",
                                       "reason": "no archive or markers",
                                       "fix": "delete empty directory and re-download"})

        if lib_issues:
            by_library[lib] = {
                "total": lib_ok + lib_skipped + lib_failed,
                "ok": lib_ok, "skipped": lib_skipped, "failed": lib_failed,
                "issues": lib_issues,
            }
            issues.extend(lib_issues)

    return {
        "total": total, "ok": ok, "skipped": skipped, "failed": failed,
        "by_library": by_library, "issues": issues,
    }


def _diagnose_failure(lib, cmap):
    """Suggest a fix based on what we know."""
    from utils.util import _lookup_call_module, HARDCODED_MODULE_MAP

    known_module = _lookup_call_module(lib)
    if known_module != lib:
        if lib in cmap:
            entry = cmap[lib]
            if not entry.get("_auto", False):
                return f"manual mapping: {lib} → {entry['module']}"
            else:
                return f"auto mapping exists: {lib} → {entry['module']} (may be wrong, verify)"
        elif lib in HARDCODED_MODULE_MAP:
            return f"hardcoded mapping: {lib} → {HARDCODED_MODULE_MAP[lib]}"
        else:
            return f"add to call_module_map.json: {{\"{lib}\": {{\"module\": \"<correct_name>\"}}}}"
    else:
        if lib in cmap:
            return f"mapped to self: {lib} → {lib} (verify source contains {lib}/ or {lib}.py)"
        else:
            return (f"no mapping for {lib}. Check source structure and "
                    f"add to call_module_map.json if needed")


def _format_markdown(r, ts=""):
    """Format report as markdown."""
    total = r["total"]
    if total == 0:
        return "_No KB data found._"

    ok_pct = r["ok"] / total * 100 if total else 0
    skip_pct = r["skipped"] / total * 100 if total else 0
    fail_pct = r["failed"] / total * 100 if total else 0

    lines = []
    lines.append("# KB Build Report")
    if ts:
        lines.append(f"_{ts}_")
    lines.append("")
    lines.append("| Category | Count | Percentage |")
    lines.append("|----------|-------|------------|")
    lines.append(f"| OK       | {r['ok']} | {ok_pct:.1f}% |")
    lines.append(f"| Skipped  | {r['skipped']} | {skip_pct:.1f}% |")
    lines.append(f"| Failed   | {r['failed']} | {fail_pct:.1f}% |")
    lines.append(f"| **Total** | **{total}** | |")

    issues = r["issues"]
    if not issues:
        lines.append("")
        lines.append("No issues found.")
        return "\n".join(lines)

    by_lib = {}
    for iss in issues:
        lib = iss["library"]
        if lib not in by_lib:
            by_lib[lib] = []
        by_lib[lib].append(iss)

    lines.append("")
    lines.append("## Issues by Library")
    lines.append("")
    for lib in sorted(by_lib.keys()):
        lib_issues = by_lib[lib]
        n = len(lib_issues)
        reason = lib_issues[0]["reason"]
        fix = lib_issues[0]["fix"]
        lines.append(f"- **{lib}** ({n} version(s)): {reason}")
        lines.append(f"  - Fix: {fix}")

    manual = [iss for iss in issues
              if "add to call_module_map.json" in iss.get("fix", "")]
    if manual:
        lines.append("")
        lines.append("## Manual Fixes Required")
        lines.append("")
        seen = set()
        for iss in manual:
            if iss["library"] not in seen:
                seen.add(iss["library"])
                lines.append(f"### {iss['library']}")
                lines.append("")
                lines.append("```json")
                lines.append(iss["fix"])
                lines.append("```")
                lines.append("")
                lines.append(f"Then delete failed markers and re-run:")
                lines.append(f"```shell")
                lines.append(f"rm {{{{kb}}}}/library_api/{iss['library']}/*.json.failed")
                lines.append(f"rm {{{{kb}}}}/libraries/{iss['library']}/*/.call_module_failed")
                lines.append(f"```")

    return "\n".join(lines)
