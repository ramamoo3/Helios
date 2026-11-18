* Primary bridge and freewheel paths
BP1 P a I={v(P,a)*(1e-8+v(cpa,N)/(5*RLO))}
BP2 a N I={v(a,N)*(1e-8+v(cpb,N)/(5*RLO))}
BP3 P b I={v(P,b)*(1e-8+v(cpb,N)/(5*RLO))}
BP4 b N I={v(b,N)*(1e-8+v(cpa,N)/(5*RLO))}
BDP1 a P I={max(0,v(a,P)-0.75)/0.008}
BDP2 N a I={max(0,v(N,a)-0.75)/0.008}
BDP3 b P I={max(0,v(b,P)-0.75)/0.008}
BDP4 N b I={max(0,v(N,b)-0.75)/0.008}
Ca a N 1n
Cb b N 1n

* Transformer: explicit primary-referred transfer inductance and resistance.
* Voltage source EX and reflected current source FX form an ideal transformer.
Ltransfer a lr {LK}
Rprimary lr wp {RP}
Lmag wp b {LM} IC={IMAG0}
EX sx d wp b {NSEC}
VsecCurrent sx c 0
FX wp b VsecCurrent {NSEC}

* Secondary bridge and freewheel paths
BS1 H c I={v(H,c)*(1e-8+v(csa,L)/(5*RHI))}
BS2 c L I={v(c,L)*(1e-8+v(csb,L)/(5*RHI))}
BS3 H d I={v(H,d)*(1e-8+v(csb,L)/(5*RHI))}
BS4 d L I={v(d,L)*(1e-8+v(csa,L)/(5*RHI))}
BDS1 c H I={max(0,v(c,H)-0.75)/0.008}
BDS2 L c I={max(0,v(L,c)-0.75)/0.008}
BDS3 d H I={max(0,v(d,H)-0.75)/0.008}
BDS4 L d I={max(0,v(L,d)-0.75)/0.008}
Cc c L 100p
Cd d L 100p
