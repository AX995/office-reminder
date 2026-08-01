import sys, os, json, re
from datetime import datetime, date
from PySide6.QtCore import Qt, QTimer, QTime, QDate, QMimeData, QPoint
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLabel, QFileDialog,
    QComboBox, QTimeEdit, QSpinBox, QSystemTrayIcon, QMenu, QMessageBox,
    QDialog, QFormLayout, QLineEdit, QTabWidget, QStyle, QCheckBox,
    QDateEdit, QTextEdit, QGroupBox, QInputDialog, QTabBar
)
from PySide6.QtGui import QIcon, QAction, QPainter, QPixmap, QColor, QBrush, QPen, QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket

DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "OfficeReminder")
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(DATA_DIR, "tasks.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
APP_KEY = "OfficeReminder_SingleInstance_v3"

BUILTIN_TABS = ["每日", "每周", "每月", "间隔"]
BUILTIN_RULES = {
    "每日": [r"每天", r"每日", r"日报", r"daily", r"每\s*天", r"每\s*日", r"每(?![周月])", r"every"],
    "每周": [r"每周", r"周报", r"weekly", r"week"],
    "每月": [r"每月", r"月度", r"月报", r"monthly", r"month"],
    "间隔": [],
}

def extract_day(dirname):
    m = re.search(r"(\d+)\s*(?:号|日|th|st|nd|rd)?", dirname, re.IGNORECASE)
    if m: return max(1, min(31, int(m.group(1))))
    cn = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10,
          "十一":11,"十二":12,"十三":13,"十四":14,"十五":15,"十六":16,"十七":17,
          "十八":18,"十九":19,"二十":20,"二十一":21,"二十二":22,"二十三":23,
          "二十四":24,"二十五":25,"二十六":26,"二十七":27,"二十八":28,"二十九":29,"三十":30,"三十一":31}
    for w, n in sorted(cn.items(), key=lambda x: -len(x[0])):
        if w in dirname: return n
    return 1

class Settings:
    def __init__(self):
        self.data = {"watch_dirs": [], "custom_tabs": {}, "tab_order": []}
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
        rules = {}
        for label in self.data.get("tab_order", []):
            if label in self.data.get("custom_tabs", {}):
                rules[label] = [re.escape(k) for k in self.data["custom_tabs"][label]]
            elif label in BUILTIN_RULES:
                rules[label] = BUILTIN_RULES[label]
        # 补上没在 order 里的
        for label, patterns in BUILTIN_RULES.items():
            if label not in rules: rules[label] = patterns
        for label, kws in self.data.get("custom_tabs", {}).items():
            if label not in rules: rules[label] = [re.escape(k) for k in kws]
        return rules
    def get_tab_order(self):
        order = self.data.get("tab_order", [])
        all_tabs = set(BUILTIN_TABS) | set(self.data.get("custom_tabs", {}).keys())
        # 补齐缺失的
        for t in all_tabs:
            if t not in order: order.append(t)
        return order

def classify_folder_name(dirname, rules):
    for label in Settings.__new__(Settings).get_tab_order():
        if label in rules:
            for pat in rules[label]:
                if re.search(pat, dirname, re.IGNORECASE):
                    return label
    # fallback: iterate rules dict in insertion order
    for label, patterns in rules.items():
        for pat in patterns:
            if re.search(pat, dirname, re.IGNORECASE):
                return label
    return "每日"

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
    def remove_by_path(self, p):
        self.tasks = [t for t in self.tasks if t.get("path") != p]

# ===== DraggableTabBar =====
class DraggableTabBar(QTabBar):
    """允许拖动 Tab 标签排序"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMovable(True)
        self._drag_start = -1

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_start = self.tabAt(e.pos())
        super().mousePressEvent(e)

# ===== DroppableListWidget =====
class DroppableListWidget(QListWidget):
    """支持跨列表拖放任务"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(self.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)

    def mimeTypes(self):
        return ["application/x-task-id"]

    def mimeData(self, items):
        m = QMimeData()
        if items:
            task = items[0].data(Qt.UserRole)
            if task:
                m.setData("application/x-task-id", str(id(task)).encode())
        return m

    def dropEvent(self, e):
        if e.source() is self:
            # internal reorder within same list — not supported for custom widgets, ignore
            e.ignore()
            return
        super().dropEvent(e)

