"""DraftMate 回归测试 —— 覆盖纯逻辑与可隔离的文件操作,不依赖 ollama/网络/截图/真机。

跑: .venv/bin/python -m unittest test_draftmate -v
"""
from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent
import history
import skills


# ════════════════════ 历史拼接去重(history.stitch / _overlap_len)════════════════════
class TestStitch(unittest.TestCase):
    def _msgs(self, *texts):
        return [{"sender": "对方", "text": t} for t in texts]

    def test_overlap_dedup(self):
        # earlier(更早一屏)的尾部与 known 的头部重叠 → 只把更早的新消息 prepend
        known = self._msgs("c", "d", "e")
        earlier = self._msgs("a", "b", "c", "d")     # 尾 c,d 与 known 头 c,d 重叠
        out, added = history.stitch(known, earlier)
        self.assertEqual([m["text"] for m in out], ["a", "b", "c", "d", "e"])
        self.assertEqual(added, 2)                   # 只新增 a,b

    def test_no_known(self):
        earlier = self._msgs("a", "b")
        out, added = history.stitch([], earlier)
        self.assertEqual([m["text"] for m in out], ["a", "b"])
        self.assertEqual(added, 2)

    def test_empty_earlier(self):
        known = self._msgs("a")
        out, added = history.stitch(known, [])
        self.assertEqual(out, known)
        self.assertEqual(added, 0)

    def test_full_overlap_zero_added(self):
        # 到顶后再滚,earlier 完全被 known 覆盖 → 新增 0(触发到顶检测)
        known = self._msgs("a", "b", "c")
        out, added = history.stitch(known, self._msgs("a", "b", "c"))
        self.assertEqual(added, 0)
        self.assertEqual(len(out), 3)

    def test_sender_in_key(self):
        # 同文本不同发言人不算重叠
        known = [{"sender": "我", "text": "好"}]
        earlier = [{"sender": "对方", "text": "好"}]
        _, added = history.stitch(known, earlier)
        self.assertEqual(added, 1)


# ════════════════════ 微信时间戳解析(history.parse_wechat_date)════════════════════
class TestParseDate(unittest.TestCase):
    T = datetime.date(2026, 6, 12)   # 周五

    def test_pure_time_is_today(self):
        self.assertEqual(history.parse_wechat_date("07:03", self.T), self.T)
        self.assertEqual(history.parse_wechat_date("0:26", self.T), self.T)

    def test_yesterday(self):
        y = self.T - datetime.timedelta(days=1)
        self.assertEqual(history.parse_wechat_date("昨天 16:11", self.T), y)
        self.assertEqual(history.parse_wechat_date("昨大 21:23", self.T), y)   # OCR 容错

    def test_weekday(self):
        self.assertEqual(history.parse_wechat_date("星期三 11:48", self.T), datetime.date(2026, 6, 10))
        self.assertEqual(history.parse_wechat_date("星期二 19:22", self.T), datetime.date(2026, 6, 9))

    def test_ymd(self):
        self.assertEqual(history.parse_wechat_date("2025年12月25日", self.T), datetime.date(2025, 12, 25))

    def test_md_current_year(self):
        self.assertEqual(history.parse_wechat_date("10.7", self.T), datetime.date(2026, 10, 7))

    def test_garbage_returns_none(self):
        self.assertIsNone(history.parse_wechat_date("乱码xyz", self.T))
        self.assertIsNone(history.parse_wechat_date("", self.T))
        self.assertIsNone(history.parse_wechat_date("13.99", self.T))   # 非法月日

    def test_earliest_in_screen_monotonic(self):
        # 一屏多个戳取最早(吸收 OCR 把二/三读混的抖动)
        scr = [{"sender": "系统", "text": "星期三 11:48"},
               {"sender": "系统", "text": "星期二 12:46"},
               {"sender": "对方", "text": "正文不算"}]
        self.assertEqual(history._earliest_in_screen(scr, self.T), datetime.date(2026, 6, 9))

    def test_earliest_no_system(self):
        self.assertIsNone(history._earliest_in_screen([{"sender": "对方", "text": "hi"}], self.T))


