"""Scientific contracts: winter mix, ice, missing data and hail handling."""
import itertools
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from winter_precip import classify, colorize, RAIN, MIX, SNOW, ICE

# All 16 binary combinations. Sleet+freezing rain alone remains ice.
for r,s,p,f in itertools.product((0,1),repeat=4):
    families = r+s+int(bool(p or f))
    expected = MIX if families>1 else ICE if p or f else SNOW if s else RAIN
    actual, supported = classify(np.array([1]),*[np.array([a]) for a in (r,s,p,f)])
    assert actual[0] == expected,(r,s,p,f,actual)
    assert supported[0] == bool(families)

# Hail/tropical mix flags are rain; dry/no coverage/unknown never show winter.
flag = np.array([7,91,96,3,0,-3,-1,99,np.nan])
actual,_ = classify(flag)
assert actual.tolist() == [RAIN,RAIN,RAIN,SNOW,0,0,0,0,0]
ones = np.ones(flag.shape)
actual,_ = classify(flag,ones,ones,ones,ones)
assert actual.tolist() == [MIX,MIX,MIX,MIX,0,0,0,0,0]
# A missing/invalid model flag falls back to MRMS, including missing snow masks.
actual,supported = classify(np.array([3,1]),np.array([1,1]),np.array([np.nan,2]),np.zeros(2),np.zeros(2))
assert actual.tolist() == [SNOW,RAIN] and not supported.any()
rgba = colorize(np.array([[4,5,30,np.nan,60.]]),np.array([[RAIN,RAIN,ICE,SNOW,0]]))
assert rgba[0,:,3].tolist() == [0,255,255,0,0]
assert not np.array_equal(rgba[0,1,:3],rgba[0,2,:3])
print('Winter type science contracts PASS: all phase combinations, hail exclusion, missing/dry masking, rendering.')