# ===== TaskDialog =====
class TaskDialog(QDialog):
    def __init__(self, parent=None, task_data=None, tab_labels=None, tab_type=None):
        super().__init__(parent)
        self.setWindowTitle("设置任务")
        self.resize(460, 420)
        self.task_data = task_data or {}
        self.tab_labels = tab_labels or BUILTIN_TABS
        self.target_tab = tab_type or self.task_data.get("type","每日")
        self.init_ui()

    def init_ui(self):
        layout = QFormLayout(self); layout.setSpacing(10)

        self.name_input = QLineEdit(); self.name_input.setText(self.task_data.get("name",""))
        layout.addRow("名称:", self.name_input)

        pl = QHBoxLayout(); self.path_input = QLineEdit(); self.path_input.setText(self.task_data.get("path",""))
        b = QPushButton("浏览"); b.clicked.connect(lambda: self._browse()); pl.addWidget(self.path_input); pl.addWidget(b)
        layout.addRow("路径:", pl)

        self.type_combo = QComboBox()
        all_l = self.tab_labels
        self.type_combo.addItems(all_l)
        self.type_combo.setCurrentText(self.target_tab if self.target_tab in all_l else "每日")
        self.type_combo.currentTextChanged.connect(self._on_type)
        layout.addRow("归类:", self.type_combo)

        self.alarm_check = QCheckBox("启用闹钟提醒"); self.alarm_check.setChecked(self.task_data.get("alarm_enabled",False))
        layout.addRow("", self.alarm_check)

        # 日期精确选择
        date_l = QHBoxLayout()
        date_l.addWidget(QLabel("日期:"))
        self.date_edit = QDateEdit(); self.date_edit.setCalendarPopup(True); self.date_edit.setDisplayFormat("yyyy-MM-dd")
        ds = self.task_data.get("remind_date","") or QDate.currentDate().toString("yyyy-MM-dd")
        self.date_edit.setDate(QDate.fromString(ds, "yyyy-MM-dd"))
        self.date_once = QCheckBox("指定日期（仅一次）")
        self.date_once.setChecked(self.task_data.get("use_specific_date", False))
        self.date_once.toggled.connect(lambda v: self.date_edit.setEnabled(v))
        self.date_edit.setEnabled(self.date_once.isChecked())
        date_l.addWidget(self.date_edit); date_l.addWidget(self.date_once)

        self.time_edit = QTimeEdit(); self.time_edit.setTime(QTime.fromString(self.task_data.get("remind_time","09:00"),"HH:mm"))
        self.day_spin = QSpinBox(); self.day_spin.setRange(1,31); self.day_spin.setValue(self.task_data.get("remind_day",1))
        self.interval_spin = QSpinBox(); self.interval_spin.setRange(5,1440); self.interval_spin.setSuffix(" 分钟"); self.interval_spin.setValue(self.task_data.get("interval",30))

        self.tw = QWidget(); tl = QHBoxLayout(self.tw); tl.setContentsMargins(0,0,0,0); tl.addWidget(QLabel("时间:")); tl.addWidget(self.time_edit)
        self.dw = QWidget(); dl = QHBoxLayout(self.dw); dl.setContentsMargins(0,0,0,0); dl.addWidget(QLabel("每月:")); dl.addWidget(self.day_spin); dl.addWidget(QLabel("号"))
        self.iw = QWidget(); il = QHBoxLayout(self.iw); il.setContentsMargins(0,0,0,0); il.addWidget(QLabel("间隔:")); il.addWidget(self.interval_spin)

        layout.addRow("", date_l)
        layout.addRow("", self.tw); layout.addRow("", self.dw); layout.addRow("", self.iw)
        self._on_type(self.type_combo.currentText())

        bl = QHBoxLayout(); bl.addStretch()
        sb = QPushButton("保存"); sb.clicked.connect(self.accept); cb = QPushButton("取消"); cb.clicked.connect(self.reject)
        bl.addWidget(sb); bl.addWidget(cb); layout.addRow(bl)

    def _browse(self):
        p = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if p: self.path_input.setText(p)
        if not self.name_input.text(): self.name_input.setText(os.path.basename(p))

    def _on_type(self, txt):
        if txt == "间隔":
            self.tw.hide(); self.dw.hide(); self.iw.show()
        elif txt == "每月":
            self.tw.show(); self.dw.show(); self.iw.hide()
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
            "last_done": self.task_data.get("last_done",""),
            "last_reminded": self.task_data.get("last_reminded",""),
            "is_custom_reminder": False,
            "use_specific_date": self.date_once.isChecked(),
            "remind_date": self.date_edit.date().toString("yyyy-MM-dd") if self.date_once.isChecked() else "",
        }

