"""核心逻辑的离线测试：解析、上下文裁剪、技能与经验的选择、用量统计。"""
import common
import context
import desktop
import lessons
import manage
import orchestra
import providers
import skills
import store
import tools
import usage


# ---------------------------------------------------------------- 领头人分派
def _members(*names):
    return [{"id": "id-" + n, "name": n} for n in names]


def test_parse_assignments_basic_and_multiline():
    text = "好的，我来安排。\n@产品经理：列出三个核心功能\n补充：要考虑手机端\n@批判者: 找出风险"
    got = {a["name"]: a["task"] for a in orchestra.parse_assignments(text, _members("产品经理", "批判者"))}
    assert got["产品经理"] == "列出三个核心功能\n补充：要考虑手机端"
    assert got["批判者"] == "找出风险"


def test_parse_assignments_tolerates_list_marks_bold_and_fullwidth_at():
    text = "1. **＠产品经理**：写需求\n- @批判者：挑毛病"
    got = {a["name"] for a in orchestra.parse_assignments(text, _members("产品经理", "批判者"))}
    assert got == {"产品经理", "批判者"}


def test_parse_assignments_prefers_longest_name_and_ignores_strangers():
    text = "@产品经理助理：做原型\n@路人甲：随便"
    got = orchestra.parse_assignments(text, _members("产品经理", "产品经理助理"))
    assert [a["name"] for a in got] == ["产品经理助理"]


# ---------------------------------------------------------------- 上下文与省 token
def test_trim_history_keeps_recent_and_notes_dropped():
    msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": "字" * 1000} for i in range(10)]
    out = context.trim_history(msgs, 3000)
    assert len(out) <= 5 and out[-1] == msgs[-1]
    assert "已省略" in out[0]["content"] and out[0]["role"] == "user"


def test_trim_history_under_budget_is_untouched():
    msgs = [{"role": "user", "content": "短"}, {"role": "assistant", "content": "也短"}]
    assert context.trim_history(list(msgs), 3000) == msgs


def test_build_context_speaks_in_first_person_and_prefixes_others():
    me = store.put_doc("agent", {"name": "甲", "system_prompt": "你是甲。", "no_tools": True})
    other = store.put_doc("agent", {"name": "乙", "no_tools": True})
    conv = {"id": "c1", "agent_ids": [me["id"], other["id"]]}
    history = [
        {"role": "user", "content": "大家好"},
        {"role": "agent", "agent_id": other["id"], "agent_name": "乙", "content": "我是乙"},
        {"role": "agent", "agent_id": me["id"], "agent_name": "甲", "content": "我是甲"},
    ]
    system, msgs = context.build_context(conv, me, history, thrifty=True)
    assert "你的名字是「甲」" in system and "乙" in system
    assert msgs[0] == {"role": "user", "content": "大家好\n\n[乙]: 我是乙"}
    assert msgs[1] == {"role": "assistant", "content": "我是甲"}
    assert msgs[-1]["role"] == "user"  # 最后一条总是 user，轮到它说


def test_thrifty_clips_older_messages_only():
    me = store.put_doc("agent", {"name": "甲", "no_tools": True})
    conv = {"id": "c1", "agent_ids": [me["id"]]}
    long = "长" * 3000
    history = [{"role": "user", "content": long} for _ in range(8)]
    _, full = context.build_context(conv, me, history, thrifty=False)
    _, thin = context.build_context(conv, me, history, thrifty=True)
    assert sum(len(m["content"]) for m in thin) < sum(len(m["content"]) for m in full) / 2
    assert long in thin[-1]["content"]  # 最新一条完整保留


def test_system_prompt_is_stable_and_relevant_skill_goes_to_last_message():
    big = "\n".join("第%d步：检查发票抬头、税号、金额。" % i for i in range(80))
    sk = store.put_doc("skill", {"name": "发票核对", "description": "核对发票信息", "instructions": big})
    me = store.put_doc("agent", {"name": "财务", "no_tools": True, "skills": [sk["id"]]})
    conv = {"id": "c1", "agent_ids": [me["id"]]}
    s1, m1 = context.build_context(conv, me, [{"role": "user", "content": "今天天气如何"}], thrifty=True)
    s2, m2 = context.build_context(conv, me, [{"role": "user", "content": "帮我核对发票"}], thrifty=True)
    assert s1 == s2  # 系统提示不随问题变化，接口才能缓存
    assert "第40步" not in m1[-1]["content"] and "skill_read" in s1
    assert "第40步" in m2[-1]["content"]


def test_tokens_estimate_counts_cjk_heavier():
    assert common._tokens("中文中文中文") > common._tokens("abcdef")


