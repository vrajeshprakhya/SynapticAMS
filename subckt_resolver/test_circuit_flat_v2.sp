* Test circuit with DFF instantiation

* Simple inverter subcircuit

* NAND gate subcircuit

* D Flip-Flop using NAND gates

* Top-level circuit
VDD VDD 0 DC 1.8
VGND GND 0 DC 0
VIN D_IN 0 PULSE(0 1.8 0 1n 1n 10n 20n)
VCLK CLK_IN 0 PULSE(0 1.8 0 1n 1n 5n 10n)

* Instantiate two DFFs
* Flattened instance: X_DFF1 D_IN CLK_IN Q1 QB1 VDD GND DFF
* Begin subcircuit: X_DFF1 (DFF)
* Flattened instance: X1 D CLK n1 VDD GND NAND2
* Begin subcircuit: X_DFF1_X1 (NAND2)
M_X_DFF1_X1_1 X_DFF1_n1 D_IN VDD VDD pmos W=2u L=0.5u
M_X_DFF1_X1_2 X_DFF1_n1 CLK_IN VDD VDD pmos W=2u L=0.5u
M_X_DFF1_X1_3 X_DFF1_n1 D_IN X_DFF1_X_DFF1_X1_net1 GND nmos W=2u L=0.5u
M_X_DFF1_X1_4 X_DFF1_X_DFF1_X1_net1 CLK_IN GND GND nmos W=2u L=0.5u
* End subcircuit: X_DFF1_X1
* Flattened instance: X2 DB CLK n2 VDD GND NAND2
* Begin subcircuit: X_DFF1_X2 (NAND2)
M_X_DFF1_X2_1 X_DFF1_n2 X_DFF1_DB VDD VDD pmos W=2u L=0.5u
M_X_DFF1_X2_2 X_DFF1_n2 CLK_IN VDD VDD pmos W=2u L=0.5u
M_X_DFF1_X2_3 X_DFF1_n2 X_DFF1_DB X_DFF1_X_DFF1_X2_net1 GND nmos W=2u L=0.5u
M_X_DFF1_X2_4 X_DFF1_X_DFF1_X2_net1 CLK_IN GND GND nmos W=2u L=0.5u
* End subcircuit: X_DFF1_X2
* Flattened instance: X3 n1 n4 n3 VDD GND NAND2
* Begin subcircuit: X_DFF1_X3 (NAND2)
M_X_DFF1_X3_1 X_DFF1_n3 X_DFF1_n1 VDD VDD pmos W=2u L=0.5u
M_X_DFF1_X3_2 X_DFF1_n3 X_DFF1_n4 VDD VDD pmos W=2u L=0.5u
M_X_DFF1_X3_3 X_DFF1_n3 X_DFF1_n1 X_DFF1_X_DFF1_X3_net1 GND nmos W=2u L=0.5u
M_X_DFF1_X3_4 X_DFF1_X_DFF1_X3_net1 X_DFF1_n4 GND GND nmos W=2u L=0.5u
* End subcircuit: X_DFF1_X3
* Flattened instance: X4 n2 n3 n4 VDD GND NAND2
* Begin subcircuit: X_DFF1_X4 (NAND2)
M_X_DFF1_X4_1 X_DFF1_n4 X_DFF1_n2 VDD VDD pmos W=2u L=0.5u
M_X_DFF1_X4_2 X_DFF1_n4 X_DFF1_n3 VDD VDD pmos W=2u L=0.5u
M_X_DFF1_X4_3 X_DFF1_n4 X_DFF1_n2 X_DFF1_X_DFF1_X4_net1 GND nmos W=2u L=0.5u
M_X_DFF1_X4_4 X_DFF1_X_DFF1_X4_net1 X_DFF1_n3 GND GND nmos W=2u L=0.5u
* End subcircuit: X_DFF1_X4
* Flattened instance: X5 n3 CLK Q VDD GND NAND2
* Begin subcircuit: X_DFF1_X5 (NAND2)
M_X_DFF1_X5_1 Q1 X_DFF1_n3 VDD VDD pmos W=2u L=0.5u
M_X_DFF1_X5_2 Q1 CLK_IN VDD VDD pmos W=2u L=0.5u
M_X_DFF1_X5_3 Q1 X_DFF1_n3 X_DFF1_X_DFF1_X5_net1 GND nmos W=2u L=0.5u
M_X_DFF1_X5_4 X_DFF1_X_DFF1_X5_net1 CLK_IN GND GND nmos W=2u L=0.5u
* End subcircuit: X_DFF1_X5
* Flattened instance: X6 n4 CLK QB VDD GND NAND2
* Begin subcircuit: X_DFF1_X6 (NAND2)
M_X_DFF1_X6_1 QB1 X_DFF1_n4 VDD VDD pmos W=2u L=0.5u
M_X_DFF1_X6_2 QB1 CLK_IN VDD VDD pmos W=2u L=0.5u
M_X_DFF1_X6_3 QB1 X_DFF1_n4 X_DFF1_X_DFF1_X6_net1 GND nmos W=2u L=0.5u
M_X_DFF1_X6_4 X_DFF1_X_DFF1_X6_net1 CLK_IN GND GND nmos W=2u L=0.5u
* End subcircuit: X_DFF1_X6
* Flattened instance: X7 D DB VDD GND INV
* Begin subcircuit: X_DFF1_X7 (INV)
M_X_DFF1_X7_1 X_DFF1_DB D_IN VDD VDD pmos W=2u L=0.5u
M_X_DFF1_X7_2 X_DFF1_DB D_IN GND GND nmos W=1u L=0.5u
* End subcircuit: X_DFF1_X7
* End subcircuit: X_DFF1
* Flattened instance: X_DFF2 Q1 CLK_IN Q2 QB2 VDD GND DFF
* Begin subcircuit: X_DFF2 (DFF)
* Flattened instance: X1 D CLK n1 VDD GND NAND2
* Begin subcircuit: X_DFF2_X1 (NAND2)
M_X_DFF2_X1_1 X_DFF2_n1 Q1 VDD VDD pmos W=2u L=0.5u
M_X_DFF2_X1_2 X_DFF2_n1 CLK_IN VDD VDD pmos W=2u L=0.5u
M_X_DFF2_X1_3 X_DFF2_n1 Q1 X_DFF2_X_DFF2_X1_net1 GND nmos W=2u L=0.5u
M_X_DFF2_X1_4 X_DFF2_X_DFF2_X1_net1 CLK_IN GND GND nmos W=2u L=0.5u
* End subcircuit: X_DFF2_X1
* Flattened instance: X2 DB CLK n2 VDD GND NAND2
* Begin subcircuit: X_DFF2_X2 (NAND2)
M_X_DFF2_X2_1 X_DFF2_n2 X_DFF2_DB VDD VDD pmos W=2u L=0.5u
M_X_DFF2_X2_2 X_DFF2_n2 CLK_IN VDD VDD pmos W=2u L=0.5u
M_X_DFF2_X2_3 X_DFF2_n2 X_DFF2_DB X_DFF2_X_DFF2_X2_net1 GND nmos W=2u L=0.5u
M_X_DFF2_X2_4 X_DFF2_X_DFF2_X2_net1 CLK_IN GND GND nmos W=2u L=0.5u
* End subcircuit: X_DFF2_X2
* Flattened instance: X3 n1 n4 n3 VDD GND NAND2
* Begin subcircuit: X_DFF2_X3 (NAND2)
M_X_DFF2_X3_1 X_DFF2_n3 X_DFF2_n1 VDD VDD pmos W=2u L=0.5u
M_X_DFF2_X3_2 X_DFF2_n3 X_DFF2_n4 VDD VDD pmos W=2u L=0.5u
M_X_DFF2_X3_3 X_DFF2_n3 X_DFF2_n1 X_DFF2_X_DFF2_X3_net1 GND nmos W=2u L=0.5u
M_X_DFF2_X3_4 X_DFF2_X_DFF2_X3_net1 X_DFF2_n4 GND GND nmos W=2u L=0.5u
* End subcircuit: X_DFF2_X3
* Flattened instance: X4 n2 n3 n4 VDD GND NAND2
* Begin subcircuit: X_DFF2_X4 (NAND2)
M_X_DFF2_X4_1 X_DFF2_n4 X_DFF2_n2 VDD VDD pmos W=2u L=0.5u
M_X_DFF2_X4_2 X_DFF2_n4 X_DFF2_n3 VDD VDD pmos W=2u L=0.5u
M_X_DFF2_X4_3 X_DFF2_n4 X_DFF2_n2 X_DFF2_X_DFF2_X4_net1 GND nmos W=2u L=0.5u
M_X_DFF2_X4_4 X_DFF2_X_DFF2_X4_net1 X_DFF2_n3 GND GND nmos W=2u L=0.5u
* End subcircuit: X_DFF2_X4
* Flattened instance: X5 n3 CLK Q VDD GND NAND2
* Begin subcircuit: X_DFF2_X5 (NAND2)
M_X_DFF2_X5_1 Q2 X_DFF2_n3 VDD VDD pmos W=2u L=0.5u
M_X_DFF2_X5_2 Q2 CLK_IN VDD VDD pmos W=2u L=0.5u
M_X_DFF2_X5_3 Q2 X_DFF2_n3 X_DFF2_X_DFF2_X5_net1 GND nmos W=2u L=0.5u
M_X_DFF2_X5_4 X_DFF2_X_DFF2_X5_net1 CLK_IN GND GND nmos W=2u L=0.5u
* End subcircuit: X_DFF2_X5
* Flattened instance: X6 n4 CLK QB VDD GND NAND2
* Begin subcircuit: X_DFF2_X6 (NAND2)
M_X_DFF2_X6_1 QB2 X_DFF2_n4 VDD VDD pmos W=2u L=0.5u
M_X_DFF2_X6_2 QB2 CLK_IN VDD VDD pmos W=2u L=0.5u
M_X_DFF2_X6_3 QB2 X_DFF2_n4 X_DFF2_X_DFF2_X6_net1 GND nmos W=2u L=0.5u
M_X_DFF2_X6_4 X_DFF2_X_DFF2_X6_net1 CLK_IN GND GND nmos W=2u L=0.5u
* End subcircuit: X_DFF2_X6
* Flattened instance: X7 D DB VDD GND INV
* Begin subcircuit: X_DFF2_X7 (INV)
M_X_DFF2_X7_1 X_DFF2_DB Q1 VDD VDD pmos W=2u L=0.5u
M_X_DFF2_X7_2 X_DFF2_DB Q1 GND GND nmos W=1u L=0.5u
* End subcircuit: X_DFF2_X7
* End subcircuit: X_DFF2

.TRAN 0.1n 100n
.END