# ===== CustomReminderDialog =====
class CustomReminderDialog(QDialog):
    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.setWindowTitle("自定义提醒"); self.resize(420, 400)
        self.data = data or {}
        self.init_ui()

    def init_ui(self):
        layout = QFormLayout(self); layout.setSpacing(10)
        self.name_input = QLineEdit(); self.name_input.setText(self.data.get("name","")); self.name_input.setPlaceholderText("内容...")
        layout.addRow("内容:", self.name_input)

        g = QGroupBox("提醒频率"); gl = QVBoxLayout(g)
        self.freq = QComboBox(); self.freq.addItems(["仅一次","每天","每周","每月","每年","间隔"])
        self.freq.setCurrentText(self.data.get("custom_freq","仅一次"))
        self.freq.currentTextChanged.connect(self._on_freq); gl.addWidget(self.freq)

        self.dr = QHBoxLayout(); self.dr.addWidget(QLabel("日期:"));
        self.de = QDateEdit(); self.de.setCalendarPopup(True); self.de.setDisplayFormat("yyyy-MM-dd")
        self.de.setDate(QDate.fromString(self.data.get("custom_date",QDate.currentDate().toString("yyyy-MM-dd")),"yyyy-MM-dd")); self.dr.addWidget(self.de)

        tr = QHBoxLayout(); tr.addWidget(QLabel("时间:")); self.te = QTimeEdit(); self.te.setTime(QTime.fromString(self.data.get("remind_time","09:00"),"HH:mm")); tr.addWidget(self.te)
        self.ir = QHBoxLayout(); self.ir.addWidget(QLabel("间隔:")); self.ie = QSpinBox(); self.ie.setRange(5,1440); self.ie.setSuffix(" 分钟"); self.ie.setValue(self.data.get("interval",30)); self.ir.addWidget(self.ie)

        gl.addLayout(self.dr); gl.addLayout(tr); gl.addLayout(self.ir)
        layout.addRow(g)
        self.note = QTextEdit(); self.note.setMaximumHeight(60); self.note.setPlaceholderText("备注..."); self.note.setText(self.data.get("note",""))
        layout.addRow("备注:", self.note)
        self._on_freq(self.freq.currentText())

        bl = QHBoxLayout(); bl.addStretch()
        sb = QPushButton("保存"); sb.clicked.connect(self.accept); cb = QPushButton("取消"); cb.clicked.connect(self.reject)
        bl.addWidget(sb); bl.addWidget(cb); layout.addRow(bl)

    def _on_freq(self, txt):
        is_once = (txt=="仅一次"); is_interval = (txt=="间隔")
        for i in range(self.dr.count()):
            w = self.dr.itemAt(i).widget()
            if w: w.setVisible(is_once)
        self.de.setVisible(is_once)
        self.te.setVisible(not is_interval)
        for i in range(self.ir.count()):
            w = self.ir.itemAt(i).widget()
            if w: w.setVisible(is_interval)
        self.ie.setVisible(is_interval)

    def get_data(self):
        freq = self.freq.currentText()
        return {
            "name": self.name_input.text().strip(), "path": "", "type": "自定义",
            "remind_time": self.te.time().toString("HH:mm"), "remind_day": 1,
            "interval": self.ie.value(), "alarm_enabled": True,
            "last_done": "", "last_reminded": "", "is_custom_reminder": True,
            "custom_freq": freq,
            "custom_date": self.de.date().toString("yyyy-MM-dd") if freq=="仅一次" else "",
            "note": self.note.toPlainText().strip(),
        }

