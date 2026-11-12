"""fm27lab command line interface."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

from .client import AgentError, Client, expand_seeds
from .drafts import EDIT_OPS, DraftService

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_APP = 3
EXIT_AUTH = 4
EXIT_ENGINE = 5
EXIT_VALIDATION = 6
EXIT_BUSY = 7
EXIT_NOT_FOUND = 8
EXIT_JOB_FAILED = 9
EXIT_INTERNAL = 10

EXIT_BY_ERROR = {
    "app_unavailable": EXIT_APP,
    "unauthorized": EXIT_AUTH,
    "forbidden_host": EXIT_AUTH,
    "forbidden_origin": EXIT_AUTH,
    "engine_unavailable": EXIT_ENGINE,
    "engine_incompatible": EXIT_ENGINE,
    "validation_failed": EXIT_VALIDATION,
    "engine_busy": EXIT_BUSY,
    "conflict": EXIT_BUSY,
    "idempotency_conflict": EXIT_VALIDATION,
    "storage_insufficient": EXIT_INTERNAL,
    "unsupported": EXIT_INTERNAL,
    "not_found": EXIT_NOT_FOUND,
    "internal_error": EXIT_INTERNAL,
}

BAD_JOB_STATES = ("error", "cancelled", "interrupted")
CSV_FREE_COLUMNS = ("mode", "variant", "seed", "tactic_pool_entry_index",
                    "tactic_pool_entry_name", "home_goals", "away_goals", "shots",
                    "shots_on_target", "xg", "possession", "passes",
                    "completed_passes", "elapsed_seconds", "attempts", "log")
CSV_EVENT_COLUMNS = ("goals", "cards")

_GLOBAL_FLAGS = {"--json": "json", "--quiet": "quiet", "--no-color": "no_color"}
_GLOBAL_VALUES = {"--data-dir": "data_dir", "--endpoint": "endpoint",
                  "--token": "token", "--timeout": "timeout"}
_COMMAND_WORDS = {"status", "engine", "draft", "run", "job", "results",
                  "fmf", "setpiece"}
_ANSI = {"red": "31", "green": "32", "yellow": "33", "cyan": "36"}


class UsageError(Exception):
    """Command line usage error, reported with exit code 2."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


class _Options:
    def __init__(self, values):
        self.data_dir = values.get("data_dir")
        self.endpoint = values.get("endpoint")
        self.token = values.get("token")
        self.json = bool(values.get("json"))
        self.quiet = bool(values.get("quiet"))
        self.no_color = bool(values.get("no_color"))
        raw_timeout = values.get("timeout")
        try:
            self.timeout = float(raw_timeout) if raw_timeout is not None else 120.0
        except ValueError:
            raise UsageError("--timeout 需要数字") from None
        if self.timeout <= 0:
            raise UsageError("--timeout 必须大于 0")
        is_tty = getattr(sys.stdout, "isatty", lambda: False)()
        self.color = (not self.no_color and not os.environ.get("NO_COLOR") and bool(is_tty))


def _extract_globals(argv):
    values = {}
    rest = []
    command = []
    index = 0
    while index < len(argv):
        token = argv[index]
        name, separator, inline = token.partition("=")
        if name in _GLOBAL_FLAGS:
            if separator and inline not in ("", "true", "1"):
                raise UsageError(f"{name} 不接受参数")
            values[_GLOBAL_FLAGS[name]] = True
            index += 1
            continue
        if name in _GLOBAL_VALUES:
            if name == "--timeout" and command[:2] == ["job", "wait"]:
                rest.append(token)
                index += 1
                continue
            if separator:
                value = inline
            else:
                index += 1
                if index >= len(argv) or argv[index].startswith("--"):
                    raise UsageError(f"{name} 需要参数")
                value = argv[index]
            values[_GLOBAL_VALUES[name]] = value
            index += 1
            continue
        if not token.startswith("-"):
            if not command and token in _COMMAND_WORDS:
                command.append(token)
            elif command == ["job"] and token == "wait":
                command.append(token)
        rest.append(token)
        index += 1
    return values, rest


def _detect_json(argv):
    return any(token == "--json" or token.startswith("--json=") for token in argv)


def _style(text, kind, options):
    if not options.color:
        return text
    return f"\033[{_ANSI[kind]}m{text}\033[0m"


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _pairs_text(pairs):
    width = max((len(str(key)) for key, _ in pairs), default=0)
    return "\n".join(f"{str(key).ljust(width)}  {_cell(value)}" for key, value in pairs)


def _table(headers, rows):
    cells = [[_cell(value) for value in row] for row in rows]
    widths = [len(str(header)) for header in headers]
    for row in cells:
        for index, value in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], len(value))
    lines = ["  ".join(str(header).ljust(widths[index])
                       for index, header in enumerate(headers)).rstrip()]
    for row in cells:
        lines.append("  ".join(value.ljust(widths[index])
                               for index, value in enumerate(row)).rstrip())
    return "\n".join(lines)


def _compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _flatten(value, prefix=""):
    items = []
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            items.extend(_flatten(item, name))
    elif isinstance(value, list):
        items.append((prefix, _compact(value)))
    else:
        items.append((prefix, value))
    return items


def _read_bytes(path):
    try:
        return Path(path).expanduser().read_bytes()
    except OSError as error:
        raise AgentError("not_found", f"无法读取文件：{error}", {"path": str(path)}) from None


