"""Tiny i18n: dict-based string lookup with cookie + Accept-Language resolution.

Adds two values to every template context via Jinja2 context_processors:

- ``t`` — callable: ``t("nav.dashboard")`` or ``t("logs.total", n=27)``
- ``lang`` — the active language code (``"en"`` or ``"zh"``)

Resolution order: ``lang`` query param > cookie > Accept-Language header > ``en``.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request


SUPPORTED: tuple[str, ...] = ("en", "zh")
DEFAULT_LANG = "en"
COOKIE_NAME = "memory_web_lang"


STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # Brand / nav
        "brand": "using-memory",
        "nav.dashboard": "Dashboard",
        "nav.logs": "Logs",
        "nav.search": "Search",
        "nav.docs": "Docs",
        "nav.memory": "Memory",
        "nav.preferences": "Preferences",
        "nav.anatomy": "Anatomy",
        "version_tag": "browse + edit",
        # Common
        "common.apply": "Apply",
        "common.reset": "Reset",
        "common.save": "Save",
        "common.create": "Create",
        "common.cancel": "Cancel",
        "common.edit": "Edit",
        "common.new": "New",
        "common.all": "all",
        "common.optional": "optional",
        "common.back": "← back",
        "common.view_source": "view source",
        "common.markdown_gfm": "Markdown · GFM",
        "common.reload": "Reload",
        "common.reload.title": "Reload this page from disk",
        # Dashboard
        "dashboard.title": "Dashboard",
        "dashboard.sub": "Lifetime stats and project overview · last event {ts}",
        "dashboard.lifetime_counters": "Lifetime counters",
        "dashboard.never": "(never)",
        "dashboard.card.sessions": "Sessions",
        "dashboard.card.sessions.hint": "SessionStart hook invocations",
        "dashboard.card.cumulative_turns": "Cumulative turns",
        "dashboard.card.cumulative_turns.hint": "across all sessions",
        "dashboard.card.log_total": "Log entries total",
        "dashboard.card.log_total.hint": "all JSONL entries on disk",
        "dashboard.card.memory_total": "MEMORY.md entries",
        "dashboard.card.memory_total.hint": "curated facts/decisions/lessons",
        "dashboard.card.log_user": "Log entries (user)",
        "dashboard.card.log_user.hint": "explicit write-log calls",
        "dashboard.card.log_auto": "Log entries (auto)",
        "dashboard.card.log_auto.hint": "silent Stop-hook summaries",
        "dashboard.card.anatomy_projects": "Anatomy projects",
        "dashboard.card.anatomy_projects.hint": "registered roots",
        "dashboard.card.anatomy_attached": "Anatomy attached",
        "dashboard.card.anatomy_attached.hint": "hit rate {pct}%",
        "dashboard.card.anatomy_upserts": "Anatomy upserts",
        "dashboard.card.anatomy_upserts.hint": "PostToolUse incrementals",
        "dashboard.card.stop_blocks": "Stop blocks",
        "dashboard.card.stop_blocks.hint": "block ratio {pct}%",
        "dashboard.card.stop_passthroughs": "Stop passthroughs",
        "dashboard.card.stop_passthroughs.hint": "silent summary appended",
        "dashboard.card.precompact": "PreCompact saves",
        "dashboard.card.precompact.hint": "emergency context dumps",
        "dashboard.log_tags": "Log tags · {n} entries",
        "dashboard.memory_tags": "MEMORY.md tags · {n} entries",
        "dashboard.anatomy_projects": "Anatomy projects · {n}",
        "dashboard.empty.log": "No log entries yet.",
        "dashboard.empty.memory": "No MEMORY.md entries yet.",
        "dashboard.empty.anatomy": "No anatomy projects registered.",
        # Logs
        "logs.title": "Logs",
        "logs.sub": "{n} entries · sorted newest first",
        "logs.form.from": "From",
        "logs.form.to": "To",
        "logs.form.days": "Days",
        "logs.form.q": "Text contains",
        "logs.form.q.placeholder": "substring",
        "logs.form.tag": "Tag",
        "logs.form.level": "Level",
        "logs.form.source": "Source",
        "logs.form.project": "Project",
        "logs.form.topic": "Topic",
        "logs.empty": "No log entries match these filters.",
        # Search
        "search.title": "Search",
        "search.sub": "Full-text across docs, MEMORY.md, and the configured log window",
        "search.form.q": "Query",
        "search.form.q.placeholder": "search term",
        "search.form.log_days": "Log days",
        "search.form.scope": "Scope",
        "search.form.scope.docs": "Docs",
        "search.form.scope.memory": "Memory",
        "search.form.scope.log": "Log",
        "search.form.scope_value.all": "All sources",
        "search.form.scope_value.docs": "Docs only",
        "search.form.scope_value.memory": "Memory only",
        "search.form.scope_value.log": "Log only",
        "search.form.time_range": "Time range",
        "search.form.time_range.7d": "Last 7 days",
        "search.form.time_range.30d": "Last 30 days",
        "search.form.time_range.90d": "Last 90 days",
        "search.form.time_range.180d": "Last 180 days",
        "search.form.time_range.365d": "Last year",
        "search.form.submit": "Search",
        "search.placeholder": "Enter a query above to search across docs, memory, and the log.",
        "search.placeholder.suggest": "Try searching for a slug, a person, a tag, or a phrase that appears in your notes.",
        "search.results.summary": "{total} hit{s} · {d} docs · {m} memory · {l} log",
        "search.section.docs": "Docs",
        "search.section.memory": "MEMORY.md",
        "search.section.log": "Log",
        "search.empty": "No hits.",
        # Docs index
        "docs.title": "Docs",
        "docs.sub": "{n} file{s} in docs/",
        "docs.sub.unindexed": " · {n} not in index.json",
        "docs.new": "New doc",
        "docs.unindexed_badge": "unindexed",
        "docs.empty": "No docs in docs/. Write one with memory_tool.py upsert-doc or drop an .html file in there.",
        "docs.empty.filtered": "No docs match these filters.",
        "docs.filter.type": "Type",
        "docs.filter.format": "Format",
        "docs.filter.project": "Project",
        "docs.filter.tag": "Tag",
        "docs.filter.q": "Title contains",
        "docs.filter.q.placeholder": "title / slug / summary",
        "docs.filter.indexed": "Indexed",
        "docs.filter.indexed.yes": "in index.json",
        "docs.filter.indexed.no": "unindexed",
        "docs.sub.filtered": "{n} / {total} file{s}",
        "docs.meta.modified": "modified",
        "docs.meta.project": "project",
        "docs.meta.tags": "tags",
        "docs.meta.bytes": "bytes",
        # Doc view
        "doc.all_docs": "← all docs",
        "doc.back_to_doc": "← back to doc",
        # Doc editor
        "doc_edit.new_title": "New document",
        "doc_edit.edit_title": "Edit · {slug}",
        "doc_edit.slug": "Slug",
        "doc_edit.type": "Type",
        "doc_edit.modified": "Modified ({optional})",
        "doc_edit.title_field": "Title ({optional} · falls back to first H1, then slug)",
        "doc_edit.projects": "Projects (comma-separated)",
        "doc_edit.tags": "Tags (comma-separated)",
        "doc_edit.summary": "Summary ({optional})",
        "doc_edit.tab.write": "Write",
        "doc_edit.tab.preview": "Preview",
        # Memory
        "memory.title": "MEMORY.md",
        "memory.sub": "Curated stable facts, confirmed decisions, durable lessons",
        "memory.form.title": "Append entry",
        "memory.form.tag": "Tag",
        "memory.form.date": "Date",
        "memory.form.text": "Text",
        "memory.form.text.placeholder": "One stable fact / confirmed decision / durable lesson.",
        "memory.form.submit": "Append",
        "memory.form.hint": "Only fact, decision, lesson are allowed here.",
        "memory.empty": "MEMORY.md is empty. Use the form above to write your first entry.",
        "memory.current": "Current content",
        # Preferences
        "pref.title": "PREFERENCES.md",
        "pref.sub": "Stable user-level habits and rules",
        "pref.form.title": "Append preference",
        "pref.form.text": "Text",
        "pref.form.text.placeholder": "One stable habit / working rule.",
        "pref.form.submit": "Append",
        "pref.form.hint": "Goes to PREFERENCES.md via write-preference.",
        "pref.empty": "PREFERENCES.md is empty. Use the form above to write your first preference.",
        "pref.current": "Current content",
        # Anatomy
        "anatomy.title": "Anatomy",
        "anatomy.sub": "{n} registered project{s}",
        "anatomy.back": "← all projects",
        "anatomy.empty_index": "No anatomy projects registered. Register one with memory_tool.py anatomy-register <root>.",
        "anatomy.empty_files": "This anatomy has no file entries yet. The PostToolUse hook will populate it on the next edit, or run memory_tool.py anatomy-scan {slug}.",
        "anatomy.files_count": "{n} files",
        "anatomy.tokens_count": "{n} tokens",
        "anatomy.scanned": "scanned {ts}",
        "anatomy.col.path": "path",
        "anatomy.col.desc": "description",
        "anatomy.col.kind": "kind",
        "anatomy.col.tokens": "tokens",
        "anatomy.desc.none": "(no description)",
    },
    "zh": {
        # Brand / nav
        "brand": "using-memory",
        "nav.dashboard": "仪表盘",
        "nav.logs": "日志",
        "nav.search": "搜索",
        "nav.docs": "文档",
        "nav.memory": "记忆",
        "nav.preferences": "偏好",
        "nav.anatomy": "项目快照",
        "version_tag": "浏览 + 编辑",
        # Common
        "common.apply": "应用",
        "common.reset": "重置",
        "common.save": "保存",
        "common.create": "创建",
        "common.cancel": "取消",
        "common.edit": "编辑",
        "common.new": "新建",
        "common.all": "全部",
        "common.optional": "可选",
        "common.back": "← 返回",
        "common.view_source": "查看源文",
        "common.markdown_gfm": "Markdown · GFM",
        "common.reload": "刷新",
        "common.reload.title": "从磁盘重新加载本页",
        # Dashboard
        "dashboard.title": "仪表盘",
        "dashboard.sub": "全生命周期统计与项目概览 · 最近事件 {ts}",
        "dashboard.lifetime_counters": "累计计数",
        "dashboard.never": "（无）",
        "dashboard.card.sessions": "会话数",
        "dashboard.card.sessions.hint": "SessionStart hook 触发次数",
        "dashboard.card.cumulative_turns": "累计轮次",
        "dashboard.card.cumulative_turns.hint": "跨所有会话",
        "dashboard.card.log_total": "日志总条数",
        "dashboard.card.log_total.hint": "磁盘上所有 JSONL 条目",
        "dashboard.card.memory_total": "MEMORY.md 条数",
        "dashboard.card.memory_total.hint": "精选的事实/决策/教训",
        "dashboard.card.log_user": "日志（用户）",
        "dashboard.card.log_user.hint": "显式 write-log 调用",
        "dashboard.card.log_auto": "日志（自动）",
        "dashboard.card.log_auto.hint": "Stop hook 静默摘要",
        "dashboard.card.anatomy_projects": "项目快照数",
        "dashboard.card.anatomy_projects.hint": "已注册的项目根",
        "dashboard.card.anatomy_attached": "快照已附加",
        "dashboard.card.anatomy_attached.hint": "命中率 {pct}%",
        "dashboard.card.anatomy_upserts": "快照增量更新",
        "dashboard.card.anatomy_upserts.hint": "PostToolUse 增量",
        "dashboard.card.stop_blocks": "Stop 拦截",
        "dashboard.card.stop_blocks.hint": "拦截比例 {pct}%",
        "dashboard.card.stop_passthroughs": "Stop 放行",
        "dashboard.card.stop_passthroughs.hint": "已静默追加摘要",
        "dashboard.card.precompact": "压缩前应急保存",
        "dashboard.card.precompact.hint": "上下文压缩前应急写入",
        "dashboard.log_tags": "日志标签 · {n} 条",
        "dashboard.memory_tags": "MEMORY.md 标签 · {n} 条",
        "dashboard.anatomy_projects": "项目快照 · {n} 个",
        "dashboard.empty.log": "暂无日志条目。",
        "dashboard.empty.memory": "暂无 MEMORY.md 条目。",
        "dashboard.empty.anatomy": "暂无注册的项目快照。",
        # Logs
        "logs.title": "日志",
        "logs.sub": "{n} 条 · 按时间倒序",
        "logs.form.from": "起始",
        "logs.form.to": "截止",
        "logs.form.days": "天数",
        "logs.form.q": "文本包含",
        "logs.form.q.placeholder": "关键词",
        "logs.form.tag": "标签",
        "logs.form.level": "级别",
        "logs.form.source": "来源",
        "logs.form.project": "项目",
        "logs.form.topic": "主题",
        "logs.empty": "没有匹配的日志条目。",
        # Search
        "search.title": "搜索",
        "search.sub": "在文档、MEMORY.md 与配置的日志窗口中做全文搜索",
        "search.form.q": "查询",
        "search.form.q.placeholder": "搜索词",
        "search.form.log_days": "日志天数",
        "search.form.scope": "范围",
        "search.form.scope.docs": "文档",
        "search.form.scope.memory": "记忆",
        "search.form.scope.log": "日志",
        "search.form.scope_value.all": "全部来源",
        "search.form.scope_value.docs": "仅文档",
        "search.form.scope_value.memory": "仅记忆",
        "search.form.scope_value.log": "仅日志",
        "search.form.time_range": "时间范围",
        "search.form.time_range.7d": "最近 7 天",
        "search.form.time_range.30d": "最近 30 天",
        "search.form.time_range.90d": "最近 90 天",
        "search.form.time_range.180d": "最近 180 天",
        "search.form.time_range.365d": "最近一年",
        "search.form.submit": "搜索",
        "search.placeholder": "在上方输入查询词以搜索文档、记忆和日志。",
        "search.placeholder.suggest": "可以试试 slug、人名、标签，或者笔记里出现过的短语。",
        "search.results.summary": "共 {total} 项命中 · 文档 {d} · 记忆 {m} · 日志 {l}",
        "search.section.docs": "文档",
        "search.section.memory": "MEMORY.md",
        "search.section.log": "日志",
        "search.empty": "无命中。",
        # Docs index
        "docs.title": "文档",
        "docs.sub": "docs/ 下共 {n} 个文件",
        "docs.sub.unindexed": " · {n} 个未在 index.json 中注册",
        "docs.new": "新建文档",
        "docs.unindexed_badge": "未注册",
        "docs.empty": "docs/ 下还没有文档。用 memory_tool.py upsert-doc 创建一个，或直接丢一个 .html 文件进来。",
        "docs.empty.filtered": "没有匹配的文档。",
        "docs.filter.type": "类型",
        "docs.filter.format": "格式",
        "docs.filter.project": "项目",
        "docs.filter.tag": "标签",
        "docs.filter.q": "标题包含",
        "docs.filter.q.placeholder": "标题 / slug / 摘要",
        "docs.filter.indexed": "是否注册",
        "docs.filter.indexed.yes": "已注册",
        "docs.filter.indexed.no": "未注册",
        "docs.sub.filtered": "{n} / {total} 个文件",
        "docs.meta.modified": "修改于",
        "docs.meta.project": "项目",
        "docs.meta.tags": "标签",
        "docs.meta.bytes": "字节",
        # Doc view
        "doc.all_docs": "← 所有文档",
        "doc.back_to_doc": "← 返回文档",
        # Doc editor
        "doc_edit.new_title": "新建文档",
        "doc_edit.edit_title": "编辑 · {slug}",
        "doc_edit.slug": "Slug",
        "doc_edit.type": "类型",
        "doc_edit.modified": "修改日期（{optional}）",
        "doc_edit.title_field": "标题（{optional} · 缺省取首个 H1，再不行用 slug）",
        "doc_edit.projects": "项目（逗号分隔）",
        "doc_edit.tags": "标签（逗号分隔）",
        "doc_edit.summary": "摘要（{optional}）",
        "doc_edit.tab.write": "编辑",
        "doc_edit.tab.preview": "预览",
        # Memory
        "memory.title": "MEMORY.md",
        "memory.sub": "精选的稳定事实、已确认决策、长期教训",
        "memory.form.title": "追加条目",
        "memory.form.tag": "标签",
        "memory.form.date": "日期",
        "memory.form.text": "正文",
        "memory.form.text.placeholder": "一条稳定事实 / 已确认决策 / 长期教训。",
        "memory.form.submit": "追加",
        "memory.form.hint": "此处仅允许 fact、decision、lesson。",
        "memory.empty": "MEMORY.md 是空的。用上方表单写入第一条。",
        "memory.current": "当前内容",
        # Preferences
        "pref.title": "PREFERENCES.md",
        "pref.sub": "稳定的用户级习惯与规则",
        "pref.form.title": "追加偏好",
        "pref.form.text": "正文",
        "pref.form.text.placeholder": "一条稳定的习惯 / 工作规则。",
        "pref.form.submit": "追加",
        "pref.form.hint": "通过 write-preference 写入 PREFERENCES.md。",
        "pref.empty": "PREFERENCES.md 是空的。用上方表单写入第一条。",
        "pref.current": "当前内容",
        # Anatomy
        "anatomy.title": "项目快照",
        "anatomy.sub": "已注册 {n} 个项目",
        "anatomy.back": "← 所有项目",
        "anatomy.empty_index": "暂无注册的项目快照。用 memory_tool.py anatomy-register <root> 注册一个。",
        "anatomy.empty_files": "这个项目快照还没有文件条目。下次 Write/Edit 时 PostToolUse hook 会自动填充，也可以手动跑 memory_tool.py anatomy-scan {slug}。",
        "anatomy.files_count": "{n} 个文件",
        "anatomy.tokens_count": "{n} tokens",
        "anatomy.scanned": "扫描于 {ts}",
        "anatomy.col.path": "路径",
        "anatomy.col.desc": "描述",
        "anatomy.col.kind": "类型",
        "anatomy.col.tokens": "tokens",
        "anatomy.desc.none": "（无描述）",
    },
}


class Translator:
    """Callable that resolves ``t("key")`` against ``STRINGS[lang]`` with fallback to English."""

    __slots__ = ("lang",)

    def __init__(self, lang: str) -> None:
        self.lang = lang if lang in SUPPORTED else DEFAULT_LANG

    def __call__(self, key: str, **kwargs: Any) -> str:
        s = STRINGS.get(self.lang, {}).get(key)
        if s is None:
            s = STRINGS[DEFAULT_LANG].get(key, key)
        if kwargs:
            try:
                return s.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return s
        return s


def resolve_lang(*, query: str | None, cookie: str | None, accept_language: str | None) -> str:
    """Pick the active language. Order: explicit query param > cookie > Accept-Language > default."""
    if query and query in SUPPORTED:
        return query
    if cookie and cookie in SUPPORTED:
        return cookie
    if accept_language:
        # Tiny parser: just check whether the most-preferred language starts with "zh".
        for chunk in accept_language.split(","):
            code = chunk.split(";", 1)[0].strip().lower()
            if code.startswith("zh"):
                return "zh"
            if code.startswith("en"):
                return "en"
    return DEFAULT_LANG


def lang_context(request: Request) -> dict[str, Any]:
    """Jinja2 context processor: inject ``t`` and ``lang`` into every TemplateResponse."""
    lang = getattr(request.state, "lang", DEFAULT_LANG)
    return {"t": Translator(lang), "lang": lang, "supported_langs": SUPPORTED}
