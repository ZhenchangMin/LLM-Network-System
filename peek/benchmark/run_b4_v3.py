#!/usr/bin/env python3
"""B4 runner: frozen W1-Lite, isolated outputs, sequential fresh services."""
import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path('/root/bayes-tmp/peek')
A = Path('/root/bayes-tmp/kvcache/a-group')
MODEL = Path('/root/bayes-tmp/kvcache/models/Qwen2.5-3B-Instruct')
DATA = Path('/root/bayes-tmp/kvcache/loogle_longdep_qa.jsonl')
APY = Path('/root/bayes-tmp/kvcache/conda-envs/sglang-0.5.9/bin/python')
BPY = REPO / '.venv/bin/python'
SERVER_SEED = 950056913  # Effective random_seed recorded in the historical A3 log.
EXPECTED = {
    str(DATA): '6c047bc6e904e5fd632e44a2f2624d75e85fe0f871c6b74bcfffa918bf2f3624',
    str(A/'bench/bench_shared_prompts.py'): '2bbdcafcaf84ff00a3a475d03f49ff410c4f18a7d9c69fb513727f6c060efae8',
    str(A/'results/w1_lite_baseline_a3.json'): 'e62dd2316c08342144162bbd4a374e11db4ff83429740bd7761360b57708b13a',
    str(A/'results/server_w1_lite_a3.log'): 'c549f0d0a98c44fedb7d252b7bc4f58dabf69100730ba4c3c8fc497f740ae286',
}
PLAN = [('vanilla',1),('peek',1),('peek',2),('vanilla',2),('vanilla',3),('peek',3)]
ROOT = None

def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()

def save(p, obj):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    temporary=p.with_name(p.name+'.writing')
    temporary.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temporary.replace(p)

