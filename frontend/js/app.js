/* =========================================================================
   KB Workbench — frontend logic (Vue 3 global build, no build step)
   ========================================================================= */
(function () {
  "use strict";

  const MD = (window.marked && window.marked.parse)
    ? window.marked.parse.bind(window.marked)
    : function (t) { return t; };

  /* ---- tiny API helper ---------------------------------------------- */
  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const ct = res.headers.get("content-type") || "";
    return ct.indexOf("application/json") !== -1 ? res.json() : res.text();
  }
  function apiJson(path, method, body) {
    return api(path, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  }

  function relTime(sec) {
    const diff = Math.floor(Date.now() / 1000) - sec;
    if (diff < 60) return "刚刚";
    if (diff < 3600) return Math.floor(diff / 60) + " 分钟前";
    if (diff < 86400) return Math.floor(diff / 3600) + " 小时前";
    if (diff < 86400 * 7) return Math.floor(diff / 86400) + " 天前";
    return new Date(sec * 1000).toISOString().slice(0, 10);
  }

  /* ---- recursive tree component ------------------------------------- */
  const TreeNode = {
    name: "tree-node",
    props: { node: Object, depth: Number, sel: String },
    data() { return { open: this.depth < 2 }; },
    template: `
      <div class="tree-node">
        <div class="tree-row"
             :class="{ sel: node.type==='file' && node.path===sel, 'tree-file': node.type==='file' }"
             @click="onClick">
          <svg v-if="node.type==='dir'" class="tw-chev" :class="{open: open}"
               viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 6l6 6-6 6"/></svg>
          <svg v-else class="tw-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 2h9l5 5v15H6z"/><path d="M14 2v6h6"/></svg>
          <span>{{ node.name }}</span>
        </div>
        <div class="tree-children" v-if="node.type==='dir' && open">
          <tree-node v-for="c in node.children" :key="c.path" :node="c"
                     :depth="depth + 1" :sel="sel"
                     @select="$emit('select', $event)" @open="$emit('open', $event)"></tree-node>
        </div>
      </div>
    `,
    methods: {
      onClick() {
        if (this.node.type === "dir") {
          this.open = !this.open;
        } else {
          this.$emit("select", this.node.path);
          this.$emit("open", this.node.path);
        }
      },
    },
  };

  /* ---- root component ----------------------------------------------- */
  const Root = {
    components: { "tree-node": TreeNode },
    data() {
      return {
        view: "dashboard",
        kbRoot: "",
        tree: { name: "vault", path: "", type: "dir", children: [] },
        selectedFile: "",
        fileContent: "",
        editorMode: "read",
        saving: false,
        searchQuery: "",
        searchResults: [],
        searched: false,
        tasks: [],
        newTaskTitle: "",
        dragId: null,
        dragOver: null,
        reportType: "weekly",
        reportDate: "",
        reportData: null,
        config: {},
        stats: {},
        theme: "dark",
        topSearch: "",
        showNewModal: false,
        newFileDir: "",
        newFileName: "",
        toastMsg: "",
        toastType: "",
        recentFiles: [],
        /* ---- work zone (日常工作) ---- */
        workNavOpen: false,
        workTab: "overview",
        workItems: [],
        workBoard: {},
        workMeta: {},
        workSel: "",
        workItem: null,
        workBody: "",
        workRead: true,
        workSaving: false,
        workFilterQ: "",
        workTitle: "",
        workProject: "",
        workTags: "",
        convEditPath: "",
        convDraft: "",
        workNew: { show: false, type: "requirement", title: "", project: "", priority: "medium" },
        workImport: {
          show: false, dir: "", files: [], project: "", type: "",
          picked: {}, scanning: false, scanned: false,
        },
        /* ---- 金融日记 (diary) ---- */
        diaryYears: [],
        diaryYear: "",
        diaryYearData: null,
        diaryMonth: -1,        // -1 = 全部（浮窗列全年）；0-11 = 指定月（浮窗只列该月）
        diaryPick: "",         // 「打开日期」输入框当前值 YYYY-MM-DD，跟随正在看的那天
        diaryListOpen: false,  // 篇数浮窗开关
        diarySel: "",
        diaryItem: { exists: false },
        diaryBody: "",
        diaryTitle: "",
        diaryTags: "",
        diaryRead: true,
        diarySaving: false,
        /* ---- 日报 / 周报（手动主观） ---- */
        dreportKind: "daily",
        dreportYears: [],
        dreportYear: "",
        dreportYearData: null,   // {year, entries[]}：日报 / 周报同一个接口，key = 日期（周报 = 周一）
        dreportMonth: -1,        // -1 = 全年（筛选用），0-11 = 指定月份（仅日报）
        dreportFilter: "",       // 结果条关键词筛选
        dreportPick: "",         // 「打开日期 / 打开周」输入框当前值
        dreportSel: "",
        dreportItem: { exists: false },
        dreportBody: "",
        dreportTitle: "",
        dreportTags: "",
        dreportRead: true,
        dreportSaving: false,
        /* ---- AI 问答 (RAG) ---- */
        chatMessages: [],
        chatInput: "",
        chatScope: "",
        chatBusy: false,
        /* ---- 设置：AI 模型配置 ---- */
        llmSettings: {},          // 后端 /api/settings/llm 的完整视图（Key 已脱敏）
        llmForm: { provider: "deepseek", api_key: "", model: "", base_url: "" },
        llmSaving: false,
        llmTesting: false,
        llmTestMsg: "",
        llmTestOk: false,
        _toastTimer: null,
        _searchTimer: null,
      };
    },
    computed: {
      /* ---- 设置：AI 模型 ---- */
      llmProviderMeta() {
        const list = this.llmSettings.providers || [];
        return list.find((p) => p.id === this.llmForm.provider) || null;
      },
      llmNeedsKey() {
        return this.llmProviderMeta ? this.llmProviderMeta.needs_key : true;
      },
      llmDefaultModel() {
        return this.llmProviderMeta ? this.llmProviderMeta.default_model : "";
      },
      llmKeyPlaceholder() {
        if (!this.llmNeedsKey) return "无需填写（本地 Ollama）";
        if (this.llmSettings.has_key) {
          return "已保存 " + this.llmSettings.key_masked + "，留空则不修改";
        }
        return "粘贴 " + this.llmProviderLabel(this.llmForm.provider) + " 的 API Key";
      },
      // 只在"值不是内置默认"时提示来源，帮用户理解为什么页面改了却不生效
      llmSourceNote() {
        const src = this.llmSettings.source || {};
        const labels = this.llmSettings.source_labels || {};
        const names = { provider: "供应商", api_key: "API Key", model: "模型名", base_url: "Base URL" };
        const parts = [];
        Object.keys(names).forEach((k) => {
          const s = src[k];
          if (s && s !== "default") parts.push(names[k] + " 来自" + (labels[s] || s));
        });
        return parts.join("　·　");
      },
      greeting() {
        const h = new Date().getHours();
        if (h < 6) return "夜深了";
        if (h < 12) return "早上好";
        if (h < 14) return "中午好";
        if (h < 18) return "下午好";
        return "晚上好";
      },
      pageTitle() {
        return {
          dashboard: "概览",
          knowledge: "知识库",
          search: "检索",
          tasks: "任务看板",
          reports: "日志",
          work: "日常工作",
          diary: "金融日记",
          dreport: "日报 / 周报",
          chat: "AI 问答",
          settings: "设置",
        }[this.view] || "";
      },
      /* 知识分区显示名: 目录路径 → 界面中文名, 避免面包屑露出 interview 这类英文路径 */
      kbRootLabel() {
        return {
          "learn/ai": "AI 学习",
          interview: "未来准备",
        }[this.kbRoot] || this.kbRoot;
      },
      crumb() {
        if (this.view === "knowledge" && this.kbRoot) return this.kbRootLabel;
        if (this.view === "work" && this.workTab !== "overview") return this.workTabLabel;
        return "";
      },
      /* 知识库与工作台(列表+详情)共用「自身分栏滚动」的布局; 总览/约定页正常整页滚动 */
      kbViewClass() {
        if (this.view === "knowledge") return true;
        if (this.view === "work") {
          return !["overview", "convention"].includes(this.workTab);
        }
        return false;
      },
      workTabLabel() {
        return {
          overview: "总览", requirement: "需求", design: "设计",
          dev: "开发", bug: "Bug", convention: "约定",
        }[this.workTab] || "";
      },
      /* 子菜单 = 同一批文件按 type 过滤 */
      workType() {
        return ["requirement", "design", "dev", "bug", "convention"].includes(this.workTab)
          ? this.workTab : null;
      },
      workKindChips() {
        const c = this.workBoard.counts || {};
        return [
          { type: "requirement", label: "需求", count: c.requirement || 0 },
          { type: "design", label: "设计", count: c.design || 0 },
          { type: "dev", label: "开发", count: c.dev || 0 },
          { type: "bug", label: "Bug", count: c.bug || 0 },
          { type: "convention", label: "约定", count: c.convention || 0 },
        ];
      },
      severityOptions() {
        return this.workMeta.severities || [];
      },
      /* 分组顺序跟随后端 projects()(版本新→旧: 12版本开发 → 0828 → 0820 → 0818)，
         不在项目列表里的(_conventions / _inbox / 未归属)沉底。
         注意：别用 localeCompare 排中文 -- 拼音序会把「12版本开发」甩到最后。 */
      groupedWork() {
        const q = (this.workFilterQ || "").trim().toLowerCase();
        const list = this.workItems.filter((it) => {
          if (!q) return true;
          return [it.title, it.id, it.project, (it.tags || []).join(" ")]
            .join(" ").toLowerCase().includes(q);
        });
        const map = new Map();
        list.forEach((it) => {
          const key = it.project || "未归属";
          if (!map.has(key)) map.set(key, []);
          map.get(key).push(it);
        });
        const order = this.workMeta.projects || [];
        const rank = (name) => {
          const i = order.indexOf(name);
          return i === -1 ? order.length : i;
        };
        return [...map.entries()]
          .map(([name, items]) => ({ name, items, rank: rank(name) }))
          .sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name, "zh"))
          .map(({ name, items }) => ({ name, items }));
      },
      pickedCount() {
        return Object.values(this.workImport.picked || {}).filter(Boolean).length;
      },
      previewHtml() {
        let html = MD(this.fileContent || "");
        // Rewrite relative image paths to the in-app /vault/ route so that
        // images bundled next to a Markdown note render correctly.
        const base = this.selectedFile || "";
        const dir = base.includes("/") ? base.slice(0, base.lastIndexOf("/")) : "";
        if (dir) {
          html = html.replace(
            /<img\b[^>]*\bsrc="((?!https?:|data:|blob:|\/\/)[^"]*)"/gi,
            (m, src) =>
              m.replace(src, src.startsWith("/") ? src : "/vault/" + dir + "/" + src)
          );
        }
        return html;
      },
      openTasks() {
        return this.tasks.filter((t) => t.status !== "done");
      },
      /* 分区视图(如 AI 学习)只显示该子目录的文件树, 顶层的"知识库"入口仍显示全库 */
      displayTree() {
        if (!this.kbRoot) return this.tree;
        const find = (n) => {
          if (n.path === this.kbRoot) return n;
          for (const c of n.children || []) {
            const hit = find(c);
            if (hit) return hit;
          }
          return null;
        };
        return find(this.tree) || this.tree;
      },
      /* ---- 金融日记 (diary) ---- */
      diaryEntryList() {
        return (this.diaryYearData && this.diaryYearData.entries) || [];
      },
      /* 浮窗范围 = 当前年 + 当前月（月份为「全部」时即全年） */
      diaryRangeCount() {
        if (this.diaryMonth < 0) return this.diaryEntryList.length;
        const mm = String(this.diaryMonth + 1).padStart(2, "0");
        return this.diaryEntryList.filter((e) => e.date.slice(5, 7) === mm).length;
      },
      diaryRangeLabel() {
        return this.diaryMonth < 0 ? "全年" : this.diaryMonth + 1 + " 月";
      },
      /* 浮窗列表：倒序（最新在上）；标题常以日期开头，单列日期后去掉重复前缀，过长截断 */
      diaryPopList() {
        let list = this.diaryEntryList;
        if (this.diaryMonth >= 0) {
          const mm = String(this.diaryMonth + 1).padStart(2, "0");
          list = list.filter((e) => e.date.slice(5, 7) === mm);
        }
        return list.slice().reverse().map((e) => {
          let t = (e.title || "").trim();
          if (t.indexOf(e.date) === 0) t = t.slice(e.date.length).trim();
          return { date: e.date, label: t || "（无标题）" };
        });
      },
      /* ---- 日报 / 周报（手动主观）—— 查询条件与「金融日记」同一套 ---- */
      dreportEntryList() {
        return (this.dreportYearData && this.dreportYearData.entries) || [];
      },
      /* 查询条件：年份由后端按年取，月份（仅日报）+ 关键词在前端过滤 */
      dreportHits() {
        let list = this.dreportEntryList;
        if (this.dreportKind === "daily") {
          const m = Number(this.dreportMonth);
          if (m >= 0) {
            const mm = String(m + 1).padStart(2, "0");
            list = list.filter((e) => e.key.slice(5, 7) === mm);
          }
        }
        const kw = (this.dreportFilter || "").trim().toLowerCase();
        if (kw) {
          // 同日记：只筛「列表里显示的那行字」（标题；标题为空时后端已兜底为键）
          list = list.filter((e) => (e.title || e.key).toLowerCase().indexOf(kw) >= 0);
        }
        return list;
      },
      dreportStats() {
        const total = this.dreportEntryList.length;
        const hit = this.dreportHits.length;
        return hit === total ? `全年 ${total} 篇` : `命中 ${hit} / 全年 ${total} 篇`;
      },
      /* 结果条：当前正在看的那篇不重复出现；周报没自定义标题时显示「周区间」比裸日期好认 */
      dreportChips() {
        const weekly = this.dreportKind === "weekly";
        return this.dreportHits
          .filter((e) => e.key !== this.dreportSel)
          .map((e) => {
            const untitled = !e.title || e.title === e.key;
            return {
              key: e.key,
              label: weekly && untitled ? this._weekLabel(e.key) : (e.title || e.key),
              tip: weekly
                ? e.key + " 起 · " + this._weekLabel(e.key) + " · 第 " + this._weekNo(e.key) + " 周"
                : e.key,
            };
          });
      },
    },
    methods: {
      md(t) { return MD(t || ""); },
      toast(msg, type) {
        this.toastMsg = msg;
        this.toastType = type || "";
        if (this._toastTimer) clearTimeout(this._toastTimer);
        this._toastTimer = setTimeout(() => (this.toastMsg = ""), 2600);
      },
      nav(view, root) {
        const nextRoot = root || "";
        // 在知识分区之间切换（全库 / AI 学习 / 未来准备）时，必须把右侧阅读区一起关掉，
        // 否则左侧树已经换了、右侧还挂着上一个分区打开的那篇笔记。
        const kbZoneChanged = view === "knowledge" && this.kbRoot !== nextRoot;
        this.view = view;
        this.kbRoot = nextRoot;
        if (kbZoneChanged) {
          this.selectedFile = "";
          this.fileContent = "";
          this.editorMode = "read";
        }
        if (view === "knowledge") this.loadTree();
        if (view === "tasks") this.loadTasks();
        if (view === "reports" && !this.reportData) this.loadReport();
        if (view === "dreport" && !this.dreportYears.length) this.loadDreportYears();
        if (view === "settings") this.loadLlmSettings();
        // 每次回到概览都重新拉取, 保证任务数与待办列表是最新的
        if (view === "dashboard") { this.loadStats(); this.loadTasks(); }
      },
      /* ---- AI 问答 (RAG) ---- */
      async sendChat() {
        const q = (this.chatInput || "").trim();
        if (!q || this.chatBusy) return;
        this.chatMessages.push({ role: "user", text: q });
        this.chatInput = "";
        this.chatBusy = true;
        this.$nextTick(this.scrollChat);
        try {
          const res = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ q: q, scope: this.chatScope }),
          });
          const d = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(d.error || ("HTTP " + res.status));
          this.chatMessages.push({
            role: "assistant",
            text: d.answer || "(空回答)",
            sources: d.sources || [],
          });
        } catch (e) {
          this.chatMessages.push({
            role: "assistant",
            text: "❌ " + (e.message || e),
            sources: [],
          });
        } finally {
          this.chatBusy = false;
          this.$nextTick(this.scrollChat);
        }
      },
      scrollChat() {
        const el = this.$refs.chatList;
        if (el) el.scrollTop = el.scrollHeight;
      },
      openChatSource(s) {
        if (s && s.path) this.openFile(s.path);
      },
      /* ---- tree / files ---- */
      async loadTree() {
        try {
          this.tree = await api("/api/tree");
          this.buildRecent();
        } catch (e) { this.toast("加载目录失败", "err"); }
      },
      buildRecent() {
        const acc = [];
        const walk = (n) => {
          if (n.type === "file") acc.push(n);
          (n.children || []).forEach(walk);
        };
        walk(this.tree);
        acc.sort((a, b) => (b.mtime || 0) - (a.mtime || 0));
        this.recentFiles = acc.slice(0, 8).map((f) => ({
          name: f.name, path: f.path, rel: relTime(f.mtime || 0),
        }));
      },
      onTreeSelect(path) { this.selectedFile = path; this.loadFile(path); },
      openFile(path) {
        this.view = "knowledge";
        this.selectedFile = path;
        this.loadFile(path);
      },
      async loadFile(path) {
        try {
          const d = await api("/api/file?path=" + encodeURIComponent(path));
          this.fileContent = d.content;
          this.selectedFile = path;
          // derive default new-file dir from current path
          this.newFileDir = path.includes("/")
            ? path.slice(0, path.lastIndexOf("/"))
            : "";
        } catch (e) { this.toast("打开失败：" + path, "err"); }
      },
      async saveFile() {
        if (!this.selectedFile) return;
        this.saving = true;
        try {
          await apiJson("/api/file", "POST", {
            path: this.selectedFile, content: this.fileContent,
          });
          this.toast("已保存", "ok");
          this.loadTree();
        } catch (e) { this.toast("保存失败", "err"); }
        finally { this.saving = false; }
      },
      newFile() { this.showNewModal = true; },
      async confirmNewFile() {
        let name = (this.newFileName || "").trim();
        if (!name) { this.toast("请输入文件名", "err"); return; }
        if (!name.toLowerCase().endsWith(".md")) name += ".md";
        const dir = (this.newFileDir || "").trim();
        const path = dir ? dir + "/" + name : name;
        try {
          await apiJson("/api/file", "POST", {
            path: path, content: "# " + name.replace(/\.md$/i, "") + "\n\n",
          });
          this.showNewModal = false;
          this.newFileName = "";
          this.editorMode = "edit"; // 新建后直接进入编辑模式
          this.loadTree();
          this.openFile(path);
          this.toast("已创建 " + path, "ok");
        } catch (e) { this.toast("创建失败", "err"); }
      },
      async deleteFile() {
        if (!this.selectedFile) return;
        if (!window.confirm("确认删除 " + this.selectedFile + " ？")) return;
        try {
          await api("/api/file?path=" + encodeURIComponent(this.selectedFile), { method: "DELETE" });
          this.toast("已删除", "ok");
          this.selectedFile = "";
          this.fileContent = "";
          this.loadTree();
        } catch (e) { this.toast("删除失败", "err"); }
      },
      /* ---- search ---- */
      goSearch() {
        this.searchQuery = this.topSearch;
        this.view = "search";
        this.doSearch();
      },
      doSearch() {
        const q = (this.searchQuery || "").trim();
        if (!q) { this.searchResults = []; this.searched = false; return; }
        api("/api/search?q=" + encodeURIComponent(q))
          .then((d) => { this.searchResults = d.results || []; this.searched = true; })
          .catch(() => this.toast("检索失败", "err"));
      },
      debouncedSearch() {
        if (this._searchTimer) clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => this.doSearch(), 280);
      },
      /* ---- tasks ---- */
      async loadTasks() {
        try { this.tasks = (await api("/api/tasks")).tasks || []; }
        catch (e) { this.toast("加载任务失败", "err"); }
      },
      colTasks(s) { return this.tasks.filter((t) => t.status === s); },
      prioLabel(p) {
        return { high: "高", medium: "中", low: "低" }[p] || "中";
      },
      async addTask() {
        const title = (this.newTaskTitle || "").trim();
        if (!title) return;
        try {
          await apiJson("/api/tasks", "POST", { title: title, status: "todo" });
          this.newTaskTitle = "";
          this.loadTasks();
        } catch (e) { this.toast("添加失败", "err"); }
      },
      async cycleStatus(t, status) {
        try {
          await apiJson("/api/tasks/" + t.id, "PUT", { status: status });
          this.loadTasks();
        } catch (e) { this.toast("更新失败", "err"); }
      },
      async delTask(id) {
        try {
          await api("/api/tasks/" + id, { method: "DELETE" });
          this.loadTasks();
        } catch (e) { this.toast("删除失败", "err"); }
      },
      dropTask(status) {
        this.dragOver = null;
        if (this.dragId == null) return;
        const t = this.tasks.find((x) => x.id === this.dragId);
        if (t && t.status !== status) this.cycleStatus(t, status);
        this.dragId = null;
      },
      /* ---- reports ---- */
      setReport(type) { this.reportType = type; this.loadReport(); },
      async loadReport() {
        const d = this.reportDate || "";
        try {
          this.reportData = await api(
            "/api/report?type=" + this.reportType +
            (d ? "&date=" + encodeURIComponent(d) : "")
          );
        } catch (e) { this.toast("生成报告失败", "err"); }
      },
      /* ---- 日常工作 (work zone) ---- */
      typeLabel(t) {
        return {
          requirement: "需求", design: "设计", dev: "开发",
          bug: "Bug", convention: "约定", note: "笔记",
        }[t] || t;
      },
      statusLabel(s) {
        return (this.workMeta.status_label || {})[s] || s;
      },
      statusOptions(type) {
        return ((this.workMeta.status_flow || {})[type] || []);
      },
      severityLabel(s) {
        const hit = (this.workMeta.severities || []).find((x) => x.value === s);
        return hit ? hit.label : s;
      },
      statusBadge(s) {
        if (["released", "closed", "done", "approved"].includes(s)) return "success";
        if (["dev", "fixing", "doing", "testing", "staging", "verifying", "locating"].includes(s)) return "warn";
        if (["paused", "blocked", "dropped", "wontfix"].includes(s)) return "danger";
        return "";
      },
      workTabForType(t) {
        return ["requirement", "design", "dev", "bug", "convention"].includes(t) ? t : "overview";
      },
      navWork(tab) {
        this.view = "work";
        this.kbRoot = "";
        this.workNavOpen = true;
        this.workTab = tab;
        if (tab === "overview") this.loadWorkBoard();
        else this.loadWorkItems();
      },
      async loadWorkMeta() {
        try { this.workMeta = await api("/api/work/meta"); } catch (e) {}
      },
      async loadWorkBoard() {
        try { this.workBoard = await api("/api/work/board"); }
        catch (e) { this.toast("加载日常工作失败", "err"); }
      },
      async loadWorkItems() {
        const t = this.workType;
        if (!(this.workMeta.projects || []).length) await this.loadWorkMeta();
        try {
          const d = await api("/api/work/items" + (t ? "?type=" + t : ""));
          this.workItems = d.items || [];
          if (this.workSel && !this.workItems.some((i) => i.path === this.workSel)) {
            this.workSel = ""; this.workItem = null; this.workBody = "";
          }
        } catch (e) { this.toast("加载工作项失败", "err"); }
      },
      applyWork(it) {
        this.workItem = it;
        this.workSel = it.path;
        this.workBody = it.body || "";
        this.workTitle = it.title || "";
        this.workProject = it.project || "";
        this.workTags = (it.tags || []).join(", ");
      },
      async selectWork(path) {
        try {
          this.applyWork(await api("/api/work/item?path=" + encodeURIComponent(path)));
          this.workRead = true;
        } catch (e) { this.toast("打开失败", "err"); }
      },
      /* 从总览点某条 → 跳到它所属的子菜单并选中 */
      openWork(it) {
        const tab = this.workTabForType(it.type);
        this.kbRoot = "";
        if (tab === "overview") {
          // 笔记类条目没有对应子菜单, 直接在知识库里打开原文
          this.openFile(it.path);
          this.toast("笔记类条目已在知识库中打开", "");
          return;
        }
        this.view = "work";
        this.workNavOpen = true;
        this.workTab = tab;
        this.loadWorkItems().then(() => this.selectWork(it.path));
      },
      openWorkCreate() {
        this.workNew.type = this.workType || "requirement";
        this.workNew.show = true;
      },
      async confirmWorkCreate() {
        const n = this.workNew;
        const title = (n.title || "").trim();
        if (!title) { this.toast("请输入标题", "err"); return; }
        try {
          const it = await apiJson("/api/work/item", "POST", {
            type: n.type, title: title, project: (n.project || "").trim(), priority: n.priority,
          });
          n.show = false;
          n.title = "";
          const tab = this.workTabForType(it.type);
          if (tab !== "overview") this.workTab = tab;
          await this.loadWorkItems();
          this.applyWork(it);
          this.workRead = false;
          this.toast("已创建 " + it.id, "ok");
        } catch (e) { this.toast("创建失败", "err"); }
      },
      async saveWorkFields(fields) {
        if (!this.workItem) return;
        this.workSaving = true;
        try {
          const payload = Object.assign({ path: this.workItem.path }, fields || {});
          const it = await apiJson("/api/work/item", "PUT", payload);
          this.applyWork(it);
          this.loadWorkItems();
          if (this.workTab === "overview") this.loadWorkBoard();
          if (fields && fields.status) {
            this.toast("状态已流转到「" + this.statusLabel(it.status) + "」", "ok");
          }
        } catch (e) { this.toast("保存失败", "err"); }
        finally { this.workSaving = false; }
      },
      setWorkStatus(s) { this.saveWorkFields({ status: s }); },
      saveWorkTitle() {
        const v = (this.workTitle || "").trim();
        if (!v || !this.workItem || v === this.workItem.title) return;
        this.saveWorkFields({ title: v });
      },
      async saveWorkBody() {
        if (!this.workItem) return;
        this.workSaving = true;
        try {
          this.applyWork(await apiJson("/api/work/item", "PUT", {
            path: this.workItem.path, body: this.workBody,
          }));
          this.toast("正文已保存", "ok");
        } catch (e) { this.toast("保存失败", "err"); }
        finally { this.workSaving = false; }
      },
      async deleteWork() {
        if (!this.workItem) return;
        const label = this.workItem.id || this.workItem.path;
        if (!window.confirm("确认删除 " + label + " ？此操作会删除对应的 Markdown 文件。")) return;
        try {
          await api("/api/work/item?path=" + encodeURIComponent(this.workItem.path), { method: "DELETE" });
          this.workSel = ""; this.workItem = null; this.workBody = "";
          this.loadWorkItems();
          this.toast("已删除 " + label, "ok");
        } catch (e) { this.toast("删除失败", "err"); }
      },
      openWorkFile() {
        if (this.workItem) this.openFile(this.workItem.path);
      },
      /* 卡片展示时去掉正文首行 H1（标题已单独渲染，避免重复） */
      bodyNoH1(t) {
        return (t || "").replace(/^\s*#\s+[^\n]*(\r?\n)?/, "");
      },
      /* 约定卡片: 就地编辑 */
      editConv(it) { this.convEditPath = it.path; this.convDraft = it.body || ""; },
      async saveConv(path) {
        try {
          await apiJson("/api/work/item", "PUT", { path: path, body: this.convDraft });
          this.convEditPath = "";
          this.loadWorkItems();
          this.toast("已保存", "ok");
        } catch (e) { this.toast("保存失败", "err"); }
      },
      async deleteConv(it) {
        if (!window.confirm("确认删除 " + (it.id || it.title) + " ？")) return;
        try {
          await api("/api/work/item?path=" + encodeURIComponent(it.path), { method: "DELETE" });
          this.loadWorkItems();
          this.toast("已删除", "ok");
        } catch (e) { this.toast("删除失败", "err"); }
      },
      /* 历史文档导入 */
      openWorkImport() {
        this.workImport.show = true;
        this.workImport.scanned = false;
      },
      async scanWorkImport() {
        const w = this.workImport;
        const dir = (w.dir || "").trim();
        if (!dir) { this.toast("请填写目录路径", "err"); return; }
        w.scanning = true;
        w.scanned = false;
        try {
          const d = await apiJson("/api/work/import/scan", "POST", { dir: dir });
          w.files = d.files || [];
          const picked = {};
          w.files.forEach((f) => { picked[f.abs] = true; });
          w.picked = picked;
          this.toast("扫描到 " + d.count + " 个文件", "ok");
        } catch (e) {
          w.files = []; w.picked = {};
          this.toast("扫描失败：请检查目录是否存在", "err");
        } finally {
          w.scanning = false;
          w.scanned = true;
        }
      },
      async runWorkImport() {
        const w = this.workImport;
        const files = (w.files || []).filter((f) => w.picked[f.abs]).map((f) => f.abs);
        if (!files.length) { this.toast("请勾选要导入的文件", "err"); return; }
        try {
          const d = await apiJson("/api/work/import", "POST", {
            files: files, project: (w.project || "").trim(), type: w.type || "",
          });
          w.show = false; w.files = []; w.picked = {}; w.scanned = false;
          this.toast("已导入 " + d.count + " 个文件", "ok");
          this.loadWorkItems();
          this.loadWorkBoard();
        } catch (e) { this.toast("导入失败", "err"); }
      },
      /* ---- 金融日记 (diary) ---- */
      /* 进入日记页：自动落到「最近的一年 + 那一年最近的一篇」，一篇都没有才开今天。
         2026-10-18：不再进门对着一块空白；年月日三个下拉由 selectDiaryDay 同步 */
      navDiary() {
        this.view = "diary";
        if (this.diarySel) return;            // 已经开着某天，切视图不打扰
        const open = () => {
          if (!this.diaryYears.length) { this.diaryToday(); return; }
          this.diaryYear = this.diaryYears[0].year;   // 后端按年份倒序，[0] 即最近一年
          this.withDiaryYear(() => {
            const es = this.diaryEntryList;
            if (es.length) this.selectDiaryDay(es[es.length - 1].date);
            // 该年一篇都没有 → 停在空状态，由用户点「今天」
          });
        };
        if (this.diaryYears.length) open();
        else this.loadDiaryYears().then(open);
      },
      async loadDiaryYears() {
        try { this.diaryYears = (await api("/api/diary/years")).years || []; }
        catch (e) { this.toast("加载日记年份失败", "err"); }
      },
      /* 切年份：落到该年最近一篇；该年没日记就回到空状态 */
      selectDiaryYear(y) {
        this.diaryYear = y;
        this.withDiaryYear(() => {
          const es = this.diaryEntryList;
          if (es.length) this.selectDiaryDay(es[es.length - 1].date);
          else this._diaryClearSel();
        });
      },
      /* 切月份：只约束浮窗范围；同时把正在看的日期落到该月最近一篇（符合"选了就跳过去"的直觉）。
         「全部」不改正在看的日期。该月没日记 → 空状态，「日」下拉留给用户自选 */
      selectDiaryMonth(m) {
        this.diaryMonth = m;
        if (m < 0) return;
        this.withDiaryYear(() => {
          const mm = String(m + 1).padStart(2, "0");
          const es = this.diaryEntryList.filter((e) => e.date.slice(5, 7) === mm);
          if (es.length) this.selectDiaryDay(es[es.length - 1].date);
          else this._diaryClearSel();
        });
      },
      async loadDiaryYear() {
        if (!this.diaryYear) return;
        try { this.diaryYearData = await api("/api/diary/year?y=" + this.diaryYear); }
        catch (e) { this.toast("加载日记失败", "err"); }
      },
      /* 保证 diaryYearData 是当前选中年份的数据，再执行 fn（已加载则同步执行） */
      withDiaryYear(fn) {
        if (this.diaryYearData && this.diaryYearData.year === this.diaryYear) { fn(); return; }
        this.loadDiaryYear().then(fn);
      },
      _diaryClearSel() {
        this.diarySel = "";
        this.diaryPick = "";
        this.diaryItem = { exists: false };
        this.diaryBody = ""; this.diaryTitle = ""; this.diaryTags = "";
      },
      /* 打开某一天：年份变了先加载该年，再打开（date input / 翻页 / 今天 / 浮窗都走这里） */
      openDiaryDate(d) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(d || "")) return;
        this.diaryYear = d.slice(0, 4);
        this.diaryPick = d;
        this.withDiaryYear(() => this.selectDiaryDay(d));
      },
      onDiaryPick() { this.openDiaryDate(this.diaryPick); },
      /* 篇数浮窗：开 / 关 / 跳转 */
      toggleDiaryList() { this.diaryListOpen = !this.diaryListOpen; },
      jumpDiary(d) { this.diaryListOpen = false; this.openDiaryDate(d); },
      diaryStepDay(n) {
        const now = new Date();
        const base = this.diarySel || this._pad(now.getFullYear(), now.getMonth() + 1, now.getDate());
        const dt = new Date(base + "T00:00:00");
        dt.setDate(dt.getDate() + n);
        this.openDiaryDate(this._pad(dt.getFullYear(), dt.getMonth() + 1, dt.getDate()));
      },
      async diaryToday() {
        const now = new Date();
        this.openDiaryDate(this._pad(now.getFullYear(), now.getMonth() + 1, now.getDate()));
      },
      async selectDiaryDay(d) {
        this.diarySel = d;
        this.diaryPick = d;
        // 月份跟随正在看的那天（翻页 / 今天 / 跳转全自动同步）
        this.diaryMonth = parseInt(d.slice(5, 7), 10) - 1;
        try {
          const it = await api("/api/diary/day?d=" + d);
          this.diaryItem = it;
          this.diaryTitle = it.title || "";
          this.diaryTags = (it.tags || []).join(", ");
          // 新的一天 → 预填模板，省得面对空白页
          this.diaryBody = it.body || this._diaryTemplate(d);
          this.diaryRead = true;
        } catch (e) { this.toast("打开失败", "err"); }
      },
      async saveDiary() {
        if (!this.diarySel) return;
        this.diarySaving = true;
        try {
          const it = await apiJson("/api/diary/day", "POST", {
            date: this.diarySel,
            title: this.diaryTitle,
            tags: this.diaryTags,
            body: this.diaryBody,
          });
          this.diaryItem = it;
          this.toast("已保存 " + this.diarySel, "ok");
          await this.loadDiaryYear();
          await this.loadDiaryYears();
        } catch (e) { this.toast("保存失败", "err"); }
        finally { this.diarySaving = false; }
      },
      async deleteDiary() {
        if (!this.diaryItem || !this.diaryItem.exists) return;
        if (!window.confirm("确认删除 " + this.diarySel + " 的日记？")) return;
        try {
          await api("/api/diary/day?d=" + this.diarySel, { method: "DELETE" });
          this.diarySel = "";
          this.diaryItem = { exists: false };
          this.diaryBody = ""; this.diaryTitle = ""; this.diaryTags = "";
          await this.loadDiaryYear();
          await this.loadDiaryYears();
          this.toast("已删除", "ok");
        } catch (e) { this.toast("删除失败", "err"); }
      },
      _pad(y, m, d) {
        return String(y) + "-" + String(m).padStart(2, "0") + "-" + String(d).padStart(2, "0");
      },
      _diaryTemplate(d) {
        return "# " + d + " 金融日记\n\n## 市场观察\n\n## 操作 / 持仓\n\n## 复盘 / 心得\n\n## 备注\n";
      },

      /* ---- 日报 / 周报（手动主观） ---- */
      navDreport() {
        this.view = "dreport";
        if (!this.dreportYears.length) this.loadDreportYears();
      },
      async loadDreportYears() {
        try {
          const data = await api("/api/dreport/years?kind=" + this.dreportKind);
          this.dreportYears = data || [];
          if (this.dreportYears.length && !this.dreportYear) {
            this.dreportYear = this.dreportYears[0].year;
            await this.loadDreportYear();
          }
        } catch (e) { this.toast("加载失败", "err"); }
      },
      selectDreportYear(y) {
        this.dreportYear = y;
        this.dreportSel = "";
        this.dreportPick = "";
        this.dreportItem = { exists: false };
        this.dreportBody = ""; this.dreportTitle = ""; this.dreportTags = "";
        this.loadDreportYear();
      },
      /* 日报 / 周报共用同一个按年接口：entries 的键 = 日期（周报 = 该周周一） */
      async loadDreportYear() {
        if (!this.dreportYear) return;
        try {
          this.dreportYearData = await api(
            "/api/dreport/year?kind=" + this.dreportKind + "&y=" + this.dreportYear);
        } catch (e) { this.toast("加载失败", "err"); }
      },
      setDreportKind(kind) {
        if (this.dreportKind === kind) return;
        this.dreportKind = kind;
        this.dreportSel = "";
        this.dreportPick = "";
        this.dreportYear = "";
        this.dreportYearData = null;
        this.dreportItem = { exists: false };
        this.dreportBody = ""; this.dreportTitle = ""; this.dreportTags = "";
        this.dreportYears = [];
        this.loadDreportYears();
      },
      /* 打开某一天（周报自动落到该周周一）：日期框、前后翻页、今天/本周都走这里 */
      openDreportKey(d) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(d || "")) return;
        const key = this.dreportKind === "weekly" ? this._mondayOf(d) : d;
        const y = key.slice(0, 4);
        this.dreportYear = y;
        this.dreportPick = key;
        const open = () => (this.dreportKind === "weekly"
          ? this.selectDreportWeek(key) : this.selectDreportDay(key));
        if (!this.dreportYearData || this.dreportYearData.year !== y) {
          this.loadDreportYear().then(open);
        } else {
          open();
        }
      },
      onDreportPick() { this.openDreportKey(this.dreportPick); },
      dreportStep(n) {
        const now = new Date();
        const today = this._pad(now.getFullYear(), now.getMonth() + 1, now.getDate());
        const base = this.dreportSel || (this.dreportKind === "weekly" ? this._mondayOf(today) : today);
        const dt = new Date(base + "T00:00:00");
        dt.setDate(dt.getDate() + n * (this.dreportKind === "weekly" ? 7 : 1));
        this.openDreportKey(this._pad(dt.getFullYear(), dt.getMonth() + 1, dt.getDate()));
      },
      dreportNow() {
        const now = new Date();
        this.openDreportKey(this._pad(now.getFullYear(), now.getMonth() + 1, now.getDate()));
      },
      _mondayOf(d) {
        const dt = new Date(d + "T00:00:00");
        dt.setDate(dt.getDate() - ((dt.getDay() + 6) % 7)); // 周一为首
        return this._pad(dt.getFullYear(), dt.getMonth() + 1, dt.getDate());
      },
      _weekLabel(key) {
        const mon = new Date(key + "T00:00:00");
        const sun = new Date(mon.getTime() + 6 * 86400000);
        const f = (d) => String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
        return f(mon) + " ~ " + f(sun);
      },
      /* ISO 周序：把日期挪到本周四，与该年第一个周四比周数，跨年不跳号 */
      _weekNo(key) {
        const thu = new Date(key + "T00:00:00");
        thu.setDate(thu.getDate() + 3);
        const firstThu = new Date(thu.getFullYear(), 0, 4);
        firstThu.setDate(firstThu.getDate() - ((firstThu.getDay() + 6) % 7) + 3);
        return 1 + Math.round((thu - firstThu) / (7 * 86400000));
      },
      async selectDreportDay(d) {
        this.dreportSel = d;
        this.dreportPick = d;
        try {
          const it = await api("/api/dreport/entry?kind=daily&key=" + d);
          this.dreportItem = it;
          this.dreportTitle = it.title || "";
          this.dreportTags = (it.tags || []).join(", ");
          this.dreportBody = it.body || this._dreportTemplate("daily", d);
          this.dreportRead = true;
        } catch (e) { this.toast("加载失败", "err"); }
      },
      async selectDreportWeek(key) {
        this.dreportSel = key;
        this.dreportPick = key;
        try {
          const it = await api("/api/dreport/entry?kind=weekly&key=" + key);
          this.dreportItem = it;
          this.dreportTitle = it.title || "";
          this.dreportTags = (it.tags || []).join(", ");
          this.dreportBody = it.body || this._dreportTemplate("weekly", key);
          this.dreportRead = true;
        } catch (e) { this.toast("加载失败", "err"); }
      },
      async saveDreport() {
        if (!this.dreportSel) return;
        this.dreportSaving = true;
        try {
          const it = await apiJson("/api/dreport/entry", "POST", {
            kind: this.dreportKind,
            key: this.dreportSel,
            title: this.dreportTitle,
            tags: this.dreportTags,
            body: this.dreportBody,
          });
          this.dreportItem = it;
          this.toast("已保存 " + this.dreportSel, "ok");
          await this.loadDreportYear();
          await this.loadDreportYears();
        } catch (e) { this.toast("保存失败", "err"); }
        finally { this.dreportSaving = false; }
      },
      async deleteDreport() {
        if (!this.dreportItem || !this.dreportItem.exists) return;
        const label = this.dreportKind === "weekly" ? "周报" : "日报";
        if (!window.confirm("确认删除 " + this.dreportSel + " 的" + label + "？")) return;
        try {
          await api("/api/dreport/entry?kind=" + this.dreportKind + "&key=" + this.dreportSel, { method: "DELETE" });
          this.dreportSel = "";
          this.dreportItem = { exists: false };
          this.dreportBody = ""; this.dreportTitle = ""; this.dreportTags = "";
          await this.loadDreportYear();
          await this.loadDreportYears();
          this.toast("已删除", "ok");
        } catch (e) { this.toast("删除失败", "err"); }
      },
      _dreportTemplate(kind, key) {
        if (kind === "weekly")
          return "# 周报 " + key + "\n\n## 本周完成\n\n## 下周计划\n\n## 问题与风险\n\n## 其他\n";
        return "# " + key + " 日报\n\n## 今日完成\n\n## 进行中\n\n## 明日计划\n\n## 风险 / 阻塞\n\n## 备注\n";
      },

      /* ---- 设置：AI 模型配置 ---- */
      llmProviderLabel(id) {
        return {
          deepseek: "DeepSeek（默认）",
          qwen: "通义千问 Qwen",
          openai: "OpenAI",
          ollama: "Ollama（本地，免 Key）",
        }[id] || id;
      },
      async loadLlmSettings(previewProvider) {
        try {
          const q = previewProvider ? "?provider=" + encodeURIComponent(previewProvider) : "";
          const d = await api("/api/settings/llm" + q);
          this.llmSettings = d;
          const src = d.source || {};
          this.llmForm = {
            provider: d.provider,
            api_key: "",   // 脱敏后的 Key 永不回填到输入框
            model: src.model && src.model !== "default" ? d.model : "",
            base_url: src.base_url && src.base_url !== "default" ? d.base_url : "",
          };
        } catch (e) { this.toast("加载模型配置失败", "err"); }
      },
      async onLlmProviderChange() {
        this.llmTestMsg = "";
        await this.loadLlmSettings(this.llmForm.provider);
      },
      _llmFormBody() {
        const b = {
          provider: this.llmForm.provider,
          model: (this.llmForm.model || "").trim(),
          base_url: (this.llmForm.base_url || "").trim(),
        };
        const key = (this.llmForm.api_key || "").trim();
        if (key) b.api_key = key;   // 留空 = 保留已保存的 Key
        return b;
      },
      async saveLlm() {
        this.llmSaving = true;
        this.llmTestMsg = "";
        try {
          await apiJson("/api/settings/llm", "POST", this._llmFormBody());
          await this.loadLlmSettings();
          this.loadConfig();
          this.toast("模型配置已保存", "ok");
        } catch (e) { this.toast("保存失败", "err"); }
        finally { this.llmSaving = false; }
      },
      async testLlm() {
        this.llmTesting = true;
        this.llmTestMsg = "";
        try {
          const res = await fetch("/api/settings/llm/test", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(this._llmFormBody()),
          });
          let d = {};
          try { d = await res.json(); } catch (e) {}
          this.llmTestOk = !!(res.ok && d.ok);
          this.llmTestMsg = this.llmTestOk
            ? "连接成功 · " + d.model + " 回复：「" + (d.reply || "") + "」"
            : "连接失败：" + (d.error || ("HTTP " + res.status));
          await this.loadLlmSettings();
          this.loadConfig();
        } catch (e) {
          this.llmTestOk = false;
          this.llmTestMsg = "测试失败：" + e.message;
        } finally { this.llmTesting = false; }
      },
      /* ---- config / stats ---- */
      async loadConfig() {
        try { this.config = await api("/api/config"); } catch (e) {}
      },
      async loadStats() {
        try {
          this.stats = await api("/api/stats");
          if (!this.reportDate) this.reportDate = this.stats.today || "";
        } catch (e) {}
      },
      async reindex() {
        try {
          const d = await apiJson("/api/reindex", "POST", {});
          this.toast("已重建索引：" + d.indexed_fts + " 篇", "ok");
          this.loadStats();
          this.loadTree();
        } catch (e) { this.toast("重建失败", "err"); }
      },
      /* ---- theme ---- */
      setTheme(t) {
        this.theme = t;
        document.documentElement.setAttribute("data-theme", t);
        try { localStorage.setItem("kb-theme", t); } catch (e) {}
      },
      toggleTheme() { this.setTheme(this.theme === "dark" ? "light" : "dark"); },
    },
    mounted() {
      let saved = "dark";
      try { saved = localStorage.getItem("kb-theme") || "dark"; } catch (e) {}
      this.setTheme(saved);
      this.loadConfig();
      this.loadLlmSettings();
      this.loadStats();
      this.loadTree();
      this.loadTasks();
      this.loadWorkMeta();
      this.loadWorkBoard();

      // 滚轮穿透：日记 / 日报周报视图里，条件条、结果条、卡片头都是固定不滚的
      // （flex:none），鼠标停在这类"死区"上时滚轮无处可去，手感像"滚不动"。
      // 这里把滚动量转交给下方真正的滚动容器，让滚轮在整块内容区都能用。
      window.addEventListener("wheel", (e) => {
        if (e.defaultPrevented || e.ctrlKey) return;
        const el = e.target;
        if (!(el instanceof Element)) return;
        // 目标自身可滚，或本身要靠滚轮交互的元素 → 交回浏览器原生处理
        if (el.closest(".preview, textarea, select, .tree, .doc-list")) return;
        const host = el.closest(".content.split-view");
        if (!host) return;
        const scroller =
          host.querySelector(".diary-wrap .preview") ||
          host.querySelector(".diary-wrap textarea");
        if (!scroller || scroller.scrollHeight <= scroller.clientHeight + 1) return;
        const before = scroller.scrollTop;
        scroller.scrollTop += e.deltaY;
        if (scroller.scrollTop !== before) e.preventDefault();
      }, { passive: false });

      // 金融日记「篇数浮窗」：Esc 或点浮窗/徽标外部即关
      document.addEventListener("click", (e) => {
        if (!this.diaryListOpen) return;
        const el = e.target;
        if (!(el instanceof Element)) return;
        if (el.closest(".diary-pop") || el.closest(".db-count")) return;
        this.diaryListOpen = false;
      });
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && this.diaryListOpen) this.diaryListOpen = false;
      });
    },
  };

  /* ---- 挂载：带全局错误兜底 -----------------------------------------
     白屏是最差的通知方式。渲染/生命周期出错时：
     ① errorHandler 把错误显示成右下红条（不卸载、不白屏）；
     ② mount 本身失败（模板编译错等）时摘掉 v-cloak 并原样显示错误。 */
  function kbErrBox(msg) {
    let box = document.getElementById("kb-err-box");
    if (!box) {
      box = document.createElement("div");
      box.id = "kb-err-box";
      box.style.cssText =
        "position:fixed;left:12px;right:12px;bottom:12px;z-index:9999;" +
        "background:#A32D2D;color:#fff;padding:10px 14px;border-radius:10px;" +
        "font:13px/1.5 sans-serif;white-space:pre-wrap;";
      document.body.appendChild(box);
    }
    box.textContent = msg;
  }
  try {
    const app = Vue.createApp(Root);
    app.config.errorHandler = (err, vm, info) => {
      console.error("[KB]", err, info);
      kbErrBox("页面出错了：" +
        (err && err.message ? err.message : String(err)) +
        (info ? "\n位置：" + info : "") +
        "\n（把这段文字发给开发者）");
    };
    app.mount("#app");
  } catch (err) {
    console.error("[KB] mount failed", err);
    const el = document.getElementById("app");
    if (el) {
      el.removeAttribute("v-cloak");
      el.innerHTML = "<pre style='padding:24px;color:#A32D2D;font:13px monospace;" +
        "white-space:pre-wrap;'>启动失败：" + String(err && err.stack ? err.stack : err) + "</pre>";
    }
  }
})();