# ---------------------------------------------------------------- 技能
def test_parse_skill_front_matter():
    got = skills.parse_skill("---\nname: 写周报\ndescription: \"按模板整理\"\n---\n# 步骤\n1. 汇总")
    assert got == {"name": "写周报", "description": "按模板整理", "instructions": "# 步骤\n1. 汇总"}


def test_skill_relevance():
    sk = {"name": "发票核对", "description": "核对发票信息是否完整一致"}
    assert skills._relevant(sk, "帮我核对一张发票")
    assert not skills._relevant(sk, "今天天气怎么样")


def test_adopt_new_skills_registers_fresh_skill_md(tmp_path):
    import time
    since = time.time()
    d = tmp_path / "pkg" / "demo"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: demo\ndescription: 测试\n---\n内容足够长，用来测试自动登记。", encoding="utf-8")
    assert skills.adopt_new_skills(since, str(tmp_path), "") == ["demo"]
    assert [k["origin"] for k in store.list_docs("skill")] == ["external"]
    assert skills.adopt_new_skills(since, str(tmp_path), "") == ["demo"]  # 再装一次 = 更新，不重复
    assert len(store.list_docs("skill")) == 1


# ---------------------------------------------------------------- 管家标签
def test_manage_parse_tags():
    text = ('<fetch url="https://a.b/c"/> <skill_add url="https://x/y"/> <skill_add path="~/skills/demo"/>'
            '<skill_remove name="旧技能"/> <mcp_add>{"name":"m","command":"npx"}</mcp_add>')
    kinds = [(a["kind"], a.get("url") or a.get("path") or a.get("name") or a.get("raw")) for a in manage.parse(text)]
    assert kinds == [("fetch", "https://a.b/c"), ("skill_add", "https://x/y"), ("skill_add", "~/skills/demo"),
                     ("skill_remove", "旧技能"), ("mcp_add", '{"name":"m","command":"npx"}')]


def test_read_local_skill_refuses_other_files(tmp_path):
    f = tmp_path / "secret.txt"
    f.write_text("x")
    try:
        manage.read_local_skill(str(f))
    except ValueError:
        return
    raise AssertionError("应当拒绝读取 SKILL.md 以外的文件")


# ---------------------------------------------------------------- 经验库
def test_lesson_quality_rejects_hollow_and_self_talk():
    assert lessons.lesson_quality("报销金额一律保留两位小数并带￥符号")
    assert not lessons.lesson_quality("要遵循用户的格式要求")
    assert not lessons.lesson_quality("我会注意的")


def test_similar_lessons_are_deduplicated():
    assert lessons._similar("项目代号一律以青鸟-开头", "项目代号一律以青鸟-开头，后跟三位数字")
    assert not lessons._similar("项目代号以青鸟-开头", "报销金额保留两位小数")


# ---------------------------------------------------------------- 本地操作的安全边界
def test_actions_parse_and_paths_cannot_escape_workspace(tmp_path):
    acts = tools.parse_actions('<run>ls</run><read>a.txt</read><write path="b.md">内容</write>')
    assert [a["kind"] for a in acts] == ["run", "read", "write"]
    root = str(tmp_path / "conv")
    _, err = tools._resolve("../../etc/passwd", root, [])
    assert err  # 跳出会话文件夹被拒绝
    _, ok = tools._resolve("sub/file.txt", root, [])
    assert not ok


def test_runnable_files_are_never_launched_directly():
    assert desktop.is_runnable("x.BAT") and desktop.is_runnable("a.ps1") and desktop.is_runnable("b.py")
    assert not desktop.is_runnable("report.docx") and not desktop.is_runnable("photo.png")


# ---------------------------------------------------------------- 模型接口
def test_clean_provider_keeps_learned_fields():
    """编辑渠道时，从报错里学到的字段（输出上限、不认的参数、不支持原生工具）不能被冲掉。"""
    from cleaning import clean_provider
    old = {"protocol": "openai", "api_key": "k", "out_caps": {"m": 64000},
           "bad_params": {"m": ["temperature"]}, "native_tools": False, "timeout": 900, "models": ["m"]}
    p = clean_provider({"protocol": "openai", "name": "改名"}, old)
    assert p["out_caps"] == {"m": 64000} and p["bad_params"] == {"m": ["temperature"]}
    assert p["native_tools"] is False and p["timeout"] == 900
    assert clean_provider({"protocol": "openai"}, {})["timeout"] is None  # 留空走默认 600 秒

def test_output_cap_parses_provider_errors():
    assert providers.output_cap('{"message":"max_tokens参数非法：限制数值范围[1,131072]"}', 200000) == 131072
    assert providers.output_cap("max_tokens: 200000 > 64000, which is the maximum allowed number of output tokens", 200000) == 64000
    assert providers.output_cap("model not found", 50000) == 0
    assert providers.output_cap("max_tokens too large", None) == 0