def event(kind, **details):
    row={'time':now(),'event':kind,**details}
    with (ROOT/'events.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print(json.dumps(row,ensure_ascii=False),flush=True)
    with (ROOT/'RUN_LOG.md').open('a',encoding='utf-8') as f:
        f.write('- '+row['time']+' — '+kind+': '+json.dumps(details,ensure_ascii=False)+'\n')

def command(cmd, timeout=30, **kw):
    r=subprocess.run([str(x) for x in cmd],capture_output=True,text=True,timeout=timeout,**kw)
    return {'command':shlex.join([str(x) for x in cmd]),'returncode':r.returncode,
            'stdout':r.stdout,'stderr':r.stderr}

def listening_ports():
    result=[]
    for name in ['/proc/net/tcp','/proc/net/tcp6']:
        for line in Path(name).read_text().splitlines()[1:]:
            f=line.split();port=int(f[1].split(':')[-1],16)
            if f[3]=='0A' and port in [30000,30001,30011]:result.append(port)
    return sorted(set(result))

def gpu_apps():
    r=command(['nvidia-smi','--query-compute-apps=pid,process_name,used_memory','--format=csv,noheader'])
    if r['returncode']!=0:raise RuntimeError('Cannot establish GPU ownership: '+r['stderr'])
    return r['stdout'].strip()

def protected_inventory():
    git=command(['git','--no-optional-locks','-C',REPO,'ls-files','-z'])
    if git['returncode']!=0:raise RuntimeError(git['stderr'])
    files={REPO/p for p in git['stdout'].split('\0') if p}
    files.update(p for p in (REPO/'b-group').rglob('*') if p.is_file() and ROOT not in p.parents
                 and '__pycache__' not in p.parts)
    files.update(p for p in A.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    files.add(DATA)
    files.update(p for p in MODEL.iterdir() if p.is_file() and p.suffix not in ['.safetensors','.bin'])
    return {str(p):{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files) if p.is_file()}

def clean_env(run, policy):
    env={k:v for k,v in os.environ.items() if not k.startswith(('PEEK_','B3_','BENCH_','A_GROUP_'))
         and k not in ['PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','CONDA_PREFIX','CONDA_DEFAULT_ENV']}
    env.update({'PYTHONDONTWRITEBYTECODE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_OFFLINE':'1',
                'TOKENIZERS_PARALLELISM':'false','CUDA_VISIBLE_DEVICES':'0',
                'LOOGLE_DATA_FILE':str(DATA),'HF_DATASETS_CACHE':str(ROOT/'runtime/hf_datasets'),
                'XDG_CACHE_HOME':str(ROOT/'runtime/cache'),
                'CUDA_CACHE_PATH':str(ROOT/'runtime/cuda'),
                'TRITON_CACHE_DIR':str(ROOT/'runtime/triton'),
                # ZMQ Unix-domain IPC paths must stay below 107 characters.
                'TMPDIR':str(ROOT/'runtime/ipc')})
    for key in ['HF_DATASETS_CACHE','XDG_CACHE_HOME','CUDA_CACHE_PATH','TRITON_CACHE_DIR','TMPDIR']:
        Path(env[key]).mkdir(parents=True,exist_ok=True)
    if policy=='peek':
        env.update({'PEEK_PRESET':'peek-online',
                    'PYTHONPATH':str(REPO/'scripts/peek_sitecustomize')+':'+str(REPO/'python'),
                    'PEEK_ONLINE_PROFILE':'0','PEEK_ONLINE_VALIDATE':'0',
                    'PEEK_ONLINE_EVICTION_DEBUG':'0','PEEK_ONLINE_VALIDATE_LPM_ORDER':'0',
                    'PEEK_ONLINE_PHASE_DUMP_PATH':str(run/'runtime/peek_phases_{pid}.json')})
    return env

def gpu_monitor(path,stop):
    with path.open('a',encoding='utf-8') as f:
        while not stop.is_set():
            try:
                g=command(['nvidia-smi','--query-gpu=name,memory.used,memory.total,utilization.gpu,power.draw',
                           '--format=csv,noheader,nounits'],timeout=8)
                f.write(json.dumps({'time':now(),**g})+'\n');f.flush()
            except Exception as e:
                f.write(json.dumps({'time':now(),'error':str(e)})+'\n');f.flush()
            stop.wait(1.0)

def get_http(port,path):
    with urllib.request.urlopen('http://127.0.0.1:'+str(port)+path,timeout=4) as r:
        return r.status,r.read().decode('utf-8','replace')

def stop_own(proc,run):
    if proc is None:return
    record={'pid':proc.pid,'pgid':proc.pid,'time':now()}
    # start_new_session=True gives this service its own process group.
    try:
        os.killpg(proc.pid,signal.SIGTERM);record['sigterm_sent']=True
    except ProcessLookupError:record['already_exited']=True
    try:proc.wait(timeout=25)
    except subprocess.TimeoutExpired:
        try:os.killpg(proc.pid,signal.SIGKILL);record['sigkill_sent']=True
        except ProcessLookupError:pass
        proc.wait(timeout=15)
    # A parent may exit before children; only kill members of our exact group.
    own=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            if os.getpgid(int(p.name))==proc.pid:own.append(int(p.name))
        except (ProcessLookupError,PermissionError):pass
    if own:
        try:os.killpg(proc.pid,signal.SIGKILL);record['remaining_group_killed']=own
        except ProcessLookupError:pass
    record['parent_returncode']=proc.returncode
    save(run/'shutdown.json',record)
    for _ in range(30):
        if not gpu_apps():break
        time.sleep(1)

def prepare():
    before=protected_inventory();save(ROOT/'metadata/protected_before.json',before)
    actual={p:sha(p) for p in EXPECTED}
    save(ROOT/'metadata/frozen_checksums.json',{'expected':EXPECTED,'actual':actual})
    if actual!=EXPECTED:raise RuntimeError('Frozen input checksum changed; do not run')
    git={name:command(['git','--no-optional-locks','-C',REPO,*args]) for name,args in
         [('head',['rev-parse','HEAD']),('status',['status','--short']),
          ('upstream_diff',['diff','3aca72b','HEAD','--name-status'])]}
    save(ROOT/'metadata/git_before.json',git)
    copies={A/'bench/bench_shared_prompts.py':'frozen_client.py',
            A/'bench/run_w1_lite.sh':'a_run_w1_lite.sh',
            A/'scripts/start_sglang.sh':'a_start_sglang.sh',
            A/'results/w1_lite_config.json':'a_w1_lite_config.json',
            A/'results/w1_lite_baseline_a3.json':'historical_a3.json',
            A/'results/server_w1_lite_a3.log':'historical_a3_server.log',
            A/'results/pilot_report.md':'a_pilot_report.md',
            REPO/'b-group/scripts/start_peek_online.sh':'b3_start_peek_online.sh',
            REPO/'b-group/docs/B3_to_B4_handoff.md':'b3_to_b4_handoff.md'}
    for src,name in copies.items():
        dst=ROOT/'inputs'/name
        if not dst.exists():shutil.copyfile(src,dst)
        if sha(src)!=sha(dst):raise RuntimeError('Snapshot differs: '+str(dst))
    save(ROOT/'metadata/plan.json',{
        'registered_before_runs':now(),'policies':PLAN,'server_seed':SERVER_SEED,'client_seed':42,
        'repetitions':'3 repeats of the same frozen seed, not 3 independent workload seeds',
        'primary_peek':'first completed PEEK run; do not select by performance',
        'fairness':'fresh process/cache per run; sequential on one GPU; ABBAAB order',
        'reporting':'per-run values plus median and sample standard deviation; historical A3 separate',
        'diagnostics':'PROFILE/VALIDATE/EVICTION_DEBUG off; default PEEK phase tracking retained',
        'client':'byte-identical snapshot of the frozen A client; same A Python for all clients',
        'added_argument':'--random-seed 950056913 fixes the effective server seed in the historical A3 log',
        'run_limits':{'n':256,'warmup':32,'groups':16,'prefix_tokens':1024,'rate':20,
                      'concurrency':64,'max_tokens':64,'kv_tokens':8192,'mem_fraction':0.75}})
    versions={}
    code="import sys,json;from importlib.metadata import version;print(json.dumps({'python':sys.version,**{p:version(p) for p in ['torch','sglang','transformers','tokenizers','flashinfer-python','flashinfer-cubin','sgl-kernel','triton','numpy','datasets','aiohttp']}}))"
    env=clean_env(ROOT/'runtime/preflight','vanilla')
    for name,py in [('A',APY),('B',BPY)]:
        versions[name]=command([py,'-c',code],timeout=60,env=env)
        if versions[name]['returncode']!=0:raise RuntimeError(versions[name]['stderr'])
    save(ROOT/'metadata/versions.json',versions)
    save(ROOT/'metadata/gpu_before.json',command(['nvidia-smi']))
    event('prepared',protected_files=len(before),git_head=git['head']['stdout'].strip())
    return before

def freeze_workload():
    code="""import importlib.util,sys,dataclasses,json,hashlib
from pathlib import Path
p=Path(sys.argv[1]);out=Path(sys.argv[2])
spec=importlib.util.spec_from_file_location('b4_frozen_client',p)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
reqs=m.generate_workload(n=256,groups=16,prefix_tokens=1024,max_tokens=64,rate_req_per_s=20,seed=42,model_name='/root/bayes-tmp/kvcache/models/Qwen2.5-3B-Instruct',dataset='loogle',distribution='zipf',zipf_alpha=1.0)
rows=[dataclasses.asdict(r) for r in reqs]
out.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\\n',encoding='utf-8')
print('FROZEN_REQUESTS',len(rows),'GROUPS',len(set(r['group_id'] for r in rows)))
"""
    env=clean_env(ROOT/'runtime/workload','vanilla')
    r=command([APY,'-c',code,ROOT/'inputs/frozen_client.py',ROOT/'inputs/workload.json'],timeout=120,env=env)
    save(ROOT/'metadata/workload_generation.json',r)
    if r['returncode']!=0 or 'loaded 16 LooGLE docs' not in r['stdout'] or 'falling back' in r['stdout']:
        raise RuntimeError('Frozen workload generation failed: '+r['stdout']+r['stderr'])
    event('workload_frozen',sha256=sha(ROOT/'inputs/workload.json'))

def run_one(index,policy,rep):
    ident=f'{index:02d}_{policy}_r{rep}'
    matches=sorted((ROOT/'runs').glob(ident+'_attempt*'))
    for old in matches:
        state=old/'state.json'
        if state.exists() and json.loads(state.read_text()).get('state')=='complete':
            event('resume_skip_completed',run=str(old));return
    run=ROOT/'runs'/(ident+f'_attempt{len(matches)+1:02d}')
    run.mkdir();(run/'runtime').mkdir()
    env=clean_env(run,policy)
    if gpu_apps() or listening_ports():raise RuntimeError('GPU or A/B service port already in use; no foreign process stopped')
    port=30000 if policy=='vanilla' else 30001
    py=APY if policy=='vanilla' else BPY
    env['PATH']=str(py.parent)+':'+os.environ.get('PATH','')
    server=[str(py),'-m','sglang.launch_server','--model-path',str(MODEL),
            '--dtype','bfloat16','--tp-size','1','--schedule-policy','lpm','--enable-cache-report',
            '--mem-fraction-static','0.75','--max-total-tokens','8192','--random-seed',str(SERVER_SEED),
            '--host','127.0.0.1','--port',str(port)]
    client=[str(APY),str(ROOT/'inputs/frozen_client.py'),'--endpoint',f'http://127.0.0.1:{port}/v1/chat/completions',
            '--model',str(MODEL),'--dataset','loogle','--n','256','--groups','16','--prefix-tokens','1024',
            '--distribution','zipf','--zipf-alpha','1.0','--max-tokens','64','--warmup-reqs','32',
            '--rate','20','--concurrency','64','--seed','42','--save-per-request',
            '--label',ident,'--phase-dump-path',str(run/'runtime/peek_phases_{pid}.json'),
            '--output',str(run/'metrics.json')]
    keys=['PYTHONDONTWRITEBYTECODE','TRANSFORMERS_OFFLINE','HF_HUB_OFFLINE','TOKENIZERS_PARALLELISM',
          'CUDA_VISIBLE_DEVICES','LOOGLE_DATA_FILE','HF_DATASETS_CACHE','XDG_CACHE_HOME','CUDA_CACHE_PATH',
          'TRITON_CACHE_DIR','TMPDIR','PATH','PYTHONPATH']
    selected={k:v for k,v in env.items() if k in keys or k.startswith(('PEEK_','B3_','BENCH_'))}
    config={'run_id':ident,'policy':policy,'repeat':rep,'directory':str(run),'started':now(),
            'server_command':server,'server_shell':shlex.join(server),'client_command':client,
            'client_shell':shlex.join(client),'environment':selected}
    save(run/'config.json',config);save(run/'state.json',{'state':'starting','time':now()})
    event('run_start',run=ident,directory=str(run),policy=policy,repeat=rep)
    stop=threading.Event();monitor=threading.Thread(target=gpu_monitor,args=(run/'gpu_monitor.jsonl',stop),daemon=True)
    monitor.start();proc=None
    try:
        with (run/'server.log').open('wb') as slog:
            proc=subprocess.Popen(server,env=env,cwd=str(run),stdin=subprocess.DEVNULL,
                                  stdout=slog,stderr=subprocess.STDOUT,start_new_session=True)
            save(run/'server_process.json',{'pid':proc.pid,'pgid':proc.pid,'created':now()})
            deadline=time.monotonic()+1200;ready=False
            while time.monotonic()<deadline:
                if proc.poll() is not None:raise RuntimeError('Server exited during startup: '+str(proc.returncode))
                try:
                    status,body=get_http(port,'/get_server_info')
                    if status==200:
                        info=json.loads(body);save(run/'server_info_before.json',info)
                        status,body=get_http(port,'/health')
                        if status==200:
                            (run/'health.txt').write_text(body,encoding='utf-8');ready=True;break
                except Exception:pass
                time.sleep(2)
            if not ready:raise RuntimeError('Server startup timeout')
            log=(run/'server.log').read_text(errors='replace')
            if not re.search(r'KV Cache is allocated\. #tokens: 8,?192\b',log):
                raise RuntimeError('Actual 8192-token KV allocation not confirmed')
            if policy=='peek':
                if 'injected PeekDemandStrategy' not in log or 'peek: installed scheduler' not in log:
                    raise RuntimeError('PEEK hook/eviction installation evidence missing')
            elif 'injected PeekDemandStrategy' in log or 'peek: phase-tracking' in log:
                raise RuntimeError('Vanilla service contaminated by PEEK')
            save(run/'state.json',{'state':'benchmarking','time':now()})
            event('server_ready',run=ident,pid=proc.pid)
            # All A/B client processes use A's Python and the same byte-identical client.
            client_env=clean_env(run,'vanilla')
            client_env['PATH']=str(APY.parent)+':'+os.environ.get('PATH','')
            with (run/'client.log').open('wb') as clog:
                result=subprocess.run(client,env=client_env,cwd=str(run),stdin=subprocess.DEVNULL,
                                      stdout=clog,stderr=subprocess.STDOUT,timeout=600)
            if result.returncode!=0:raise RuntimeError('Benchmark client exit '+str(result.returncode))
            text=(run/'client.log').read_text(errors='replace')
            if 'loaded 16 LooGLE docs' not in text or 'falling back' in text:
                raise RuntimeError('Workload failed to use the frozen LooGLE documents')
            data=json.loads((run/'metrics.json').read_text())
            if data['counts']['submitted']!=256 or data['counts']['ok']!=224 or data['counts']['errored']!=0:
                raise RuntimeError('Request acceptance failed: '+str(data['counts']))
            hist=json.loads((ROOT/'inputs/historical_a3.json').read_text())
            ours=sorted(data['per_request'],key=lambda r:r['req_id'])
            old=sorted(hist['per_request'],key=lambda r:r['req_id'])
            parity=[(r['req_id'],r['group_id'],r['prompt_tokens']) for r in ours]==[(r['req_id'],r['group_id'],r['prompt_tokens']) for r in old]
            save(run/'input_parity.json',{'all_256_req_id_group_and_prompt_token_counts_match_historical_A3':parity,
                                         'frozen_workload_sha256':sha(ROOT/'inputs/workload.json'),
                                         'frozen_client_sha256':sha(ROOT/'inputs/frozen_client.py')})
            if not parity:raise RuntimeError('Request groups/prompt token counts differ from frozen A3')
            # Permit one default phase dump interval after timing; no extra model requests.
            time.sleep(1.5)
            try:
                status,body=get_http(port,'/get_server_info')
                if status==200:save(run/'server_info_after.json',json.loads(body))
            except Exception as exc:event('optional_server_info_failed',run=ident,error=str(exc))
            save(run/'state.json',{'state':'complete','time':now()})
            event('run_complete',run=ident,ttft_mean_ms=data['ttft_ms']['mean'],
                  cache_hit_pct=data['cache']['hit_rate_pct'],throughput=data['throughput']['request_per_s'])
    except Exception as exc:
        save(run/'state.json',{'state':'failed','time':now(),'error':str(exc),'traceback':traceback.format_exc()})
        event('run_failed',run=ident,error=str(exc));raise
    finally:
        stop_own(proc,run);stop.set();monitor.join(timeout=12)

def main():
    global ROOT
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);args=parser.parse_args()
    ROOT=Path(args.root).resolve()
    if ROOT.parent!=REPO/'b-group/results' or not ROOT.name.startswith('b4_'):
        raise RuntimeError('Unsafe output root')
    if (ROOT/'JOB_PID').exists():
        oldpid=int((ROOT/'JOB_PID').read_text())
        oldstat=Path('/proc/'+str(oldpid)+'/stat')
        if oldstat.exists() and oldstat.read_text().split(') ',1)[1].split()[0]!='Z':
            raise RuntimeError('Another B4 runner may be active')
    (ROOT/'JOB_PID').write_text(str(os.getpid())+'\n')
    before=None
    try:
        save(ROOT/'STATUS.json',{'state':'preparing','time':now(),'pid':os.getpid()})
        if gpu_apps() or listening_ports():raise RuntimeError('GPU/service ports busy before preparation')
        if (ROOT/'metadata/protected_before.json').exists():
            before=json.loads((ROOT/'metadata/protected_before.json').read_text())
        else:before=prepare()
        if not (ROOT/'inputs/workload.json').exists():freeze_workload()
        for index,(policy,rep) in enumerate(PLAN,1):
            save(ROOT/'STATUS.json',{'state':'running','time':now(),'current':index,
                                    'total':len(PLAN),'policy':policy,'repeat':rep,'pid':os.getpid()})
            run_one(index,policy,rep)
        save(ROOT/'STATUS.json',{'state':'experiments_complete','time':now(),'runs':len(PLAN)})
        event('all_experiments_complete',runs=len(PLAN))
    except Exception as exc:
        save(ROOT/'STATUS.json',{'state':'failed','time':now(),'error':str(exc),'traceback':traceback.format_exc()})
        event('job_failed',error=str(exc));return 1
    finally:
        if before is not None:
            changes=[]
            for name,record in before.items():
                p=Path(name)
                if not p.is_file():changes.append({'path':name,'change':'missing'})
                elif sha(p)!=record['sha256']:changes.append({'path':name,'change':'content_changed'})
            save(ROOT/'metadata/protected_after.json',{'checked_at':now(),'original_file_count':len(before),
                  'changed_or_missing':changes,'all_original_protected_files_unchanged':not changes})
            event('protected_files_check',checked=len(before),changes=changes)
        save(ROOT/'metadata/git_after.json',command(['git','--no-optional-locks','-C',REPO,'status','--short']))
        save(ROOT/'metadata/gpu_after.json',command(['nvidia-smi']))
    return 0

if __name__=='__main__':raise SystemExit(main())
