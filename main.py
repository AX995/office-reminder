import sys
import os
import json
import re
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, QTime, QDate
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLabel, QFileDialog,
    QComboBox, QTimeEdit, QSpinBox, QSystemTrayIcon, QMenu, QMessageBox,
    QDialog, QFormLayout, QLineEdit, QTabWidget, QStyle, QCheckBox,
    QDateEdit, QTextEdit, QGroupBox
)
from PySide6.QtGui import QIcon, QAction, QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket

CONFIG_FILE = "config.json"
SETTINGS_FILE = "settings.json"

# ==================== 单实例锁 ====================
APP_KEY = "OfficeFolderManager_SingleInstance"

# ==================== 文件夹名自动分类 ====================
CLASSIFY_RULES = [
    (r"(?:每周|周报|weekly|week)",              "每周任务"),
    (r"(?:每月|月度|月报|monthly)",              "每月固定日任务"),
    (r"(?:每天|每日|日报|daily|每\s*天|每\s*日)", "每日任务"),
    (r"(?:每|every)",                           "每日任务"),
]

TAB_ORDER = ["全部", "每日", "每周", "每月", "间隔", "自定义"]

TYPE_TO_TAB = {
    "每日任务":     "每日",
    "每周任务":     "每周",
    "每月固定日任务": "每月",
    "间隔时间提醒":   "间隔",
    "自定义提醒":    "自定义",
}


def classify_folder_name(dirname: str) -> str:
    for pattern, task_type in CLASSIFY_RULES:
        if re.search(pattern, dirname, re.IGNORECASE):
            return task_type
    return "每日任务"


def extract_day_from_name(dirname: str) -> int:
    m = re.search(r"(\d+)\s*(?:号|日|th|st|nd|rd)?", dirname, re.IGNORECASE)
    if m:
        day = int(m.group(1))
        return max(1, min(day, 31))
    cn = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10,
          "十一":11,"十二":12,"十三":13,"十四":14,"十五":15,"十六":16,"十七":17,
          "十八":18,"十九":19,"二十":20,"二十一":21,"二十二":22,"二十三":23,
          "二十四":24,"二十五":25,"二十六":26,"二十七":27,"二十八":28,
          "二十九":29,"三十":30,"三十一":31}
    for word, num in sorted(cn.items(), key=lambda x: -len(x[0])):
        if word in dirname:
            return num
    return 1


# ==================== 全局设置 ====================
class Settings:
    def __init__(self):
        self.data = {"watch_dirs": []}
        self.load()

    def load(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                pass

    def save(self):
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)


# ==================== 数据管理 ====================
class TaskManager:
    def __init__(self):
        self.tasks = []
        self.load_tasks()

    def load_tasks(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self.tasks = json.load(f)
            except Exception:
                self.tasks = []
        else:
            self.tasks = []

    def save_tasks(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.tasks, f, ensure_ascii=False, indent=2)

    def get_by_path(self, path):
        for t in self.tasks:
            if t.get("path") == path:
                return t
        return None

    def remove_by_path(self, path):
        self.tasks = [t for t in self.tasks if t.get("path") != path]

# ==================== 文件夹任务对话框 ====================
class TaskDialog(QDialog):
    def __init__(self, parent=None, task_data=None):
        super().__init__(parent)
        self.setWindowTitle("设置文件夹任务")
        self.resize(420, 360)
        self.task_data = task_data or {}
        self.init_ui()

    def init_ui(self):
        layout = QFormLayout(self)
        layout.setSpacing(10)

        self.name_input = QLineEdit()
        self.name_input.setText(self.task_data.get("name", ""))
        layout.addRow("任务名称:", self.name_input)

        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setText(self.task_data.get("path", ""))
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_path)
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(browse_btn)
        layout.addRow("文件夹路径:", path_layout)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["每日任务", "每周任务", "每月固定日任务", "间隔时间提醒"])
        current_type = self.task_data.get("type", "每日任务")
        self.type_combo.setCurrentText(current_type)
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        layout.addRow("任务类型:", self.type_combo)

        # 闹钟开关
        self.alarm_check = QCheckBox("启用提醒闹钟")
        self.alarm_check.setChecked(self.task_data.get("alarm_enabled", False))
        layout.addRow("", self.alarm_check)

        self.time_edit = QTimeEdit()
        time_str = self.task_data.get("remind_time", "09:00")
        self.time_edit.setTime(QTime.fromString(time_str, "HH:mm"))

        self.day_spin = QSpinBox()
        self.day_spin.setRange(1, 31)
        self.day_spin.setValue(self.task_data.get("remind_day", 1))

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setSuffix(" 分钟")
        self.interval_spin.setValue(self.task_data.get("interval", 60))

        self.time_widget = QWidget()
        tl = QHBoxLayout(self.time_widget)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(QLabel("提醒时间:"))
        tl.addWidget(self.time_edit)

        self.day_widget = QWidget()
        dl = QHBoxLayout(self.day_widget)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(QLabel("每月:"))
        dl.addWidget(self.day_spin)
        dl.addWidget(QLabel("号"))

        self.interval_widget = QWidget()
        il = QHBoxLayout(self.interval_widget)
        il.setContentsMargins(0, 0, 0, 0)
        il.addWidget(QLabel("每隔:"))
        il.addWidget(self.interval_spin)

        layout.addRow("", self.time_widget)
        layout.addRow("", self.day_widget)
        layout.addRow("", self.interval_widget)

        self.on_type_changed(self.type_combo.currentText())

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

    def browse_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择办公文件夹")
        if path:
            self.path_input.setText(path)
            if not self.name_input.text():
                self.name_input.setText(os.path.basename(path))

    def on_type_changed(self, text):
        if text in ("每日任务", "每周任务"):
            self.time_widget.show()
            self.day_widget.hide()
            self.interval_widget.hide()
        elif text == "每月固定日任务":
            self.time_widget.show()
            self.day_widget.show()
            self.interval_widget.hide()
        elif text == "间隔时间提醒":
            self.time_widget.hide()
            self.day_widget.hide()
            self.interval_widget.show()

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
            "is_custom": False,
        }

