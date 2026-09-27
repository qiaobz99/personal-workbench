/* =========================================================================
   Local KB Workbench — frontend logic (Vue 3 global build, no build step)
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
        _toastTimer: null,
        _searchTimer: null,
      };
    },
    computed: {
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
          reports: "日报 / 周报",
          work: "日常工作",
          settings: "设置",
        }[this.view] || "";
      },
      crumb() {
        if (this.view === "knowledge" && this.kbRoot) return this.kbRoot;
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
        return [...map.entries()]
          .map(([name, items]) => ({ name, items }))
          .sort((a, b) => a.name.localeCompare(b.name, "zh"));
      },
      pickedCount() {
        return Object.values(this.workImport.picked || {}).filter(Boolean).length;
      },
      previewHtml() {
        return MD(this.fileContent || "");
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
        this.view = view;
        this.kbRoot = root || "";
        if (view === "knowledge") this.loadTree();
        if (view === "tasks") this.loadTasks();
        if (view === "reports" && !this.reportData) this.loadReport();
        // 每次回到概览都重新拉取, 保证任务数与待办列表是最新的
        if (view === "dashboard") { this.loadStats(); this.loadTasks(); }
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
      this.loadStats();
      this.loadTree();
      this.loadTasks();
      this.loadWorkMeta();
      this.loadWorkBoard();
    },
  };

  Vue.createApp(Root).mount("#app");
})();