# ===== MainWindow =====
class MainWindow(QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app; self.mgr = TaskManager(); self.settings = Settings()
        self.setWindowTitle("办公助手"); self.resize(960, 600)
        self._current_tab = "全部"
        self.init_ui(); self.init_tray(); self.refresh_all()

        self.remind_timer = QTimer(self); self.remind_timer.timeout.connect(self.check_reminders); self.remind_timer.start(30000)
        self.sync_timer = QTimer(self); self.sync_timer.timeout.connect(self.auto_sync)
        if self.settings.data.get("watch_dirs"): self.sync_timer.start(300000)

    def init_ui(self):
        c = QWidget(); ml = QVBoxLayout(c); ml.setContentsMargins(4,4,4,4); ml.setSpacing(4)

        self.tab_widget = QTabWidget(); self.tab_widget.setDocumentMode(True)
        self.tab_bar = DraggableTabBar()
        self.tab_widget.setTabBar(self.tab_bar)
        self.tab_bar.tabMoved.connect(self._on_tab_moved)
        self.tab_lists = {}; self.tab_order = []
        self._rebuild_tabs()
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        ml.addWidget(self.tab_widget)

        br = QHBoxLayout(); br.setSpacing(4)
        btns = [
            ("+ 添加", self.add_task, "#333"),
            ("📂 批量导入", self.batch_import, "#1565C0"),
            ("🕐 自定义", self.add_custom, "#6A1B9A"),
            ("✏️ 修改", self.edit_task, "#333"),
            ("📁 打开", self.open_selected, "#333"),
            ("🗑 删除", self.delete_task, "#C62828"),
            ("🏷 标签管理", self.manage_tabs, "#E65100"),
        ]
        for txt, cb, color in btns:
            btn = QPushButton(txt); btn.clicked.connect(cb); btn.setMinimumHeight(32)
            if color != "#333": btn.setStyleSheet(f"QPushButton{{font-weight:bold;color:{color};}}")
            br.addWidget(btn)
        br.addStretch(); ml.addLayout(br)
        self.setCentralWidget(c)

    def _rebuild_tabs(self):
        self.tab_widget.blockSignals(True); self.tab_widget.clear(); self.tab_lists.clear()
        self.tab_order = ["全部"] + self.settings.get_tab_order() + ["自定义"]
        for label in self.tab_order:
            lst = DroppableListWidget()
            lst.setAlternatingRowColors(True)
            lst.setContextMenuPolicy(Qt.CustomContextMenu)
            lst.customContextMenuRequested.connect(self._on_context)
            lst.itemDoubleClicked.connect(self._on_dblclick)
            lst.dropEvent = lambda e, l=label: self._handle_drop(e, l)
            self.tab_widget.addTab(lst, f"  {label}  ")
            self.tab_lists[label] = lst
        self.tab_widget.blockSignals(False)

    def _on_tab_moved(self, from_idx, to_idx):
        # Update tab_order (skip "全部" at index 0 and "自定义" at end)
        label_order = []
        for i in range(self.tab_widget.count()):
            txt = self.tab_widget.tabText(i).strip()
            if txt not in ("全部","自定义"):
                label_order.append(txt)
        self.settings.data["tab_order"] = label_order
        self.settings.save()
        # Update self.tab_order
        self.tab_order = ["全部"] + label_order + ["自定义"]
        self._current_tab = self.tab_order[self.tab_widget.currentIndex()]

    def _handle_drop(self, e, target_label):
        """处理拖放：把任务移动到目标标签"""
        data = e.mimeData().data("application/x-task-id")
        if data:
            task_id = int(data.data().decode())
            # find task
            task = None
            for t in self.mgr.tasks:
                if id(t) == task_id:
                    task = t; break
            if task:
                old_type = task.get("type")
                new_type = target_label if target_label not in ("全部","自定义") else "每日"
                if target_label == "自定义":
                    task["is_custom_reminder"] = True
                    task["type"] = "自定义"
                else:
                    task["is_custom_reminder"] = False
                    task["type"] = new_type
                self.mgr.save(); self.refresh_all()
                e.acceptProposedAction()

    def _get_tab_type(self, tab_name):
        if tab_name in BUILTIN_TABS: return tab_name
        if tab_name == "自定义": return "自定义"
        return tab_name

    def _cur_list(self): return self.tab_lists.get(self._current_tab, self.tab_lists.get("全部"))

    def _filter(self, tab_name):
        if tab_name == "全部": return list(self.mgr.tasks)
        if tab_name == "自定义": return [t for t in self.mgr.tasks if t.get("is_custom_reminder")]
        target = self._get_tab_type(tab_name)
        return [t for t in self.mgr.tasks if t.get("type") == target and not t.get("is_custom_reminder")]

    def _sort_key(self, t):
        """排序：已完成的排后面，按日期+名称排列"""
        today = QDate.currentDate().toString("yyyy-MM-dd")
        done = 1 if t.get("last_done") == today else 0
        day = t.get("remind_day", 0)
        name = t.get("name", "")
        return (done, day, name)

    def refresh_all(self):
        today = QDate.currentDate().toString("yyyy-MM-dd")
        if self._current_tab not in self.tab_lists: self._current_tab = "全部"

        for tab_name, lst in self.tab_lists.items():
            lst.clear()
            tasks = sorted(self._filter(tab_name), key=self._sort_key)
            for t in tasks:
                is_done = (t.get("last_done") == today)
                path_ok = t.get("is_custom_reminder") or os.path.exists(t.get("path",""))

                # 构建显示 widget
                row_w = QWidget()
                row_l = QHBoxLayout(row_w); row_l.setContentsMargins(4,2,4,2); row_l.setSpacing(6)

                # 左侧复选框
                cb = QCheckBox(); cb.setChecked(is_done)
                cb.toggled.connect(lambda checked, tk=t: self._on_checkbox(tk, checked))
                row_l.addWidget(cb)

                # 名称
                name_lbl = QLabel(t["name"])
                if is_done:
                    name_lbl.setStyleSheet("color:gray; text-decoration:line-through;")
                elif not path_ok:
                    name_lbl.setStyleSheet("color:red;")
                row_l.addWidget(name_lbl)
                row_l.addStretch()

                # 右侧闹钟图标
                alarm_lbl = QLabel("🔕" if not t.get("alarm_enabled", True) else "🔔")
                alarm_lbl.setToolTip("闹钟已关闭" if not t.get("alarm_enabled", True) else "闹钟已开启")
                alarm_lbl.mousePressEvent = lambda e, tk=t, al=alarm_lbl: self._toggle_alarm_icon(tk, al)
                row_l.addWidget(alarm_lbl)

                # 存储数据
                item = QListWidgetItem()
                item.setSizeHint(row_w.sizeHint())
                item.setData(Qt.UserRole, t)
                lst.addItem(item)
                lst.setItemWidget(item, row_w)

            cnt = len(tasks)
            idx = self.tab_order.index(tab_name) if tab_name in self.tab_order else 0
            self.tab_widget.setTabText(idx, f"  {tab_name}（{cnt}）" if cnt else f"  {tab_name}  ")

        if self._current_tab in self.tab_lists:
            idx = self.tab_order.index(self._current_tab) if self._current_tab in self.tab_order else 0
            self.tab_widget.setCurrentIndex(idx)

    def _on_checkbox(self, task, checked):
        today = QDate.currentDate().toString("yyyy-MM-dd")
        task["last_done"] = today if checked else ""
        self.mgr.save(); self.refresh_all()

    def _toggle_alarm_icon(self, task, lbl):
        task["alarm_enabled"] = not task.get("alarm_enabled", True)
        lbl.setText("🔕" if not task["alarm_enabled"] else "🔔")
        self.mgr.save()

    def on_tab_changed(self, idx):
        if idx < len(self.tab_order): self._current_tab = self.tab_order[idx]

    def _on_context(self, pos):
        lst = self._cur_list(); item = lst.itemAt(pos)
        if not item: return
        lst.setCurrentItem(item); task = item.data(Qt.UserRole)
        menu = QMenu(self)
        if not task.get("is_custom_reminder"):
            menu.addAction("📁 打开文件夹", self.open_selected)
        menu.addAction("✅ 打卡/取消", self.toggle_done)
        menu.addAction("🔔 切换闹钟", self.toggle_alarm)
        menu.addAction("✏️ 修改", self.edit_task)
        menu.addSeparator()
        menu.addAction("🗑 删除", self.delete_task)
        menu.exec(lst.viewport().mapToGlobal(pos))

    def _on_dblclick(self, item):
        t = item.data(Qt.UserRole)
        if t and not t.get("is_custom_reminder"): self.open_folder(t.get("path",""))

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
        dlg = TaskDialog(self, tab_labels=self.settings.get_tab_order())
        if dlg.exec():
            d = dlg.get_data()
            if d["name"] and d["path"]: self.mgr.tasks.append(d); self.mgr.save(); self.refresh_all()

    def add_custom(self):
        dlg = CustomReminderDialog(self)
        if dlg.exec():
            d = dlg.get_data()
            if d["name"]: self.mgr.tasks.append(d); self.mgr.save(); self.refresh_all()

    def edit_task(self):
        idx = self._sel_idx()
        if idx < 0: QMessageBox.information(self,"提示","请选中任务"); return
        t = self.mgr.tasks[idx]
        if t.get("is_custom_reminder"):
            dlg = CustomReminderDialog(self, t)
        else:
            dlg = TaskDialog(self, t, self.settings.get_tab_order(), t.get("type","每日"))
        if dlg.exec(): self.mgr.tasks[idx] = dlg.get_data(); self.mgr.save(); self.refresh_all()

    def delete_task(self):
        idx = self._sel_idx()
        if idx < 0: return
        t = self.mgr.tasks[idx]
        if QMessageBox.Yes == QMessageBox.question(self,"确认",f"删除「{t['name']}」？"):
            self.mgr.tasks.pop(idx); self.mgr.save(); self.refresh_all()

    def open_selected(self):
        t = self._sel_task()
        if t and not t.get("is_custom_reminder"): self.open_folder(t.get("path",""))

    def open_folder(self, p):
        if p and os.path.exists(p): os.startfile(p)
        else: QMessageBox.warning(self,"错误",f"路径不存在:\n{p}")

    def toggle_done(self):
        idx = self._sel_idx()
        if idx < 0: return
        today = QDate.currentDate().toString("yyyy-MM-dd")
        cur = self.mgr.tasks[idx].get("last_done")
        self.mgr.tasks[idx]["last_done"] = "" if cur == today else today
        self.mgr.save(); self.refresh_all()

    def toggle_alarm(self):
        t = self._sel_task()
        if t: t["alarm_enabled"] = not t.get("alarm_enabled",False); self.mgr.save(); self.refresh_all()

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
            label = classify_folder_name(d, rules); day = extract_day(d)
            task = {"name":d,"path":fp,"type":label,"remind_time":"09:00","remind_day":day,
                    "interval":30,"alarm_enabled":False,"last_done":"","last_reminded":"",
                    "is_custom_reminder":False,"use_specific_date":False,"remind_date":""}
            self.mgr.tasks.append(task); imported.append(f"  📁 {d} → {label}")
        if parent not in self.settings.data.get("watch_dirs",[]):
            self.settings.data.setdefault("watch_dirs",[]).append(parent); self.settings.save(); self.sync_timer.start(300000)
        self.mgr.save(); self.refresh_all()
        msg = f"导入完成！\n\n✅ {len(imported)} 个（🔕 默认关闭）\n"
        if imported: msg += "\n".join(imported[:15])
        if len(imported)>15: msg += f"\n  ...还有 {len(imported)-15} 个"
        if skipped: msg += f"\n\n⏭ 跳过 {len(skipped)} 个（已存在）"
        QMessageBox.information(self,"导入结果",msg)

    def auto_sync(self):
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
                dn = os.path.basename(np); label = classify_folder_name(dn, rules); day = extract_day(dn)
                task = {"name":dn,"path":np,"type":label,"remind_time":"09:00","remind_day":day,
                        "interval":30,"alarm_enabled":False,"last_done":"","last_reminded":"",
                        "is_custom_reminder":False,"use_specific_date":False,"remind_date":""}
                self.mgr.tasks.append(task); added.append(dn)
            removed = []
            for op in (managed - cur):
                self.mgr.remove_by_path(op); removed.append(os.path.basename(op))
            if added or removed:
                self.mgr.save(); self.refresh_all()
                if added: self.tray_icon.showMessage("同步",f"新增 {len(added)} 个文件夹", QSystemTrayIcon.Information, 3000)
                if removed: self.tray_icon.showMessage("同步",f"移除 {len(removed)} 个文件夹", QSystemTrayIcon.Information, 3000)

    # ---- 管理标签 ----
    def manage_tabs(self):
        dlg = ManageTabsDialog(self, self.settings)
        if dlg.exec():
            self.settings.save()
            self._rebuild_tabs()
            self._current_tab = "全部"
            self.refresh_all()

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
        px = QPixmap(64,64); px.fill(Qt.transparent)
        p = QPainter(px); p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor(59,130,246))); p.setPen(Qt.NoPen)
        p.drawRoundedRect(2,2,60,60,14,14)
        p.setBrush(QBrush(QColor(255,255,255,220)))
        p.drawRoundedRect(10,14,28,6,3,3)
        p.drawRoundedRect(10,20,44,32,6,6)
        p.end(); return QIcon(px)

    def show_and_activate(self):
        self.show(); self.activateWindow(); self.raise_()

    def closeEvent(self, e):
        e.ignore(); self.hide()
        self.tray_icon.showMessage("办公助手","已最小化到托盘", QSystemTrayIcon.Information, 2000)

    # ---- 提醒 ----
    def check_reminders(self):
        now = datetime.now(); today = now.strftime("%Y-%m-%d"); ct = now.strftime("%H:%M")
        cd = now.day; cw = now.weekday()

        # ---- 自动重置已完成标记 ----
        # 只在每天第一次检测到跨天时重置
        last_reset_date = getattr(self, "_last_reset_date", "")
        if last_reset_date != today:
            self._last_reset_date = today
            reset_count = 0
            for t in self.mgr.tasks:
                tp = t.get("type", "每日")
                if t.get("is_custom_reminder"):
                    continue
                last = t.get("last_done", "")
                if not last:
                    continue

                should_reset = False
                if tp == "每日":
                    # 每天零点后重置
                    if last != today:
                        should_reset = True
                elif tp == "每周":
                    # 每周一凌晨重置
                    if cw == 0 and last != today:
                        should_reset = True
                elif tp == "每月":
                    # 每月1号凌晨重置
                    if cd == 1 and last != today:
                        should_reset = True

                if should_reset:
                    t["last_done"] = ""
                    reset_count += 1

            if reset_count:
                self.mgr.save()
        # ---- 重置完毕，继续正常提醒 ----

        for t in self.mgr.tasks:
            if t.get("last_done") == today: continue
            if not t.get("alarm_enabled", True): continue
            key = f"{today}_{ct}"; remind = False
            if t.get("is_custom_reminder"):
                remind = self._check_custom(t, now, today, ct, cd, cw, key)
            else:
                # 指定日期（仅一次）
                if t.get("use_specific_date") and t.get("remind_date"):
                    if t["remind_date"] == today and t.get("remind_time")==ct and t.get("last_reminded")!=key:
                        remind = True
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
            if remind: t["last_reminded"]=key; self.mgr.save(); self._alert(t)

    def _check_custom(self, t, now, today, ct, cd, cw, key):
        freq = t.get("custom_freq","仅一次"); rt = t.get("remind_time","09:00")
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

    def _alert(self, t):
        QApplication.beep()
        title = f"提醒: {t['name']}"
        msg = t.get("note","") or (f"分类: {t.get('type','')}")
        self.tray_icon.showMessage(title, msg, QSystemTrayIcon.Information, 15000)


