import sys,os,json,re
from datetime import datetime
from PySide6.QtCore import Qt,QTimer,QTime,QDate
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,
    QListWidget,QListWidgetItem,QPushButton,QLabel,QFileDialog,QComboBox,QTimeEdit,
    QSpinBox,QSystemTrayIcon,QMenu,QMessageBox,QDialog,QFormLayout,QLineEdit,
    QTabWidget,QStyle,QCheckBox,QDateEdit,QTextEdit,QGroupBox,QInputDialog,QTabBar,QFrame)
from PySide6.QtGui import QIcon,QAction,QPainter,QPixmap,QColor,QBrush,QFont
from PySide6.QtNetwork import QLocalServer,QLocalSocket

DATA_DIR=os.path.join(os.environ.get("APPDATA",os.path.expanduser("~")),"OfficeReminder")
os.makedirs(DATA_DIR,exist_ok=True)
CFG=os.path.join(DATA_DIR,"tasks.json")
SET=os.path.join(DATA_DIR,"settings.json")
AK="OR_v6"

BUILTIN_TABS=["每日","每周","每月","间隔"]
BUILTIN_RULES={"每日":[r"每天",r"每日",r"日报",r"daily",r"每\s*天",r"每\s*日",r"每(?![周月])",r"every"],
    "每周":[r"每周",r"周报",r"weekly",r"week"],"每月":[r"每月",r"月度",r"月报",r"monthly",r"month"],"间隔":[]}

