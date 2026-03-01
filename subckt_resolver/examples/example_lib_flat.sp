* Test circuit with .LIB statement

* Load only TYPICAL section from library

* Use the loaded subcircuit
VDD VDD 0 DC 1.8
VG GATE 0 PULSE(0 1.8 0 1n 1n 5n 10n)

* Flattened instance: X1 DRAIN GATE 0 0 NMOS_TYP
* Begin subcircuit: X1 (NMOS_TYP)
* Typical corner NMOS
.model nmos_typ NMOS (level=1 vto=0.7 kp=120u)
M_X1_1 DRAIN GATE 0 0 nmos_typ W=1u L=0.5u
* End subcircuit: X1

.TRAN 0.1n 20n
.END