# ==================== 自定义提醒对话框 ====================
class CustomTaskDialog(QDialog):
    def __init__(self, parent=None, task_data=None):
        super().__init__(parent)
        self.setWindowTitle("自定义提醒任务")
        self.resize(420, 380)
        self.task_data = task_data or {}
        self.init_ui()

    def init_ui(self):
        layout = QFormLayout(self)
        layout.setSpacing(10)

        self.name_input = QLineEdit()
        self.name_input.setText(self.task_data.get("name", ""))
        self.name_input.setPlaceholderText("输入提醒内容...")
        layout.addRow("提醒内容:", self.name_input)

        # 提醒频率
        freq_group = QGroupBox("提醒频率")
        freq_layout = QVBoxLayout(freq_group)

        self.freq_combo = QComboBox()
        self.freq_combo.addItems(["仅一次", "每天", "每周", "每月", "每年"])
        current_freq = self.task_data.get("custom_freq", "仅一次")
        self.freq_combo.setCurrentText(current_freq)
        self.freq_combo.currentTextChanged.connect(self.on_freq_changed)
        freq_layout.addWidget(self.freq_combo)

        # 日期
        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("日期:"))
        self.date_edit = QDateEdit()
        date_str = self.task_data.get("custom_date", QDate.currentDate().toString("yyyy-MM-dd"))
        self.date_edit.setDate(QDate.fromString(date_str, "yyyy-MM-dd"))
        self.date_edit.setCalendarPopup(True)
        date_row.addWidget(self.date_edit)
        self.date_row = date_row

        # 时间
        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("时间:"))
        self.time_edit = QTimeEdit()
        time_str = self.task_data.get("remind_time", "09:00")
        self.time_edit.setTime(QTime.fromString(time_str, "HH:mm"))
        time_row.addWidget(self.time_edit)

        freq_layout.addLayout(date_row)
        freq_layout.addLayout(time_row)
        layout.addRow(freq_group)

        # 备注
        self.note_input = QTextEdit()
        self.note_input.setMaximumHeight(80)
        self.note_input.setPlaceholderText("可选：添加备注说明...")
        self.note_input.setText(self.task_data.get("note", ""))
        layout.addRow("备注:", self.note_input)

        self.on_freq_changed(self.freq_combo.currentText())

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

    def on_freq_changed(self, text):
        if text == "仅一次":
            self.date_row[0].setVisible(True)
            self.date_edit.setVisible(True)
        else:
            self.date_row[0].setVisible(False)
            self.date_edit.setVisible(False)

    def get_data(self):
        freq = self.freq_combo.currentText()
        date_str = self.date_edit.date().toString("yyyy-MM-dd") if freq == "仅一次" else ""
        return {
            "name": self.name_input.text().strip(),
            "path": "",
            "type": "自定义提醒",
            "remind_time": self.time_edit.time().toString("HH:mm"),
            "remind_day": 1,
            "interval": 60,
            "alarm_enabled": True,
            "last_done": "",
            "last_reminded": "",
            "is_custom": True,
            "custom_freq": freq,
            "custom_date": date_str,
            "note": self.note_input.toPlainText().strip(),
        }