def _read_base64_file(path):
    return base64.b64encode(_read_bytes(path)).decode("ascii")


def _write_text(path, text):
    target = Path(path).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except OSError as error:
        raise AgentError("internal_error", f"无法写入文件：{error}",
                         {"path": str(target)}) from None
    return target


def _write_json(path, value):
    return _write_text(path, json.dumps(value, ensure_ascii=False, indent=2))


def _parse_side(value):
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "a":
            return 0
        if lowered == "b":
            return 1
        if lowered in ("0", "1"):
            return int(lowered)
    raise argparse.ArgumentTypeError("side 需要 A、B、0 或 1")


def _parse_int_list(value):
    items = [item.strip() for item in str(value).split(",") if item.strip()]
    try:
        return [int(item) for item in items]
    except ValueError:
        raise argparse.ArgumentTypeError("需要逗号分隔的整数") from None


def _parse_text_list(value):
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _parse_seeds(value):
    seeds = []
    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, _, end_text = part.partition("-")
            try:
                start, end = int(start_text), int(end_text)
            except ValueError:
                raise argparse.ArgumentTypeError("种子格式需要 1-10 或 1,2,3") from None
            if start < 0 or end < start:
                raise argparse.ArgumentTypeError("种子区间无效")
            if end - start + 1 > 10000:
                raise argparse.ArgumentTypeError("种子数量不能超过 10000")
            seeds.extend(range(start, end + 1))
        else:
            try:
                seeds.append(int(part))
            except ValueError:
                raise argparse.ArgumentTypeError("种子格式需要 1-10 或 1,2,3") from None
    if not seeds:
        raise argparse.ArgumentTypeError("需要至少一个种子")
    return seeds


def _emit(value, options, render):
    if options.json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        render(value)


def _exit_code(code):
    return EXIT_BY_ERROR.get(code, EXIT_INTERNAL)


def _report_error(error, options):
    code = _exit_code(error.code)
    if options.json:
        print(json.dumps({"error": error.to_dict()}, ensure_ascii=False), file=sys.stderr)
    else:
        prefix = _style("fm27lab:", "red", options)
        print(f"{prefix} {error.code}: {error.message}", file=sys.stderr)
        if error.details:
            print(f"  {json.dumps(error.details, ensure_ascii=False)}", file=sys.stderr)
    return code


def _report_usage(error, options):
    if options.json:
        payload = {"error": {"code": "usage", "message": str(error), "details": {},
                             "retriable": False}}
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    else:
        prefix = _style("fm27lab:", "red", options)
        print(f"{prefix} usage: {error}", file=sys.stderr)
        print("使用 fm27lab --help 查看用法", file=sys.stderr)
    return EXIT_USAGE


def _make_client(options):
    if options.endpoint and options.token:
        return Client(base_url=options.endpoint, token=options.token,
                      data_dir=options.data_dir, timeout=options.timeout)
    return Client(data_dir=options.data_dir, timeout=options.timeout)


def _job_exit(job):
    return EXIT_JOB_FAILED if job.get("status") in BAD_JOB_STATES else EXIT_OK


def _progress_callback(options):
    last = [None]

    def report(job):
        if options.quiet:
            return
        state = (job.get("id"), job.get("status"), job.get("completed"), job.get("total"))
        if state == last[0]:
            return
        last[0] = state
        print(f"[{_cell(job.get('id'))}] {_cell(job.get('status'))} "
              f"{_cell(job.get('completed'))}/{_cell(job.get('total'))}",
              file=sys.stderr, flush=True)

    return report


def _score(run):
    result = run.get("result") or {}
    score = result.get("score") if isinstance(result, dict) else None
    if isinstance(score, (list, tuple)) and len(score) >= 2:
        return score[0], score[1]
    if isinstance(score, dict):
        return score.get("home"), score.get("away")
    return "", ""


def _job_progress(job):
    return f"{_cell(job.get('completed'))}/{_cell(job.get('total'))}"


def _print_submission(value):
    print(_pairs_text([("job", value.get("id")), ("total", value.get("total")),
                       ("workers", value.get("workers"))]))


def _print_job(value):
    pairs = [("job", value.get("id")), ("name", value.get("name")),
             ("status", value.get("status")), ("mode", value.get("mode")),
             ("progress", _job_progress(value)), ("workers", value.get("workers")),
             ("elapsed", value.get("elapsed_seconds")),
             ("eta", value.get("eta_seconds"))]
    if "timed_out" in value:
        pairs.append(("timed_out", value.get("timed_out")))
    print(_pairs_text(pairs))
    runs = value.get("runs") or []
    if runs:
        rows = []
        for run in runs[:20]:
            home, away = _score(run)
            rows.append([run.get("sequence"), run.get("variant"), run.get("seed"),
                         f"{_cell(home)}-{_cell(away)}", run.get("verified"),
                         run.get("elapsed_seconds"), run.get("log")])
        print(_table(["seq", "variant", "seed", "score", "verified", "elapsed", "log"], rows))
        if len(runs) > 20:
            print(f"... 共 {len(runs)} 场")
    if value.get("error"):
        print(f"error: {value['error']}")


def _source_text(source):
    if not isinstance(source, dict):
        return _cell(source)
    return _cell(source.get("kind"))


