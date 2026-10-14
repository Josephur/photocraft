#!/usr/bin/env python3
"""Original conformance fixture across Wine x86/x64. No vendor code or binaries."""
import argparse,json,os,pathlib,signal,struct,subprocess,time
p=argparse.ArgumentParser();p.add_argument('--prefix',required=True);p.add_argument('--large',action='store_true');a=p.parse_args()
root=pathlib.Path(__file__).resolve().parents[1]
env=dict(os.environ,WINEPREFIX=str(pathlib.Path(a.prefix).resolve()),WINEDEBUG='-all')
results=[]
for arch in ['i686','x86_64']:
 target=arch+'-pc-windows-gnu';out=root/'target'/target/'release';out.mkdir(parents=True,exist_ok=True)
 linker=os.environ.get('CARGO_TARGET_'+target.upper().replace('-','_')+'_LINKER',arch+'-w64-mingw32-gcc')
 fixture=out/'photocraft-conformance.8bf'
 subprocess.run(['rustc','--edition=2024','--crate-type=cdylib','--target',target,'-C','linker='+linker,'-O',str(root/'tests/fixture.rs'),'-o',str(fixture)],check=True)
 for mode in ['invert','noise','cancel','crash','bad_rect','ignored_callback']:
  w,h=320,240;pixels=bytes(i%256 for i in range(w*h*3))
  req=dict(path='Z:'+str(fixture).replace('/','\\'),entry='PluginMain',width=w,height=h,channels=3,depth=8,show_ui=False)
  m=json.dumps(req).encode();frame=b'PC8BF001'+struct.pack('<IQ',len(m),len(pixels))+m+pixels
  start=time.monotonic();proc=subprocess.Popen(['wine',str(out/'photocraft-8bf-worker.exe')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=dict(env,PHOTOCRAFT_8BF_FIXTURE_MODE=mode),start_new_session=True)
  try:response,stderr=proc.communicate(frame,timeout=40)
  except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);raise RuntimeError(arch+' '+mode+' timed out')
  if mode=='crash':assert proc.returncode!=0
  else:
   assert response[:8]==b'PC8BF001',(arch,mode,response[:100],stderr[-1000:])
   ml,pl=struct.unpack('<IQ',response[8:20]);meta=json.loads(response[20:20+ml]);data=response[20+ml:]
   if mode in ['invert','noise']:assert meta['status']=='ok' and data==bytes(255-v for v in pixels),(meta,len(data))
   elif mode=='cancel':assert meta['status']=='cancelled' and not data
   else:assert meta['status']=='error' and not data,(mode,meta)
  results.append(dict(architecture=arch,case=mode,passed=True,seconds=round(time.monotonic()-start,4)))
  print(json.dumps(results[-1]),flush=True)
 if a.large:
  w,h=6000,4000;pixels=bytes(range(256))*(w*h*3//256)
  req.update(width=w,height=h);m=json.dumps(req).encode();frame=b'PC8BF001'+struct.pack('<IQ',len(m),len(pixels))+m+pixels
  start=time.monotonic();proc=subprocess.Popen(['wine',str(out/'photocraft-8bf-worker.exe')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=dict(env,PHOTOCRAFT_8BF_FIXTURE_MODE='invert'),start_new_session=True)
  response,stderr=proc.communicate(frame,timeout=60)
  assert response[:8]==b'PC8BF001',(response[:100],stderr[-1000:]);ml,pl=struct.unpack('<IQ',response[8:20]);meta=json.loads(response[20:20+ml]);data=response[20+ml:]
  assert meta['status']=='ok' and len(data)==len(pixels)
  assert all(data[i]==255-pixels[i] for i in range(len(data)))
  results.append(dict(architecture=arch,case='24mp_invert',passed=True,seconds=round(time.monotonic()-start,4),pixels=w*h))
  print(json.dumps(results[-1]),flush=True)
(root/'target/conformance.json').write_text(json.dumps(results,indent=2)+'\n')
