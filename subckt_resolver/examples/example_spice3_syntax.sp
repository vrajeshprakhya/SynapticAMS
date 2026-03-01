* SPICE 3f5 Syntax Features Example
* Demonstrates official SPICE 3 syntax support

* Feature 1: Line continuation with '+'
* Lines starting with '+' in column 1 continue the previous line
.SUBCKT EIGHT_PORT_MUX A B C D
+ E F G H
+ VDD GND
* This subcircuit has 10 ports total
R1 A B 1k
R2 C D 1k
R3 E F 1k
R4 G H 1k
.ENDS

* Feature 2: Leading whitespace comments
* Lines starting with spaces or tabs are treated as comments
.SUBCKT INVERTER IN OUT VDD GND
  This line starts with spaces - it's a comment
    This one has even more leading spaces
	This line starts with a tab - also a comment
  All these lines are ignored by the parser
M1 OUT IN VDD VDD pmos W=2u L=0.5u
M2 OUT IN GND GND nmos W=1u L=0.5u
.ENDS

* Feature 3: Combining both features
* Multi-line subcircuit with comments inside
.SUBCKT NAND2 A B OUT
+ VDD GND
  NAND gate implementation
  Uses 4 transistors
M1 OUT A VDD VDD pmos W=2u L=0.5u
M2 OUT B VDD VDD pmos W=2u L=0.5u
M3 OUT A net1 GND nmos W=2u L=0.5u
M4 net1 B GND GND nmos W=2u L=0.5u
.ENDS

* Top-level circuit
VDD VDD 0 DC 1.8
V1 A 0 PULSE(0 1.8 0 1n 1n 10n 20n)
V2 B 0 PULSE(0 1.8 0 1n 1n 5n 10n)

* Multi-line instance call
X1 sig_a sig_b sig_c sig_d
+ sig_e sig_f sig_g sig_h
+ VDD 0
+ EIGHT_PORT_MUX

* Regular instances
X2 A OUT VDD 0 INVERTER
X3 A B NAND_OUT VDD 0 NAND2

.TRAN 0.1n 50n
.END
