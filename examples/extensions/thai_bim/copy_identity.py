"""Undoable copy adoption; never move geometry or guess reinforcement hosts."""
import copy
from core.history import Command
from .identity_data import repaired

class RepairCopies(Command):
    def __init__(self,scene):
        self.scene=scene;self.roots=list(scene.groups)
        groups=[g for g in scene.groups if (g.ext or {}).get('thai_bim')]
        mapped=dict(repaired([(g.uid,g.ext['thai_bim']) for g in groups]))
        self.items=[]
        for g in groups:
            old=copy.deepcopy(g.ext);new=copy.deepcopy(old);new['thai_bim']=mapped[g.uid]
            if old!=new:self.items.append((g,old,new))
    def do(self,scene):
        if scene is not self.scene or list(scene.groups)!=self.roots or any(g.ext!=old for g,old,new in self.items):raise ValueError('Document changed; review copies again')
        for g,old,new in self.items:g.ext=copy.deepcopy(new)
        scene.version+=1
    def undo(self,scene):
        for g,old,new in self.items:g.ext=copy.deepcopy(old)
        scene.version+=1

class RepairAndCreate(Command):
    def __init__(self,repair,create):self.repair=repair;self.create=create
    def do(self,scene):
        self.repair.do(scene)
        try:self.create.do(scene)
        except Exception:self.repair.undo(scene);raise
    def undo(self,scene):self.create.undo(scene);self.repair.undo(scene)

def wrap_creation(scene,command):
    from . import ExchangeGroups,identity_issues
    base=getattr(command,'member',command)
    # Only independent additions: selected edits/rebuilds retain their own guards.
    if isinstance(base,ExchangeGroups) and len(base.after)>len(base.before) and all(g in base.after for g in base.before) and identity_issues(scene):
        return RepairAndCreate(RepairCopies(scene),command)
    return command

def adopt(panel):
    command=RepairCopies(panel.app.scene);panel.execute(command)
    panel.report.setPlainText(f'ตรวจรหัสสำเนาแล้ว {len(command.items)} ชิ้น • geometry เดิม • Undo ได้\nเหล็ก/ชุดหลายชิ้นที่คัดลอกต้องตรวจความสัมพันธ์ใหม่ก่อน QTO/BBS')

def install(panel):
    if getattr(panel,'_copy_identity_installed',False):return
    panel._copy_identity_installed=True
    panel.button(panel.members,'รับสำเนา Copy เป็นชิ้นงานอิสระ / แก้รหัสซ้ำ',lambda:adopt(panel))