def _print_draft(value):
    pairs = [("draft", value.get("draft_id")), ("name", value.get("name")),
             ("source", _source_text(value.get("source"))),
             ("schema", value.get("scenario_schema")),
             ("created", value.get("created_at")), ("updated", value.get("updated_at"))]
    for index, team in enumerate(value.get("teams") or []):
        pairs.append((f"team {index}",
                      f"{_cell(team.get('name'))} · {_cell(team.get('tactic_name'))} · "
                      f"mentality {_cell(team.get('mentality'))} · "
                      f"lineup {_cell(team.get('lineup'))}"))
    print(_pairs_text(pairs))


def _print_draft_list(value):
    rows = []
    for draft in value.get("drafts") or []:
        teams = ", ".join(_cell(team.get("name")) for team in draft.get("teams") or [])
        rows.append([draft.get("draft_id"), draft.get("name"), teams or "-",
                     _source_text(draft.get("source")), draft.get("updated_at")])
    print(_table(["draft_id", "name", "teams", "source", "updated_at"], rows))
    print(f"共 {value.get('total', len(rows))} 个草案")


def _print_edit(value):
    print(f"draft {_cell(value.get('draft_id'))}: changed={_cell(value.get('changed'))}")
    validation = value.get("validation") or {}
    print(f"validation: valid={_cell(validation.get('valid'))} "
          f"records={_cell(validation.get('records'))}")
    if value.get("summary"):
        _print_draft(value["summary"])


def _print_validation(value):
    valid = bool(value.get("valid"))
    state = "valid" if valid else "invalid"
    print(f"draft {_cell(value.get('draft_id'))}: {state}")
    if valid:
        print(f"records: {_cell(value.get('records'))}")
    else:
        for error in value.get("errors") or []:
            print(f"{_cell(error.get('code'))}: {_cell(error.get('message'))}")


def _print_export(value):
    pairs = [(key, value.get(key)) for key in
             ("draft_id", "side", "filename", "path", "sha256", "out", "bytes")
             if value.get(key) is not None]
    print(_pairs_text(pairs))
    if value.get("report"):
        print(f"report: {_compact(value['report'])}")


def _print_export_bundle(value):
    print(_pairs_text([("job", value.get("job_id")), ("out", value.get("out"))]))
    for key, path in (value.get("files") or {}).items():
        print(f"{key}: {path}")


def _print_jobs(value):
    rows = [[job.get("id"), job.get("status"), _job_progress(job), job.get("mode"),
             job.get("name")] for job in value.get("jobs") or []]
    print(_table(["id", "status", "progress", "mode", "name"], rows))
    print(f"total {_cell(value.get('total'))}  offset {_cell(value.get('offset'))}  "
          f"limit {_cell(value.get('limit'))}  next {_cell(value.get('next_offset'))}")


def _print_summary(value):
    print(_pairs_text([("job", value.get("job_id")), ("name", value.get("name")),
                       ("status", value.get("status")), ("mode", value.get("mode")),
                       ("completed", value.get("completed")), ("total", value.get("total")),
                       ("runs", value.get("runs_total")),
                       ("event_details", value.get("event_details")),
                       ("eta", value.get("eta_seconds")),
                       ("matches_per_minute", value.get("matches_per_minute"))]))
    rows = [[key, item] for key, item in _flatten(value.get("metrics") or {})]
    if rows:
        print(_table(["metric", "value"], rows))
    if value.get("distributions"):
        rows = [[key, item] for key, item in _flatten(value["distributions"])]
        print(_table(["distribution", "value"], rows))
    if value.get("paired") is not None:
        print(f"paired: {_compact(value['paired'])}")
    failures = value.get("failures") or {}
    print(f"failures: {_cell(failures.get('count'))}")


def _print_matches(value):
    rows = []
    for run in value.get("runs") or []:
        home, away = _score(run)
        rows.append([run.get("sequence"), run.get("variant"), run.get("seed"),
                     f"{_cell(home)}-{_cell(away)}", run.get("verified"),
                     run.get("elapsed_seconds"), run.get("log")])
    print(_table(["seq", "variant", "seed", "score", "verified", "elapsed", "log"], rows))
    print(f"runs {_cell(value.get('offset', 0))}+{len(rows)} / "
          f"{_cell(value.get('runs_total'))}")


def _print_match(value):
    run = value.get("run") or {}
    home, away = _score(run)
    print(_pairs_text([("job", value.get("job_id")), ("seed", run.get("seed")),
                       ("variant", run.get("variant")), ("sequence", run.get("sequence")),
                       ("score", f"{_cell(home)}-{_cell(away)}"),
                       ("verified", run.get("verified")), ("attempts", run.get("attempts")),
                       ("elapsed", run.get("elapsed_seconds")), ("log", run.get("log"))]))
    if run.get("statistics"):
        print(f"statistics: {_compact(run['statistics'])}")
    if run.get("events"):
        print(f"events: {_compact(run['events'])}")


def _print_csv(value):
    print(_pairs_text([("out", value.get("out")), ("rows", value.get("rows")),
                       ("sha256", value.get("sha256"))]))


def _print_mapping(value):
    if isinstance(value, dict):
        pairs = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                item = _compact(item)
            pairs.append((key, item))
        print(_pairs_text(pairs))
    else:
        print(_cell(value))


