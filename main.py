import sys, os, json, re
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, QTime, QDate
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLabel, QFileDialog,
    QComboBox, QTimeEdit, QSpinBox, QSystemTrayIcon, QMenu, QMessageBox,
    QDialog, QFormLayout, QLineEdit, QTabWidget, QStyle, QCheckBox,
    QDateEdit, QTextEdit, QGroupBox, QInputDialog, QGridLayout
)
from PySide6.QtGui import QIcon, QAction, QFont, QPixmap, QPainter, QColor, QBrush, QPen
from PySide6.QtNetwork import QLocalServer, QLocalSocket

# ---- 数据目录（统一放 AppData，不在桌面留文件） ----
DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "OfficeReminder")
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(DATA_DIR, "tasks.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

APP_KEY = "OfficeReminder_SingleInstance_v2"

# ---- 内置分类规则（不可删除） ----
BUILTIN_TABS = ["每日", "每周", "每月", "间隔"]

BUILTIN_RULES = {
    "每日": [r"每天", r"每日", r"日报", r"daily", r"每\s*天", r"每\s*日", r"每(?![周月])", r"every"],
    "每周": [r"每周", r"周报", r"weekly", r"week"],
    "每月": [r"每月", r"月度", r"月报", r"monthly", r"month"],
    "间隔": [],  # 间隔类不靠关键词匹配，手动指定
}

def classify_folder_name(dirname, rules):
    """按自定义规则匹配，返回标签名。优先匹配自定义标签再内置"""
    for label, patterns in rules.items():
        for pat in patterns:
            if re.search(pat, dirname, re.IGNORECASE):
                return label
    return "每日"  # 默认

def extract_day_from_name(dirname):
    m = re.search(r"(\d+)\s*(?:号|日|th|st|nd|rd)?", dirname, re.IGNORECASE)
    if m:
        return max(1, min(31, int(m.group(1))))
    cn = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10,
          "十一":11,"十二":12,"十三":13,"十四":14,"十五":15,"十六":16,"十七":17,
          "十八":18,"十九":19,"二十":20,"二十一":21,"二十二":22,"二十三":23,
          "二十四":24,"二十五":25,"二十六":26,"二十七":27,"二十八":28,
          "二十九":29,"三十":30,"三十一":31}
    for word, num in sorted(cn.items(), key=lambda x: -len(x[0])):
        if word in dirname:
            return num
    return 1

