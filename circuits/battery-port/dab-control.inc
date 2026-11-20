.param TPER={1/FSW} EDGE=25n
.param TPRI={max(-D,0)*TPER/2} TSEC={max(D,0)*TPER/2}

* Ideal gate commands with both diagonals off during dead time.
VPA rawpa N PULSE(0 5 {TPRI+DT/2} {EDGE} {EDGE} {TPER/2-DT-EDGE} {TPER})
VPB rawpb N PULSE(0 5 {TPRI+TPER/2+DT/2} {EDGE} {EDGE} {TPER/2-DT-EDGE} {TPER})
VSA rawsa L PULSE(0 5 {TSEC+DT/2} {EDGE} {EDGE} {TPER/2-DT-EDGE} {TPER})
VSB rawsb L PULSE(0 5 {TSEC+TPER/2+DT/2} {EDGE} {EDGE} {TPER/2-DT-EDGE} {TPER})
* Body diodes remain present whenever permission is removed.
Ben en N V={max(0,min(min(1,(time-START)/EDGE),(STOP-time)/EDGE))*max(0,min(1,v(PWM_PERMIT,N)/3.3))}
Bpa cpa N V={v(rawpa,N)*v(en,N)}
Bpb cpb N V={v(rawpb,N)*v(en,N)}
Bsa csa L V={v(rawsa,L)*v(en,N)}
Bsb csb L V={v(rawsb,L)*v(en,N)}