# ===== ManageTabsDialog =====
class ManageTabsDialog(QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.setWindowTitle("管理标签"); self.resize(480, 400)
        self.settings = settings
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>标签管理</b> — 拖动标签栏可直接排序"))

        self.list_widget = QListWidget()
        self._refresh(); layout.addWidget(self.list_widget)

        bl = QHBoxLayout()
        b1 = QPushButton("+ 新建"); b1.clicked.connect(self._add)
        b2 = QPushButton("✏️ 关键词"); b2.clicked.connect(self._edit)
        b3 = QPushButton("🗑 删除"); b3.clicked.connect(self._delete)
        bl.addWidget(b1); bl.addWidget(b2); bl.addWidget(b3); layout.addLayout(bl)

        bl2 = QHBoxLayout(); bl2.addStretch()
        ok = QPushButton("完成"); ok.clicked.connect(self.accept); bl2.addWidget(ok)
        layout.addLayout(bl2)

    def _refresh(self):
        self.list_widget.clear()
        self.list_widget.addItem("📌 每日 — 每天, 每日, daily, every...")
        self.list_widget.addItem("📌 每周 — 每周, 周报, weekly, week")
        self.list_widget.addItem("📌 每月 — 每月, 月度, monthly, month")
        self.list_widget.addItem("📌 间隔 — 手动指定")
        for label, kws in self.settings.data.get("custom_tabs",{}).items():
            self.list_widget.addItem(f"🏷 {label} — {', '.join(kws)}")

    def _add(self):
        name, ok = QInputDialog.getText(self,"新建标签","标签名称:")
        if not ok or not name.strip(): return
        name = name.strip()
        if name in BUILTIN_TABS or name in ("全部","自定义"):
            QMessageBox.warning(self,"错误","名称冲突"); return
        if name in self.settings.data.get("custom_tabs",{}):
            QMessageBox.warning(self,"错误","已存在"); return
        kw, ok2 = QInputDialog.getText(self,"关键词",f"「{name}」的匹配关键词(逗号分隔):\n如: 季度, quarterly, Q")
        if not ok2: return
        keywords = [k.strip() for k in kw.split(",") if k.strip()]
        if not keywords: QMessageBox.warning(self,"错误","需要关键词"); return
        self.settings.data.setdefault("custom_tabs",{})[name] = keywords
        self.settings.save(); self._refresh()

    def _edit(self):
        row = self.list_widget.currentRow()
        if row < 0: return
        customs = self.settings.data.get("custom_tabs",{}); labels = list(customs.keys())
        if row < 4 or row-4 >= len(labels):
            QMessageBox.information(self,"提示","内置标签不可编辑"); return
        label = labels[row-4]; cur = customs[label]
        kw, ok = QInputDialog.getText(self,"编辑关键词",f"「{label}」的关键词:", text=", ".join(cur))
        if ok:
            kws = [k.strip() for k in kw.split(",") if k.strip()]
            if kws: customs[label] = kws; self.settings.save(); self._refresh()

    def _delete(self):
        row = self.list_widget.currentRow()
        if row < 0: return
        customs = self.settings.data.get("custom_tabs",{}); labels = list(customs.keys())
        if row < 4 or row-4 >= len(labels):
            QMessageBox.information(self,"提示","内置标签不可删除"); return
        label = labels[row-4]
        if QMessageBox.Yes == QMessageBox.question(self,"确认",f"删除标签「{label}」？"):
            del customs[label]; self.settings.save(); self._refresh()


# ===== 入口 =====
if __name__ == "__main__":
    app = QApplication(sys.argv); app.setQuitOnLastWindowClosed(False)
    server = QLocalServer(); sock = QLocalSocket(); sock.connectToServer(APP_KEY)
    if sock.waitForConnected(500):
        sock.write(b"show"); sock.flush(); sock.waitForBytesWritten(500); sock.close(); sys.exit(0)
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
