import requests, json, re, sys
from concurrent.futures import ThreadPoolExecutor
B="https://physionet-open.s3.amazonaws.com/chbmit/1.0.0/"
recs=requests.get(B+"RECORDS",timeout=60).text.split()
def hdr(p):
    for _ in range(4):
        try:
            r=requests.get(B+p,headers={"Range":"bytes=0-14000"},timeout=60); b=r.content
            ns=int(b[252:256]); L=[b[256+i*16:256+(i+1)*16].decode().strip() for i in range(ns)]
            dim=[b[256+ns*(16+80)+i*8:256+ns*(16+80)+(i+1)*8].decode().strip() for i in range(ns)]
            off=256+ns*(16+80+8)
            pmin=[float(b[off+i*8:off+(i+1)*8]) for i in range(ns)]
            pmax=[float(b[off+ns*8+i*8:off+ns*8+(i+1)*8]) for i in range(ns)]
            dmin=[float(b[off+ns*16+i*8:off+ns*16+(i+1)*8]) for i in range(ns)]
            dmax=[float(b[off+ns*24+i*8:off+ns*24+(i+1)*8]) for i in range(ns)]
            return p,dict(labels=L,dim=dim,pmin=pmin,pmax=pmax,dmin=dmin,dmax=dmax)
        except Exception as e: err=e
    return p,dict(error=str(err))
with ThreadPoolExecutor(8) as ex: out=dict(ex.map(hdr,recs))
json.dump(out,open('../results/audit/chbmit_edf_headers.json','w'))
print(len(out), sum('error' in v for v in out.values()))
