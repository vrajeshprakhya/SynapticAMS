* SPICE 3f5 Syntax Features Example
* Demonstrates official SPICE 3 syntax support

* Feature 1: Line continuation with '+'
* Lines starting with '+' in column 1 continue the previous line

* Feature 2: Leading whitespace comments
* Lines starting with spaces or tabs are treated as comments

* Feature 3: Combining both features
* Multi-line subcircuit with comments inside

* Top-level circuit
VDD VDD 0 DC 1.8
V1 A 0 PULSE(0 1.8 0 1n 1n 10n 20n)
V2 B 0 PULSE(0 1.8 0 1n 1n 5n 10n)

* Multi-line instance call
* Flattened instance: X1 sig_a sig_b sig_c sig_d  sig_e sig_f sig_g sig_h  VDD 0  EIGHT_PORT_MUX
* Begin subcircuit: X1 (EIGHT_PORT_MUX)
* This subcircuit has 10 ports total
R_X1_1 sig_a sig_b 1k
R_X1_2 sig_c sig_d 1k
R_X1_3 sig_e sig_f 1k
R_X1_4 sig_g sig_h 1k
* End subcircuit: X1

* Regular instances
* Flattened instance: X2 A OUT VDD 0 INVERTER
* Begin subcircuit: X2 (INVERTER)
  This line starts with spaces - it's a comment
    This one has even more leading spaces
	This line starts with a tab - also a comment
  All these lines are ignored by the parser
M_X2_1 OUT A VDD VDD pmos W=2u L=0.5u
M_X2_2 OUT A 0 0 nmos W=1u L=0.5u
* End subcircuit: X2
* Flattened instance: X3 A B NAND_OUT VDD 0 NAND2
* Begin subcircuit: X3 (NAND2)
  NAND gate implementation
  Uses 4 transistors
M_X3_1 NAND_OUT A VDD VDD pmos W=2u L=0.5u
M_X3_2 NAND_OUT B VDD VDD pmos W=2u L=0.5u
M_X3_3 NAND_OUT A X3_net1 0 nmos W=2u L=0.5u
M_X3_4 X3_net1 B 0 0 nmos W=2u L=0.5u
* End subcircuit: X3

.TRAN 0.1n 50n
.END
