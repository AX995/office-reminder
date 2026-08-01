import sys
import os
import json
import subprocess
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, QTime, QDate
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLabel, QFileDialog,
    QComboBox, QTimeEdit, QSpinBox, QSystemTrayIcon, QMenu, QMessageBox,
    QDialog, QFormLayout, QLineEdit, QCheckBox, QGroupBox, QStyle
)
from PySide6.QtGui import QIcon, QAction
import re

CONFIG_FILE = "config.json"

# ---------- 文件夹名自动分类 ----------
# 匹配规则：按关键词识别任务类型，优先级从高到低
CLASSIFY_RULES = [
    (r"(?:每周|周报|weekly|week)",    "每周任务"),
    (r"(?:每月|月度|月报|monthly|month)",  "每月固定日任务"),
    (r"(?:每天|每日|日报|daily|每\s*天|每\s*日)", "每日任务"),
    (r"(?:每|every)",                "每日任务"),   # 模糊"每"字兜底
]


def classify_folder_name(dirname: str) -> str:
    """根据文件夹名识别任务类型，默认返回每日任务"""
    for pattern, task_type in CLASSIFY_RULES:
        if re.search(pattern, dirname, re.IGNORECASE):
            return task_type
    return "每日任务"


def extract_day_from_name(dirname: str) -> int:
    """尝试从文件夹名中提取日期（支持中英文数字）；失败返回 1"""
    # 数字格式: 每月5号 / 5号 / 月5 / day5 / 5th
    m = re.search(r"(\d+)\s*(?:号|日|th|st|nd|rd)?", dirname, re.IGNORECASE)
    if m:
        day = int(m.group(1))
        return max(1, min(day, 31))
    # 中文数字简写
    cn = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10,
          "十一":11,"十二":12,"十三":13,"十四":14,"十五":15,"十六":16,"十七":17,
          "十八":18,"十九":19,"二十":20,"二十一":21,"二十二":22,"二十三":23,
          "二十四":24,"二十五":25,"二十六":26,"二十七":27,"二十八":28,
          "二十九":29,"三十":30,"三十一":31}
    for word, num in sorted(cn.items(), key=lambda x: -len(x[0])):
        if word in dirname:
            return num
    return 1


class TaskManager:
    """数据管理类，负责配置的读取与保存"""
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

