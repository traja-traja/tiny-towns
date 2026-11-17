"""MODULE candidate telemetry: optional per-building, nested-call accounting.

Times are disjoint measured stages, not inclusive parent timers. 'Selected'
counts selections inside calls, including alternatives for volume/annex work.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import time

_ACTIVE=ContextVar('roof_candidate_telemetry',default=None)

class Collector:
    def __init__(self,detailed=False):
        self.detailed=bool(detailed);self.families={};self.attempts=[];self.started=time.perf_counter()
    def record(self,family,label='',status='considered',reason=None,fitting_seconds=0.,geometry_seconds=0.,count=1,stage='fit',**metadata):
        family=str(family);count=int(count)
        row=self.families.setdefault(family,dict(family=family,considered=0,skipped=0,failed=0,rejected=0,selected=0,fitting_seconds=0.,geometry_seconds=0.,overhead_seconds=0.))
        if status=='skipped':row['skipped']+=max(1,count)
        elif stage!='eligibility':row['considered']+=count
        if status=='failed':row['failed']+=max(1,count)
        if status=='rejected':row['rejected']+=max(1,count)
        row['fitting_seconds']+=max(0.,float(fitting_seconds));row['geometry_seconds']+=max(0.,float(geometry_seconds))
        row['overhead_seconds']+=max(0.,float(metadata.get('overhead_seconds',0.)))
        if self.detailed:
            self.attempts.append(dict(family=family,label=str(label),status=status,reason=reason,stage=stage,count=count,
                fitting_seconds=max(0.,float(fitting_seconds)),geometry_seconds=max(0.,float(geometry_seconds)),**metadata))
    def to_dict(self):
        rows=[dict(v) for _,v in sorted(self.families.items())]
        return dict(schema='roof-candidate-telemetry/1',detailed=self.detailed,families=rows,attempts=list(self.attempts),
            total_fitting_seconds=sum(r['fitting_seconds'] for r in rows),total_geometry_seconds=sum(r['geometry_seconds'] for r in rows),
            total_overhead_seconds=sum(r['overhead_seconds'] for r in rows),elapsed_seconds=time.perf_counter()-self.started,
            count_policy='All actual attempts including internal volume/annex calls; selections are per-call, not final house counts.')

@contextmanager
def capture(detailed=False):
    collector=Collector(detailed);token=_ACTIVE.set(collector)
    try:yield collector
    finally:_ACTIVE.reset(token)

def record_attempt(family,label='',status='considered',reason=None,fitting_seconds=0.,geometry_seconds=0.,count=1,stage='fit',**metadata):
    current=_ACTIVE.get()
    if current is not None:current.record(family,label,status,reason,fitting_seconds,geometry_seconds,count,stage,**metadata)

def record_selection(family,label=''):
    current=_ACTIVE.get()
    if current is not None:
        current.record(family,label,status='selected',count=0,stage='selection')
        current.families[str(family)]['selected']+=1
