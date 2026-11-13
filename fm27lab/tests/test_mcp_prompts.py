from __future__ import annotations

import io
import json
import re

import pytest

from fm27lab.interfaces.mcp.prompts import build_prompts
from fm27lab.interfaces.mcp.protocol import McpServer

CJK = re.compile(r"[\u4e00-\u9fff]")


def make_server():
    return McpServer(name="fm27lab-test", version="9.9.9", prompts=build_prompts())


def request(method, params):
    return json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, ensure_ascii=False)


def serve(line):
    outstream = io.StringIO()
    make_server().serve(io.StringIO(line + "\n"), outstream)
    return json.loads(outstream.getvalue())


def prompt_result(name, arguments=None):
    params = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    return serve(request("prompts/get", params))["result"]


def prompt_text(name, arguments=None):
    return prompt_result(name, arguments)["messages"][0]["content"]["text"]


def test_build_prompts_declares_experiment_design_and_pool_review():
    prompts = {prompt.name: prompt for prompt in build_prompts()}
    assert set(prompts) == {"experiment-design", "pool-review"}
    design = {argument.name: argument for argument in prompts["experiment-design"].arguments}
    assert list(design) == ["draft_id", "instruction", "baseline_draft_id", "seeds"]
    assert [argument.required for argument in design.values()] == [True, True, False, False]
    pool = {argument.name: argument for argument in prompts["pool-review"].arguments}
    assert list(pool) == ["job_id", "focus"]
    assert [argument.required for argument in pool.values()] == [True, False]
    for prompt in prompts.values():
        assert CJK.search(prompt.description)
        for argument in prompt.arguments:
            assert CJK.search(argument.description)


def test_prompts_list_exposes_argument_required_flags():
    listed = serve(request("prompts/list", {}))["result"]["prompts"]
    assert [item["name"] for item in listed] == ["experiment-design", "pool-review"]
    design = listed[0]["arguments"]
    assert [argument["name"] for argument in design] == [
        "draft_id",
        "instruction",
        "baseline_draft_id",
        "seeds",
    ]
    assert [argument["required"] for argument in design] == [True, True, False, False]


def test_experiment_design_prompt_embeds_arguments_and_workflow():
    result = prompt_result(
        "experiment-design",
        {
            "draft_id": "dr_candidate",
            "instruction": "提高高位逼抢强度",
            "baseline_draft_id": "dr_baseline",
            "seeds": "101:200",
        },
    )
    assert CJK.search(result["description"])
    text = result["messages"][0]["content"]["text"]
    for fragment in ("dr_candidate", "提高高位逼抢强度", "dr_baseline", "101:200"):
        assert fragment in text
    for tool in ("drafts_get", "drafts_update", "jobs_create", "jobs_get", "jobs_runs"):
        assert tool in text
    assert CJK.search(text)


def test_experiment_design_prompt_defaults_optional_arguments():
    text = prompt_text(
        "experiment-design",
        {"draft_id": "dr_candidate", "instruction": "提高高位逼抢强度"},
    )
    assert "dr_candidate" in text
    assert "None" not in text
    assert "默认" in text


def test_pool_review_prompt_embeds_job_and_focus():
    result = prompt_result("pool-review", {"job_id": "job_123", "focus": "净胜球"})
    assert CJK.search(result["description"])
    text = result["messages"][0]["content"]["text"]
    assert "job_123" in text
    assert "净胜球" in text
    for tool in ("pools_list", "jobs_get", "jobs_runs"):
        assert tool in text
    assert CJK.search(text)


def test_pool_review_prompt_defaults_focus():
    text = prompt_text("pool-review", {"job_id": "job_123"})
    assert "job_123" in text
    assert "None" not in text
    assert "默认" in text


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("experiment-design", {}),
        ("experiment-design", {"draft_id": "dr_candidate"}),
        ("pool-review", {}),
    ],
)
def test_missing_required_argument_is_rejected(name, arguments):
    reply = serve(request("prompts/get", {"name": name, "arguments": arguments}))
    assert reply["error"]["code"] == -32602
    assert "缺少必填参数" in reply["error"]["message"]
    assert CJK.search(reply["error"]["message"])
    assert "result" not in reply


def test_unknown_prompt_is_rejected():
    reply = serve(request("prompts/get", {"name": "bogus-prompt"}))
    assert reply["error"]["code"] == -32602
    assert "未知提示词" in reply["error"]["message"]
    assert CJK.search(reply["error"]["message"])


def test_unknown_prompt_argument_is_rejected():
    reply = serve(
        request(
            "prompts/get",
            {
                "name": "experiment-design",
                "arguments": {
                    "draft_id": "dr_candidate",
                    "instruction": "提高逼抢",
                    "extra": "多余",
                },
            },
        )
    )
    assert reply["error"]["code"] == -32602
    assert "未知提示词参数" in reply["error"]["message"]


def test_prompt_argument_value_must_be_string():
    reply = serve(
        request(
            "prompts/get",
            {"name": "experiment-design", "arguments": {"draft_id": 3, "instruction": "提高逼抢"}},
        )
    )
    assert reply["error"]["code"] == -32602
    assert "类型必须是字符串" in reply["error"]["message"]
