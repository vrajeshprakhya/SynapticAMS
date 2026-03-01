* Test circuit with .LIB statement

* Load only TYPICAL section from library
.LIB 'lib/corners.lib' TYPICAL

* Use the loaded subcircuit
VDD VDD 0 DC 1.8
VG GATE 0 PULSE(0 1.8 0 1n 1n 5n 10n)

X1 DRAIN GATE 0 0 NMOS_TYP

.TRAN 0.1n 20n
.END