class TaskDialog(QDialog):
    """添加/编辑任务对话框"""
    def __init__(self, parent=None, task_data=None):
        super().__init__(parent)
        self.setWindowTitle("设置文件夹任务")
        self.resize(400, 300)
        self.task_data = task_data or {}
        self.init_ui()

    def init_ui(self):
        layout = QFormLayout(self)

        # 1. 任务名称
        self.name_input = QLineEdit()
        self.name_input.setText(self.task_data.get("name", ""))
        layout.addRow("任务名称:", self.name_input)

        # 2. 路径选择
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setText(self.task_data.get("path", ""))
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_path)
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(browse_btn)
        layout.addRow("文件夹路径/快捷方式:", path_layout)

        # 3. 分类标签
        self.type_combo = QComboBox()
        self.type_combo.addItems(["每日任务", "每周任务", "每月固定日任务", "间隔时间提醒"])
        current_type = self.task_data.get("type", "每日任务")
        self.type_combo.setCurrentText(current_type)
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        layout.addRow("任务类型:", self.type_combo)

        # 4. 提醒时间设置
        self.time_edit = QTimeEdit()
        time_str = self.task_data.get("remind_time", "09:00")
        self.time_edit.setTime(QTime.fromString(time_str, "HH:mm"))
        
        self.day_spin = QSpinBox()
        self.day_spin.setRange(1, 31)
        self.day_spin.setValue(self.task_data.get("remind_day", 1))

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440) # 最长24小时
        self.interval_spin.setSuffix(" 分钟")
        self.interval_spin.setValue(self.task_data.get("interval", 60))

        self.time_widget = QWidget()
        time_layout = QHBoxLayout(self.time_widget)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.addWidget(QLabel("时间:"))
        time_layout.addWidget(self.time_edit)
        
        self.day_widget = QWidget()
        day_layout = QHBoxLayout(self.day_widget)
        day_layout.setContentsMargins(0, 0, 0, 0)
        day_layout.addWidget(QLabel("每月:"))
        day_layout.addWidget(self.day_spin)
        day_layout.addWidget(QLabel("号"))

        self.interval_widget = QWidget()
        interval_layout = QHBoxLayout(self.interval_widget)
        interval_layout.setContentsMargins(0, 0, 0, 0)
        interval_layout.addWidget(QLabel("每隔:"))
        interval_layout.addWidget(self.interval_spin)

        layout.addRow("固定日期:", self.day_widget)
        layout.addRow("每日时间:", self.time_widget)
        layout.addRow("间隔设置:", self.interval_widget)

        self.on_type_changed(self.type_combo.currentText())

        # 5. 确定取消按钮
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
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
            self.day_widget.hide()
            self.time_widget.show()
            self.interval_widget.hide()
        elif text == "每月固定日任务":
            self.day_widget.show()
            self.time_widget.show()
            self.interval_widget.hide()
        elif text == "间隔时间提醒":
            self.day_widget.hide()
            self.time_widget.hide()
            self.interval_widget.show()

    def get_data(self):
        return {
            "name": self.name_input.text().strip(),
            "path": self.path_input.text().strip(),
            "type": self.type_combo.currentText(),
            "remind_time": self.time_edit.time().toString("HH:mm"),
            "remind_day": self.day_spin.value(),
            "interval": self.interval_spin.value(),
            "last_done": self.task_data.get("last_done", ""),
            "last_reminded": self.task_data.get("last_reminded", "")
        }

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.mgr = TaskManager()
        self.setWindowTitle("办公文件夹统一管理助手")
        self.resize(700, 450)

        self.init_ui()
        self.init_tray()
        self.load_list()

        # 定时器：每30秒检测一次提醒
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_reminders)
        self.timer.start(30000)

    def init_ui(self):
        main_widget = QWidget()
        layout = QHBoxLayout(main_widget)

        # 左侧：任务列表
        self.task_list = QListWidget()
        layout.addWidget(self.task_list, stretch=3)

        # 右侧：操作面板
        btn_layout = QVBoxLayout()
        
        add_btn = QPushButton("添加新文件夹")
        add_btn.clicked.connect(self.add_task)
        
        import_btn = QPushButton("批量导入文件夹")
        import_btn.setStyleSheet("QPushButton { font-weight: bold; color: #1565C0; }")
        import_btn.clicked.connect(self.batch_import)

        edit_btn = QPushButton("修改设置")
        edit_btn.clicked.connect(self.edit_task)

        open_btn = QPushButton("打开选中文件夹")
        open_btn.clicked.connect(self.open_selected_folder)

        done_btn = QPushButton("打卡/标记完成")
        done_btn.clicked.connect(self.toggle_done)

        del_btn = QPushButton("删除任务")
        del_btn.clicked.connect(self.delete_task)

        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(import_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(open_btn)
        btn_layout.addWidget(done_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addStretch()

        layout.addLayout(btn_layout, stretch=1)
        self.setCentralWidget(main_widget)

    def init_tray(self):
        """初始化系统托盘图标"""
        self.tray_icon = QSystemTrayIcon(self)
        # 使用系统自带文件夹图标作为托盘图标
        icon = self.style().standardIcon(QStyle.SP_DirIcon)
        self.tray_icon.setIcon(icon)

        tray_menu = QMenu()
        show_action = QAction("显示主界面", self)
        show_action.triggered.connect(self.show)
        quit_action = QAction("退出程序", self)
        quit_action.triggered.connect(QApplication.instance().quit)

        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger: # 双击或单击托盘图标
            if self.isVisible():
                self.hide()
            else:
                self.show()
                self.activateWindow()

    def closeEvent(self, event):
        """关闭窗口时最小化到托盘而非直接退出"""
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "办公助手",
            "程序已最小化到系统托盘，将在后台持续为你管理提醒。",
            QSystemTrayIcon.Information,
            2000
        )

    def load_list(self):
        self.task_list.clear()
        today_str = QDate.currentDate().toString("yyyy-MM-dd")

        for idx, t in enumerate(self.mgr.tasks):
            is_done = (t.get("last_done") == today_str)
            status_tag = "[已完成]" if is_done else "[待处理]"
            
            # 显示文本结构
            display_text = f"{status_tag} {t['name']} | 类型: {t['type']} | 路径: {t['path']}"
            item = QListWidgetItem(display_text)
            
            # 高亮处理
            if is_done:
                item.setForeground(Qt.gray)
            elif not os.path.exists(t['path']):
                item.setText(f"[路径失效] {t['name']} - {t['path']}")
                item.setForeground(Qt.red)

            self.task_list.addItem(item)

    def add_task(self):
        dlg = TaskDialog(self)
        if dlg.exec():
            data = dlg.get_data()
            if data["name"] and data["path"]:
                self.mgr.tasks.append(data)
                self.mgr.save_tasks()
                self.load_list()

    def edit_task(self):
        row = self.task_list.currentRow()
        if row < 0:
            return
        dlg = TaskDialog(self, self.mgr.tasks[row])
        if dlg.exec():
            self.mgr.tasks[row] = dlg.get_data()
            self.mgr.save_tasks()
            self.load_list()

    def delete_task(self):
        row = self.task_list.currentRow()
        if row >= 0:
            self.mgr.tasks.pop(row)
            self.mgr.save_tasks()
            self.load_list()

    def open_selected_folder(self):
        row = self.task_list.currentRow()
        if row >= 0:
            path = self.mgr.tasks[row]["path"]
            self.open_folder(path)

    def open_folder(self, path):
        if os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.warning(self, "错误", f"文件夹路径不存在：\n{path}")

    def toggle_done(self):
        row = self.task_list.currentRow()
        if row >= 0:
            today_str = QDate.currentDate().toString("yyyy-MM-dd")
            current = self.mgr.tasks[row].get("last_done")
            if current == today_str:
                self.mgr.tasks[row]["last_done"] = ""
            else:
                self.mgr.tasks[row]["last_done"] = today_str
            self.mgr.save_tasks()
            self.load_list()

    def check_reminders(self):
        """核心定时提醒算法"""
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        current_time_str = now.strftime("%H:%M")
        current_day = now.day

        for t in self.mgr.tasks:
            # 如果今天已经打卡完成，则跳过提醒
            if t.get("last_done") == today_str:
                continue

            should_remind = False
            
            # 1. 每日任务判定
            if t["type"] == "每日任务":
                if t["remind_time"] == current_time_str and t.get("last_reminded") != f"{today_str}_{current_time_str}":
                    should_remind = True

            # 2. 每周任务判定（只在周一提醒）
            elif t["type"] == "每周任务":
                if now.weekday() == 0 and t["remind_time"] == current_time_str:
                    if t.get("last_reminded") != f"{today_str}_{current_time_str}":
                        should_remind = True

            # 3. 每月固定日判定
            elif t["type"] == "每月固定日任务":
                if current_day == t["remind_day"] and t["remind_time"] == current_time_str:
                    if t.get("last_reminded") != f"{today_str}_{current_time_str}":
                        should_remind = True

            # 4. 间隔提醒判定
            elif t["type"] == "间隔时间提醒":
                last_time_str = t.get("last_interval_check")
                if not last_time_str:
                    t["last_interval_check"] = now.timestamp()
                else:
                    if (now.timestamp() - float(last_time_str)) >= (t["interval"] * 60):
                        should_remind = True
                        t["last_interval_check"] = now.timestamp()

            if should_remind:
                t["last_reminded"] = f"{today_str}_{current_time_str}"
                self.mgr.save_tasks()
                self.trigger_alert(t)

    def batch_import(self):
        """批量导入：选择一个父目录，扫描子文件夹并按命名自动分类"""
        parent_dir = QFileDialog.getExistingDirectory(self, "选择包含办公文件夹的父目录")
        if not parent_dir:
            return

        try:
            entries = os.listdir(parent_dir)
        except OSError as e:
            QMessageBox.warning(self, "错误", f"无法读取目录：\n{e}")
            return

        # 只取子文件夹
        subdirs = [
            d for d in entries
            if os.path.isdir(os.path.join(parent_dir, d))
        ]
        if not subdirs:
            QMessageBox.information(self, "提示", "所选目录下没有子文件夹。")
            return

        # 扫描 → 自动分类
        imported = []
        skipped = []
        for d in sorted(subdirs):
            full_path = os.path.join(parent_dir, d)
            task_type = classify_folder_name(d)
            remind_day = extract_day_from_name(d)

            # 检查是否已存在相同路径的任务
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
                "last_done": "",
                "last_reminded": "",
            }
            self.mgr.tasks.append(task)
            imported.append(f"  📁 {d}  →  {task_type}（每月{remind_day}号）"
                            if task_type == "每月固定日任务"
                            else f"  📁 {d}  →  {task_type}")

        self.mgr.save_tasks()
        self.load_list()

        # 结果弹窗
        msg = f"导入完成！\n\n✅ 成功导入 {len(imported)} 个文件夹：\n"
        msg += "\n".join(imported[:20])  # 最多展示前20条
        if len(imported) > 20:
            msg += f"\n  ... 还有 {len(imported) - 20} 个"
        if skipped:
            msg += f"\n\n⏭ 跳过 {len(skipped)} 个（已存在）：{', '.join(skipped[:10])}"
            if len(skipped) > 10:
                msg += f" ... 等"

        QMessageBox.information(self, "批量导入结果", msg)

    def trigger_alert(self, task):
        """右下角弹窗提醒 + 蜂鸣声音"""
        # 播放系统标准提示音
        QApplication.beep()
        
        # 右下角气泡弹窗
        self.tray_icon.showMessage(
            f"工作提醒: {task['name']}",
            f"任务内容/分类：{task['type']}\n点击查看或直接打开该文件夹。",
            QSystemTrayIcon.Information,
            10000 # 悬停 10 秒
        )

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # 退出时避免隐藏主界面而导致无法退出
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
