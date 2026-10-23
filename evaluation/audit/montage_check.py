import sys, json, numpy as np, requests
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from fetch_chbmit import read_edf_channels, _bipolar_path
B="https://physionet-open.s3.amazonaws.com/chbmit/1.0.0/"
files=sys.argv[1:]
out={}
for f in files:
    buf=requests.get(B+f,timeout=300).content
    H,chan=read_edf_channels(buf)
    L=[l.upper() for l in H['labels']]
    g=lambda k:(H['pmax'][k]-H['pmin'][k])/(H['dmax'][k]-H['dmin'][k])
    ph=lambda k:(chan(k).astype(np.float64)-H['dmin'][k])*g(k)+H['pmin'][k]
    fs=H['nsamp'][0]/H['dur']
    ch=_bipolar_path(L,'FP1','FP2')
    d=sum(s*ph(k) for k,s in ch)
    a=ph(L.index('FP1-F7')); b=ph(L.index('FP2-F8'))
    r={'file':f,'fs':fs,'lsb_uV':[round(g(k),4) for k,_ in ch],
       'rms':{'FP1-FP2':float(d.std()),'FP1-F7':float(a.std()),'FP2-F8':float(b.std())}}
    # polarity: correlation of recon with FP1-F7 (+) and FP2-F8 (-) in 1-12 Hz band (blinks/delta)
    from scipy.signal import butter,sosfiltfilt
    sos=butter(2,[1,12],btype='band',fs=fs,output='sos')
    fd,fa,fb=[sosfiltfilt(sos,x) for x in (d,a,b)]
    r['corr_recon_vs_FP1F7']=float(np.corrcoef(fd,fa)[0,1]); r['corr_recon_vs_FP2F8']=float(np.corrcoef(fd,fb)[0,1])
    # blink test: large events in FP1-F7 and FP2-F8 in-phase (common FP). In FP1-FP2 they should cancel.
    thr=np.percentile(np.abs(fa),99.5); idx=np.where(np.abs(fa)>thr)[0]
    r['blink_ratio_recon_over_FP1F7']=float(np.median(np.abs(fd[idx])/np.abs(fa[idx])))
    r['blink_same_sign_FP1F7_FP2F8']=float(np.mean(np.sign(fa[idx])==np.sign(fb[idx])))
    # a wrong-polarity chain (FP2-F8 added instead of subtracted) would be:
    wrong=d+2*b   # = chain with +FP2-F8
    r['wrongpol_blink_ratio']=float(np.median(np.abs(sosfiltfilt(sos,wrong)[idx])/np.abs(fa[idx])))
    # redundancy check: the two T8-P8 channels and P7-T7 vs T7-P7 where present
    if L.count('T8-P8')==2:
        i,j=[k for k,l in enumerate(L) if l=='T8-P8']; x,y=ph(i),ph(j)
        r['T8P8_dup_maxabsdiff_uV']=float(np.abs(x-y).max()); r['T8P8_dup_corr']=float(np.corrcoef(x,y)[0,1])
    if 'P7-T7' in L and 'T7-P7' in L:
        x,y=ph(L.index('P7-T7')),ph(L.index('T7-P7')); r['P7T7_plus_T7P7_maxabs_uV']=float(np.abs(x+y).max())
    # quantisation noise of the 7-term sum
    r['quant_noise_rms_uV']=float(np.sqrt(sum((g(k)**2)/12 for k,_ in ch)))
    out[f]=r; print(json.dumps(r))
json.dump(out,open('../results/audit/recon_test.json','w'),indent=1)