def _print_status(value, options):
    manifest_value = value.get("manifest") or {}
    status_value = value.get("status") or {}
    engine = status_value.get("engine_compatibility") or {}
    active = status_value.get("active_job")
    if isinstance(active, dict):
        active = active.get("id")
    save_active = status_value.get("save_active")
    if isinstance(save_active, dict):
        save_active = save_active.get("id") or save_active.get("status")
    engine_text = "compatible" if engine.get("compatible") else "incompatible"
    kind = "green" if engine.get("compatible") else "red"
    print(_pairs_text([("api", manifest_value.get("api")),
                       ("server", manifest_value.get("server_version")),
                       ("adapter", manifest_value.get("adapter_version")),
                       ("engine", _style(engine_text, kind, options)),
                       ("can_simulate", engine.get("can_simulate")),
                       ("active_job", active), ("save_active", save_active)]))


def _cmd_status(client, options):
    value = {"manifest": client.manifest(), "status": client.status()}
    _emit(value, options, lambda data: _print_status(data, options))
    return EXIT_OK


def _cmd_engine(client, args, options):
    if args.engine_command != "select":
        raise UsageError(f"未知 engine 子命令：{args.engine_command}")
    result = client.engine_select(args.game)
    _emit(result, options, lambda value: print(_pairs_text(
        [("compatible", value.get("compatible")),
         ("can_simulate", value.get("can_simulate")),
         ("message", value.get("message")),
         ("game_root", value.get("selected_game_root"))])))
    return EXIT_OK


def _cmd_draft_create(args, client, options):
    service = DraftService(client)
    source = args.source
    params = {}
    if source == "fmf":
        if not args.file:
            raise UsageError("fmf 来源需要 --file")
        if args.side is None:
            raise UsageError("fmf 来源需要 --side")
        params = {"side": args.side, "file_base64": _read_base64_file(args.file)}
        if args.base_draft:
            params["base_draft_id"] = args.base_draft
    elif source == "job":
        if not args.job:
            raise UsageError("job 来源需要 --job")
        params = {"job_id": args.job, "variant": args.variant}
    elif source == "draft":
        if not args.base_draft:
            raise UsageError("draft 来源需要 --base-draft")
        params = {"base_draft_id": args.base_draft}
    elif source == "inline":
        if not args.inline:
            raise UsageError("inline 来源需要 --inline")
        params = {"scenario_path": args.inline}
    result = service.create(source=source, name=args.name, **params)
    _emit(result, options, _print_draft)
    return EXIT_OK


def _cmd_draft_list(client, options):
    service = DraftService(client)
    drafts = service.list()
    value = {"drafts": drafts, "total": len(drafts)}
    _emit(value, options, _print_draft_list)
    return EXIT_OK


def _cmd_draft_show(args, client, options):
    service = DraftService(client)
    value = service.get(args.draft_id, include_scenario=args.full)

    def render(value):
        _print_draft(value)
        if "scenario" in value:
            print(json.dumps(value["scenario"], ensure_ascii=False, indent=2))

    _emit(value, options, render)
    return EXIT_OK


def _edit_params(args):
    params = {}
    if args.team is not None:
        params["side"] = args.team
    if args.phase is not None:
        params["phase"] = args.phase
    if args.group is not None:
        params["group"] = args.group
    if args.option is not None:
        params["option"] = args.option
    if args.value is not None:
        if args.op == "mentality":
            try:
                params["value"] = int(args.value)
            except ValueError:
                raise AgentError("validation_failed", "mentality 必须是 1 到 7") from None
        else:
            params["value"] = args.value
    if args.slot is not None:
        params["slot"] = args.slot
    if args.role is not None:
        params["role"] = args.role
    if args.duty is not None:
        params["duty"] = args.duty
    if args.starters is not None:
        params["starters"] = args.starters
    if args.bench is not None:
        params["bench"] = args.bench
    if args.positions is not None:
        params["positions"] = args.positions
    return params


def _cmd_draft_edit(args, client, options):
    service = DraftService(client)
    result = service.edit(args.draft_id, args.op, **_edit_params(args))
    _emit(result, options, _print_edit)
    return EXIT_OK


def _cmd_draft_validate(args, client, options):
    service = DraftService(client)
    result = service.validate(args.draft_id)
    _emit(result, options, _print_validation)
    return EXIT_OK if result.get("valid") else EXIT_VALIDATION


def _cmd_draft_delete(args, client, options):
    service = DraftService(client)
    result = service.delete(args.draft_id)
    _emit(result, options, lambda value: print(f"deleted {_cell(value.get('draft_id'))}"))
    return EXIT_OK


def _cmd_draft(args, client, options):
    if args.draft_command == "create":
        return _cmd_draft_create(args, client, options)
    if args.draft_command == "list":
        return _cmd_draft_list(client, options)
    if args.draft_command == "show":
        return _cmd_draft_show(args, client, options)
    if args.draft_command == "edit":
        return _cmd_draft_edit(args, client, options)
    if args.draft_command == "validate":
        return _cmd_draft_validate(args, client, options)
    if args.draft_command == "delete":
        return _cmd_draft_delete(args, client, options)
    raise UsageError(f"未知 draft 子命令：{args.draft_command}")


def _run_and_wait(client, response, options, wait_timeout):
    job_id = response.get("id")
    if not job_id:
        raise AgentError("internal_error", "服务端未返回任务标识")
    job = client.wait_job(job_id, timeout=wait_timeout, poll=1.0,
                          on_progress=_progress_callback(options))
    _emit(job, options, _print_job)
    return _job_exit(job)


