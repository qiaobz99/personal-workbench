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
          settings: "设置",
        }[this.view] || "";
      },
      crumb() {
        if (this.view === "knowledge" && this.kbRoot) return this.kbRoot;
        return "";
      },
      previewHtml() {
        return MD(this.fileContent || "");
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
    },
  };

  Vue.createApp(Root).mount("#app");
})();