def extract_day(dn):
    m=re.search(r"(\d+)\s*(?:号|日|th|st|nd|rd)?",dn,re.IGNORECASE)
    if m: return max(1,min(31,int(m.group(1))))
    cn={"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10,"十一":11,"十二":12,"十三":13,"十四":14,"十五":15,"十六":16,"十七":17,"十八":18,"十九":19,"二十":20,"二十一":21,"二十二":22,"二十三":23,"二十四":24,"二十五":25,"二十六":26,"二十七":27,"二十八":28,"二十九":29,"三十":30,"三十一":31}
    for w,n in sorted(cn.items(),key=lambda x:-len(x[0])):
        if w in dn: return n
    return 1

class Settings:
    def __init__(s): s.data={"watch_dirs":[],"custom_tabs":{},"tab_order":[]}; s.load()
    def load(s):
        if os.path.exists(SET):
            try:
                with open(SET,"r",encoding="utf-8") as f: s.data=json.load(f)
            except: pass
    def save(s):
        with open(SET,"w",encoding="utf-8") as f: json.dump(s.data,f,ensure_ascii=False,indent=2)
    def all_rules(s):
        r={}
        for l in s.data.get("tab_order",[]):
            if l in s.data.get("custom_tabs",{}): r[l]=[re.escape(k) for k in s.data["custom_tabs"][l]]
            elif l in BUILTIN_RULES: r[l]=BUILTIN_RULES[l]
        for l,p in BUILTIN_RULES.items():
            if l not in r: r[l]=p
        for l,k in s.data.get("custom_tabs",{}).items():
            if l not in r: r[l]=[re.escape(x) for x in k]
        return r
    def tab_order(s):
        o=s.data.get("tab_order",[])
        all_t=set(BUILTIN_TABS)|set(s.data.get("custom_tabs",{}).keys())
        for t in all_t:
            if t not in o: o.append(t)
        return o

def classify(name,rules):
    for l,p in rules.items():
        for pat in p:
            if re.search(pat,name,re.IGNORECASE): return l
    return "每日"

class TaskMgr:
    def __init__(s): s.tasks=[]; s.load()
    def load(s):
        if os.path.exists(CFG):
            try:
                with open(CFG,"r",encoding="utf-8") as f: s.tasks=json.load(f)
            except: s.tasks=[]
        else: s.tasks=[]
    def save(s):
        with open(CFG,"w",encoding="utf-8") as f: json.dump(s.tasks,f,ensure_ascii=False,indent=2)
    def rm_by_path(s,p): s.tasks=[t for t in s.tasks if t.get("path")!=p]

class DraggableTabBar(QTabBar):
    def __init__(s,p=None): super().__init__(p); s.setMovable(True)

class TaskDialog(QDialog):
    def __init__(s,p=None,d=None,labels=None,tt=None):
        super().__init__(p); s.setWindowTitle("设置任务"); s.resize(460,420)
        s.d=d or {}; s.labels=labels or BUILTIN_TABS; s.tt=tt or s.d.get("type","每日"); s.ui()
    def ui(s):
        lo=QFormLayout(s); lo.setSpacing(10)
        s.ni=QLineEdit(s.d.get("name","")); lo.addRow("名称:",s.ni)
        pl=QHBoxLayout(); s.pi=QLineEdit(s.d.get("path","")); b=QPushButton("浏览"); b.clicked.connect(s.br); pl.addWidget(s.pi); pl.addWidget(b); lo.addRow("路径:",pl)
        s.tc=QComboBox(); s.tc.addItems(s.labels); s.tc.setCurrentText(s.tt if s.tt in s.labels else "每日"); s.tc.currentTextChanged.connect(s.ot); lo.addRow("归类:",s.tc)
        s.ac=QCheckBox("启用闹钟"); s.ac.setChecked(s.d.get("alarm_enabled",False)); lo.addRow("",s.ac)
        dl=QHBoxLayout(); dl.addWidget(QLabel("日期:"));
        s.de=QDateEdit(); s.de.setCalendarPopup(True); s.de.setDisplayFormat("yyyy-MM-dd")
        ds=s.d.get("remind_date","") or QDate.currentDate().toString("yyyy-MM-dd"); s.de.setDate(QDate.fromString(ds,"yyyy-MM-dd"))
        s.dx=QCheckBox("指定日期(仅一次)"); s.dx.setChecked(s.d.get("use_specific_date",False)); s.dx.toggled.connect(lambda v:s.de.setEnabled(v)); s.de.setEnabled(s.dx.isChecked())
        dl.addWidget(s.de); dl.addWidget(s.dx)
        s.te=QTimeEdit(); s.te.setTime(QTime.fromString(s.d.get("remind_time","09:00"),"HH:mm"))
        s.ds=QSpinBox(); s.ds.setRange(1,31); s.ds.setValue(s.d.get("remind_day",1))
        s.iv=QSpinBox(); s.iv.setRange(5,1440); s.iv.setSuffix(" 分钟"); s.iv.setValue(s.d.get("interval",30))
        s.tw=QWidget(); tl=QHBoxLayout(s.tw); tl.setContentsMargins(0,0,0,0); tl.addWidget(QLabel("时间:")); tl.addWidget(s.te)
        s.dw=QWidget(); dwl=QHBoxLayout(s.dw); dwl.setContentsMargins(0,0,0,0); dwl.addWidget(QLabel("每月:")); dwl.addWidget(s.ds); dwl.addWidget(QLabel("号"))
        s.iw=QWidget(); iwl=QHBoxLayout(s.iw); iwl.setContentsMargins(0,0,0,0); iwl.addWidget(QLabel("间隔:")); iwl.addWidget(s.iv)
        lo.addRow("",dl); lo.addRow("",s.tw); lo.addRow("",s.dw); lo.addRow("",s.iw)
        s.ot(s.tc.currentText())
        bl=QHBoxLayout(); bl.addStretch(); sb=QPushButton("保存"); sb.clicked.connect(s.accept); cb=QPushButton("取消"); cb.clicked.connect(s.reject); bl.addWidget(sb); bl.addWidget(cb); lo.addRow(bl)
    def br(s):
        p=QFileDialog.getExistingDirectory(s,"选择文件夹")
        if p: s.pi.setText(p)
        if not s.ni.text(): s.ni.setText(os.path.basename(p))
    def ot(s,t):
        if t=="间隔": s.tw.hide(); s.dw.hide(); s.iw.show()
        elif t=="每月": s.tw.show(); s.dw.show(); s.iw.hide()
        else: s.tw.show(); s.dw.hide(); s.iw.hide()
    def get(s):
        return {"name":s.ni.text().strip(),"path":s.pi.text().strip(),"type":s.tc.currentText(),
            "remind_time":s.te.time().toString("HH:mm"),"remind_day":s.ds.value(),"interval":s.iv.value(),
            "alarm_enabled":s.ac.isChecked(),"last_done":s.d.get("last_done",""),"last_reminded":s.d.get("last_reminded",""),
            "is_custom":False,"use_specific_date":s.dx.isChecked(),
            "remind_date":s.de.date().toString("yyyy-MM-dd") if s.dx.isChecked() else ""}

class CustomDialog(QDialog):
    def __init__(s,p=None,d=None):
        super().__init__(p); s.setWindowTitle("自定义提醒"); s.resize(420,400); s.d=d or {}; s.ui()
    def ui(s):
        lo=QFormLayout(s); lo.setSpacing(10)
        s.ni=QLineEdit(s.d.get("name","")); s.ni.setPlaceholderText("内容..."); lo.addRow("内容:",s.ni)
        g=QGroupBox("频率"); gl=QVBoxLayout(g)
        s.fc=QComboBox(); s.fc.addItems(["仅一次","每天","每周","每月","每年","间隔"]); s.fc.setCurrentText(s.d.get("custom_freq","仅一次")); s.fc.currentTextChanged.connect(s.of); gl.addWidget(s.fc)
        s.dr=QHBoxLayout(); s.dr.addWidget(QLabel("日期:")); s.de=QDateEdit(); s.de.setCalendarPopup(True); s.de.setDisplayFormat("yyyy-MM-dd"); s.de.setDate(QDate.fromString(s.d.get("custom_date",QDate.currentDate().toString("yyyy-MM-dd")),"yyyy-MM-dd")); s.dr.addWidget(s.de)
        tr=QHBoxLayout(); tr.addWidget(QLabel("时间:")); s.te=QTimeEdit(); s.te.setTime(QTime.fromString(s.d.get("remind_time","09:00"),"HH:mm")); tr.addWidget(s.te)
        s.ir=QHBoxLayout(); s.ir.addWidget(QLabel("间隔:")); s.ie=QSpinBox(); s.ie.setRange(5,1440); s.ie.setSuffix(" 分钟"); s.ie.setValue(s.d.get("interval",30)); s.ir.addWidget(s.ie)
        gl.addLayout(s.dr); gl.addLayout(tr); gl.addLayout(s.ir); lo.addRow(g)
        s.nt=QTextEdit(); s.nt.setMaximumHeight(60); s.nt.setPlaceholderText("备注..."); s.nt.setText(s.d.get("note","")); lo.addRow("备注:",s.nt)
        s.of(s.fc.currentText())
        bl=QHBoxLayout(); bl.addStretch(); sb=QPushButton("保存"); sb.clicked.connect(s.accept); cb=QPushButton("取消"); cb.clicked.connect(s.reject); bl.addWidget(sb); bl.addWidget(cb); lo.addRow(bl)
    def of(s,t):
        o=(t=="仅一次"); iv=(t=="间隔")
        for i in range(s.dr.count()):
            w=s.dr.itemAt(i).widget()
            if w: w.setVisible(o)
        s.de.setVisible(o); s.te.setVisible(not iv)
        for i in range(s.ir.count()):
            w=s.ir.itemAt(i).widget()
            if w: w.setVisible(iv)
        s.ie.setVisible(iv)
    def get(s):
        f=s.fc.currentText()
        return {"name":s.ni.text().strip(),"path":"","type":"自定义","remind_time":s.te.time().toString("HH:mm"),
            "remind_day":1,"interval":s.ie.value(),"alarm_enabled":True,"last_done":"","last_reminded":"",
            "is_custom":True,"custom_freq":f,
            "custom_date":s.de.date().toString("yyyy-MM-dd") if f=="仅一次" else "","note":s.nt.toPlainText().strip()}

class MainWindow(QMainWindow):
    def __init__(s,app):
        super().__init__()
        s.app=app; s.mgr=TaskMgr(); s.settings=Settings()
        s.setWindowTitle("办公助手"); s.resize(960,620)
        s._cur="全部"; s._lrd=""
        s.ui(); s.tray(); s.refresh()
        s.rt=QTimer(s); s.rt.timeout.connect(s.check_r); s.rt.start(30000)
        s.ct=QTimer(s); s.ct.timeout.connect(s._update_clock); s.ct.start(1000)
        s.st=QTimer(s); s.st.timeout.connect(s.sync)
        if s.settings.data.get("watch_dirs"): s.st.start(300000)

    def ui(s):
        c=QWidget(); ml=QVBoxLayout(c); ml.setContentsMargins(4,4,4,4); ml.setSpacing(4)
        s.tw=QTabWidget(); s.tw.setDocumentMode(True)
        s.tb=DraggableTabBar(); s.tw.setTabBar(s.tb)
        s.tb.tabMoved.connect(s._tm)
        s.lists={}; s.torder=[]
        s._rebuild()
        s.tw.currentChanged.connect(s._tc)
        ml.addWidget(s.tw)

        bot=QHBoxLayout(); bot.setSpacing(4)
        bts=[("+ 添加",s.add,"#333"),("📂 批量导入",s.batch,"#1565C0"),("🕐 自定义",s.custom,"#6A1B9A"),
             ("✏️ 修改",s.edit,"#333"),("📁 打开",s.open_sel,"#333"),("🗑 删除",s.delete,"#C62828"),
             ("🏷 标签管理",s.mtab,"#E65100")]
        for txt,cb,cl in bts:
            btn=QPushButton(txt); btn.clicked.connect(cb); btn.setMinimumHeight(32)
            if cl!="#333": btn.setStyleSheet(f"QPushButton{{font-weight:bold;color:{cl};}}")
            bot.addWidget(btn)
        bot.addStretch()

        s.cf=QFrame(); s.cf.setFrameShape(QFrame.StyledPanel)
        s.cf.setStyleSheet("QFrame{background:#1565C0;border-radius:8px;padding:4px 12px;}")
        clk=QVBoxLayout(s.cf); clk.setContentsMargins(14,6,14,6); clk.setSpacing(0)
        s.dlbl=QLabel(); s.dlbl.setStyleSheet("color:white;font-size:13px;")
        s.tlbl=QLabel(); s.tlbl.setStyleSheet("color:white;font-size:20px;font-weight:bold;")
        s.dlbl.setAlignment(Qt.AlignCenter); s.tlbl.setAlignment(Qt.AlignCenter)
        clk.addWidget(s.dlbl); clk.addWidget(s.tlbl)
        bot.addWidget(s.cf)
        s._update_clock()
        ml.addLayout(bot); s.setCentralWidget(c)

    def _update_clock(s):
        now=datetime.now()
        wd=["周一","周二","周三","周四","周五","周六","周日"]
        s.dlbl.setText(now.strftime("%Y年%m月%d日 ")+wd[now.weekday()])
        s.tlbl.setText(now.strftime("%H:%M:%S"))

    def _rebuild(s):
        s.tw.blockSignals(True)
        while s.tw.count()>0: s.tw.removeTab(0)
        s.lists.clear()
        s.torder=["全部"]+s.settings.tab_order()+["自定义"]
        seen=set()
        dedup=[]
        for lb in s.torder:
            if lb not in seen:
                seen.add(lb); dedup.append(lb)
        s.torder=dedup
        for lb in s.torder:
            lst=QListWidget(); lst.setAlternatingRowColors(True)
            lst.setFont(QFont("Microsoft YaHei",11))
            lst.setStyleSheet("QListWidget::item{padding:4px 8px;}")
            lst.setContextMenuPolicy(Qt.CustomContextMenu)
            lst.customContextMenuRequested.connect(s._ctx)
            lst.itemDoubleClicked.connect(s._dbl)
            lst.itemClicked.connect(s._hit)
            s.tw.addTab(lst,f"  {lb}  "); s.lists[lb]=lst
        s.tw.blockSignals(False)

    def _tm(s,frm,to):
        lo=[]
        for i in range(s.tw.count()):
            t=s.tw.tabText(i).strip()
            if t not in ("全部","自定义"): lo.append(t)
        s.settings.data["tab_order"]=lo; s.settings.save()
        s.torder=["全部"]+lo+["自定义"]
        s._cur=s.torder[s.tw.currentIndex()]

    def _tt(s,tn):
        if tn in BUILTIN_TABS: return tn
        if tn=="自定义": return "自定义"
        return tn

    def _cl(s): return s.lists.get(s._cur,s.lists.get("全部"))

    def _flt(s,tn):
        if tn=="全部": return list(s.mgr.tasks)
        if tn=="自定义": return [t for t in s.mgr.tasks if t.get("is_custom")]
        tg=s._tt(tn)
        return [t for t in s.mgr.tasks if t.get("type")==tg and not t.get("is_custom")]

    def _sk(s,t):
        today=QDate.currentDate().toString("yyyy-MM-dd")
        d=1 if t.get("last_done")==today else 0
        return (d,t.get("remind_day",0),t.get("name",""))

    def refresh(s):
        today=QDate.currentDate().toString("yyyy-MM-dd")
        if s._cur not in s.lists: s._cur="全部"
        for tn,lst in s.lists.items():
            idx=s.torder.index(tn) if tn in s.torder else 0
            sb=lst.verticalScrollBar().value()
            lst.clear()
            tasks=sorted(s._flt(tn),key=s._sk)
            for t in tasks:
                done=(t.get("last_done")==today)
                pok=t.get("is_custom") or os.path.exists(t.get("path",""))
                al=t.get("alarm_enabled",True)
                chk="☑" if done else "☐"
                bel="🔔" if al else "🔕"
                txt=f"{chk}  {t['name']}     {bel}"
                item=QListWidgetItem(txt)
                item.setData(Qt.UserRole,t)
                if done:
                    item.setForeground(QColor(150,150,150))
                elif not pok:
                    item.setForeground(QColor(200,50,50))
                    item.setText(f"☐  {t['name']} ❌失效")
                else:
                    item.setForeground(QColor(0,0,0))
                item.setToolTip(f"路径:{t.get('path','(自定义)')}\n类型:{t.get('type','')}")
                lst.addItem(item)
            cnt=len(tasks)
            s.tw.setTabText(idx,f"  {tn}（{cnt}）" if cnt else f"  {tn}  ")
            lst.verticalScrollBar().setValue(min(sb,lst.verticalScrollBar().maximum()))
        if s._cur in s.lists:
            idx=s.torder.index(s._cur) if s._cur in s.torder else 0
            s.tw.setCurrentIndex(idx)

    def _tc(s,idx):
        if idx<len(s.torder): s._cur=s.torder[idx]

    def _hit(s,item):
        t=item.data(Qt.UserRole)
        if not t: return
        today=QDate.currentDate().toString("yyyy-MM-dd")
        cur=t.get("last_done")
        t["last_done"]="" if cur==today else today
        s.mgr.save()
        done=(t.get("last_done")==today)
        al=t.get("alarm_enabled",True); pok=t.get("is_custom") or os.path.exists(t.get("path",""))
        chk="☑" if done else "☐"; bel="🔔" if al else "🔕"
        item.setText(f"{chk}  {t['name']}     {bel}")
        if done: item.setForeground(QColor(150,150,150))
        elif not pok: item.setForeground(QColor(200,50,50))
        else: item.setForeground(QColor(0,0,0))

    def _ctx(s,pos):
        lst=s._cl(); item=lst.itemAt(pos)
        if not item: return
        lst.setCurrentItem(item)
        t=item.data(Qt.UserRole)
        if not t: return
        menu=QMenu(s)
        if not t.get("is_custom"): menu.addAction("📁 打开文件夹",s.open_sel)
        menu.addAction("✅ 打卡/取消",s.toggle_done)
        menu.addAction("🔔 切换闹钟",s.toggle_alarm)
        menu.addAction("✏️ 修改",s.edit)
        menu.addSeparator()
        menu.addAction("🗑 删除",s.delete)
        menu.exec(lst.viewport().mapToGlobal(pos))

    def _dbl(s,item):
        t=item.data(Qt.UserRole)
        if t and not t.get("is_custom"): s.open_folder(t.get("path",""))

    def _sel(s):
        item=s._cl().currentItem()
        return item.data(Qt.UserRole) if item else None

    def _idx(s):
        t=s._sel()
        if t:
            try: return s.mgr.tasks.index(t)
            except: pass
        return -1

    def add(s):
        dlg=TaskDialog(s,labels=s.settings.tab_order())
        if dlg.exec():
            d=dlg.get()
            if d["name"] and d["path"]: s.mgr.tasks.append(d); s.mgr.save(); s.refresh()

    def custom(s):
        dlg=CustomDialog(s)
        if dlg.exec():
            d=dlg.get()
            if d["name"]: s.mgr.tasks.append(d); s.mgr.save(); s.refresh()

    def edit(s):
        idx=s._idx()
        if idx<0: QMessageBox.information(s,"提示","请先选中"); return
        t=s.mgr.tasks[idx]
        if t.get("is_custom"): dlg=CustomDialog(s,t)
        else: dlg=TaskDialog(s,t,s.settings.tab_order(),t.get("type","每日"))
        if dlg.exec(): s.mgr.tasks[idx]=dlg.get(); s.mgr.save(); s.refresh()

    def delete(s):
        idx=s._idx()
        if idx<0: return
        t=s.mgr.tasks[idx]
        if QMessageBox.Yes==QMessageBox.question(s,"确认",f"删除「{t['name']}」？"):
            s.mgr.tasks.pop(idx); s.mgr.save(); s.refresh()

    def open_sel(s):
        t=s._sel()
        if t and not t.get("is_custom"): s.open_folder(t.get("path",""))

    def open_folder(s,p):
        if p and os.path.exists(p): os.startfile(p)
        else: QMessageBox.warning(s,"错误",f"路径不存在:\n{p}")

    def toggle_done(s):
        idx=s._idx()
        if idx<0: return
        today=QDate.currentDate().toString("yyyy-MM-dd")
        cur=s.mgr.tasks[idx].get("last_done")
        s.mgr.tasks[idx]["last_done"]="" if cur==today else today
        s.mgr.save(); s.refresh()

    def toggle_alarm(s):
        t=s._sel()
        if t: t["alarm_enabled"]=not t.get("alarm_enabled",False); s.mgr.save(); s.refresh()

    def batch(s):
        parent=QFileDialog.getExistingDirectory(s,"选择父目录")
        if not parent: return
        try: ents=os.listdir(parent)
        except OSError as e: QMessageBox.warning(s,"错误",str(e)); return
        subs=[d for d in ents if os.path.isdir(os.path.join(parent,d))]
        if not subs: QMessageBox.information(s,"提示","无子文件夹"); return
        rules=s.settings.all_rules()
        imp,skp=[],[]
        for d in sorted(subs):
            fp=os.path.join(parent,d)
            if any(t.get("path")==fp for t in s.mgr.tasks): skp.append(d); continue
            lb=classify(d,rules); dy=extract_day(d)
            t={"name":d,"path":fp,"type":lb,"remind_time":"09:00","remind_day":dy,"interval":30,
               "alarm_enabled":False,"last_done":"","last_reminded":"","is_custom":False,
               "use_specific_date":False,"remind_date":""}
            s.mgr.tasks.append(t); imp.append(f"{d} -> {lb}")
        if parent not in s.settings.data.get("watch_dirs",[]):
            s.settings.data.setdefault("watch_dirs",[]).append(parent); s.settings.save(); s.st.start(300000)
        s.mgr.save(); s.refresh()
        QMessageBox.information(s,"导入",f"✅ {len(imp)} 个(默认🔕)\n⏭ 跳过 {len(skp)} 个")

    def sync(s):
        for parent in s.settings.data.get("watch_dirs",[]):
            if not os.path.exists(parent): continue
            try: ents=os.listdir(parent)
            except: continue
            cur={os.path.join(parent,d) for d in ents if os.path.isdir(os.path.join(parent,d))}
            ex={t["path"] for t in s.mgr.tasks if t.get("path") and not t.get("is_custom")}
            mg={p for p in ex if p.startswith(parent+os.sep)}
            rules=s.settings.all_rules()
            ad,rm=[],[]
            for np in (cur-mg):
                dn=os.path.basename(np); lb=classify(dn,rules); dy=extract_day(dn)
                t={"name":dn,"path":np,"type":lb,"remind_time":"09:00","remind_day":dy,"interval":30,
                   "alarm_enabled":False,"last_done":"","last_reminded":"","is_custom":False,
                   "use_specific_date":False,"remind_date":""}
                s.mgr.tasks.append(t); ad.append(dn)
            for op in (mg-cur):
                s.mgr.rm_by_path(op); rm.append(os.path.basename(op))
            if ad or rm: s.mgr.save(); s.refresh()
            if ad: s.tray.showMessage("同步",f"+{len(ad)} 个文件夹",QSystemTrayIcon.Information,3000)
            if rm: s.tray.showMessage("同步",f"-{len(rm)} 个文件夹",QSystemTrayIcon.Information,3000)

    def mtab(s):
        dlg=ManageTabs(s,s.settings)
        if dlg.exec(): s.settings.save(); s._rebuild(); s._cur="全部"; s.refresh()

    def tray(s):
        s.tray=QSystemTrayIcon(s); s.tray.setIcon(s._icon())
        m=QMenu(); a1=QAction("显示",s); a1.triggered.connect(s.show_act); m.addAction(a1); m.addSeparator()
        a2=QAction("退出",s); a2.triggered.connect(s.app.quit); m.addAction(a2)
        s.tray.setContextMenu(m)
        s.tray.activated.connect(lambda r: s.show_act() if r==QSystemTrayIcon.Trigger else None)
        s.tray.show()

    def _icon(s):
        px=QPixmap(64,64); px.fill(Qt.transparent)
        p=QPainter(px); p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor(59,130,246))); p.setPen(Qt.NoPen)
        p.drawRoundedRect(2,2,60,60,14,14)
        p.setBrush(QBrush(QColor(255,255,255,220)))
        p.drawRoundedRect(10,14,28,6,3,3); p.drawRoundedRect(10,20,44,32,6,6)
        p.end(); return QIcon(px)

    def show_act(s): s.show(); s.activateWindow(); s.raise_()
    def closeEvent(s,e): e.ignore(); s.hide(); s.tray.showMessage("办公助手","已最小化到托盘",QSystemTrayIcon.Information,2000)

    def check_r(s):
        now=datetime.now(); today=now.strftime("%Y-%m-%d"); ct=now.strftime("%H:%M"); cd=now.day; cw=now.weekday()
        if s._lrd!=today:
            s._lrd=today; rc=0
            for t in s.mgr.tasks:
                if t.get("is_custom"): continue
                last=t.get("last_done","")
                if not last: continue
                tp=t.get("type","每日"); rst=False
                if tp=="每日" and last!=today: rst=True
                elif tp=="每周" and cw==0 and last!=today: rst=True
                elif tp=="每月" and cd==1 and last!=today: rst=True
                if rst: t["last_done"]=""; rc+=1
            if rc: s.mgr.save()

        for t in s.mgr.tasks:
            if t.get("last_done")==today: continue
            if not t.get("alarm_enabled",True): continue
            key=f"{today}_{ct}"; r=False
            if t.get("is_custom"): r=s._cc(t,now,today,ct,cd,cw,key)
            else:
                if t.get("use_specific_date") and t.get("remind_date"):
                    if t["remind_date"]==today and t.get("remind_time")==ct and t.get("last_reminded")!=key: r=True
                else:
                    tp=t.get("type","每日")
                    if tp in ("每日",) and t.get("remind_time")==ct and t.get("last_reminded")!=key: r=True
                    elif tp in ("每周",) and cw==0 and t.get("remind_time")==ct and t.get("last_reminded")!=key: r=True
                    elif tp in ("每月",) and cd==t.get("remind_day",1) and t.get("remind_time")==ct and t.get("last_reminded")!=key: r=True
                    elif tp in ("间隔",):
                        lt=t.get("last_interval_check")
                        if not lt: t["last_interval_check"]=now.timestamp()
                        elif (now.timestamp()-float(lt))>=t.get("interval",30)*60: r=True; t["last_interval_check"]=now.timestamp()
            if r: t["last_reminded"]=key; s.mgr.save(); s._al(t)

    def _cc(s,t,now,today,ct,cd,cw,key):
        f=t.get("custom_freq","仅一次"); rt=t.get("remind_time","09:00")
        if rt!=ct: return False
        if t.get("last_reminded")==key: return False
        if f=="仅一次": return t.get("custom_date","")==today
        if f=="每天": return True
        if f=="每周":
            try:
                i=datetime.strptime(t.get("custom_date",today),"%Y-%m-%d")
                return cw==i.weekday()
            except: return cw==0
        if f=="每月": return cd==t.get("remind_day",1)
        if f=="每年":
            try:
                i=datetime.strptime(t.get("custom_date",today),"%Y-%m-%d")
                return cd==i.day and now.month==i.month
            except: return False
        if f=="间隔":
            lt=t.get("last_interval_check")
            if not lt: t["last_interval_check"]=now.timestamp(); return False
            if (now.timestamp()-float(lt))>=t.get("interval",30)*60: t["last_interval_check"]=now.timestamp(); return True
        return False

    def _al(s,t):
        QApplication.beep()
        s.tray.showMessage(f"提醒: {t['name']}",t.get("note","") or f"分类: {t.get('type','')}",QSystemTrayIcon.Information,15000)