def _cmd_run(client, args, options):
    service = DraftService(client)
    scenario = service.scenario(args.draft_id)
    reference = service.scenario(args.baseline_draft) if args.baseline_draft else None
    seeds = expand_seeds(args.seeds)
    response = client.run(scenario, reference=reference, seeds=seeds,
                          workers=args.workers, event_details=not args.quick,
                          name=args.name)
    if not args.wait:
        _emit(response, options, _print_submission)
        return EXIT_OK
    return _run_and_wait(client, response, options, args.wait_timeout)


def _cmd_job_list(client, args, options):
    page = client.jobs(limit=args.limit, offset=args.offset, status=args.status)
    _emit(page, options, _print_jobs)
    return EXIT_OK


def _cmd_job_get(client, args, options):
    job = client.job(args.job_id)
    _emit(job, options, _print_job)
    return EXIT_OK


def _cmd_job_wait(client, args, options):
    job = client.wait_job(args.job_id, timeout=args.wait_timeout, poll=args.poll,
                          on_progress=_progress_callback(options))
    _emit(job, options, _print_job)
    return _job_exit(job)


def _cmd_job_action(client, args, options):
    if args.cancel:
        result = client.cancel(args.job_id)
    elif args.resume:
        result = client.resume(args.job_id, args.workers)
    elif args.delete:
        result = client.delete(args.job_id)
    else:
        result = client.rename(args.job_id, args.rename)
    _emit(result, options, _print_mapping)
    return EXIT_OK


