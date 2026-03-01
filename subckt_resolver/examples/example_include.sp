* Test circuit with .INCLUDE statement

* Include library from subdirectory
.INCLUDE "lib/basic_gates.sp"

* Use the included subcircuits
VDD VDD 0 DC 1.8
VIN IN 0 PULSE(0 1.8 0 1n 1n 5n 10n)

X1 IN OUT1 VDD 0 INV_TEST
X2 IN OUT1 OUT2 VDD 0 NAND2_TEST

.TRAN 0.1n 20n
.END