def test_unsupported_param_detection():
    # 新版 OpenAI 模型只收默认 temperature 的报错：认出参数名，调用方去掉它重试
    assert providers.unsupported_param("Unsupported value: 'temperature' does not support 0.7 with this model.") == "temperature"
    assert providers.unsupported_param('{"error": {"message": "Unsupported parameter: top_p is not supported with this model."}}') == "top_p"
    assert providers.unsupported_param("temperature 参数不支持") == "temperature"
    # 输出上限报错走 output_cap，这里不能抢；与参数无关的报错不误判
    assert providers.unsupported_param("max_tokens参数非法：限制数值范围[1,131072]") == ""
    assert providers.unsupported_param("model not found") == ""
    assert providers.unsupported_param("") == ""


def test_requirements_files_are_ascii():
    """pip 按系统区域编码读 requirements 文件（中文 Windows 是 GBK）：注释里有中文会让安装直接失败。"""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    for name in ("backend/requirements.txt", "backend/requirements.lock", "backend/requirements-dev.txt"):
        data = (root / name).read_bytes()
        assert all(b < 128 for b in data), name + " 含有非 ASCII 字符"


# ---------------------------------------------------------------- 瞬时错误重试
def _collect(p, model="m"):
    import asyncio

    async def go():
        out = []
        async for kind, text in providers.stream(p, model, "", [], {}):
            out.append((kind, text))
        return out

    return asyncio.run(go())


def test_stream_retries_transient_errors_until_output(monkeypatch):
    import httpx
    monkeypatch.setattr(providers, "_BACKOFF", (0, 0))
    calls = {"n": 0}

    async def fake(p, model, system, messages, opts):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection reset")  # 网络抖动
        if calls["n"] == 2:
            raise providers.ProviderError("HTTP 429：too many requests", status=429)  # 限流
        yield "text", "你好"

    monkeypatch.setitem(providers._STREAMS, "openai", fake)
    assert _collect({"protocol": "openai"}) == [("text", "你好")]
    assert calls["n"] == 3


def test_stream_never_retries_after_output_started(monkeypatch):
    import httpx
    monkeypatch.setattr(providers, "_BACKOFF", (0, 0))
    calls = {"n": 0}

    async def fake(p, model, system, messages, opts):
        calls["n"] += 1
        yield "text", "半句"
        raise httpx.ReadTimeout("timeout")  # 已经开始输出：重试会重复计费，直接报错

    monkeypatch.setitem(providers._STREAMS, "openai", fake)
    try:
        _collect({"protocol": "openai"})
    except providers.ProviderError:
        pass
    else:
        raise AssertionError("应当报错")
    assert calls["n"] == 1  # 没有重试


def test_stream_does_not_retry_client_errors(monkeypatch):
    monkeypatch.setattr(providers, "_BACKOFF", (0, 0))
    calls = {"n": 0}

    async def fake(p, model, system, messages, opts):
        calls["n"] += 1
        raise providers.ProviderError("HTTP 400：model not found", status=400)
        yield  # 让它成为异步生成器

    monkeypatch.setitem(providers._STREAMS, "openai", fake)
    try:
        _collect({"protocol": "openai"})
    except providers.ProviderError as e:
        assert e.status == 400
    else:
        raise AssertionError("应当报错")
    assert calls["n"] == 1  # 4xx 不是抖动，重试无意义


# ---------------------------------------------------------------- 用量统计
def test_usage_is_aggregated_per_day_agent_model():
    agent = {"id": "a1", "name": "甲"}
    usage.record_usage(agent, "m", "c1", {"in": 100, "out": 20, "cached": 50, "saved": 30})
    usage.record_usage(agent, "m", "c1", {"in": 200, "out": 10, "est": True})
    s = usage.usage_summary(30)
    assert s["today"] == {"calls": 2, "in": 300, "out": 30, "cached": 50, "saved": 30, "est": 1}
    assert s["convs"][0]["tokens"] == 330 and s["models"][0]["model"] == "m"


def test_set_doc_never_overwrites_a_document_of_another_kind():
    import sqlite3
    conv = store.put_doc("conversation", {"title": "我的会话"})
    try:
        store.set_doc("runstate", conv["id"], {"since": 1})  # 同一个 id、另一类：必须报错，不能把会话改掉
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("应该拒绝")
    assert store.get_doc("conversation", conv["id"])["title"] == "我的会话"
    store.set_doc("usage", "k1", {"n": 1})
    store.set_doc("usage", "k1", {"n": 2})  # 同类同 id：正常覆盖
    assert store.get_doc("usage", "k1")["n"] == 2