# ---- Settings ----
class Settings:
    def __init__(self):
        self.data = {"watch_dirs": [], "custom_tabs": {}, "custom_reminders": []}
        self.load()
    def load(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except: pass
    def save(self):
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    def get_all_rules(self):
        """合并自定义+内置规则(自定义优先匹配)"""
        rules = {}
        for label, keywords in self.data.get("custom_tabs", {}).items():
            patterns = [re.escape(k) for k in keywords]
            rules[label] = patterns
        for label, patterns in BUILTIN_RULES.items():
            rules[label] = patterns
        return rules

# ---- TaskManager ----
class TaskManager:
    def __init__(self):
        self.tasks = []
        self.load()
    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self.tasks = json.load(f)
            except: self.tasks = []
        else: self.tasks = []
    def save(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.tasks, f, ensure_ascii=False, indent=2)
    def get_by_path(self, path):
        for t in self.tasks:
            if t.get("path") == path:
                return t
        return None
    def remove_by_path(self, path):
        self.tasks = [t for t in self.tasks if t.get("path") != path]

# ============== TaskDialog ==============
class TaskDialog(QDialog):
    def __init__(self, parent=None, task_data=None, tab_labels=None, tab_type=None):
        super().__init__(parent)
        self.setWindowTitle("设置文件夹任务")
        self.resize(440, 380)
        self.task_data = task_data or {}
        self.tab_labels = tab_labels or []
        self.target_tab = tab_type or self.task_data.get("type", "每日")
        self.init_ui()

    def init_ui(self):
        layout = QFormLayout(self); layout.setSpacing(10)

        self.name_input = QLineEdit()
        self.name_input.setText(self.task_data.get("name", ""))
        layout.addRow("名称:", self.name_input)

        pl = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setText(self.task_data.get("path", ""))
        b = QPushButton("浏览"); b.clicked.connect(lambda: self._browse())
        pl.addWidget(self.path_input); pl.addWidget(b)
        layout.addRow("路径:", pl)

        # 类型选择 = Tab 标签
        self.type_combo = QComboBox()
        all_labels = ["每日", "每周", "每月", "间隔"] + [l for l in self.tab_labels if l not in ("每日","每周","每月","间隔","自定义","全部")]
        self.type_combo.addItems(all_labels)
        self.type_combo.setCurrentText(self.target_tab if self.target_tab in all_labels else "每日")
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        layout.addRow("归类标签:", self.type_combo)

        self.alarm_check = QCheckBox("启用提醒")
        self.alarm_check.setChecked(self.task_data.get("alarm_enabled", False))
        layout.addRow("", self.alarm_check)

        self.time_edit = QTimeEdit()
        self.time_edit.setTime(QTime.fromString(self.task_data.get("remind_time", "09:00"), "HH:mm"))
        self.day_spin = QSpinBox(); self.day_spin.setRange(1,31); self.day_spin.setValue(self.task_data.get("remind_day",1))
        self.interval_spin = QSpinBox(); self.interval_spin.setRange(5,1440); self.interval_spin.setSuffix(" 分钟"); self.interval_spin.setValue(self.task_data.get("interval",30))

        self.tw = QWidget(); tl = QHBoxLayout(self.tw); tl.setContentsMargins(0,0,0,0); tl.addWidget(QLabel("时间:")); tl.addWidget(self.time_edit)
        self.dw = QWidget(); dl = QHBoxLayout(self.dw); dl.setContentsMargins(0,0,0,0); dl.addWidget(QLabel("每月:")); dl.addWidget(self.day_spin); dl.addWidget(QLabel("号"))
        self.iw = QWidget(); il = QHBoxLayout(self.iw); il.setContentsMargins(0,0,0,0); il.addWidget(QLabel("每隔:")); il.addWidget(self.interval_spin)

        layout.addRow("", self.tw); layout.addRow("", self.dw); layout.addRow("", self.iw)
        self._on_type_changed(self.type_combo.currentText())

        bl = QHBoxLayout(); bl.addStretch()
        sb = QPushButton("保存"); sb.clicked.connect(self.accept)
        cb = QPushButton("取消"); cb.clicked.connect(self.reject)
        bl.addWidget(sb); bl.addWidget(cb); layout.addRow(bl)

    def _browse(self):
        p = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if p:
            self.path_input.setText(p)
            if not self.name_input.text(): self.name_input.setText(os.path.basename(p))

    def _on_type_changed(self, txt):
        if txt in ("每日", "每周"):
            self.tw.show(); self.dw.hide(); self.iw.hide()
        elif txt == "每月":
            self.tw.show(); self.dw.show(); self.iw.hide()
        elif txt == "间隔":
            self.tw.hide(); self.dw.hide(); self.iw.show()
        else:
            self.tw.show(); self.dw.hide(); self.iw.hide()

    def get_data(self):
        return {
            "name": self.name_input.text().strip(),
            "path": self.path_input.text().strip(),
            "type": self.type_combo.currentText(),
            "remind_time": self.time_edit.time().toString("HH:mm"),
            "remind_day": self.day_spin.value(),
            "interval": self.interval_spin.value(),
            "alarm_enabled": self.alarm_check.isChecked(),
            "last_done": self.task_data.get("last_done", ""),
            "last_reminded": self.task_data.get("last_reminded", ""),
            "is_custom_reminder": False,
        }

# ============== CustomReminderDialog ==============
class CustomReminderDialog(QDialog):
    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.setWindowTitle("自定义提醒"); self.resize(420, 380)
        self.data = data or {}
        self.init_ui()

    def init_ui(self):
        layout = QFormLayout(self); layout.setSpacing(10)

        self.name_input = QLineEdit()
        self.name_input.setText(self.data.get("name", ""))
        self.name_input.setPlaceholderText("提醒内容...")
        layout.addRow("内容:", self.name_input)

        g = QGroupBox("提醒频率"); gl = QVBoxLayout(g)
        self.freq = QComboBox(); self.freq.addItems(["仅一次","每天","每周","每月","每年","间隔"]);
        self.freq.setCurrentText(self.data.get("custom_freq","仅一次"))
        self.freq.currentTextChanged.connect(self._on_freq)
        gl.addWidget(self.freq)

        self.dr = QHBoxLayout(); self.dr.addWidget(QLabel("日期:"));
        self.de = QDateEdit(); self.de.setCalendarPopup(True)
        ds = self.data.get("custom_date", QDate.currentDate().toString("yyyy-MM-dd"))
        self.de.setDate(QDate.fromString(ds, "yyyy-MM-dd")); self.dr.addWidget(self.de)

        tr = QHBoxLayout(); tr.addWidget(QLabel("时间:"))
        self.te = QTimeEdit(); self.te.setTime(QTime.fromString(self.data.get("remind_time","09:00"),"HH:mm")); tr.addWidget(self.te)

        self.ir = QHBoxLayout(); self.ir.addWidget(QLabel("间隔:"))
        self.ie = QSpinBox(); self.ie.setRange(5,1440); self.ie.setSuffix(" 分钟"); self.ie.setValue(self.data.get("interval",30)); self.ir.addWidget(self.ie)

        gl.addLayout(self.dr); gl.addLayout(tr); gl.addLayout(self.ir)
        layout.addRow(g)

        self.note = QTextEdit(); self.note.setMaximumHeight(60); self.note.setPlaceholderText("备注..."); self.note.setText(self.data.get("note",""))
        layout.addRow("备注:", self.note)
        self._on_freq(self.freq.currentText())

        bl = QHBoxLayout(); bl.addStretch()
        sb = QPushButton("保存"); sb.clicked.connect(self.accept); cb = QPushButton("取消"); cb.clicked.connect(self.reject)
        bl.addWidget(sb); bl.addWidget(cb); layout.addRow(bl)



    def _on_freq(self, txt):
        is_once = (txt == "仅一次")
        is_interval = (txt == "间隔")
        # date row
        for i in range(self.dr.count()):
            w = self.dr.itemAt(i).widget()
            if w: w.setVisible(is_once)
        self.de.setVisible(is_once)
        # time row
        self.te.setVisible(not is_interval)
        # interval row
        for i in range(self.ir.count()):
            w = self.ir.itemAt(i).widget()
            if w: w.setVisible(is_interval)
        self.ie.setVisible(is_interval)

    def get_data(self):
        freq = self.freq.currentText()
        return {
            "name": self.name_input.text().strip(),
            "path": "", "type": "自定义",
            "remind_time": self.te.time().toString("HH:mm"),
            "remind_day": 1,
            "interval": self.ie.value(),
            "alarm_enabled": True,
            "last_done": "", "last_reminded": "",
            "is_custom_reminder": True,
            "custom_freq": freq,
            "custom_date": self.de.date().toString("yyyy-MM-dd") if freq == "仅一次" else "",
            "note": self.note.toPlainText().strip(),
        }

# ============== MainWindow ==============
class MainWindow(QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.mgr = TaskManager()
        self.settings = Settings()
        self.setWindowTitle("办公助手")
        self.resize(920, 580)
        self._current_tab = "全部"

        self.init_ui()
        self.init_tray()
        self.refresh_all_tabs()

        self.remind_timer = QTimer(self); self.remind_timer.timeout.connect(self.check_reminders); self.remind_timer.start(30000)

        self.sync_timer = QTimer(self); self.sync_timer.timeout.connect(self.auto_sync_folders)
        if self.settings.data.get("watch_dirs"):
            self.sync_timer.start(300000)

    # ---- UI ----
    def init_ui(self):
        c = QWidget(); ml = QVBoxLayout(c); ml.setContentsMargins(6,6,6,6); ml.setSpacing(4)

        self.tab_bar = QTabWidget(); self.tab_bar.setDocumentMode(True)
        self.tab_lists = {}; self.tab_order = []

        self._rebuild_tabs()

        self.tab_bar.currentChanged.connect(self.on_tab_changed)
        ml.addWidget(self.tab_bar)

        br = QHBoxLayout(); br.setSpacing(5)
        btns = [
            ("➕ 添加文件夹", self.add_task, "#333"),
            ("📂 批量导入", self.batch_import, "#1565C0"),
            ("🕐 自定义提醒", self.add_custom, "#6A1B9A"),
            ("✏️ 修改", self.edit_task, "#333"),
            ("📁 打开", self.open_selected_folder, "#333"),
            ("✅ 打卡", self.toggle_done, "#2E7D32"),
            ("🗑 删除", self.delete_task, "#C62828"),
            ("🏷 管理标签", self.manage_tabs, "#E65100"),
        ]
        for txt, cb, color in btns:
            btn = QPushButton(txt); btn.clicked.connect(cb)
            btn.setMinimumHeight(32)
            if color != "#333": btn.setStyleSheet(f"QPushButton {{ font-weight:bold; color:{color}; }}")
            br.addWidget(btn)
        br.addStretch(); ml.addLayout(br)
        self.setCentralWidget(c)

    def _rebuild_tabs(self):
        """重建所有 Tab（标签变化时调用）"""
        self.tab_bar.blockSignals(True)
        self.tab_bar.clear()
        self.tab_lists.clear()

        custom_tabs = list(self.settings.data.get("custom_tabs", {}).keys())
        self.tab_order = ["全部"] + BUILTIN_TABS + custom_tabs + ["自定义"]

        for label in self.tab_order:
            lst = QListWidget(); lst.setAlternatingRowColors(True)
            lst.setContextMenuPolicy(Qt.CustomContextMenu)
            lst.customContextMenuRequested.connect(self._on_context)
            lst.itemDoubleClicked.connect(self._on_dblclick)
            self.tab_bar.addTab(lst, f"  {label}  ")
            self.tab_lists[label] = lst

        self.tab_bar.blockSignals(False)

    def _get_tab_type(self, tab_name):
        """Tab 名称 → task type 字段值"""
        if tab_name in BUILTIN_TABS:
            return tab_name
        if tab_name == "自定义":
            return "自定义"
        return tab_name  # custom tabs use their label directly

    # ---- 刷新列表 ----
    def _cur_list(self): return self.tab_lists.get(self._current_tab, self.tab_lists.get("全部"))

    def _filter(self, tab_name):
        if tab_name == "全部": return list(self.mgr.tasks)
        target = self._get_tab_type(tab_name)
        if tab_name == "间隔":
            return [t for t in self.mgr.tasks if t.get("type") == "间隔" and not t.get("is_custom_reminder")]
        if tab_name == "自定义":
            return [t for t in self.mgr.tasks if t.get("is_custom_reminder")]
        return [t for t in self.mgr.tasks if t.get("type") == target and not t.get("is_custom_reminder")]

    def refresh_all_tabs(self):
        today = QDate.currentDate().toString("yyyy-MM-dd")
        # 确保 tab 存在
        if self._current_tab not in self.tab_lists:
            self._current_tab = "全部"

        for tab_name, lst in self.tab_lists.items():
            lst.clear()
            tasks = self._filter(tab_name)
            for t in tasks:
                is_done = (t.get("last_done") == today)
                path_ok = t.get("is_custom_reminder") or os.path.exists(t.get("path",""))
                prefix = "✅ " if is_done else "⬜ "
                text = f"{prefix}{t['name']}"
                item = QListWidgetItem(text); item.setData(Qt.UserRole, t)
                if is_done: item.setForeground(Qt.gray)
                elif not path_ok: item.setForeground(Qt.red); item.setText(f"❌ {t['name']}（失效）")
                if not t.get("alarm_enabled", True) and not is_done: item.setText(f"🔕 {t['name']}")
                lst.addItem(item)
            cnt = len(tasks)
            idx = self.tab_order.index(tab_name) if tab_name in self.tab_order else 0
            self.tab_bar.setTabText(idx, f"  {tab_name}（{cnt}）" if cnt else f"  {tab_name}  ")

        if self._current_tab in self.tab_lists:
            idx = self.tab_order.index(self._current_tab) if self._current_tab in self.tab_order else 0
            self.tab_bar.setCurrentIndex(idx)

    def on_tab_changed(self, idx):
        if idx < len(self.tab_order):
            self._current_tab = self.tab_order[idx]

    # ---- 右键 ----
    def _on_context(self, pos):
        lst = self._cur_list(); item = lst.itemAt(pos)
        if not item: return
        lst.setCurrentItem(item)
        task = item.data(Qt.UserRole)
        menu = QMenu(self)
        if task.get("is_custom_reminder"):
            menu.addAction("✏️ 修改", self.edit_task)
            menu.addAction("✅ 打卡", self.toggle_done)
            menu.addAction("🗑 删除", self.delete_task)
        else:
            menu.addAction("📁 打开文件夹", self.open_selected_folder)
            menu.addAction("✅ 打卡", self.toggle_done)
            menu.addAction("🔔 切换闹钟", self.toggle_alarm)
            menu.addAction("✏️ 修改", self.edit_task)
            menu.addSeparator()
            menu.addAction("🗑 删除", self.delete_task)
        menu.exec(lst.viewport().mapToGlobal(pos))

    def _on_dblclick(self, item):
        t = item.data(Qt.UserRole)
        if t and not t.get("is_custom_reminder"):
            self.open_folder(t.get("path",""))

    def _sel_task(self):
        item = self._cur_list().currentItem()
        return item.data(Qt.UserRole) if item else None

    def _sel_idx(self):
        t = self._sel_task()
        if t:
            try: return self.mgr.tasks.index(t)
            except ValueError: pass
        return -1

    # ---- 操作 ----
    def add_task(self):
        dlg = TaskDialog(self, tab_labels=list(self.settings.data.get("custom_tabs", {}).keys()))
        if dlg.exec():
            d = dlg.get_data()
            if d["name"] and d["path"]:
                self.mgr.tasks.append(d); self.mgr.save(); self.refresh_all_tabs()

    def add_custom(self):
        dlg = CustomReminderDialog(self)
        if dlg.exec():
            d = dlg.get_data()
            if d["name"]:
                self.mgr.tasks.append(d); self.mgr.save(); self.refresh_all_tabs()

    def edit_task(self):
        idx = self._sel_idx()
        if idx < 0: QMessageBox.information(self,"提示","请先选中一个任务"); return
        t = self.mgr.tasks[idx]
        if t.get("is_custom_reminder"):
            dlg = CustomReminderDialog(self, t)
        else:
            dlg = TaskDialog(self, t, list(self.settings.data.get("custom_tabs", {}).keys()), t.get("type","每日"))
        if dlg.exec():
            self.mgr.tasks[idx] = dlg.get_data(); self.mgr.save(); self.refresh_all_tabs()

    def delete_task(self):
        idx = self._sel_idx()
        if idx < 0: return
        t = self.mgr.tasks[idx]
        if QMessageBox.Yes == QMessageBox.question(self,"确认",f"删除「{t['name']}」？"):
            self.mgr.tasks.pop(idx); self.mgr.save(); self.refresh_all_tabs()

    def open_selected_folder(self):
        t = self._sel_task()
        if t and not t.get("is_custom_reminder"):
            self.open_folder(t.get("path",""))

    def open_folder(self, p):
        if p and os.path.exists(p): os.startfile(p)
        else: QMessageBox.warning(self,"错误",f"路径不存在:\n{p}")

    def toggle_done(self):
        idx = self._sel_idx()
        if idx < 0: QMessageBox.information(self,"提示","请先选中一个任务"); return
        today = QDate.currentDate().toString("yyyy-MM-dd")
        cur = self.mgr.tasks[idx].get("last_done")
        self.mgr.tasks[idx]["last_done"] = "" if cur == today else today
        self.mgr.save(); self.refresh_all_tabs()

    def toggle_alarm(self):
        t = self._sel_task()
        if t:
            t["alarm_enabled"] = not t.get("alarm_enabled", False)
            self.mgr.save(); self.refresh_all_tabs()

    # ---- 管理自定义标签 ----
    def manage_tabs(self):
        """管理自定义标签：添加/删除/编辑关键词"""
        dlg = ManageTabsDialog(self, self.settings)
        if dlg.exec():
            self.settings.save()
            self._rebuild_tabs()
            self._current_tab = "全部"
            self.refresh_all_tabs()

    # ---- 批量导入 ----
    def batch_import(self):
        parent = QFileDialog.getExistingDirectory(self, "选择父目录")
        if not parent: return
        try: entries = os.listdir(parent)
        except OSError as e: QMessageBox.warning(self,"错误",str(e)); return

        subdirs = [d for d in entries if os.path.isdir(os.path.join(parent,d))]
        if not subdirs: QMessageBox.information(self,"提示","无子文件夹"); return

        rules = self.settings.get_all_rules()
        imported, skipped = [], []
        for d in sorted(subdirs):
            fp = os.path.join(parent, d)
            if any(t.get("path")==fp for t in self.mgr.tasks): skipped.append(d); continue
            label = classify_folder_name(d, rules)
            day = extract_day_from_name(d)
            task = {"name":d,"path":fp,"type":label,"remind_time":"09:00","remind_day":day,
                    "interval":30,"alarm_enabled":False,"last_done":"","last_reminded":"",
                    "is_custom_reminder":False}
            self.mgr.tasks.append(task)
            imported.append(f"  📁 {d} → {label}")

        if parent not in self.settings.data.get("watch_dirs",[]):
            self.settings.data.setdefault("watch_dirs",[]).append(parent)
            self.settings.save(); self.sync_timer.start(300000)

        self.mgr.save(); self.refresh_all_tabs()
        msg = f"导入完成！\n\n✅ {len(imported)} 个（🔕 闹钟默认关闭）\n"
        if imported: msg += "\n".join(imported[:15])
        if len(imported)>15: msg += f"\n  ...还有 {len(imported)-15} 个"
        if skipped: msg += f"\n\n⏭ 跳过 {len(skipped)} 个（已存在）"
        msg += "\n\n💡 右键开启闹钟 | 自动同步每5分钟"
        QMessageBox.information(self,"导入结果",msg)

    def auto_sync_folders(self):
        for parent in self.settings.data.get("watch_dirs",[]):
            if not os.path.exists(parent): continue
            try: entries = os.listdir(parent)
            except: continue
            cur = {os.path.join(parent,d) for d in entries if os.path.isdir(os.path.join(parent,d))}
            existing = {t["path"] for t in self.mgr.tasks if t.get("path") and not t.get("is_custom_reminder")}
            managed = {p for p in existing if p.startswith(parent+os.sep)}

            rules = self.settings.get_all_rules()
            added = []
            for np in (cur - managed):
                dn = os.path.basename(np)
                label = classify_folder_name(dn, rules)
                day = extract_day_from_name(dn)
                task = {"name":dn,"path":np,"type":label,"remind_time":"09:00","remind_day":day,
                        "interval":30,"alarm_enabled":False,"last_done":"","last_reminded":"",
                        "is_custom_reminder":False}
                self.mgr.tasks.append(task); added.append(dn)

            removed = []
            for op in (managed - cur):
                self.mgr.remove_by_path(op); removed.append(os.path.basename(op))

            if added or removed:
                self.mgr.save(); self.refresh_all_tabs()
                if added: self.tray_icon.showMessage("同步","新增 {} 个文件夹（🔕）".format(len(added)), QSystemTrayIcon.Information, 3000)
                if removed: self.tray_icon.showMessage("同步","移除 {} 个文件夹".format(len(removed)), QSystemTrayIcon.Information, 3000)

    # ---- 托盘 ----
    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self._make_icon())
        m = QMenu()
        a1 = QAction("显示", self); a1.triggered.connect(self.show_and_activate); m.addAction(a1)
        m.addSeparator()
        a2 = QAction("退出", self); a2.triggered.connect(self.app.quit); m.addAction(a2)
        self.tray_icon.setContextMenu(m)
        self.tray_icon.activated.connect(lambda r: self.show_and_activate() if r==QSystemTrayIcon.Trigger else None)
        self.tray_icon.show()

    def _make_icon(self):
        """生成一个现代风格的方形图标（蓝紫渐变 + 白色文件夹）"""
        px = QPixmap(64,64); px.fill(Qt.transparent)
        p = QPainter(px); p.setRenderHint(QPainter.Antialiasing)
        # 圆角矩形背景
        p.setBrush(QBrush(QColor(59,130,246))); p.setPen(Qt.NoPen)
        p.drawRoundedRect(2,2,60,60,14,14)
        # 白色文件夹简笔
        p.setBrush(QBrush(QColor(255,255,255,220))); p.setPen(Qt.NoPen)
        p.drawRoundedRect(10,14,28,6,3,3)   # tab
        p.drawRoundedRect(10,20,44,32,6,6)   # body
        p.end()
        return QIcon(px)

    def show_and_activate(self):
        self.show(); self.activateWindow(); self.raise_()

    def closeEvent(self, e):
        e.ignore(); self.hide()
        self.tray_icon.showMessage("办公助手","已最小化到托盘，后台运行中", QSystemTrayIcon.Information, 2000)

    # ---- 提醒 ----
    def check_reminders(self):
        now = datetime.now(); today = now.strftime("%Y-%m-%d"); ct = now.strftime("%H:%M")
        cd = now.day; cw = now.weekday()

        for t in self.mgr.tasks:
            if t.get("last_done") == today: continue
            if not t.get("alarm_enabled", True): continue
            key = f"{today}_{ct}"; remind = False

            if t.get("is_custom_reminder"):
                remind = self._check_custom(t, now, today, ct, cd, cw, key)
            else:
                tp = t.get("type","每日")
                if tp in ("每日",) and t.get("remind_time")==ct and t.get("last_reminded")!=key:
                    remind=True
                elif tp in ("每周",) and cw==0 and t.get("remind_time")==ct and t.get("last_reminded")!=key:
                    remind=True
                elif tp in ("每月",) and cd==t.get("remind_day",1) and t.get("remind_time")==ct and t.get("last_reminded")!=key:
                    remind=True
                elif tp in ("间隔",):
                    last=t.get("last_interval_check")
                    if not last: t["last_interval_check"]=now.timestamp()
                    elif (now.timestamp()-float(last))>=t.get("interval",30)*60:
                        remind=True; t["last_interval_check"]=now.timestamp()
            if remind:
                t["last_reminded"]=key; self.mgr.save(); self._alert(t)

    def _check_custom(self, t, now, today, ct, cd, cw, key):
        freq = t.get("custom_freq","仅一次")
        rt = t.get("remind_time","09:00")
        if rt != ct: return False
        if t.get("last_reminded")==key: return False
        if freq=="仅一次": return t.get("custom_date","")==today
        if freq=="每天": return True
        if freq=="每周":
            try:
                init=datetime.strptime(t.get("custom_date",today),"%Y-%m-%d")
                return cw==init.weekday()
            except: return cw==0
        if freq=="每月": return cd==t.get("remind_day",1)
        if freq=="每年":
            try:
                init=datetime.strptime(t.get("custom_date",today),"%Y-%m-%d")
                return cd==init.day and now.month==init.month
            except: return False
        if freq=="间隔":
            last=t.get("last_interval_check")
            if not last: t["last_interval_check"]=now.timestamp(); return False
            if (now.timestamp()-float(last))>=t.get("interval",30)*60:
                t["last_interval_check"]=now.timestamp(); return True
            return False
        return False

    def _alert(self, t):
        QApplication.beep()
        title = f"提醒: {t['name']}"
        msg = t.get("note","") or (f"分类：{t.get('type','')}")
        self.tray_icon.showMessage(title, msg, QSystemTrayIcon.Information, 15000)


# ============== ManageTabsDialog ==============
class ManageTabsDialog(QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.setWindowTitle("管理自定义标签")
        self.resize(480, 400)
        self.settings = settings
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>自定义标签</b> — 按关键词自动归类文件夹"))
        layout.addWidget(QLabel("内置标签（每日/每周/每月/间隔）不可删除"))

        self.list_widget = QListWidget()
        self._refresh_list()
        layout.addWidget(self.list_widget)

        bl = QHBoxLayout()
        add_btn = QPushButton("➕ 新建标签"); add_btn.clicked.connect(self._add)
        edit_btn = QPushButton("✏️ 编辑关键词"); edit_btn.clicked.connect(self._edit)
        del_btn = QPushButton("🗑 删除标签"); del_btn.clicked.connect(self._delete)
        bl.addWidget(add_btn); bl.addWidget(edit_btn); bl.addWidget(del_btn)
        layout.addLayout(bl)

        bl2 = QHBoxLayout(); bl2.addStretch()
        ok = QPushButton("完成"); ok.clicked.connect(self.accept); bl2.addWidget(ok)
        layout.addLayout(bl2)

    def _refresh_list(self):
        self.list_widget.clear()
        customs = self.settings.data.get("custom_tabs", {})
        self.list_widget.addItem("📌 每日 — 关键词: 每天, 每日, 日报, daily, every...")
        self.list_widget.addItem("📌 每周 — 关键词: 每周, 周报, weekly, week")
        self.list_widget.addItem("📌 每月 — 关键词: 每月, 月度, 月报, monthly, month")
        self.list_widget.addItem("📌 间隔 — 手动指定（不自动匹配关键词）")
        for label, keywords in customs.items():
            self.list_widget.addItem(f"🏷 {label} — 关键词: {', '.join(keywords)}")

    def _add(self):
        name, ok = QInputDialog.getText(self, "新建标签", "标签名称（如：每季度、每小时）：")
        if not ok or not name.strip(): return
        name = name.strip()
        if name in BUILTIN_TABS or name in ("全部","自定义"):
            QMessageBox.warning(self,"错误","标签名与内置标签冲突"); return
        if name in self.settings.data.get("custom_tabs", {}):
            QMessageBox.warning(self,"错误","标签已存在"); return

        kw, ok2 = QInputDialog.getText(self, "设置关键词", f"「{name}」的匹配关键词（逗号分隔）：\n如：季度, quarterly, Q")
        if not ok2: return
        keywords = [k.strip() for k in kw.split(",") if k.strip()]
        if not keywords:
            QMessageBox.warning(self,"错误","至少需要一个关键词"); return

        self.settings.data.setdefault("custom_tabs",{})[name] = keywords
        self.settings.save()
        self._refresh_list()

    def _edit(self):
        row = self.list_widget.currentRow()
        if row < 0: return
        customs = self.settings.data.get("custom_tabs",{})
        labels = list(customs.keys())
        if row < 4 or row-4 >= len(labels):
            QMessageBox.information(self,"提示","内置标签不可编辑"); return
        label = labels[row-4]
        cur_kw = customs[label]
        kw, ok = QInputDialog.getText(self, "编辑关键词", f"「{label}」的关键词（逗号分隔）：", text=", ".join(cur_kw))
        if ok:
            keywords = [k.strip() for k in kw.split(",") if k.strip()]
            if keywords:
                customs[label] = keywords; self.settings.save(); self._refresh_list()

    def _delete(self):
        row = self.list_widget.currentRow()
        if row < 0: return
        customs = self.settings.data.get("custom_tabs",{})
        labels = list(customs.keys())
        if row < 4 or row-4 >= len(labels):
            QMessageBox.information(self,"提示","内置标签不可删除"); return
        label = labels[row-4]
        if QMessageBox.Yes == QMessageBox.question(self,"确认",f"删除标签「{label}」？\n已有任务不会被删除"):
            del customs[label]; self.settings.save(); self._refresh_list()


# ============== 入口 ==============
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 单实例锁
    server = QLocalServer()
    sock = QLocalSocket(); sock.connectToServer(APP_KEY)
    if sock.waitForConnected(500):
        sock.write(b"show"); sock.flush(); sock.waitForBytesWritten(500); sock.close()
        sys.exit(0)
    sock.close(); server.listen(APP_KEY)

    window = MainWindow(app); window.show()

    def _on_conn():
        conn = server.nextPendingConnection()
        if conn:
            conn.waitForReadyRead(500)
            if b"show" in bytes(conn.readAll()): window.show_and_activate()
            conn.close()
    server.newConnection.connect(_on_conn)

    sys.exit(app.exec())