def _log_text(payload):
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("text", "content", "lines", "log"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                return "\n".join(item if isinstance(item, str) else _compact(item)
                                for item in value)
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return json.dumps(payload, ensure_ascii=False)


def _cmd_job_logs(client, args, options):
    payload = client.job_logs(args.job_id, args.run)
    text = _log_text(payload)
    if args.out:
        target = _write_text(args.out, text)
        value = {"job_id": args.job_id, "run": args.run, "out": str(target),
                 "bytes": len(text.encode("utf-8"))}
        _emit(value, options, lambda value: print(_pairs_text(
            [("out", value.get("out")), ("bytes", value.get("bytes"))])))
        return EXIT_OK
    if options.json:
        _emit({"job_id": args.job_id, "run": args.run, "text": text},
              options, lambda value: None)
        return EXIT_OK
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
    return EXIT_OK


def _cmd_job_export(client, args, options):
    exported = client.job_export(args.job_id)
    directory = Path(args.out).expanduser()
    files = {}
    for key in ("summary", "scenarios", "provenance"):
        files[key] = str(_write_json(directory / f"{key}.json",
                                     exported.get(key) if exported.get(key) is not None else {}))
    value = {"job_id": args.job_id, "out": str(directory), "files": files}
    _emit(value, options, _print_export_bundle)
    return EXIT_OK


def _cmd_job(args, client, options):
    if args.job_command == "list":
        return _cmd_job_list(client, args, options)
    if args.job_command == "get":
        return _cmd_job_get(client, args, options)
    if args.job_command == "wait":
        return _cmd_job_wait(client, args, options)
    if args.job_command == "action":
        return _cmd_job_action(client, args, options)
    if args.job_command == "logs":
        return _cmd_job_logs(client, args, options)
    if args.job_command == "export":
        return _cmd_job_export(client, args, options)
    raise UsageError(f"未知 job 子命令：{args.job_command}")


def _summary_value(job):
    failures = job.get("failures") or []
    runs_total = job.get("runs_total")
    if runs_total is None:
        runs_total = job.get("total")
    value = {"job_id": job.get("id"), "name": job.get("name"),
             "status": job.get("status"), "mode": job.get("mode"),
             "completed": job.get("completed"), "total": job.get("total"),
             "runs_total": runs_total, "workers": job.get("workers"),
             "event_details": job.get("event_details"),
             "metrics": job.get("metrics") or {}, "paired": job.get("paired"),
             "failures": {"count": len(failures), "items": failures[:20]},
             "eta_seconds": job.get("eta_seconds"),
             "matches_per_minute": job.get("matches_per_minute"),
             "elapsed_seconds": job.get("elapsed_seconds")}
    if job.get("distributions"):
        value["distributions"] = job["distributions"]
    if job.get("opponent_metrics"):
        value["opponent_metrics"] = job["opponent_metrics"]
    return value


def _cmd_results_summary(client, args, options):
    job = client.job(args.job_id, runs_limit=1)
    value = _summary_value(job)
    _emit(value, options, _print_summary)
    return EXIT_OK


def _cmd_results_matches(client, args, options):
    page = client.job(args.job_id, runs_offset=args.offset, runs_limit=args.limit,
                      variant=args.variant)
    runs = list(page.get("runs") or [])
    if not args.events:
        runs = [{key: item for key, item in run.items() if key != "events"} for run in runs]
    value = {"job_id": args.job_id, "variant": args.variant, "runs": runs,
             "runs_total": page.get("runs_total", len(runs)),
             "runs_truncated": page.get("runs_truncated", False),
             "limit": args.limit, "offset": args.offset}
    _emit(value, options, _print_matches)
    return EXIT_OK


def _find_run(client, job_id, seed, variant):
    offset = 0
    while True:
        page = client.job(job_id, runs_offset=offset, runs_limit=200, variant=variant)
        runs = list(page.get("runs") or [])
        for run in runs:
            if run.get("seed") == seed:
                return run
        total = page.get("runs_total")
        if not isinstance(total, int):
            total = offset + len(runs)
        offset += len(runs)
        if not runs or offset >= total:
            raise AgentError("not_found", f"任务 {job_id} 中没有 seed {seed} 的比赛")


def _cmd_results_match(client, args, options):
    run = _find_run(client, args.job_id, args.seed, args.variant)
    value = {"job_id": args.job_id, "run": run}
    _emit(value, options, _print_match)
    return EXIT_OK


def _all_runs(client, job_id):
    first = client.job(job_id, runs_offset=0, runs_limit=200)
    runs = list(first.get("runs") or [])
    total = first.get("runs_total")
    if not isinstance(total, int):
        total = len(runs)
    while len(runs) < total:
        page = client.job(job_id, runs_offset=len(runs), runs_limit=200)
        chunk = list(page.get("runs") or [])
        if not chunk:
            break
        runs.extend(chunk)
    return first, runs


def _tested_side(run, job_value):
    schedule = job_value.get("schedule") or {}
    spec = schedule.get(run.get("variant")) if isinstance(schedule, dict) else None
    side = spec.get("tested_side") if isinstance(spec, dict) else None
    if type(side) is not int:
        side = run.get("tested_side")
    if type(side) is not int:
        side = 0
    return side


def _csv_row(run, job_value, events):
    variant = run.get("variant")
    schedule = job_value.get("schedule") or {}
    spec = schedule.get(variant) if isinstance(schedule, dict) else None
    if not isinstance(spec, dict):
        spec = {}
    statistics = run.get("statistics") or {}
    teams = statistics.get("teams") if isinstance(statistics, dict) else None
    side = _tested_side(run, job_value)
    team = teams[side] if (isinstance(teams, list) and side < len(teams)
                           and isinstance(teams[side], dict)) else {}
    home, away = _score(run)
    pool_entry = run.get("tactic_pool_entry") if isinstance(run.get("tactic_pool_entry"), dict) else {}
    row = [job_value.get("mode") or run.get("mode") or "", variant or "",
           run.get("seed", ""), pool_entry.get("index", ""), pool_entry.get("name", ""),
           home, away, team.get("shots", ""),
           team.get("shots_on_target", ""), team.get("xg", ""),
           team.get("possession", ""), team.get("passes", ""),
           team.get("completed_passes", ""), run.get("elapsed_seconds", ""),
           run.get("attempts", ""), run.get("log", "")]
    if events:
        payload = run.get("events") or {}
        row.extend([_compact(payload.get("goals", [])), _compact(payload.get("cards", []))])
    return row


def _cmd_results_csv(client, args, options):
    job_value, runs = _all_runs(client, args.job_id)
    columns = list(CSV_FREE_COLUMNS)
    if args.events:
        columns.extend(CSV_EVENT_COLUMNS)
    target = Path(args.out).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            for run in runs:
                writer.writerow(_csv_row(run, job_value, args.events))
    except OSError as error:
        raise AgentError("internal_error", f"无法写入 CSV：{error}",
                         {"path": str(target)}) from None
    value = {"job_id": args.job_id, "out": str(target), "rows": len(runs),
             "columns": columns,
             "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    _emit(value, options, _print_csv)
    return EXIT_OK


def _cmd_results(args, client, options):
    if args.results_command == "summary":
        return _cmd_results_summary(client, args, options)
    if args.results_command == "matches":
        return _cmd_results_matches(client, args, options)
    if args.results_command == "match":
        return _cmd_results_match(client, args, options)
    if args.results_command == "csv":
        return _cmd_results_csv(client, args, options)
    raise UsageError(f"未知 results 子命令：{args.results_command}")


def _materialize_export(result, out):
    target = Path(out).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise AgentError("internal_error", f"无法创建目录：{error}") from None
    encoded = result.get("file_base64")
    if isinstance(encoded, str) and encoded:
        try:
            payload = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise AgentError("internal_error", "导出数据无法解码") from None
        try:
            target.write_bytes(payload)
        except OSError as error:
            raise AgentError("internal_error", f"无法写入文件：{error}") from None
        return target
    source = result.get("path")
    try:
        if not source or not Path(source).is_file():
            raise AgentError("not_found", f"导出文件不存在：{source}")
        shutil.copyfile(source, target)
    except OSError as error:
        raise AgentError("internal_error", f"无法复制导出文件：{error}") from None
    return target


def _export_value(result, draft_id, side, out):
    value = {"draft_id": draft_id, "side": side,
             "filename": result.get("filename"), "path": result.get("path"),
             "sha256": result.get("sha256"), "report": result.get("report")}
    if out:
        target = _materialize_export(result, out)
        value["out"] = str(target)
        if not value.get("sha256"):
            value["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        value["bytes"] = target.stat().st_size
    return value


def _cmd_fmf_import(client, args, options):
    service = DraftService(client)
    scenario = service.scenario(args.draft_id)
    file_base64 = _read_base64_file(args.file)
    loaded = client.fmf_import(args.side, scenario, file_base64)
    imported = loaded.get("scenario") if isinstance(loaded, dict) else None
    if not isinstance(imported, dict):
        raise AgentError("internal_error", "服务端未返回导入后的场景")
    checked = client.validate(imported)
    summary = service.replace_scenario(args.draft_id, imported)
    value = {"draft_id": args.draft_id, "side": args.side,
             "report": loaded.get("report"), "records": checked.get("records"),
             "summary": summary}

    def render(value):
        print(f"draft {_cell(value.get('draft_id'))} 已导入")
        print(f"records: {_cell(value.get('records'))}")
        if value.get("report"):
            print(f"report: {_compact(value['report'])}")

    _emit(value, options, render)
    return EXIT_OK


def _cmd_fmf_export(client, args, options):
    service = DraftService(client)
    scenario = service.scenario(args.draft_id)
    result = client.fmf_export(args.side, scenario, args.name)
    value = _export_value(result if isinstance(result, dict) else {}, args.draft_id,
                          args.side, args.out)
    _emit(value, options, _print_export)
    return EXIT_OK


def _cmd_fmf(args, client, options):
    if args.fmf_command == "import":
        return _cmd_fmf_import(client, args, options)
    if args.fmf_command == "export":
        return _cmd_fmf_export(client, args, options)
    raise UsageError(f"未知 fmf 子命令：{args.fmf_command}")


def _cmd_setpiece_export(client, args, options):
    service = DraftService(client)
    scenario = service.scenario(args.draft_id)
    result = client.setpiece_export(args.side, scenario, args.type, args.variant)
    value = _export_value(result if isinstance(result, dict) else {}, args.draft_id,
                          args.side, args.out)
    value["type"] = args.type
    value["variant"] = args.variant
    _emit(value, options, _print_export)
    return EXIT_OK


def _cmd_setpiece(args, client, options):
    if args.setpiece_command == "export":
        return _cmd_setpiece_export(client, args, options)
    raise UsageError(f"未知 setpiece 子命令：{args.setpiece_command}")


def _dispatch(args, options):
    client = _make_client(options)
    command = args.command
    if command == "status":
        return _cmd_status(client, options)
    if command == "engine":
        return _cmd_engine(client, args, options)
    if command == "draft":
        return _cmd_draft(args, client, options)
    if command == "run":
        return _cmd_run(client, args, options)
    if command == "job":
        return _cmd_job(args, client, options)
    if command == "results":
        return _cmd_results(args, client, options)
    if command == "fmf":
        return _cmd_fmf(args, client, options)
    if command == "setpiece":
        return _cmd_setpiece(args, client, options)
    raise UsageError(f"未知命令：{command}")


def _build_parser():
    parser = _Parser(
        prog="fm27lab",
        description="FM Tactics Lab 本机 Agent 命令",
        epilog=("全局选项：--data-dir PATH  --endpoint URL  --token TOKEN  --json  "
                "--timeout SECONDS  --quiet  --no-color（可放在子命令前后）。"
                "fm27lab mcp 以 stdio 启动 MCP sidecar。"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="清单、引擎与活动任务")

    engine = sub.add_parser("engine", help="引擎操作")
    engine_sub = engine.add_subparsers(dest="engine_command", required=True)
    engine_select = engine_sub.add_parser("select", help="设置游戏根并预检")
    engine_select.add_argument("--game", required=True, metavar="PATH")

    draft = sub.add_parser("draft", help="场景草案")
    draft_sub = draft.add_subparsers(dest="draft_command", required=True)
    create = draft_sub.add_parser("create", help="创建草案")
    create.add_argument("--from", dest="source", default="default",
                        choices=["default", "fmf", "job", "inline", "draft"],
                        help="草案来源")
    create.add_argument("--name")
    create.add_argument("--job", dest="job")
    create.add_argument("--variant")
    create.add_argument("--file", metavar="FMF", help="FMF 文件")
    create.add_argument("--side", type=_parse_side)
    create.add_argument("--base-draft", dest="base_draft")
    create.add_argument("--inline", metavar="FILE", help="内联场景 JSON 文件")
    draft_sub.add_parser("list", help="列出草案")
    show = draft_sub.add_parser("show", help="查看草案")
    show.add_argument("draft_id")
    show.add_argument("--full", action="store_true")
    edit = draft_sub.add_parser("edit", help="语义编辑草案")
    edit.add_argument("draft_id")
    edit.add_argument("--op", required=True, choices=list(EDIT_OPS))
    edit.add_argument("--team", type=_parse_side, metavar="A|B")
    edit.add_argument("--phase")
    edit.add_argument("--group")
    edit.add_argument("--option", type=int)
    edit.add_argument("--value")
    edit.add_argument("--slot", type=int)
    edit.add_argument("--role")
    edit.add_argument("--duty")
    edit.add_argument("--starters", type=_parse_int_list)
    edit.add_argument("--bench", type=_parse_int_list)
    edit.add_argument("--positions", type=_parse_text_list)
    validate = draft_sub.add_parser("validate", help="校验并规范化草案")
    validate.add_argument("draft_id")
    delete = draft_sub.add_parser("delete", help="删除草案")
    delete.add_argument("draft_id")

    run = sub.add_parser("run", help="自由模式批次")
    run.add_argument("--draft", required=True, dest="draft_id")
    run.add_argument("--baseline", dest="baseline_draft")
    run.add_argument("--seeds", required=True, type=_parse_seeds, metavar="1-10|1,2,3")
    run.add_argument("--workers", type=int)
    run.add_argument("--quick", action="store_true", help="关闭事件明细")
    run.add_argument("--name")
    run.add_argument("--wait", action="store_true")
    run.add_argument("--wait-timeout", dest="wait_timeout", type=float, default=300.0,
                     metavar="SECONDS")

    job = sub.add_parser("job", help="任务")
    job_sub = job.add_subparsers(dest="job_command", required=True)
    job_list = job_sub.add_parser("list", help="任务分页")
    job_list.add_argument("--status")
    job_list.add_argument("--limit", type=int, default=50)
    job_list.add_argument("--offset", type=int, default=0)
    job_get = job_sub.add_parser("get", help="任务详情")
    job_get.add_argument("job_id")
    job_wait = job_sub.add_parser("wait", help="等待任务终态")
    job_wait.add_argument("job_id")
    job_wait.add_argument("--timeout", dest="wait_timeout", type=float, default=300.0,
                          metavar="SECONDS")
    job_wait.add_argument("--poll", type=float, default=1.0, metavar="SECONDS")
    job_action = job_sub.add_parser("action", help="任务操作")
    job_action.add_argument("job_id")
    action_group = job_action.add_mutually_exclusive_group(required=True)
    action_group.add_argument("--cancel", action="store_true")
    action_group.add_argument("--resume", action="store_true")
    action_group.add_argument("--delete", action="store_true")
    action_group.add_argument("--rename", metavar="NAME")
    job_action.add_argument("--workers", type=int)
    job_logs = job_sub.add_parser("logs", help="下载单场原始日志")
    job_logs.add_argument("job_id")
    job_logs.add_argument("--run", required=True, metavar="LOG")
    job_logs.add_argument("--out")
    job_export = job_sub.add_parser("export", help="导出任务汇总")
    job_export.add_argument("job_id")
    job_export.add_argument("--out", required=True, metavar="DIR")

    results = sub.add_parser("results", help="结果视图")
    results_sub = results.add_subparsers(dest="results_command", required=True)
    summary = results_sub.add_parser("summary", help="汇总指标")
    summary.add_argument("job_id")
    matches = results_sub.add_parser("matches", help="逐场分页")
    matches.add_argument("job_id")
    matches.add_argument("--variant")
    matches.add_argument("--limit", type=int, default=50)
    matches.add_argument("--offset", type=int, default=0)
    matches.add_argument("--events", action="store_true")
    match = results_sub.add_parser("match", help="单场详情")
    match.add_argument("job_id")
    match.add_argument("--variant")
    match.add_argument("--seed", required=True, type=int)
    results_csv = results_sub.add_parser("csv", help="导出 CSV")
    results_csv.add_argument("job_id")
    results_csv.add_argument("--out", required=True, metavar="FILE")
    results_csv.add_argument("--events", action="store_true")

    fmf = sub.add_parser("fmf", help="战术文件")
    fmf_sub = fmf.add_subparsers(dest="fmf_command", required=True)
    fmf_import = fmf_sub.add_parser("import", help="导入战术到草案")
    fmf_import.add_argument("--draft", required=True, dest="draft_id")
    fmf_import.add_argument("--side", required=True, type=_parse_side)
    fmf_import.add_argument("--file", required=True, metavar="FMF")
    fmf_export = fmf_sub.add_parser("export", help="导出战术文件")
    fmf_export.add_argument("--draft", required=True, dest="draft_id")
    fmf_export.add_argument("--side", required=True, type=_parse_side)
    fmf_export.add_argument("--out", metavar="FILE")
    fmf_export.add_argument("--name")

    setpiece = sub.add_parser("setpiece", help="定位球文件")
    setpiece_sub = setpiece.add_subparsers(dest="setpiece_command", required=True)
    setpiece_export = setpiece_sub.add_parser("export", help="导出定位球文件")
    setpiece_export.add_argument("--draft", required=True, dest="draft_id")
    setpiece_export.add_argument("--side", required=True, type=_parse_side)
    setpiece_export.add_argument("--type", required=True, type=int)
    setpiece_export.add_argument("--variant", required=True, type=int)
    setpiece_export.add_argument("--out", metavar="FILE")

    return parser


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    json_hint = _detect_json(arguments)
    try:
        values, rest = _extract_globals(arguments)
    except UsageError as error:
        return _report_usage(error, _Options({"json": json_hint}))
    try:
        options = _Options(values)
    except UsageError as error:
        return _report_usage(error, _Options({"json": json_hint}))
    parser = _build_parser()
    if not rest:
        parser.print_help()
        return EXIT_OK
    try:
        args = parser.parse_args(rest)
    except UsageError as error:
        return _report_usage(error, options)
    except SystemExit as exit_value:
        code = exit_value.code
        if isinstance(code, int):
            return code
        return EXIT_OK if code is None else 1
    try:
        return _dispatch(args, options)
    except AgentError as error:
        return _report_error(error, options)
    except KeyboardInterrupt:
        if not options.quiet:
            print("已中断", file=sys.stderr)
        return 130
    except OSError as error:
        return _report_error(AgentError("internal_error", f"文件操作失败：{error}"), options)
    except Exception as error:
        if os.environ.get("FM27LAB_DEBUG"):
            import traceback
            traceback.print_exc()
        return _report_error(AgentError("internal_error", str(error) or error.__class__.__name__),
                             options)


if __name__ == "__main__":
    raise SystemExit(main())
