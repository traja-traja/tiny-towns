"""MODULE input refinement: opt-in wider-cloud support before exact cropping.

Preserve original input checksums/outline and archive the wider context. Only
training roof points influence the outline; held-out roof points stay withheld.
"""
import copy
import hashlib
from pathlib import Path
import shutil
import time
import numpy as np
import shapely
from shapely.geometry import shape,mapping
from roof_footprint_support import refine_footprint


def refine_input_part(part,input_base,output,filename,config):
    started=time.perf_counter();record=part.get('context_cache')
    if not record:raise ValueError('footprint_support requires a frozen wider context_cache')
    if record.get('coordinate_reference')!='local_xy_relative_ground':
        raise ValueError('Context points must use the part origin and ground reference')
    if record.get('origin_xy')!=part.get('origin_xy') or record.get('ground_z')!=part.get('ground_z'):
        raise ValueError('Context spatial reference differs from the building')
    path=Path(record['path']);path=path if path.is_absolute() else Path(input_base)/path
    if hashlib.sha256(path.read_bytes()).hexdigest()!=record.get('sha256'):
        raise ValueError('Wider context differs from the frozen checksum')
    original=shape(part['footprint']);coverage=shape(record['coverage_polygon'])
    if not coverage.buffer(1e-7).covers(original):raise ValueError('Context coverage misses the original building')
    folder=Path(output)/'context-clouds';folder.mkdir(exist_ok=True)
    archived=folder/filename;shutil.copyfile(path,archived)
    with np.load(archived,allow_pickle=False) as data:
        xyz=data['xyz'];classes=data['classification'];held=data['holdout'].astype(bool)
    if len(xyz)!=len(classes) or len(xyz)!=len(held):raise ValueError('Invalid context arrays')
    load_seconds=time.perf_counter()-started
    selected=(classes==2)|((classes==6)&~held)
    effective,metadata=refine_footprint(original,xyz[selected],classes[selected],config['footprint_support'])
    if not coverage.buffer(1e-7).covers(effective):raise ValueError('Derived footprint exceeds measured context coverage')
    roof=(classes==6)&shapely.contains_xy(effective,xyz[:,0],xyz[:,1])
    train=xyz[roof&~held];holdout=xyz[roof&held]
    destination=Path(output)/'point-clouds'/filename
    with destination.open('wb') as stream:np.savez_compressed(stream,train=train,holdout=holdout)
    part['context_cache']={**copy.deepcopy(record),'path':'context-clouds/'+filename}
    part['cache']={'path':'point-clouds/'+filename,'bytes':destination.stat().st_size,
                   'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}
    metadata.update(context_read_seconds=load_seconds,
        point_policy='Training class-6 roof points and all class-2 ground points determine the outline; held-out roof points never select it.',
        wall_footprint_status='Simplified modeling hypothesis derived from roof/ground support, not a surveyed wall boundary.',
        source_context_sha256=record['sha256'],effective_train_points=len(train),effective_holdout_points=len(holdout),
        total_input_stage_seconds=time.perf_counter()-started)
    part['footprint_support']=metadata
    part['effective_footprint']=mapping(effective)
    return part,train,metadata
