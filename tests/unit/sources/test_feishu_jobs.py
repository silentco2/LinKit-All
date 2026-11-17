import json

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.feishu_jobs import FeishuJobs
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def test_search_posts_like_the_tenants_own_page(search_pages, load_fixture):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("feishu-jobs/posts.json"))

    ((a, b),) = search_pages(FeishuJobs(), handler, board="vrfi1sk8a0.jobs.feishu.cn")
    (req,) = seen
    assert str(req.url) == "https://vrfi1sk8a0.jobs.feishu.cn/api/v1/search/job/posts"
    assert json.loads(req.content) == {"limit": 100, "offset": 0}
    assert req.headers["user-agent"] != "" and "Macintosh" not in req.headers["user-agent"]
    assert (a.title, a.location) == ("大模型算法工程师", "上海/北京")
    assert a.url == "https://vrfi1sk8a0.jobs.feishu.cn/index/position/7300000000000000001/detail"
    assert a.description.startswith("Category: 研发\nType: 社招\n负责模型训练。")
    assert a.posted_at is not None and b.location == "Singapore"


def test_bytedance_uses_its_own_route():
    stub = FeishuJobs.stub({"id": "9", "title": "SRE"}, "jobs.bytedance.com")
    assert stub and stub.url == "https://jobs.bytedance.com/experienced/position/9/detail"
    assert stub.company == "ByteDance"


def test_url_patterns():
    assert detect("https://vrfi1sk8a0.jobs.feishu.cn/index") == (
        "feishu-jobs",
        "vrfi1sk8a0.jobs.feishu.cn",
    )
    assert detect("https://jobs.bytedance.com/experienced/position") == (
        "feishu-jobs",
        "jobs.bytedance.com",
    )