# ════════════════════ agent 辅助(render / 温度 / 手动上下文)════════════════════
class TestAgentHelpers(unittest.TestCase):
    def test_render_truncates_to_last_n(self):
        msgs = [{"sender": "对方", "text": str(i)} for i in range(10)]
        out = agent.render(msgs, 3)
        self.assertEqual(out, "对方: 7\n对方: 8\n对方: 9")

    def test_temperature_per_persona(self):
        self.assertLess(agent.temperature_for("serious"), agent.temperature_for("flirty"))
        self.assertGreater(agent.temperature_for("flirty", regen=True), agent.temperature_for("flirty"))
        self.assertLessEqual(agent.temperature_for("flirty", regen=True), 1.0)   # 不超 1.0

    def test_render_manual_context(self):
        self.assertEqual(agent._render_manual_context(None), "(暂无)")
        self.assertEqual(agent._render_manual_context({}), "(暂无)")
        out = agent._render_manual_context({"goal": "推进到暧昧", "person_info": ""})
        self.assertIn("推进到暧昧", out)
        self.assertNotIn("对方信息", out)   # 空字段不出现


# ════════════════════ 人设加载(skills.load_persona,.md 优先 / .local.md 回退)════════════════════
class TestPersona(unittest.TestCase):
    def test_public_persona(self):
        self.assertIn("深情流", skills.load_persona("shenqing"))

    def test_local_fallback(self):
        # 真名版以 .local.md 存在(不入库),应能回退加载
        local = skills.PERSONA_DIR / "tongjincheng.local.md"
        if local.exists():
            self.assertTrue(skills.load_persona("tongjincheng"))
        else:
            self.skipTest("无 tongjincheng.local.md")

    def test_missing_persona(self):
        self.assertEqual(skills.load_persona("不存在的人设xyz"), "")

    def test_manual_context_roundtrip(self):
        # save → load 往返;隔离到临时目录,不碰真实记忆
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(skills, "MEM_DIR", Path(d)):
                skills.save_manual_context("测试人", {"goal": "约出来", "person_info": "USC同学"})
                got = skills.manual_context("测试人")
                self.assertEqual(got["goal"], "约出来")
                self.assertEqual(got["person_info"], "USC同学")

    def test_save_summary(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(skills, "MEM_DIR", Path(d)):
                p = skills.save_summary("张三", "## 画像\n- 爱猫")
                self.assertTrue(p.exists())
                self.assertIn("爱猫", skills.load_memory("张三"))


# ════════════════════ 用量计数(copilot,手动/自动分计)════════════════════
class TestUsage(unittest.TestCase):
    def setUp(self):
        import copilot
        self.copilot = copilot
        self._tmp = Path(tempfile.mkstemp(suffix=".json")[1])
        self._tmp.unlink()
        self._orig = copilot.USAGE_PATH
        copilot.USAGE_PATH = self._tmp

    def tearDown(self):
        self.copilot.USAGE_PATH = self._orig
        if self._tmp.exists():
            self._tmp.unlink()

    def test_split_manual_auto(self):
        self.assertEqual(self.copilot._usage(), {"reads": 0, "auto_reads": 0, "last_used": ""})
        self.copilot._bump_usage()
        self.copilot._bump_usage(auto=True)
        self.copilot._bump_usage(auto=True)
        u = self.copilot._usage()
        self.assertEqual(u["reads"], 1)          # 手动只算 1(周留存指标)
        self.assertEqual(u["auto_reads"], 2)     # 监控触发单独记


# ════════════════════ 云端检测(copilot._cloud_available,无 key 必本地)════════════════════
class TestCloudGate(unittest.TestCase):
    def test_no_key_is_local(self):
        import copilot
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(copilot._cloud_available())


if __name__ == "__main__":
    unittest.main()