# ==================== 主窗口 ====================
class MainWindow(QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.mgr = TaskManager()
        self.settings = Settings()
        self.setWindowTitle("办公文件夹统一管理助手")
        self.resize(860, 560)
        self._current_tab = "全部"

        self.init_ui()
        self.init_tray()
        self.refresh_all_tabs()

        # 提醒定时器
        self.remind_timer = QTimer(self)
        self.remind_timer.timeout.connect(self.check_reminders)
        self.remind_timer.start(30000)

        # 文件夹同步定时器（每5分钟）
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.auto_sync_folders)
        if self.settings.data.get("watch_dirs"):
            self.sync_timer.start(300000)  # 5分钟

    # ---------- UI ----------
    def init_ui(self):
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        self.tab_bar = QTabWidget()
        self.tab_bar.setDocumentMode(True)
        self.tab_lists = {}

        for label in TAB_ORDER:
            lst = QListWidget()
            lst.setAlternatingRowColors(True)
            lst.setContextMenuPolicy(Qt.CustomContextMenu)
            lst.customContextMenuRequested.connect(self.on_list_context_menu)
            lst.itemDoubleClicked.connect(self.on_item_double_clicked)
            self.tab_bar.addTab(lst, f"  {label}  ")
            self.tab_lists[label] = lst

        self.tab_bar.currentChanged.connect(self.on_tab_changed)
        main_layout.addWidget(self.tab_bar)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        add_btn    = QPushButton("➕ 添加文件夹")
        import_btn = QPushButton("📂 批量导入")
        custom_btn = QPushButton("🕐 自定义提醒")
        edit_btn   = QPushButton("✏️ 修改")
        open_btn   = QPushButton("📁 打开")
        done_btn   = QPushButton("✅ 打卡")
        del_btn    = QPushButton("🗑 删除")

        import_btn.setStyleSheet("QPushButton { font-weight: bold; color: #1565C0; }")
        custom_btn.setStyleSheet("QPushButton { font-weight: bold; color: #6A1B9A; }")
        done_btn.setStyleSheet("QPushButton { color: #2E7D32; }")
        del_btn.setStyleSheet("QPushButton { color: #C62828; }")

        add_btn.clicked.connect(self.add_task)
        import_btn.clicked.connect(self.batch_import)
        custom_btn.clicked.connect(self.add_custom_task)
        edit_btn.clicked.connect(self.edit_task)
        open_btn.clicked.connect(self.open_selected_folder)
        done_btn.clicked.connect(self.toggle_done)
        del_btn.clicked.connect(self.delete_task)

        for btn in [add_btn, import_btn, custom_btn, edit_btn, open_btn, done_btn, del_btn]:
            btn.setMinimumHeight(34)
            btn_row.addWidget(btn)

        btn_row.addStretch()
        main_layout.addLayout(btn_row)

        self.setCentralWidget(central)

    # ---------- 列表刷新 ----------
    def _current_list(self):
        return self.tab_lists.get(self._current_tab, self.tab_lists["全部"])

    def _filter_tasks(self, tab_name):
        if tab_name == "全部":
            return list(self.mgr.tasks)
        reverse_map = {v: k for k, v in TYPE_TO_TAB.items()}
        target_type = reverse_map.get(tab_name, "")
        return [t for t in self.mgr.tasks if t.get("type") == target_type]

    def refresh_all_tabs(self):
        today_str = QDate.currentDate().toString("yyyy-MM-dd")

        for tab_name, lst in self.tab_lists.items():
            lst.clear()
            tasks = self._filter_tasks(tab_name)

            for t in tasks:
                is_done = (t.get("last_done") == today_str)
                path_ok = t.get("is_custom") or os.path.exists(t.get("path", ""))

                prefix = "✅ " if is_done else "⬜ "
                text = f"{prefix}{t['name']}"

                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, t)

                if is_done:
                    item.setForeground(Qt.gray)
                elif not path_ok:
                    item.setForeground(Qt.red)
                    item.setText(f"❌ {t['name']}（失效）")

                # 闹钟关闭标记
                if not t.get("alarm_enabled", True) and not is_done:
                    item.setText(f"🔕 {t['name']}")

                lst.addItem(item)

            count = len(tasks)
            self.tab_bar.setTabText(
                TAB_ORDER.index(tab_name),
                f"  {tab_name}（{count}）" if count else f"  {tab_name}  "
            )

        if self._current_tab in self.tab_lists:
            idx = TAB_ORDER.index(self._current_tab)
            self.tab_bar.setCurrentIndex(idx)

    def on_tab_changed(self, index):
        self._current_tab = TAB_ORDER[index]

    # ---------- 右键菜单 ----------
    def on_list_context_menu(self, pos):
        lst = self._current_list()
        item = lst.itemAt(pos)
        if not item:
            return
        lst.setCurrentItem(item)
        task = item.data(Qt.UserRole)

        menu = QMenu(self)
        if task.get("is_custom"):
            menu.addAction("✏️ 修改", self.edit_task)
            menu.addAction("✅ 打卡/取消打卡", self.toggle_done)
            menu.addAction("🗑 删除", self.delete_task)
        else:
            menu.addAction("📁 打开文件夹", self.open_selected_folder)
            menu.addAction("✅ 打卡/取消打卡", self.toggle_done)
            if task.get("alarm_enabled", False):
                menu.addAction("🔕 关闭闹钟", self.toggle_alarm)
            else:
                menu.addAction("🔔 开启闹钟", self.toggle_alarm)
            menu.addAction("✏️ 修改设置", self.edit_task)
            menu.addSeparator()
            menu.addAction("🗑 删除任务", self.delete_task)
        menu.exec(lst.viewport().mapToGlobal(pos))

    def on_item_double_clicked(self, item):
        task = item.data(Qt.UserRole)
        if task and not task.get("is_custom"):
            self.open_folder(task.get("path", ""))

    # ---------- 选中任务 ----------
    def _selected_task(self):
        lst = self._current_list()
        item = lst.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _selected_index_in_mgr(self):
        task = self._selected_task()
        if task:
            try:
                return self.mgr.tasks.index(task)
            except ValueError:
                pass
        return -1

    # ---------- 操作 ----------
    def add_task(self):
        dlg = TaskDialog(self)
        if dlg.exec():
            data = dlg.get_data()
            if data["name"] and data["path"]:
                self.mgr.tasks.append(data)
                self.mgr.save_tasks()
                self.refresh_all_tabs()

    def add_custom_task(self):
        dlg = CustomTaskDialog(self)
        if dlg.exec():
            data = dlg.get_data()
            if data["name"]:
                self.mgr.tasks.append(data)
                self.mgr.save_tasks()
                self.refresh_all_tabs()

    def edit_task(self):
        row = self._selected_index_in_mgr()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中一个任务。")
            return
        task = self.mgr.tasks[row]
        if task.get("is_custom"):
            dlg = CustomTaskDialog(self, task)
        else:
            dlg = TaskDialog(self, task)
        if dlg.exec():
            self.mgr.tasks[row] = dlg.get_data()
            self.mgr.save_tasks()
            self.refresh_all_tabs()

    def delete_task(self):
        row = self._selected_index_in_mgr()
        if row < 0:
            return
        task = self.mgr.tasks[row]
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定删除「{task['name']}」吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.mgr.tasks.pop(row)
            self.mgr.save_tasks()
            self.refresh_all_tabs()

    def open_selected_folder(self):
        task = self._selected_task()
        if task and not task.get("is_custom"):
            self.open_folder(task.get("path", ""))

    def open_folder(self, path):
        if path and os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.warning(self, "错误", f"文件夹路径不存在：\n{path}")

    def toggle_done(self):
        row = self._selected_index_in_mgr()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中一个任务。")
            return
        today_str = QDate.currentDate().toString("yyyy-MM-dd")
        current = self.mgr.tasks[row].get("last_done")
        self.mgr.tasks[row]["last_done"] = "" if current == today_str else today_str
        self.mgr.save_tasks()
        self.refresh_all_tabs()

    def toggle_alarm(self):
        task = self._selected_task()
        if task:
            task["alarm_enabled"] = not task.get("alarm_enabled", False)
            self.mgr.save_tasks()
            self.refresh_all_tabs()

    # ---------- 批量导入 ----------
    def batch_import(self):
        parent_dir = QFileDialog.getExistingDirectory(self, "选择包含办公文件夹的父目录")
        if not parent_dir:
            return

        try:
            entries = os.listdir(parent_dir)
        except OSError as e:
            QMessageBox.warning(self, "错误", f"无法读取目录：\n{e}")
            return

        subdirs = [d for d in entries if os.path.isdir(os.path.join(parent_dir, d))]
        if not subdirs:
            QMessageBox.information(self, "提示", "所选目录下没有子文件夹。")
            return

        imported = []
        skipped = []
        for d in sorted(subdirs):
            full_path = os.path.join(parent_dir, d)
            task_type = classify_folder_name(d)
            remind_day = extract_day_from_name(d)

            if any(t.get("path") == full_path for t in self.mgr.tasks):
                skipped.append(d)
                continue

            task = {
                "name": d,
                "path": full_path,
                "type": task_type,
                "remind_time": "09:00",
                "remind_day": remind_day,
                "interval": 60,
                "alarm_enabled": False,   # 默认关闭闹钟
                "last_done": "",
                "last_reminded": "",
                "is_custom": False,
            }
            self.mgr.tasks.append(task)
            imported.append(f"  📁 {d}  →  {task_type}"
                            + (f"（{remind_day}号）🔕" if task_type == "每月固定日任务" else " 🔕"))

        # 将父目录加入监控
        if parent_dir not in self.settings.data.get("watch_dirs", []):
            self.settings.data.setdefault("watch_dirs", []).append(parent_dir)
            self.settings.save()
            self.sync_timer.start(300000)

        self.mgr.save_tasks()
        self.refresh_all_tabs()

        msg = f"导入完成！\n\n✅ 成功导入 {len(imported)} 个文件夹（闹钟默认关闭 🔕）\n"
        if imported:
            msg += "\n".join(imported[:15])
            if len(imported) > 15:
                msg += f"\n  ... 还有 {len(imported) - 15} 个"
        if skipped:
            msg += f"\n\n⏭ 跳过 {len(skipped)} 个（已存在）"
        msg += "\n\n💡 右键任务可开启闹钟 | 程序每5分钟自动同步文件夹变化"
        QMessageBox.information(self, "批量导入结果", msg)

    def auto_sync_folders(self):
        """自动同步：扫描监控目录，新增文件夹自动加入，删除的文件夹自动移除"""
        watch_dirs = self.settings.data.get("watch_dirs", [])
        for parent_dir in watch_dirs:
            if not os.path.exists(parent_dir):
                continue
            try:
                entries = os.listdir(parent_dir)
            except OSError:
                continue

            current_subdirs = set()
            for d in entries:
                full_path = os.path.join(parent_dir, d)
                if os.path.isdir(full_path):
                    current_subdirs.add(full_path)

            # 现有路径
            existing_paths = {t["path"] for t in self.mgr.tasks if t.get("path") and not t.get("is_custom")}
            # 属于此父目录的路径
            managed_paths = {p for p in existing_paths if p.startswith(parent_dir + os.sep)}

            added = []
            removed = []
            for new_path in (current_subdirs - managed_paths):
                d = os.path.basename(new_path)
                task_type = classify_folder_name(d)
                remind_day = extract_day_from_name(d)
                task = {
                    "name": d, "path": new_path, "type": task_type,
                    "remind_time": "09:00", "remind_day": remind_day,
                    "interval": 60, "alarm_enabled": False,
                    "last_done": "", "last_reminded": "", "is_custom": False,
                }
                self.mgr.tasks.append(task)
                added.append(d)

            for old_path in (managed_paths - current_subdirs):
                d = os.path.basename(old_path)
                self.mgr.remove_by_path(old_path)
                removed.append(d)

            if added or removed:
                self.mgr.save_tasks()
                self.refresh_all_tabs()
                if added:
                    self.tray_icon.showMessage("文件夹同步", f"新增 {len(added)} 个文件夹（闹钟已关闭）", QSystemTrayIcon.Information, 3000)
                if removed:
                    self.tray_icon.showMessage("文件夹同步", f"移除 {len(removed)} 个已删除的文件夹", QSystemTrayIcon.Information, 3000)

    # ---------- 系统托盘 ----------
    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        icon = self.style().standardIcon(QStyle.SP_DirIcon)
        self.tray_icon.setIcon(icon)

        tray_menu = QMenu()
        show_action = QAction("显示主界面", self)
        show_action.triggered.connect(self.show_and_activate)
        quit_action = QAction("退出程序", self)
        quit_action.triggered.connect(self.app.quit)

        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def show_and_activate(self):
        self.show()
        self.activateWindow()
        self.raise_()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show_and_activate()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "办公助手",
            "程序已最小化到系统托盘，后台持续运行。",
            QSystemTrayIcon.Information,
            2000
        )

    # ---------- 提醒引擎 ----------
    def check_reminders(self):
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        current_time_str = now.strftime("%H:%M")
        current_day = now.day
        current_weekday = now.weekday()  # 0=周一

        for t in self.mgr.tasks:
            if t.get("last_done") == today_str:
                continue
            if not t.get("alarm_enabled", True):
                continue

            should_remind = False
            key = f"{today_str}_{current_time_str}"

            if t.get("is_custom"):
                should_remind = self._check_custom_reminder(t, now, today_str, current_time_str, current_day, current_weekday, key)
            elif t["type"] == "每日任务":
                if t["remind_time"] == current_time_str and t.get("last_reminded") != key:
                    should_remind = True
            elif t["type"] == "每周任务":
                if current_weekday == 0 and t["remind_time"] == current_time_str and t.get("last_reminded") != key:
                    should_remind = True
            elif t["type"] == "每月固定日任务":
                if current_day == t["remind_day"] and t["remind_time"] == current_time_str and t.get("last_reminded") != key:
                    should_remind = True
            elif t["type"] == "间隔时间提醒":
                last = t.get("last_interval_check")
                if not last:
                    t["last_interval_check"] = now.timestamp()
                elif (now.timestamp() - float(last)) >= (t["interval"] * 60):
                    should_remind = True
                    t["last_interval_check"] = now.timestamp()

            if should_remind:
                t["last_reminded"] = key
                self.mgr.save_tasks()
                self.trigger_alert(t)

    def _check_custom_reminder(self, t, now, today_str, current_time, current_day, current_weekday, key):
        freq = t.get("custom_freq", "仅一次")
        remind_time = t.get("remind_time", "09:00")
        if remind_time != current_time:
            return False
        if t.get("last_reminded") == key:
            return False

        if freq == "仅一次":
            custom_date = t.get("custom_date", "")
            return custom_date == today_str
        elif freq == "每天":
            return True
        elif freq == "每周":
            initial_date = t.get("custom_date", "")
            if initial_date:
                try:
                    init_dt = datetime.strptime(initial_date, "%Y-%m-%d")
                    return current_weekday == init_dt.weekday()
                except ValueError:
                    pass
            return current_weekday == 0  # 默认周一
        elif freq == "每月":
            initial_day = t.get("remind_day", 1)
            return current_day == initial_day
        elif freq == "每年":
            initial_date = t.get("custom_date", "")
            if initial_date:
                try:
                    init_dt = datetime.strptime(initial_date, "%Y-%m-%d")
                    return current_day == init_dt.day and now.month == init_dt.month
                except ValueError:
                    pass
            return False
        return False

    def trigger_alert(self, task):
        QApplication.beep()
        title = f"提醒: {task['name']}"
        if task.get("note"):
            msg = f"{task.get('note')}"
        elif task.get("is_custom"):
            msg = f"自定义提醒"
        else:
            msg = f"分类：{task['type']}"
        self.tray_icon.showMessage(title, msg, QSystemTrayIcon.Information, 15000)


# ==================== 入口 ====================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # ---- 单实例锁 ----
    server = QLocalServer()
    socket = QLocalSocket()
    socket.connectToServer(APP_KEY)
    if socket.waitForConnected(500):
        # 已有实例在运行，通知它显示窗口
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(500)
        socket.close()
        sys.exit(0)

    socket.close()
    server.listen(APP_KEY)

    window = MainWindow(app)
    window.show()

    # 监听其他进程的激活请求
    def handle_new_connection():
        conn = server.nextPendingConnection()
        if conn:
            conn.waitForReadyRead(500)
            data = bytes(conn.readAll())
            if b"show" in data:
                window.show_and_activate()
            conn.close()

    server.newConnection.connect(handle_new_connection)

    sys.exit(app.exec())
