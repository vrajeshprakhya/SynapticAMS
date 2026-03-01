* Test circuit with .INCLUDE statement

* Include library from subdirectory

* Use the included subcircuits
VDD VDD 0 DC 1.8
VIN IN 0 PULSE(0 1.8 0 1n 1n 5n 10n)

* Flattened instance: X1 IN OUT1 VDD 0 INV_TEST
* Begin subcircuit: X1 (INV_TEST)
M_X1_1 OUT1 IN VDD VDD pmos W=2u L=0.5u
M_X1_2 OUT1 IN 0 0 nmos W=1u L=0.5u
* End subcircuit: X1
* Flattened instance: X2 IN OUT1 OUT2 VDD 0 NAND2_TEST
* Begin subcircuit: X2 (NAND2_TEST)
M_X2_1 OUT2 IN VDD VDD pmos W=2u L=0.5u
M_X2_2 OUT2 OUT1 VDD VDD pmos W=2u L=0.5u
M_X2_3 OUT2 IN X2_net1 0 nmos W=2u L=0.5u
M_X2_4 X2_net1 OUT1 0 0 nmos W=2u L=0.5u
* End subcircuit: X2

.TRAN 0.1n 20n
.END