class ManageTabs(QDialog):
    def __init__(s,p,st):
        super().__init__(p); s.setWindowTitle("管理标签"); s.resize(480,400); s.st=st; s.ui()
    def ui(s):
        lo=QVBoxLayout(s); lo.addWidget(QLabel("<b>标签管理</b> - 拖动标签栏可直接排序"))
        s.lw=QListWidget(); s._rf(); lo.addWidget(s.lw)
        bl=QHBoxLayout(); b1=QPushButton("+ 新建"); b1.clicked.connect(s._ad); b2=QPushButton("✏️ 关键词"); b2.clicked.connect(s._ed); b3=QPushButton("🗑 删除"); b3.clicked.connect(s._dl)
        bl.addWidget(b1); bl.addWidget(b2); bl.addWidget(b3); lo.addLayout(bl)
        bl2=QHBoxLayout(); bl2.addStretch(); ok=QPushButton("完成"); ok.clicked.connect(s.accept); bl2.addWidget(ok); lo.addLayout(bl2)
    def _rf(s):
        s.lw.clear(); s.lw.addItem("📌 每日 - 每天,每日,daily..."); s.lw.addItem("📌 每周 - 每周,周报,weekly..."); s.lw.addItem("📌 每月 - 每月,月度,monthly..."); s.lw.addItem("📌 间隔 - 手动指定")
        for lb,kw in s.st.data.get("custom_tabs",{}).items(): s.lw.addItem(f"🏷 {lb} - {', '.join(kw)}")
    def _ad(s):
        n,ok=QInputDialog.getText(s,"新建标签","标签名称:")
        if not ok or not n.strip(): return
        n=n.strip()
        if n in BUILTIN_TABS or n in ("全部","自定义"): QMessageBox.warning(s,"错误","名称冲突"); return
        if n in s.st.data.get("custom_tabs",{}): QMessageBox.warning(s,"错误","已存在"); return
        kw,ok2=QInputDialog.getText(s,"关键词",f"「{n}」匹配关键词(逗号分隔):\n如: 季度,quarterly,Q")
        if not ok2: return
        ks=[k.strip() for k in kw.split(",") if k.strip()]
        if not ks: QMessageBox.warning(s,"错误","需要关键词"); return
        s.st.data.setdefault("custom_tabs",{})[n]=ks; s.st.save(); s._rf()
    def _ed(s):
        r=s.lw.currentRow()
        if r<0: return
        cs=s.st.data.get("custom_tabs",{}); ls=list(cs.keys())
        if r<4 or r-4>=len(ls): QMessageBox.information(s,"提示","内置标签不可编辑"); return
        lb=ls[r-4]; cur=cs[lb]
        kw,ok=QInputDialog.getText(s,"编辑关键词",f"「{lb}」的关键词:",text=", ".join(cur))
        if ok:
            ks=[k.strip() for k in kw.split(",") if k.strip()]
            if ks: cs[lb]=ks; s.st.save(); s._rf()
    def _dl(s):
        r=s.lw.currentRow()
        if r<0: return
        cs=s.st.data.get("custom_tabs",{}); ls=list(cs.keys())
        if r<4 or r-4>=len(ls): QMessageBox.information(s,"提示","内置标签不可删除"); return
        lb=ls[r-4]
        if QMessageBox.Yes==QMessageBox.question(s,"确认",f"删除标签「{lb}」？"): del cs[lb]; s.st.save(); s._rf()


if __name__=="__main__":
    app=QApplication(sys.argv); app.setQuitOnLastWindowClosed(False)
    sv=QLocalServer(); sk=QLocalSocket(); sk.connectToServer(AK)
    if sk.waitForConnected(500): sk.write(b"show"); sk.flush(); sk.waitForBytesWritten(500); sk.close(); sys.exit(0)
    sk.close(); sv.listen(AK)
    w=MainWindow(app); w.show()
    def _nc():
        cn=sv.nextPendingConnection()
        if cn:
            cn.waitForReadyRead(500)
            if b"show" in bytes(cn.readAll()): w.show_act()
            cn.close()
    sv.newConnection.connect(_nc)
    sys.exit(app.exec())
