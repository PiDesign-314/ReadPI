"""Smoke tests for the parts that do not need a live model.

Run:  python tests/test_smoke.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import runner  # noqa: E402


def test_stage_detection() -> None:
    cases = [
        ("INFO babeldoc.docvision.doclayout:Loading ONNX model...", 0),
        ("INFO babeldoc.format.pdf.high_level:start to translate: a.pdf", 2),
        ("WARNING ...:Error Error code: 502 during translation. try fallback", 2),
        ("INFO pdf_creater:PDF save with clean=True completed successfully", 3),
        ("INFO result_merger:Translation completed. Total: 2", 4),
    ]
    for line, expected in cases:
        actual = runner.detect_stage(line)
        assert actual == expected, f"{line!r} -> {actual}, expected {expected}"

    job = runner.Job(id="t", config={}, files=[], command=[])
    for line in [
        "Loading ONNX model...",
        "Parse Page Layout (1/1) ----- 2/2",
        "start to translate: a.pdf",
        "Translation completed. Total: 2",
    ]:
        job.add_log(line)
    assert job.stage == "收尾" and job.progress >= 97, (job.stage, job.progress)
    print("PASS  stage detection + monotonic progress")


def test_build_command() -> None:
    cfg = {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "api_key": "sk-test",
        "lang_in": "en",
        "lang_out": "zh",
        "page_mode": "custom",
        "page_range": "1-3,7",
        "dual_mode": "alternate",
        "output_dir": r"C:\tmp\out",
        "watermark": "no_watermark",
        "glossary_paths": [r"C:\g\terms.csv"],
        "auto_glossary": False,
        "save_glossary": True,
        "qps": 6,
        "custom_prompt": "这是一篇论文",
        "skip_scanned": True,
        "ocr_workaround": False,
        "term_model_enabled": True,
        "term_model": "glm-4-air",
    }
    cmd = runner.build_command(cfg, [r"C:\in\a.pdf", r"C:\in\b.pdf"], "babeldoc.exe")
    joined = " ".join(cmd)
    for fragment in (
        "--openai",
        "--openai-model glm-4-flash",
        "--pages 1-3,7",
        "--use-alternating-pages-dual",
        r"--glossary-files C:\g\terms.csv",
        "--no-auto-extract-glossary",
        "--save-auto-extracted-glossary",
        "--watermark-output-mode no_watermark",
        "--openai-term-extraction-model glm-4-air",
        "--custom-system-prompt 这是一篇论文",
    ):
        assert fragment in joined, fragment
    assert cmd.count("--files") == 2
    assert "--no-dual" in runner.build_command({**cfg, "dual_mode": "mono"}, [], "x")
    # 兼容性优先 turns off rich-text placeholders for long/blank-prone papers.
    assert "--disable-rich-text-translate" not in cmd
    compat = runner.build_command({**cfg, "compat_first": True}, [], "x")
    assert "--disable-rich-text-translate" in compat
    print("PASS  command assembly")


def test_speed_and_cost_knobs() -> None:
    """Workers, thinking switch and the term-token accounting that goes with them."""
    base = {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "api_key": "sk-test",
        "lang_out": "zh",
        "output_dir": r"C:\tmp\out",
        "dual_mode": "side",
        "watermark": "no_watermark",
        "qps": 4,
    }
    # Reasoning models burn ~3/4 of their completion tokens before writing a
    # single translated character; the default asks for it to be turned off.
    tuned = runner.build_command(
        {**base, "provider": "deepseek", "thinking_mode": "off", "pool_workers": 8},
        [],
        "babeldoc.exe",
    )
    joined = " ".join(tuned)
    assert "--openai-thinking disabled" in joined, joined
    assert "--pool-max-workers 8" in joined, joined
    assert " --qps 4" in joined, joined

    # Providers without the switch must not receive it (some gateways answer
    # 400 for an unknown body field, which would fail every batch).
    for provider in ("qwen", "openai", "openrouter", "google_free", "ollama"):
        cmd = runner.build_command(
            {**base, "provider": provider, "thinking_mode": "off"}, [], "babeldoc.exe"
        )
        assert "--openai-thinking" not in cmd, (provider, cmd)

    enabled = runner.build_command(
        {**base, "provider": "zhipu", "thinking_mode": "on"}, [], "babeldoc.exe"
    )
    assert "enabled" in enabled and "--openai-thinking" in enabled, enabled
    assert (
        "--openai-thinking" not in runner.build_command(
            {**base, "provider": "deepseek", "thinking_mode": "auto"}, [], "babeldoc.exe"
        )
    )

    # Workers are clamped, and 0/absent keeps BabelDOC's own default.
    assert runner.pool_workers({"pool_workers": 999}) == runner.MAX_POOL_WORKERS
    assert runner.pool_workers({"pool_workers": -3}) == 0
    assert runner.pool_workers({}) == 0
    assert "--pool-max-workers" not in runner.build_command(
        {**base, "provider": "deepseek", "pool_workers": 0}, [], "babeldoc.exe"
    )

    # The guard receives the same switch so a separate term-extraction model
    # cannot keep reasoning on.
    env = runner.guard_environment(
        {}, Path(tempfile.gettempdir()) / "guard.json", "doc.pdf",
        {"provider": "deepseek", "thinking_mode": "off"},
    )
    assert env.get("BABELDOC_STUDIO_THINKING") == "disabled", env
    untouched = runner.guard_environment(
        {}, Path(tempfile.gettempdir()) / "guard.json", "doc.pdf",
        {"provider": "qwen", "thinking_mode": "off"},
    )
    assert "BABELDOC_STUDIO_THINKING" not in untouched, untouched
    print("PASS  workers + thinking knobs")


def test_output_renaming() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        before = runner._snapshot_dir(out)
        time.sleep(0.01)
        samples = {
            "paper.zh.mono.pdf": "paper_译文.pdf",
            "paper.zh.dual.pdf": "paper_双语对照.pdf",
            "paper.no_watermark.zh.mono.pdf": "paper_译文（无水印）.pdf",
            "other.zh.dual.pdf": "other_双语对照.pdf",
        }
        for name in samples:
            (out / name).write_bytes(b"%PDF-1.4 fake")
        (out / "paper.zh.glossary.csv").write_text("source,target\n", encoding="utf-8")

        results = runner.collect_results(
            out, before, [r"C:\in\paper.pdf", r"C:\in\other.pdf"], "zh"
        )
        # Every artefact of one paper lives in <output>/<paper>/.
        expected = {
            "paper_译文.pdf": out / "paper" / "paper_译文.pdf",
            "paper_双语对照.pdf": out / "paper" / "paper_双语对照.pdf",
            "paper_译文（无水印）.pdf": out / "paper" / "paper_译文（无水印）.pdf",
            "paper_术语表.csv": out / "paper" / "paper_术语表.csv",
            "other_双语对照.pdf": out / "other" / "other_双语对照.pdf",
        }
        got = {item["name"]: Path(item["path"]) for item in results}
        assert got == expected, got
        assert all(path.exists() for path in expected.values())
        # Nothing is left loose in the output root.
        assert sorted(path.name for path in out.iterdir()) == ["other", "paper"]

        # Translating the same paper again reuses the folder instead of
        # scattering a second copy into the root.
        time.sleep(0.01)
        before = runner._snapshot_dir(out)
        (out / "paper.zh.mono.pdf").write_bytes(b"%PDF-1.4 fake")
        again = runner.collect_results(out, before, [r"C:\in\paper.pdf"], "zh")
        assert [item["name"] for item in again] == ["paper_译文 (2).pdf"], again
        assert Path(again[0]["path"]).parent == out / "paper"
    print("PASS  output renaming + per-paper folders")


def test_page_specs() -> None:
    pages = runner.parse_page_spec("1-3,7,9-10")
    assert pages == [1, 2, 3, 7, 9, 10], pages
    assert runner.format_page_spec(pages) == "1-3,7,9-10"
    assert runner.format_page_spec([4]) == "4"

    cfg = {"skip_references": True, "reference_page": "3", "page_mode": "all", "page_range": ""}
    runs = runner.plan_runs(cfg, [r"C:\in\a.pdf"])
    assert runs == [
        {
            "files": [r"C:\in\a.pdf"],
            "pages": "1-2",
            "reference_page": 3,
            "skip": False,
        }
    ], runs

    cfg_custom = {
        "skip_references": True,
        "reference_page": "3",
        "page_mode": "custom",
        "page_range": "2-10",
    }
    runs = runner.plan_runs(cfg_custom, [r"C:\in\a.pdf"])
    assert runs[0]["pages"] == "2", runs

    cfg_off = {"skip_references": False, "page_mode": "all", "reference_page": ""}
    runs = runner.plan_runs(cfg_off, [r"C:\in\a.pdf", r"C:\in\b.pdf"])
    assert len(runs) == 1 and runs[0]["pages"] == "", runs
    print("PASS  page specs + reference run planning")


def test_reference_detection() -> None:
    import pymupdf

    from core import pdfinfo

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "paper.pdf"
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 500, 300), "Intro text\n" * 8, fontsize=12)
        refs = doc.new_page()
        refs.insert_textbox(
            pymupdf.Rect(50, 50, 500, 300),
            "References\n\n[1] A. Author. A paper. 2024.\n",
            fontsize=11,
        )
        doc.save(path)
        doc.close()
        assert pdfinfo.find_references_page(path) == 2
    print("PASS  reference page detection")


def test_reference_mid_page() -> None:
    import pymupdf

    from core import pdfinfo

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "twocol.pdf"
        doc = pymupdf.open()
        doc.new_page()
        page = doc.new_page()
        page.insert_textbox(
            pymupdf.Rect(40, 40, 280, 700),
            "Body text column continues here.\n" * 20,
            fontsize=9,
        )
        page.insert_textbox(
            pymupdf.Rect(320, 420, 560, 700),
            "REFERENCES\n\n[1] A. Author. A paper. 2024.\n",
            fontsize=9,
        )
        doc.save(path)
        doc.close()

        heading = pdfinfo.find_references_heading(path)
        assert heading is not None and heading[0] == 2, heading
        assert heading[1] is False, "mid-page heading must not trigger a page cut"

        cfg = {
            "skip_references": True,
            "page_mode": "all",
            "page_range": "",
            "reference_page": "",
        }
        runs = runner.plan_runs(cfg, [str(path)])
        assert runs[0].get("prompt_mode") is True, runs
        assert runs[0]["pages"] == "", runs

        cmd = runner.build_command(
            {**cfg, "reference_prompt": True, "lang_out": "zh", "custom_prompt": "",
             "model": "m", "base_url": "u", "output_dir": r"C:\tmp\out"},
            [],
            "babeldoc.exe",
        )
        joined = " ".join(cmd)
        assert "--custom-system-prompt" in joined
        assert "--disable-same-text-fallback" in cmd
    print("PASS  mid-page references fall back to prompt mode")


def test_usage_and_cost() -> None:
    from core import pricing

    job = runner.Job(
        id="u",
        config={"model": "deepseek-chat", "provider": "deepseek"},
        files=[],
        command=[],
    )
    job.add_log("2026 INFO babeldoc.main:Total tokens: 1500")
    job.add_log("2026 INFO babeldoc.main:Prompt tokens: 1,200")
    job.add_log("2026 INFO babeldoc.main:Completion tokens: 300")
    job.add_log("2026 INFO babeldoc.main:Cache hit prompt tokens: 200")
    job.add_log(
        "INFO babeldoc.main:Term extraction tokens: total=100 prompt=80 "
        "completion=20 cache_hit_prompt=0"
    )
    job.commit_usage()

    usage = job.total_usage()
    # One model does both phases, so BabelDOC's totals already include the term
    # extraction calls: adding the "Term extraction tokens" line again would
    # double count them (this is what used to inflate the shown cost by ~40%).
    assert usage["prompt_tokens"] == 1200, usage
    assert usage["completion_tokens"] == 300, usage
    assert usage["cached_tokens"] == 200, usage
    # …but the share stays visible for the "其中术语提取" note in the UI.
    assert usage["term_prompt_tokens"] == 80, usage
    assert usage["term_completion_tokens"] == 20, usage

    cost = job.snapshot(0)["cost"]
    assert cost["known"] and cost["currency"] == "CNY", cost
    expected = 1000 / 1e6 * 2.0 + 200 / 1e6 * 0.5 + 300 / 1e6 * 8.0
    assert abs(cost["amount"] - expected) < 1e-9, (cost, expected)

    # A separate term-extraction model reports its own counters, which are NOT
    # part of the translation totals — those must be added.
    separate = runner.Job(
        id="s",
        config={"model": "deepseek-chat", "provider": "deepseek"},
        files=[],
        command=[],
    )
    separate.add_log("INFO babeldoc.main:Total tokens: 1000")
    separate.add_log("INFO babeldoc.main:Prompt tokens: 800")
    separate.add_log("INFO babeldoc.main:Completion tokens: 200")
    separate.add_log("INFO babeldoc.main:Cache hit prompt tokens: 0")
    separate.add_log(
        "INFO babeldoc.main:Term extraction tokens: total=100 prompt=80 "
        "completion=20 cache_hit_prompt=0"
    )
    separate.add_log(
        "INFO babeldoc.main:Term extraction translator raw tokens: total=100 "
        "prompt=80 completion=20 cache_hit_prompt=0"
    )
    separate.commit_usage()
    usage = separate.total_usage()
    assert usage["prompt_tokens"] == 880, usage
    assert usage["completion_tokens"] == 220, usage

    override = pricing.estimate(
        usage, "some-private-model", "custom",
        {"input": 1, "output": 2, "currency": "USD"},
    )
    assert override["known"] and override["source"] == "override", override
    assert override["symbol"] == "$"

    unknown = pricing.estimate(usage, "totally-unknown-model", "custom", {})
    assert unknown["known"] is False
    print("PASS  token usage parsing + cost estimate")


def main() -> None:
    test_stage_detection()
    test_build_command()
    test_speed_and_cost_knobs()
    test_output_renaming()
    test_page_specs()
    test_reference_detection()
    test_reference_mid_page()
    test_usage_and_cost()
    print("ALL OK")


if __name__ == "__main__":
    main()
